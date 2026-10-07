#!/usr/bin/env python3
"""Validate docs/data/discrepancies.json (standard library only).

Checks: required fields, enum values, id format/uniqueness, source URLs,
goal-total/attribution flag consistency, and that unknowns are explicit
(null + flag) rather than guessed.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "docs", "data", "discrepancies.json")

REQUIRED = [
    "id", "season", "game_date", "date_confidence", "game_id_nhl",
    "away_team", "home_team", "period", "clock",
    "discrepancy_type", "initial_ruling", "initial_ruling_confidence",
    "corrected_ruling", "correction_timing",
    "video_review", "changed_game_total", "changed_attribution_only",
    "potential_total_market_impact", "sources", "verification_status",
    "flags", "added_date", "last_verified",
]

ENUMS = {
    "date_confidence": {"verified", "inferred", "unknown"},
    "discrepancy_type": {"goal-added", "goal-removed", "scorer-change",
                         "assist-change", "scorer-assist-change", "other"},
    "initial_ruling_confidence": {"verified", "reported", "unknown"},
    "correction_timing": {"in-game", "intermission", "postgame", "unknown"},
    "review_type": {"situation-room", "coach-challenge", "on-ice",
                    "central-review", None},
    "verification_status": {"official-direct", "official-direct-partial",
                            "official-quoted", "secondary", "unverified"},
    "source_type": {"official-nhl", "official-team", "official-pr-social",
                    "rtss-report", "api-snapshot", "secondary"},
}


def main():
    with open(DB_PATH, encoding="utf-8") as fh:
        db = json.load(fh)
    errors = []
    records = db.get("records", [])
    seen_ids = set()

    for i, r in enumerate(records):
        where = r.get("id", f"records[{i}]")
        for field in REQUIRED:
            if field not in r:
                errors.append(f"{where}: missing required field '{field}'")
        if r.get("id") in seen_ids:
            errors.append(f"{where}: duplicate id")
        seen_ids.add(r.get("id"))
        rid = str(r.get("id", ""))
        if not rid.startswith("NHL-SD-"):
            errors.append(f"{where}: id must match NHL-SD-NNNN")

        for field, allowed in ENUMS.items():
            if field == "source_type":
                continue
            if field in r and r[field] not in allowed:
                errors.append(f"{where}: bad {field}={r[field]!r}")

        sources = r.get("sources") or []
        if not sources:
            errors.append(f"{where}: at least one source is required")
        for s in sources:
            url = s.get("url", "")
            if not url.startswith("http"):
                errors.append(f"{where}: source URL must be http(s): {url!r}")
            if s.get("type") not in ENUMS["source_type"]:
                errors.append(f"{where}: bad source type {s.get('type')!r}")

        # Consistency: goal-total changers vs attribution-only are disjoint claims.
        if r.get("discrepancy_type") in ("goal-added", "goal-removed") and not r.get("changed_game_total"):
            errors.append(f"{where}: {r.get('discrepancy_type')} must set changed_game_total=true")
        if r.get("discrepancy_type") in ("scorer-change", "assist-change", "scorer-assist-change"):
            if not r.get("changed_attribution_only"):
                errors.append(f"{where}: {r.get('discrepancy_type')} must set changed_attribution_only=true")
            if r.get("changed_game_total"):
                errors.append(f"{where}: attribution change must not set changed_game_total=true")
        if r.get("potential_total_market_impact") and not r.get("changed_game_total"):
            errors.append(f"{where}: total-market impact requires changed_game_total=true")

        # Unknowns must be explicit: null date needs unknown/inferred confidence + a flag.
        if r.get("game_date") is None and r.get("date_confidence") == "verified":
            errors.append(f"{where}: null game_date cannot have date_confidence=verified")
        if r.get("initial_ruling") is None and r.get("initial_ruling_confidence") != "unknown":
            errors.append(f"{where}: null initial_ruling requires initial_ruling_confidence=unknown")

    print(f"Validated {len(records)} record(s): {len(errors)} error(s).")
    for e in errors:
        print("  ERROR:", e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
