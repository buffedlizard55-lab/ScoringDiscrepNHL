"""Alert construction, persistence (JSON + RSS), and GitHub Issue payloads."""

from __future__ import annotations

import hashlib
import html
import json
from email.utils import format_datetime
from datetime import datetime, timezone

from . import config


def _alert_hash(alert: dict) -> str:
    basis = json.dumps([alert.get("type"), alert.get("record_id"),
                        alert.get("title")], sort_keys=True)
    return hashlib.sha256(basis.encode()).hexdigest()[:16]


def make_alert(alert_type: str, title: str, body: str, record_id: str | None = None,
               links: list[str] | None = None, severity: str = "info",
               now_iso: str | None = None) -> dict:
    now_iso = now_iso or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    alert = {
        "type": alert_type,
        "severity": severity,
        "created_at": now_iso,
        "record_id": record_id,
        "title": title,
        "body": body,
        "links": links or [],
    }
    alert["id"] = _alert_hash(alert)
    return alert


def describe_record(record: dict) -> tuple[str, str]:
    """Human-readable (title, body) for a discrepancy record."""
    game = record.get("game") or {}
    away = (game.get("away") or {}).get("tri") or "?"
    home = (game.get("home") or {}).get("tri") or "?"
    cls = record.get("classification") or {}
    orig = record.get("original") or {}
    corr = record.get("corrected") or {}
    ev = record.get("event") or {}

    if cls.get("changes_game_total"):
        title = (f"[{game.get('date')}] {away}@{home} — goal ruling changed "
                 f"(P{ev.get('period')}): {orig.get('ruling')} -> {corr.get('ruling')}")
    else:
        bits = []
        if orig.get("scorer") != corr.get("scorer"):
            bits.append(f"scorer {orig.get('scorer')} -> {corr.get('scorer')}")
        if orig.get("assists") != corr.get("assists"):
            bits.append("assists changed")
        title = (f"[{game.get('date')}] {away}@{home} — scoring attribution corrected "
                 f"(P{ev.get('period')}): " + ("; ".join(bits) if bits else "fields changed"))

    lines = [
        f"Game: {away} @ {home} on {game.get('date')} (gamePk {game.get('game_pk')}, "
        f"season {game.get('season')})",
        f"Event: period {ev.get('period')}, clock {orig.get('clock') or corr.get('clock')}, "
        f"team {ev.get('team')}",
        f"Original:  ruling={orig.get('ruling')} scorer={orig.get('scorer')} "
        f"assists={orig.get('assists')} strength={orig.get('strength')}",
        f"Corrected: ruling={corr.get('ruling')} scorer={corr.get('scorer')} "
        f"assists={corr.get('assists')} strength={corr.get('strength')}",
        f"Types: {', '.join(cls.get('types', []))}",
        f"Timing: {cls.get('timing')} ({cls.get('timing_confidence')})",
        f"Changes game total: {cls.get('changes_game_total')}  |  "
        f"Settlement risk: {cls.get('settlement_risk')}",
    ]
    if cls.get("reason"):
        lines.append(f"Reason (from official review event): {cls.get('reason')}")
    lines.append("")
    lines.append("Evidence (official sources):")
    for e in record.get("evidence", []):
        lines.append(f"- {e.get('label')}: {e.get('url')} [{e.get('status')}]")
    flags = record.get("flags") or []
    if flags:
        lines.append("")
        lines.append(f"Flags: {', '.join(flags)}")
    lines.append("")
    lines.append("This record is automated and starts as pending_review; verify via "
                 "the evidence links before relying on it.")
    return title, "\n".join(lines)


def append_alerts(new_alerts: list[dict], now_iso: str) -> list[dict]:
    """Append new alerts to alerts.json (deduped by id) and rewrite the RSS feed.

    Returns only the alerts that were actually new.
    """
    from . import store

    db = store.load_alerts()
    existing_ids = {a.get("id") for a in db.get("alerts", [])}
    added = [a for a in new_alerts if a.get("id") not in existing_ids]
    if added:
        db["alerts"] = (added + db.get("alerts", []))[: config.ALERTS_MAX]
        db["generated_at"] = now_iso
        store.save_alerts(db)
        write_rss(db)
    return added


def write_rss(db: dict) -> None:
    from . import store

    items = []
    for alert in db.get("alerts", [])[:50]:
        created = alert.get("created_at") or ""
        try:
            dt = datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            pub = format_datetime(dt, usegmt=True)
        except ValueError:
            pub = created
        links_html = "".join(
            f'<p><a href="{html.escape(link)}">{html.escape(link)}</a></p>'
            for link in alert.get("links", [])
        )
        items.append(
            "    <item>\n"
            f"      <title>{html.escape(alert.get('title', ''))}</title>\n"
            f"      <guid isPermaLink=\"false\">sdnhl-{html.escape(alert.get('id', ''))}</guid>\n"
            f"      <pubDate>{pub}</pubDate>\n"
            f"      <description>{html.escape(alert.get('body', ''))}{links_html}</description>\n"
            "    </item>"
        )
    rss = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0">\n'
        "  <channel>\n"
        "    <title>ScoringDiscrepNHL alerts</title>\n"
        "    <link>https://github.com/buffedlizard55-lab/ScoringDiscrepNHL</link>\n"
        "    <description>Automated alerts for detected NHL scoring discrepancies and "
        "corrections. Every alert links to official-source evidence.</description>\n"
        f"    <lastBuildDate>{format_datetime(datetime.now(timezone.utc), usegmt=True)}</lastBuildDate>\n"
        + ("\n".join(items) + "\n" if items else "")
        + "  </channel>\n</rss>\n"
    )
    config.ALERTS_RSS_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.ALERTS_RSS_PATH.write_text(rss, encoding="utf-8")


def queue_issue(alert: dict, now_iso: str) -> None:
    """Append a GitHub Issue payload for CI to create (deduped via notify state)."""
    from . import store

    state = store.load_notify_state()
    if alert.get("id") in set(state.get("notified_alert_hashes", [])):
        return
    issues = store.load_json(config.PENDING_ISSUES_PATH, {"issues": []})
    issues.setdefault("issues", []).append({
        "title": f"[alert] {alert.get('title')}",
        "labels": ["scoring-alert", "automated"],
        "body": (alert.get("body") or "") + f"\n\nAlert id: {alert.get('id')} ({now_iso})",
    })
    store.save_json(config.PENDING_ISSUES_PATH, issues)
    state.setdefault("notified_alert_hashes", []).append(alert.get("id"))
    store.save_notify_state(state)
