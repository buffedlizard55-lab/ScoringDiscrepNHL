"""Alerting.

Kept deliberately dumb: alerts are derived from records, never from a separate
notion of truth, so an alert can always be traced to a record with sources.

Channels, in order of how much they cost to keep running:

1. ``data/alerts/YYYY-MM-DD/*.md`` in the repo - zero external dependency, and
   the alert itself becomes a versioned artifact a reviewer can check.
2. A GitHub issue on the repository (via ``gh`` or the REST API in Actions) -
   gives subscribers inbox/notification delivery for free.
3. A generic JSON webhook (Slack/Discord/PagerDream) - only if the operator
   supplies a URL as a secret. We do not store credentials in this repo.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Iterable, List, Optional

#: Alert-worthy = something a human should look at before the game is "settled".
ALERT_RULES = {
    "post_snapshot_goal_count_change": ("immediate", "Goal added or removed between two pulls of the "
                                       "official feed: the number of goals in the game is in motion."),
    "goal_missing_from_one_source": ("review", "A goal exists in one official artifact and not the other."),
    "post_snapshot_attribution_change": ("review", "Scoring credit changed after the fact."),
    "scorer_attribution_conflict": ("review", "The two official records credit different scorers."),
    "assist_attribution_conflict": ("info", "Assist credits differ between the official records."),
    "goal_total_mismatch": ("review", "An official artifact is internally inconsistent on goal totals."),
    "final_score_conflict": ("immediate", "The two official records disagree on the final score."),
}
RANK = {"immediate": 0, "review": 1, "info": 2}


def should_alert(record: Dict[str, Any]) -> Optional[str]:
    rule = ((record.get("detection") or {}).get("rule")) or ((record.get("discrepancy") or {}).get("change_type"))
    if record.get("status") in {"retired", "disputed"}:
        return None
    entry = ALERT_RULES.get(rule or "")
    if entry:
        return entry[0]
    mi = ((record.get("discrepancy") or {}).get("market_impact") or {})
    if mi.get("affects_game_total") == "yes":
        return "immediate"
    if mi.get("affects_game_total") == "possible":
        return "review"
    return None


def triage(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return ``[{level, record}]`` sorted most urgent first, deduped by record id."""
    out: List[Dict[str, Any]] = []
    seen = set()
    for record in records:
        level = should_alert(record)
        rid = record.get("record_id")
        if not level or rid in seen:
            continue
        seen.add(rid)
        out.append({"level": level, "record": record})
    out.sort(key=lambda item: (RANK.get(item["level"], 9),
                               (item["record"].get("game") or {}).get("date") or "",
                               item["record"].get("record_id") or ""))
    return out


def _fmt_player(state: Optional[Dict[str, Any]], key: str = "scorer") -> str:
    state = state or {}
    value = state.get(key)
    if isinstance(value, dict):
        return value.get("name") or "?"
    if isinstance(value, list):
        return "; ".join(v.get("name", "?") if isinstance(v, dict) else str(v) for v in value) or "none"
    return value or "none"


def render_record(record: Dict[str, Any], *, level: str = "review") -> str:
    game = record.get("game") or {}
    disc = record.get("discrepancy") or {}
    ini = record.get("initial_state") or {}
    cor = record.get("corrected_state") or {}
    mi = disc.get("market_impact") or {}
    lines = [
        f"### [{level.upper()}] {game.get('away_team')} at {game.get('home_team')} - "
        f"{game.get('date')} (game {game.get('game_id')})",
        "",
        f"- **What changed:** {disc.get('summary') or disc.get('detail')}",
        f"- **Rule fired:** `{(record.get('detection') or {}).get('check_id')}` "
        f"{(record.get('detection') or {}).get('rule_label')} "
        f"({(record.get('detection') or {}).get('severity')})",
        f"- **Initial state:** {_fmt_player(ini)}; assists {_fmt_player(ini, 'assists')}"
        f" (period {ini.get('period')} {ini.get('clock')}, {ini.get('strength')})",
        f"- **Corrected state:** {_fmt_player(cor)}; assists {_fmt_player(cor, 'assists')}"
        f" (period {cor.get('period')} {cor.get('clock')}, {cor.get('strength')})",
        f"- **Goal total affected:** {mi.get('affects_game_total')} "
        f"(total_changed={disc.get('total_changed')}; attribution-only={disc.get('attribution_only')})",
        f"- **Player props affected:** {mi.get('affects_player_props')}",
        f"- **When corrected:** {disc.get('when_corrected')}"
        + (" (timing uncertain)" if disc.get("timing_uncertain") else ""),
        f"- **Record status:** {record.get('status')} / confidence {record.get('confidence')}",
        "",
        "**Why it matters for settlement:** " + (mi.get("reason") or ""),
        "",
    ]
    flags = [f"`{f}`" for f in (record.get("flags") or [])]
    if flags:
        lines.append("**Flags:** " + ", ".join(flags))
        lines.append("")
    lines.append("**Official sources**")
    for src in record.get("sources") or []:
        lines.append(f"- [{src.get('label')}]({src.get('url')}) "
                     f"_(evidence: {src.get('evidence')}; retrieved: {src.get('retrieved_at') or 'n/a'}"
                     + (f"; sha256 `{src.get('sha256')[:12]}`" if src.get("sha256") else "") + ")_")
    lines += ["", f"Record id: `{record.get('record_id')}` - "
                  "open each link and read the goal line before acting on this.", ""]
    return "\n".join(lines)


