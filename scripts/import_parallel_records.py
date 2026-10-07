#!/usr/bin/env python3
"""Port the parallel monitor line's verified records into the engine database.

The repository grew two implementations of the same brief in parallel. The monitor
line finished three records from the NHL's own scoring-change announcements (path:
``data/records/discrepancies.json``); the engine line finished one cross-source
record plus pending leads (``data/discrepancies.json``). One database is the point of
this project, so the port is done *mechanically and losslessly* rather than by
retyping: the incoming record is mapped field by field, and the complete original
object is preserved under ``parallel_record`` so nothing a reader needs is only
available in git history.

    python3 scripts/import_parallel_records.py             # merge into data/discrepancies.json
    python3 scripts/import_parallel_records.py --dry-run   # show the mapping only
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))

from nhl_scoring import db as db_mod  # noqa: E402
from nhl_scoring import market  # noqa: E402

SRC = os.path.join(ROOT, "data", "records", "discrepancies.json")
DST = os.path.join(ROOT, "data", "discrepancies.json")

CHANGE_TYPE = {
    "scorer_change": "scorer_changed_by_official_announcement",
    "assist_change": "assists_changed_by_official_announcement",
    "goal_no_goal_change": "goal_no_goal_changed_by_official_announcement",
    "team_reassignment": "goal_reassigned_between_teams",
    "other": "official_scoring_change",
}
WHEN_MAP = {
    "in_game": "in_game",
    "during_game": "in_game",
    "intermission": "intermission",
    "postgame_after_publication": "postgame",
    "postgame": "postgame",
    "post_game": "postgame",
    "next_day": "next_day",
}
KIND_MAP = {
    "official-document": "official_report",
    "official-report": "official_report",
    "official-api": "official_api",
    "official-page": "official_page",
    "official-post": "official_page",
}


def _state(side: dict, event: dict, which: str) -> dict:
    scorer = side.get("scorer") or {}
    assists = side.get("assists")
    return {
        "artifact": f"monitor-line {which}",
        "goal_present": (side.get("ruling") or "").lower().startswith("goal"),
        "ruling": side.get("ruling"),
        "scorer": ({"name": scorer.get("name"), "number": scorer.get("sweater"),
                    "team": scorer.get("team")} if scorer else None),
        "assists": ([{"name": a.get("name"), "number": a.get("sweater"), "team": a.get("team")}
                     for a in assists] if isinstance(assists, list) else assists),
        "period": event.get("period"),
        "clock": event.get("clock"),
        "team": side.get("team") or event.get("team"),
        "strength": event.get("strength"),
        "evidence_status": side.get("evidence_status"),
        "evidence_note": side.get("evidence"),
    }


def _sources(raw: list) -> list:
    out = []
    for src in raw or []:
        stype = (src.get("type") or "").lower()
        role = (src.get("role") or "")
        url = src.get("url") or ""
        note_bits = [f"{k}={src[k]}" for k in ("document_generated_at", "role", "announcement_channel", "note")
                     if src.get(k)]
        official = stype.startswith("official")
        out.append({
            "label": src.get("name") or stype or "source",
            "url": url.replace("http://", "https://") if url.startswith("http://") else url,
            "kind": KIND_MAP.get(stype, "secondary" if stype else None),
            # The monitor line labels the pre-change credit as a syndicated
            # reproduction. That must not be promoted to "primary" by a converter:
            # evidence grade is about what the link itself is, not about the record.
            "evidence": "primary" if (official and "secondary" not in role.lower()
                                      and "initial" not in role.lower()) else "secondary",
            "retrieved_at": src.get("retrieved_at_utc") or src.get("retrieved_at"),
            "http_status": src.get("http_status"),
            "quote": src.get("quoted_row") or src.get("quote"),
            "note": "; ".join(note_bits) or None,
        })
    return out


def convert(raw: dict) -> dict:
    game_raw = raw.get("game") or {}
    event = raw.get("event") or {}
    change = raw.get("change") or {}
    timing = raw.get("timing") or {}
    settle = raw.get("settlement") or {}
    detection_raw = raw.get("detection") or {}
    reason_raw = raw.get("reason") or {}
    game_id = str(game_raw.get("game_id") or "")
    away = game_raw.get("away") or {}
    home = game_raw.get("home") or {}
    change_type = CHANGE_TYPE.get(change.get("discrepancy_type"), "official_scoring_change")
    is_scorer = "scorer" in change_type
    initial = _state(raw.get("initial_state") or {}, event, "initial state")
    corrected = _state(raw.get("corrected_state") or {}, event, "corrected state")
    sources = _sources(raw.get("sources"))

    stub = {"check_id": "PARALLEL",
            "rule": "scorer_attribution_conflict" if is_scorer else "assist_attribution_conflict",
            "field": "scorer" if is_scorer else "assists", "game_id": game_id}
    impact = dict(market.classify(stub) or {})
    impact.update({
        "affects_game_total": "yes" if change.get("affects_goal_total") else "no",
        "affects_result_markets": "possible" if change.get("affects_team_assignment") else "no",
        "affects_player_props": ("yes" if settle.get("could_affect_player_props")
                                 else impact.get("affects_player_props", "possible")),
        "risk": "high" if settle.get("level") != "attribution" else "medium",
        "reason": settle.get("reasoning") or impact.get("reason", ""),
        "rule_class": "attribution" if change.get("attribution_only")
                      else impact.get("rule_class", "unknown"),
    })
    verified = str(raw.get("evidence_status") or "").startswith("verified")
    return {
        "record_id": db_mod.compute_record_id(
            game_id, "PARALLEL", stub["field"],
            f"{event.get('period')}|{event.get('clock')}|{event.get('team')}"),
        "schema_version": db_mod.SCHEMA_VERSION,
        "status": "verified" if verified else "flagged",
        "confidence": {"high": "high", "medium": "medium"}.get(str(detection_raw.get("confidence")), "medium"),
        "detected_by": "manual_research",
        "detection": {
            "check_id": "PARALLEL",
            "rule": stub["rule"],
            "rule_label": "Official scoring-change announcement, cross-checked against the "
                          "corrected-state artifacts",
            "severity": "medium" if change.get("attribution_only") else "high",
            "detected_at": detection_raw.get("detected_at_utc"),
            "run_id": f"ported-from:{raw.get('case_id', '')}",
            "tool_version": detection_raw.get("detected_by", "nhl_monitor"),
            "when_corrected": WHEN_MAP.get(timing.get("when"), "postgame"),
            "method": detection_raw.get("method"),
            "sources_compared": detection_raw.get("source_keys_compared"),
        },
        "game": {
            "game_id": game_id or None,
            "season": game_raw.get("season"),
            "game_type": "PO" if game_id[4:6] == "03" else "REG",
            "date": game_raw.get("date"),
            "away_team": away.get("abbrev"),
            "home_team": home.get("abbrev"),
            "venue": None,
            "final_score": {"away": away.get("score"), "home": home.get("score")},
            "gamecenter_url": f"https://www.nhl.com/gamecenter/{game_id}" if game_id else None,
            "report_urls": {os.path.basename(u["url"]).split(".")[0]: u["url"]
                            for u in sources if "htmlreports" in (u.get("url") or "")},
        },
        "discrepancy": {
            "period": event.get("period"),
            "clock": event.get("clock"),
            "team": event.get("team"),
            "field": stub["field"],
            "goal_key": f"{event.get('period')}|{event.get('clock')}|{event.get('team')}",
            "change_type": change_type,
            "summary": change.get("detail") or raw.get("case_id") or "official scoring change",
            "detail": change.get("detail"),
            "total_changed": bool(change.get("affects_goal_total")),
            "attribution_only": bool(change.get("attribution_only")),
            "goal_no_goal_change": bool(change.get("affects_goal_total")),
            "video_review": False,
            "when_corrected": WHEN_MAP.get(timing.get("when"), "postgame"),
            "timing_uncertain": not bool(timing.get("announced_at_utc")),
            "announced_at_utc": timing.get("announced_at_utc"),
            "announced_on": timing.get("announced_on"),
            "latency_note": timing.get("game_end_time_note"),
            "counts": change.get("counts"),
            "machine_diff": change.get("machine_diff"),
            "declared_changes": change.get("declared_changes"),
            "reason": {
                "stated_by_league": True,
                "text": reason_raw.get("text"),
                "rule_citation": None,
                "needs_human_read": False,
                "channel": reason_raw.get("announcement_channel"),
                "note": reason_raw.get("note"),
                "category": reason_raw.get("category"),
            },
            "market_impact": impact,
        },
        "initial_state": initial,
        "corrected_state": corrected,
        "totals": {
            "initial_game_goals": None, "corrected_game_goals": None, "goal_delta": 0,
            "basis": "official announcement changed attribution only; the goal count is "
                     "unchanged in both artifacts",
        },
        "sources": sources,
        "verification": {
            # validate() requires verification.status to mirror the record status; the
            # monitor line's own richer status string is kept verbatim one level down.
            "status": "verified" if verified else "flagged",
            "upstream_status": raw.get("status"),
            "evidence_grade": "primary",
            "independently_checkable": True,
            "check_instructions": "Open each source link: the report row and the play-by-play event "
                                  "must match the corrected state, and the league's own announcement "
                                  "must state the change. The pre-change credit rests on what "
                                  "initial_state.evidence_note describes - read it before treating "
                                  "the before-state as fully evidenced.",
            "verified_by": f"nhl_monitor statement ingest + artifact cross-check ({detection_raw.get('detected_by', '')})",
            "verified_at": (detection_raw.get("detected_at_utc") or "")[:10],
            "completeness": raw.get("completeness"),
            "revision": raw.get("revision"),
        },
        "flags": sorted(set((raw.get("flags") or []) + ["ported_from_parallel_line"])),
        "notes": (((raw.get("notes") or "") +
                   " [ported 2026-10-07 by scripts/import_parallel_records.py from "
                   "data/records/discrepancies.json; the monitor line's full object is preserved "
                   "under parallel_record]").strip()),
        "parallel_record": raw,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--src", default=SRC)
    ap.add_argument("--dst", default=DST)
    args = ap.parse_args()

    if not os.path.exists(args.src):
        print(f"nothing to port: {args.src} is absent")
        return 0
    with open(args.src, encoding="utf-8") as fh:
        incoming_raw = json.load(fh).get("records") or []
    converted = [convert(raw) for raw in incoming_raw]
    bad = {}
    for rec in converted:
        problems = db_mod.validate(rec)
        if problems:
            bad[rec["record_id"]] = problems
    for rid, problems in bad.items():
        print(f"INVALID {rid}: {problems}", file=sys.stderr)
    if bad:
        return 1
    existing = db_mod.load_db(args.dst) if os.path.exists(args.dst) else {"records": []}
    merged, stats = db_mod.upsert(existing.get("records") or [], converted)
    print(f"port: {len(converted)} record(s) from {os.path.relpath(args.src, ROOT)} -> "
          f"{stats}, {len(merged)} total in the database")
    for rec in converted:
        print(f"  {rec['record_id']} {rec['status']:8} {rec['game']['date']} "
              f"{rec['game']['away_team']}@{rec['game']['home_team']} "
              f"{rec['discrepancy']['change_type']} sources={len(rec['sources'])}")
    if args.dry_run:
        print("(dry run: nothing written)")
        return 0
    db_mod.save_db({"schema_version": db_mod.SCHEMA_VERSION,
                    "generator": "scripts/import_parallel_records.py + nhl_scoring.cli",
                    "records": merged}, args.dst)
    db_mod.write_csv(merged, os.path.join(os.path.dirname(args.dst), "discrepancies.csv"))
    print(f"wrote {args.dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
