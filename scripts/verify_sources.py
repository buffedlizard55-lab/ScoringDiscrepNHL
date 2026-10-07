#!/usr/bin/env python3
"""Re-check the source-availability claims this repository is built on.

docs/SOURCES.md and docs/FEASIBILITY.md make concrete claims of the form "this URL
returns 200 and contains an official artifact" and "this URL 404s, so coverage starts
where it starts". Those claims rot: the league moves and prunes files. This script
turns them into an executable check so CI notices before a human is misled.

Exit code: 0 when every expectation matched, 1 on any mismatch. Network is required;
with --offline it prints the expectation table and exits 0 so docs builds never break.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline"))

from nhl_scoring.fetch import Fetcher  # noqa: E402

# (expect_status, url, what it proves)
EXPECTATIONS = [
    (200, "https://www.nhl.com/scores/htmlreports/20002001/GS020001.HTM",
     "earliest official HTML report season (2000-01) is present"),
    (200, "https://www.nhl.com/scores/htmlreports/20152016/GS020001.HTM",
     "modern sheet layout still published"),
    (200, "https://www.nhl.com/scores/htmlreports/20262027/GS020001.HTM",
     "current season reports exist"),
    (404, "https://www.nhl.com/scores/htmlreports/19992000/GS020001.HTM",
     "coverage floor: 1999-2000 season directory has no GS file"),
    (404, "https://www.nhl.com/scores/htmlreports/19941995/GS020001.HTM",
     "coverage floor: mid-90s has no GS file"),
    (200, "https://api-web.nhle.com/v1/gamecenter/2000020001/landing",
     "game center JSON reaches back to 2000-01"),
    (200, "https://api-web.nhle.com/v1/gamecenter/1999020001/landing",
     "game center JSON reaches back to 1999-2000"),
    (200, "https://api-web.nhle.com/v1/gamecenter/2026020001/right-rail",
     "right rail exposes gameReports (the canonical link set)"),
    (200, "https://api-web.nhle.com/v1/score/2024-05-01",
     "daily scoreboard endpoint (backfill entry point)"),
    (404, "https://api-web.nhle.com/v1/club-schedule/COL/2026-10-01/2026-10-05",
     "documented dead end: that range pattern does not exist"),
    (404, "https://www.nhl.com/webapi/v1/statspdf",
     "documented dead end: retired statspdf endpoint"),
]

MUST_CONTAIN = {
    "https://www.nhl.com/scores/htmlreports/20002001/GS020001.HTM": ["SCORING SUMMARY"],
    "https://www.nhl.com/scores/htmlreports/20152016/GS020001.HTM": ["SCORING SUMMARY", "BY PERIOD"],
    "https://api-web.nhle.com/v1/gamecenter/2026020001/right-rail": ["gameReports"],
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--offline", action="store_true", help="print expectations only")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                                  "docs", "source-probe.json"))
    args = ap.parse_args()
    fetcher = Fetcher(cache_dir=os.environ.get("SDN_CACHE", "cache/raw"), offline=True, throttle_s=0.4)
    results = []
    failed = 0
    for expect, url, why in EXPECTATIONS:
        row = {"url": url, "expect": expect, "proves": why}
        if args.offline:
            row.update({"status": None, "match": None, "skipped": "offline"})
            results.append(row)
            continue
        body, res = fetcher.get_text(url)
        row.update({"status": res.status, "error": res.error, "sha256": res.sha256,
                    "retrieved_at": res.retrieved_at})
        row["match"] = res.status == expect
        needle_failures = []
        for needle in MUST_CONTAIN.get(url, []):
            if not (body and needle in body):
                needle_failures.append(needle)
        row["missing_markers"] = needle_failures
        if needle_failures:
            row["match"] = False
        if not row["match"]:
            failed += 1
            print(f"MISMATCH {url}: expected {expect}, got {res.status}"
                  + (f", missing markers {needle_failures}" if needle_failures else ""), file=sys.stderr)
        results.append(row)
    if args.offline:
        print(f"verify_sources: {len(EXPECTATIONS)} documented claims (offline, not checked)")
        return 0
    payload = {"generated_at": results[0].get("retrieved_at") if results else None,
               "checked": len(results), "mismatches": failed, "results": results}
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    print(f"verify_sources: {len(results)} claims checked, {failed} mismatch(es) -> {args.out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