def render_digest(alerts: List[Dict[str, Any]], *, run_id: str = "", coverage: Optional[Dict[str, Any]] = None) -> str:
    head = [
        f"# Scoring discrepancy alerts ({len(alerts)})",
        "",
        f"Run `{run_id or 'local'}`. Every entry below is machine-detected from official NHL "
        "artifacts and carries its source links. Nothing here has been adjudicated by a human.",
        "",
    ]
    if coverage:
        head += [
            f"Scan coverage: {coverage.get('games_scanned', 0)} games scanned, "
            f"{coverage.get('games_parsed', 0)} parsed by both sources, "
            f"{coverage.get('games_unreadable', 0)} unreadable "
            f"(parser or source gap - those games are *not* cleared).",
            "",
        ]
    body = [render_record(item["record"], level=item["level"]) for item in alerts]
    tail = [
        "---",
        "",
        "### Limitations of this alert set",
        "- Silent post-game edits are only detectable when we polled the endpoint beforehand.",
        "- Cross-source findings cannot say which artifact is the corrected one, only that the "
        "league's two records disagree.",
        "- No public feed of official scoring corrections exists to monitor; see docs/FEASIBILITY.md.",
        "- Rule text (why the league changed something) usually lives only in a Situation Room "
        "statement or a beat report, which we do not auto-ingest.",
        "",
    ]
    return "\n".join(head + body + tail)


def webhook_payload(alerts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Slack/Discord-friendly payload (``text`` + ``content`` both present)."""
    text = "\n".join(
        f"*[{item['level']}]* {((item['record'].get('game') or {}).get('date'))} "
        f"{(item['record'].get('game') or {}).get('away_team')}@{(item['record'].get('game') or {}).get('home_team')}: "
        f"{(item['record'].get('discrepancy') or {}).get('summary')}"
        for item in alerts[:20]
    ) or "No new scoring discrepancies detected."
    return {"text": text, "content": text,
            "username": "NHL scoring discrepancy monitor",
            "_sdn": {"count": len(alerts),
                     "record_ids": [i["record"].get("record_id") for i in alerts]}}


def write_alerts(alerts: List[Dict[str, Any]], out_dir: str, *, date_str: str,
                 run_id: str = "", coverage: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    os.makedirs(os.path.join(out_dir, date_str), exist_ok=True)
    md_path = os.path.join(out_dir, date_str, "alerts.md")
    json_path = os.path.join(out_dir, date_str, "alerts.json")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(render_digest(alerts, run_id=run_id, coverage=coverage))
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump({"date": date_str, "run_id": run_id,
                   "count": len(alerts),
                   # level counts are duplicated into the payload so a CI shell step can
                   # gate on them without re-implementing triage in bash.
                   "immediate_count": sum(1 for a in alerts if a["level"] == "immediate"),
                   "review_count": sum(1 for a in alerts if a["level"] == "review"),
                   "info_count": sum(1 for a in alerts if a["level"] == "info"),
                   "coverage": coverage or {},
                   "alerts": [{"level": a["level"], "record": a["record"]} for a in alerts]},
                  fh, indent=2, ensure_ascii=False)
    return {"markdown": md_path, "json": json_path}


def issue_title(alerts: List[Dict[str, Any]]) -> str:
    if not alerts:
        return "NHL scoring discrepancy monitor: no new discrepancies"
    top = alerts[0]["level"].upper()
    return f"[{top}] {len(alerts)} NHL scoring discrepancy alert(s)"


def parse_situation_room_text(text: str) -> List[Dict[str, str]]:
    """Extract league-statement quotes that explain a ruling.

    Used only to attach human-supplied context to a record; never to create one.
    A record with no quote is fine, a record whose quote does not appear in the
    linked page is not.
    """
    out = []
    for match in re.finditer(r"[\u201c\"]([^\u201d\"]{40,600})[\u201d\"]", text or ""):
        quote = match.group(1).strip()
        if re.search(r"(goal|net|crease|review|challenge|scor|assist|awarded|no-goal|waived)", quote, re.I):
            out.append({"quote": quote})
    return out
