"""Alert generation.

An alert is a claim about the official record that must be auditable later, so it
always carries: what changed, when each state was captured, and the exact official
URLs. Alerts are written to ``data/alerts/`` and can additionally be pushed to a
GitHub Issue (the durable, reviewable notification channel used by the scheduled
workflow).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Dict, List, Optional

from . import store

ALERTS_DIR = os.path.join(store.REPO_ROOT, "data", "alerts")


def severity_for(record: dict) -> str:
    change = record.get("change", {})
    settlement = record.get("settlement", {})
    if change.get("affects_goal_total") and settlement.get("level") == "high":
        return "critical"
    if change.get("affects_goal_total"):
        return "high"
    if change.get("attribution_only"):
        return "medium"
    return "low"


def format_record_markdown(record: dict) -> str:
    g = record.get("game", {})
    ev = record.get("event", {})
    change = record.get("change", {})
    before = record.get("initial_state", {})
    after = record.get("corrected_state", {})
    lines = [
        f"**{g.get('away', {}).get('abbrev')} @ {g.get('home', {}).get('abbrev')}** — "
        f"{g.get('date')} (game {g.get('game_id')}, season {g.get('season')})",
        "",
        f"- Event: {ev.get('period_type')} period {ev.get('period')} at {ev.get('clock')} "
        f"({ev.get('strength') or 'strength unknown'}), team {ev.get('team')}",
        f"- Type: `{change.get('discrepancy_type')}` — affects goal total: "
        f"**{change.get('affects_goal_total')}** / attribution only: **{change.get('attribution_only')}**",
        f"- Timing: `{record.get('timing', {}).get('when')}` — {record.get('timing', {}).get('reasoning')}",
        "",
        "**Initial ruling (as previously published)**",
        f"- {_describe(before)}",
        "",
        "**Corrected ruling**",
        f"- {_describe(after)}",
        "",
        f"**What changed:** {change.get('detail')}",
        "",
        "**Why (official statements only):** "
        + (record.get("reason", {}).get("text")
           or "_No official statement of the reason was found in the retrieved artifacts._"),
        "",
        f"**Settlement relevance:** {record.get('settlement', {}).get('level')} — "
        f"{record.get('settlement', {}).get('reasoning')}",
        "",
        f"**Evidence status:** `{record.get('evidence_status')}`"
        + (f" | flags: {', '.join(record.get('flags', []))}" if record.get("flags") else ""),
        "",
        "**Official sources**",
    ]
    for s in record.get("sources", []):
        lines.append(f"- [{s.get('role')}] {s.get('name')} — {s.get('url')} "
                     f"(HTTP {s.get('http_status', '?')}, retrieved {s.get('retrieved_at_utc', '?')})")
    lines.append("")
    lines.append(f"_Record id `{record.get('record_id')}` · detected "
                 f"{record.get('detection', {}).get('detected_at_utc')} by "
                 f"{record.get('detection', {}).get('detected_by')} · status "
                 f"`{record.get('status')}`_")
    return "\n".join(lines)


def _describe(blob: dict) -> str:
    ruling = blob.get("ruling", "unknown")
    if ruling == "no_goal":
        return "No goal credited (the event is absent from the official scoring record)."
    scorer = blob.get("scorer") or {}
    assists = blob.get("assists") or []
    who = scorer.get("name") or "unknown"
    sweater = f"#{scorer.get('sweater')} " if scorer.get("sweater") else ""
    ast = ", ".join((a.get("name") or "?") for a in assists) or "unassisted"
    return f"Goal credited to {sweater}{who} (assists: {ast}), strength {blob.get('strength') or 'unknown'}"


def build_alert(record: dict) -> dict:
    return {
        "alert_id": f"ALERT-{record.get('record_id')}",
        "record_id": record.get("record_id"),
        "created_at_utc": store.utcnow(),
        "severity": severity_for(record),
        "discrepancy_type": record.get("change", {}).get("discrepancy_type"),
        "affects_goal_total": record.get("change", {}).get("affects_goal_total"),
        "title": _title(record),
        "body_markdown": format_record_markdown(record),
        "official_urls": [s.get("url") for s in record.get("sources", [])],
    }


def _title(record: dict) -> str:
    g = record.get("game", {})
    ev = record.get("event", {})
    change = record.get("change", {})
    kind = change.get("discrepancy_type")
    subject = {
        "goal_to_no_goal": "Goal removed from official record",
        "no_goal_to_goal": "Goal added to official record",
        "scorer_change": "Goal scorer changed",
        "assist_change": "Assists changed",
        "strength_change": "Goal strength changed",
        "own_goal_flag_change": "Own-goal annotation changed",
        "multi_change": "Multiple scoring changes",
        "metadata_change": "Non-scoring metadata changed",
    }.get(kind, "Scoring discrepancy detected")
    return (f"[{severity_for(record).upper()}] {subject}: "
            f"{g.get('away', {}).get('abbrev')} @ {g.get('home', {}).get('abbrev')} "
            f"{g.get('date')} — {ev.get('period_type')} P{ev.get('period')} {ev.get('clock')}")


def write_alerts(alerts: List[dict], *, root: str = ALERTS_DIR) -> List[str]:
    """Write one file per alert, preserving the first time the alert was raised.

    Re-detecting the same change (a backfill re-run, a re-ingest) must not make the
    alert look new: ``created_at_utc`` is kept from the existing file and the re-emit
    is recorded separately, so the feed cannot be used to fake recency.
    """
    os.makedirs(root, exist_ok=True)
    paths = []
    for a in alerts:
        path = os.path.join(root, f"{a['alert_id']}.json")
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    existing = json.load(fh)
                if existing.get("created_at_utc"):
                    a.setdefault("first_seen_at_utc", existing["created_at_utc"])
                    a["created_at_utc"] = existing["created_at_utc"]
                a["last_emitted_at_utc"] = store.utcnow()
            except Exception:
                pass
        with open(path, "w") as fh:
            json.dump(a, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        paths.append(path)
    return paths


def emit_for_records(records, *, root: str = ALERTS_DIR, github_issue: bool = False,
                     repo: Optional[str] = None, dry_run: bool = False) -> dict:
    """One alert per record, index refreshed - the single alerting entry point.

    Every detection route (live monitor, the league's own announcements, and both
    backfill methods) calls this, so a discrepancy cannot reach the database without
    reaching the feed. See docs/DETECTION.md.
    """
    emitted = [build_alert(r) for r in records]
    out = {"alerts": emitted, "paths": [], "issues": [], "index": None}
    if not emitted or dry_run:
        return out
    out["paths"] = write_alerts(emitted, root=root)
    out["index"] = write_alert_index(root=root)
    if github_issue:
        for a in emitted:
            out["issues"].append(open_github_issue(a["title"], a["body_markdown"], repo=repo))
    return out


def write_alert_index(*, root: str = ALERTS_DIR) -> List[str]:
    """Write data/alerts/index.json (a static site cannot glob a directory)."""
    os.makedirs(root, exist_ok=True)
    alerts = []
    for name in sorted(os.listdir(root)):
        if not name.endswith(".json") or name == "index.json":
            continue
        try:
            with open(os.path.join(root, name)) as fh:
                alerts.append(json.load(fh))
        except Exception as exc:  # pragma: no cover
            alerts.append({"alert_id": name, "error": f"unreadable: {exc}"})
    index = {
        "generated_at_utc": store.utcnow(),
        "count": len(alerts),
        "counts_by_severity": {
            sev: sum(1 for a in alerts if a.get("severity") == sev)
            for sev in ("critical", "high", "medium", "low")
        },
        "alerts": sorted(alerts, key=lambda a: a.get("created_at_utc", ""), reverse=True),
    }
    path = os.path.join(root, "index.json")
    with open(path, "w") as fh:
        json.dump(index, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return [path]


def open_github_issue(title: str, body: str, *, labels: Optional[List[str]] = None,
                      repo: Optional[str] = None) -> Dict[str, object]:
    """Create a GitHub issue as the durable notification channel.

    Returns ``{"created": bool, "url": str|None, "reason": str}``. If ``gh`` is not
    available or not authenticated the alert is still written to disk; the caller
    must report the failure rather than pretend a notification was delivered.
    """
    if not shutil.which("gh"):
        return {"created": False, "url": None, "reason": "gh CLI not available in this environment"}
    cmd = ["gh", "issue", "create", "--title", title, "--body", body]
    for label in labels or ["scoring-discrepancy", "auto-detected"]:
        cmd += ["--label", label]
    if repo:
        cmd += ["--repo", repo]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    except Exception as exc:  # pragma: no cover - environment dependent
        return {"created": False, "url": None, "reason": f"{type(exc).__name__}: {exc}"}
    if proc.returncode != 0:
        return {"created": False, "url": None,
                "reason": (proc.stderr or proc.stdout or "gh issue create failed").strip()[:500]}
    return {"created": True, "url": (proc.stdout or "").strip(), "reason": ""}
