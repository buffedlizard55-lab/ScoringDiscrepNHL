#!/usr/bin/env python3
"""Regenerate data/discrepancies.csv from data/discrepancies.json.

Usage:  python3 scripts/build_csv.py

The JSON file is the single source of truth; the CSV is a derived artifact
kept for spreadsheet review. Run this whenever discrepancies.json changes.
"""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "discrepancies.json"
DST = ROOT / "data" / "discrepancies.csv"

COLUMNS = [
    "id", "date", "season", "away_team", "home_team", "period", "game_clock",
    "type", "category", "video_review", "correction_timing",
    "changed_goal_total", "attribution_changed", "market_impact",
    "evidence_status", "initial_ruling", "corrected_ruling", "reason",
    "sources", "evidence_notes",
]


def main() -> int:
    payload = json.loads(SRC.read_text(encoding="utf-8"))
    records = payload.get("records", [])
    if not records:
        print("No records found in discrepancies.json", file=sys.stderr)
        return 1

    with DST.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        for rec in records:
            row = {}
            for col in COLUMNS:
                value = rec.get(col)
                if col == "type":
                    row[col] = "|".join(value or [])
                elif col == "sources":
                    row[col] = " ; ".join(s.get("url", "") for s in value or [])
                elif isinstance(value, bool):
                    row[col] = "yes" if value else "no"
                elif value is None:
                    row[col] = ""
                else:
                    row[col] = value
            writer.writerow(row)

    print(f"Wrote {len(records)} records -> {DST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
