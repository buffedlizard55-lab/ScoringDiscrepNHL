#!/usr/bin/env python3
"""Turn a season into a list of official game ids, one HTTP call per calendar day.

Why dates instead of a season-schedule endpoint: ``/v1/score/{YYYY-MM-DD}`` is the one
listing endpoint we verified returns 200 and carries the game array, so the backfill
depends on nothing that we have not confirmed exists. Ids are only accepted when they
match the official 10-digit shape; a day that will not parse is recorded in the state
file as a coverage hole instead of being skipped silently.

    python3 scripts/backfill.py --season 20002001 --max-dates 40 --out out/ids.txt
    python3 -m nhl_scoring.cli scan --games-file out/ids.txt --apply
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline"))

from nhl_scoring.fetch import Fetcher  # noqa: E402

GAME_ID_RE = re.compile(r"^\d{4}(0[1-9]|1[0-2])\d{4}$")


def season_window(season: str) -> tuple:
    start_year = int(season[:4])
    return date(start_year, 9, 1), date(start_year + 1, 7, 1)


def load_state(path: str) -> dict:
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return {"season": None, "next_date": None, "seen_games": [], "days_failed": [], "done": False}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--season", required=True, help="e.g. 20002001")
    ap.add_argument("--max-dates", type=int, default=40, help="calendar days to poll this run")
    ap.add_argument("--state", default=os.path.join("data", "backfill-state.json"))
    ap.add_argument("--out", default="out/ids.txt")
    ap.add_argument("--cache", default=os.environ.get("SDN_CACHE", "cache/raw"))
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    os.makedirs(os.path.dirname(args.state) or ".", exist_ok=True)
    start, end = season_window(args.season)
    state = load_state(args.state)
    if state.get("season") != args.season or state.get("done"):
        state = {"season": args.season, "next_date": start.isoformat(),
                 "seen_games": [], "days_failed": [], "done": False}
    seen = set(state.get("seen_games") or [])
    cursor = datetime.strptime(state["next_date"], "%Y-%m-%d").date()
    fetcher = Fetcher(cache_dir=args.cache, offline=args.offline, throttle_s=0.35)
    new_ids, days = [], 0
    while cursor <= end and days < args.max_dates:
        days += 1
        url = f"https://api-web.nhle.com/v1/score/{cursor.isoformat()}"
        payload, res = fetcher.get_json(url)
        if payload is None:
            # 404 on an off-day is normal; anything else is a coverage hole we keep.
            if res.status not in (404, 410):
                state["days_failed"].append({"date": cursor.isoformat(), "status": res.status,
                                             "error": res.error})
            cursor += timedelta(days=1)
            state["next_date"] = cursor.isoformat()
            continue
        games = payload.get("games") if isinstance(payload.get("games"), list) else []
        for game in games:
            gid = str(game.get("id") or "")
            if GAME_ID_RE.fullmatch(gid) and gid not in seen:
                seen.add(gid)
                new_ids.append(gid)
        cursor += timedelta(days=1)
        state["next_date"] = cursor.isoformat()
    if cursor > end:
        state["done"] = True
    state["seen_games"] = sorted(seen)
    with open(args.state, "w", encoding="utf-8") as fh:
        json.dump({"season": state["season"], "next_date": state["next_date"], "done": state["done"],
                   "games_found": len(seen), "days_failed": state["days_failed"][-40:],
                   "updated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}, fh, indent=2)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(new_ids) + ("\n" if new_ids else ""))
    print(f"backfill {args.season}: polled {days} day(s) up to {state['next_date']}, "
          f"{len(new_ids)} new game id(s) -> {args.out}; "
          f"{len(seen)} known so far; {len(state['days_failed'])} day(s) unreadable; done={state['done']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
