"""Promote a verified research lead from the inbox into the database.

Leads in docs/inbox/*.json are quarantined claims. Once a human has verified a
lead line-by-line against its cited official sources, this tool converts it into
a schema-compliant record. It refuses to invent any missing field — every
required value must be supplied explicitly (usually looked up from the official
NHL API/reports during verification), keeping the no-hallucination guarantee.

Usage:
  python3 -m pipeline.promote --list
  python3 -m pipeline.promote --lead-id 2025-03-08-NYR-OTT-soucy \
      --game-pk 2024021123 --season 20242025 --date 2025-03-08 \
      --away-tri NYR --home-tri OTT --period 1 --clock 08:37 --team OTT \
      --original-ruling no_goal --corrected-ruling goal \
      --types no_goal_to_goal,video_review_overturn --timing in_game \
      --reason "Situation Room: puck crossed the line (Rule 37.3(i))" \
      --evidence-url "https://www.nhl.com/news/new-york-rangers-ottawa-senators-video-review" \
      --evidence-label "NHL.com Video Review post" --evidence-kind situation_room
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from . import config, store, validate
from .records import record_id

INBOX_DIR = config.REPO_ROOT / "docs" / "inbox"


def load_leads() -> list[tuple[str, dict]]:
    """Return [(file_name, lead)] across all inbox files."""
    leads = []
    for path in sorted(INBOX_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for lead in data.get("records", []) or []:
            if isinstance(lead, dict):
                leads.append((path.name, lead))
    return leads


def find_lead(lead_id: str) -> tuple[str, dict] | None:
    for fname, lead in load_leads():
        if lead.get("id") == lead_id:
            return fname, lead
    return None


def build_record(args, lead: dict) -> dict:
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    types = [t.strip() for t in args.types.split(",") if t.strip()]
    family = "total" if any(t in types for t in
                            ("goal_to_no_goal", "no_goal_to_goal")) else "attrib"
    evidence = [{
        "label": args.evidence_label,
        "url": args.evidence_url,
        "kind": args.evidence_kind,
        "status": "verified",
        "captured_at": now_iso,
        "archive_url": None,
        "note": "Lead verified line-by-line by a human against this source.",
    }]
    # Preserve the lead's original citations as corroboration.
    for src in lead.get("sources", []) or []:
        url = src.get("url")
        if not url:
            continue
        evidence.append({
            "label": src.get("label") or url,
            "url": url,
            "kind": "secondary" if not src.get("official") else "other",
            "status": "verified" if src.get("official") else "incomplete",
            "captured_at": None,
            "archive_url": None,
            "note": "Original lead citation carried over from the inbox.",
        })
    rec = {
        "id": record_id(args.game_pk, args.period, args.team, args.ordinal, family),
        "status": "confirmed",
        "game": {
            "game_pk": args.game_pk,
            "season": args.season,
            "game_type": args.game_type,
            "date": args.date,
            "away": {"tri": args.away_tri, "name": args.away_name or args.away_tri},
            "home": {"tri": args.home_tri, "name": args.home_name or args.home_tri},
            "venue": None,
            "links": {},
        },
        "event": {
            "period": args.period,
            "period_type": None,
            "team": args.team,
            "goal_ordinal": args.ordinal,
            "description": None,
        },
        "original": {"ruling": args.original_ruling, "scorer": args.original_scorer,
                     "assists": [], "strength": None, "empty_net": None,
                     "clock": args.clock, "description": lead.get("initial_ruling")},
        "corrected": {"ruling": args.corrected_ruling, "scorer": args.corrected_scorer,
                      "assists": [], "strength": None, "empty_net": None,
                      "clock": args.clock, "description": lead.get("corrected_ruling")},
        "classification": {
            "changes_game_total": bool(lead.get("changed_goal_total")),
            "attribution_only": bool(lead.get("attribution_changed")
                                      or lead.get("changed_attribution_only")),
            "types": types,
            "timing": args.timing,
            "timing_confidence": "direct" if args.timing_direct else "heuristic",
            "reason": args.reason,
            "settlement_risk": bool(lead.get("changed_goal_total")),
        },
        "detection": {"method": "manual_verified", "first_detected_at": now_iso,
                      "detector_version": "promote.py"},
        "evidence": evidence,
        "flags": ["promoted_from_inbox", f"inbox_file:{args.inbox_file}"],
        "revisions": [{"at": now_iso,
                       "note": f"Promoted from inbox lead {lead.get('id')} after "
                               "line-by-line human verification."}],
    }
    return rec


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Promote a verified inbox lead")
    parser.add_argument("--list", action="store_true", help="list all leads")
    parser.add_argument("--lead-id")
    parser.add_argument("--game-pk", type=int)
    parser.add_argument("--season", help="8-digit season, e.g. 20242025")
    parser.add_argument("--game-type", default="R")
    parser.add_argument("--date", help="YYYY-MM-DD")
    parser.add_argument("--away-tri"), parser.add_argument("--away-name")
    parser.add_argument("--home-tri"), parser.add_argument("--home-name")
    parser.add_argument("--team", help="tri-code of the team affected")
    parser.add_argument("--period", type=int)
    parser.add_argument("--ordinal", type=int, default=1,
                        help="goal ordinal within period+team")
    parser.add_argument("--clock", help="MM:SS")
    parser.add_argument("--original-ruling", choices=["goal", "no_goal", "unknown"])
    parser.add_argument("--corrected-ruling", choices=["goal", "no_goal", "unknown"])
    parser.add_argument("--original-scorer"), parser.add_argument("--corrected-scorer")
    parser.add_argument("--types", help="comma-separated classification.types")
    parser.add_argument("--timing", choices=["in_game", "intermission",
                                              "postgame", "unknown"])
    parser.add_argument("--timing-direct", action="store_true")
    parser.add_argument("--reason")
    parser.add_argument("--evidence-url"), parser.add_argument("--evidence-label")
    parser.add_argument("--evidence-kind", default="official_report",
                        choices=["live_feed", "official_report", "situation_room",
                                 "schedule", "archive", "secondary", "other"])
    args = parser.parse_args(argv)

    if args.list:
        for fname, lead in load_leads():
            print(f"{lead.get('id'):<45} {fname}")
        return 0

    if not args.lead_id:
        parser.error("--lead-id required (or --list)")
    found = find_lead(args.lead_id)
    if not found:
        print(f"lead not found: {args.lead_id}", file=sys.stderr)
        return 2
    fname, lead = found
    args.inbox_file = fname

    record = build_record(args, lead)
    errors = validate.validate_record(record)
    if errors:
        print("Refusing to write an invalid record:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    now_iso = record["revisions"][0]["at"]
    db = store.load_discrepancies()
    outcome = store.upsert_record(db, record, now_iso)
    db["generated_at"] = now_iso
    db["generator"] = "pipeline.promote"
    store.save_discrepancies(db)
    print(f"{outcome}: {record['id']} (status={record['status']})")
    print("Lead remains in the inbox until manually removed after audit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
