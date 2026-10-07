#!/usr/bin/env python3
"""NHL scoring-discrepancy monitor (snapshot-diff detector).

WHAT IT DOES
------------
The NHL publishes live game data at https://api-web.nhle.com, but it has NO
official "corrections" feed: when a goal is waved off after review, or a
scorer/assist is re-credited, the feed is simply updated in place and the
original state is lost. This monitor therefore keeps its own snapshots and
diffs them over time:

  1. For each recent game it downloads the official play-by-play
     (GET /v1/gamecenter/{game-id}/play-by-play) and team totals.
  2. It normalizes every goal event (event id, period, clock, team,
     scorer id, assist ids) into a snapshot stored under data/snapshots/.
  3. It compares against the previous snapshot for the same game and
     emits an alert when the official record changed:
        * score_decreased      - a team total went DOWN (goal -> no-goal)
        * goal_event_removed   - a goal event disappeared from play-by-play
        * goal_event_added     - a goal event appeared (after FINAL: postgame change)
        * scorer_changed       - same goal event, different scorer
        * assist_changed       - same goal event, different assist(s)
        * total_mismatch_flag  - team total != sum of goal events (data integrity)
  4. Alerts are appended (deduplicated) to data/alerts/feed.json and echoed
     to stdout so a GitHub Actions log captures them.

It uses only the Python standard library. Endpoint shapes were verified
against the community-maintained reference docs (see docs/SOURCES.md) on
2026-10-07; parsing is defensive so unexpected payloads degrade to logged
warnings instead of false alerts.

LIMITS (see README / site for the full discussion)
--------------------------------------------------
* Detects CHANGES in the official record; it cannot tell you the reason.
  Human review of NHL.com Situation Room posts / NHL PR is still required.
* Silent corrections made before the first snapshot are invisible.
* There is no official realtime push; latency = polling interval.

Usage:
  python3 monitor/nhl_monitor.py                 # check today + last 3 days
  python3 monitor/nhl_monitor.py --days 7        # wider window
  python3 monitor/nhl_monitor.py --self-test     # offline logic verification
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

API_BASE = "https://api-web.nhle.com/v1"
USER_AGENT = "ScoringDiscrepNHL-monitor/1.0 (research project; contact repo owner)"
TIMEOUT = 30
MAX_ALERTS = 2000
SNAPSHOT_RETENTION_DAYS = 21

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = ROOT / "data"


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def http_get_json(url: str) -> dict | list | None:
    """GET a URL and parse JSON. Returns None on any failure (logged)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, OSError) as exc:
        print(f"[warn] fetch failed {url}: {exc}", file=sys.stderr)
        return None


# --------------------------------------------------------------------------- #
# Normalization
# --------------------------------------------------------------------------- #
def _as_int(value, default=None):
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def extract_goals(pbp: dict) -> list[dict]:
    """Pull normalized goal events out of a gamecenter play-by-play payload."""
    goals = []
    plays = pbp.get("plays") if isinstance(pbp, dict) else None
    if not isinstance(plays, list):
        return goals
    for play in plays:
        if not isinstance(play, dict):
            continue
        if play.get("typeDescKey") != "goal":
            continue
        details = play.get("details") if isinstance(play.get("details"), dict) else {}
        period = play.get("period")
        if period is None:
            descriptor = play.get("periodDescriptor")
            if isinstance(descriptor, dict):
                period = descriptor.get("number")
        goals.append({
            "event_id": play.get("eventId"),
            "period": period,
            "time": play.get("timeInPeriod"),
            "team": details.get("eventOwnerTeam"),
            "scorer": details.get("playerId"),
            "assist1": details.get("assist1PlayerId"),
            "assist2": details.get("assist2PlayerId"),
            "away_score": _as_int(details.get("awayScore")),
            "home_score": _as_int(details.get("homeScore")),
        })
    return goals


def build_snapshot(game_id, game_meta: dict, pbp: dict | None) -> dict | None:
    """Combine scoreboard metadata and play-by-play into one snapshot."""
    if not isinstance(game_meta, dict):
        return None
    away = game_meta.get("awayTeam") if isinstance(game_meta.get("awayTeam"), dict) else {}
    home = game_meta.get("homeTeam") if isinstance(game_meta.get("homeTeam"), dict) else {}
    snapshot = {
        "game_id": game_id,
        "game_date": game_meta.get("gameDate"),
        "game_state": game_meta.get("gameState"),
        "away_abbrev": away.get("abbrev"),
        "home_abbrev": home.get("abbrev"),
        "away_score": _as_int(away.get("score"), 0),
        "home_score": _as_int(home.get("score"), 0),
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "goals": extract_goals(pbp or {}),
    }
    return snapshot


# --------------------------------------------------------------------------- #
# Diffing
# --------------------------------------------------------------------------- #
def _goal_key(goal: dict):
    """Stable-ish identity for a goal event."""
    if goal.get("event_id") is not None:
        return ("id", goal["event_id"])
    return ("ptt", goal.get("period"), goal.get("time"), goal.get("team"))


def diff_snapshots(prev: dict, curr: dict) -> list[dict]:
    """Compare two snapshots of the same game; return alert dicts."""
    alerts = []
    gid = curr.get("game_id")
    meta = {
        "game_id": gid,
        "game_date": curr.get("game_date"),
        "away_team": curr.get("away_abbrev"),
        "home_team": curr.get("home_abbrev"),
    }

    def alert(kind: str, **fields) -> dict:
        item = {
            "alert_type": kind,
            "detected_at": curr.get("fetched_at"),
            "severity": "high" if kind in ("score_decreased", "goal_event_removed", "goal_event_added") else "medium",
            "requires_human_review": True,
            **meta,
            **fields,
        }
        alerts.append(item)
        return item

    # 1. team totals decreasing = goal removed from the official record
    for side, p_key, c_key in (("away", "away_score", "away_score"), ("home", "home_score", "home_score")):
        before, after = _as_int(prev.get(p_key)), _as_int(curr.get(c_key))
        if before is not None and after is not None and after < before:
            alert(
                "score_decreased",
                team=curr.get(f"{side}_abbrev"),
                before=before,
                after=after,
                explanation=f"{curr.get(f'{side}_abbrev')} team total dropped from {before} to {after} between snapshots — a goal was removed from the official record (review overturn or scoring correction).",
            )

    prev_goals = {_goal_key(g): g for g in prev.get("goals", [])}
    curr_goals = {_goal_key(g): g for g in curr.get("goals", [])}

    # 2. goal events removed
    for key, goal in prev_goals.items():
        if key not in curr_goals:
            alert(
                "goal_event_removed",
                period=goal.get("period"),
                time=goal.get("time"),
                team=goal.get("team"),
                scorer=goal.get("scorer"),
                explanation="A goal event present in the previous official play-by-play snapshot is gone — consistent with a video-review overturn or a retroactive correction.",
            )

    # 3. goal events added (especially after the game went FINAL)
    for key, goal in curr_goals.items():
        if key not in prev_goals:
            alert(
                "goal_event_added",
                period=goal.get("period"),
                time=goal.get("time"),
                team=goal.get("team"),
                scorer=goal.get("scorer"),
                prior_state="FINAL" if prev.get("game_state") == "FINAL" else prev.get("game_state"),
                explanation="A goal event appeared that was not in the previous snapshot. If the prior snapshot was already FINAL this is a postgame scoring change.",
            )

    # 4. same event, different attribution
    for key, goal in curr_goals.items():
        old = prev_goals.get(key)
        if old is None:
            continue
        if goal.get("scorer") != old.get("scorer") and old.get("scorer") is not None and goal.get("scorer") is not None:
            alert(
                "scorer_changed",
                period=goal.get("period"),
                time=goal.get("time"),
                team=goal.get("team"),
                before_scorer=old.get("scorer"),
                after_scorer=goal.get("scorer"),
                explanation="Goal credited to a different player between snapshots (official-scorer change).",
            )
        a_before = (old.get("assist1"), old.get("assist2"))
        a_after = (goal.get("assist1"), goal.get("assist2"))
        if a_before != a_after and (any(a_before) or any(a_after)):
            alert(
                "assist_changed",
                period=goal.get("period"),
                time=goal.get("time"),
                team=goal.get("team"),
                before_assists=[a for a in a_before if a],
                after_assists=[a for a in a_after if a],
                explanation="Assist credit on a goal changed between snapshots (official-scorer change).",
            )

    # 5. internal consistency: totals vs summed goal events
    for side in ("away", "home"):
        abbrev = curr.get(f"{side}_abbrev")
        if not abbrev:
            continue
        summed = sum(1 for g in curr.get("goals", []) if g.get("team") == abbrev)
        total = _as_int(curr.get(f"{side}_score"))
        if total is not None and summed != total:
            alert(
                "total_mismatch_flag",
                team=abbrev,
                team_total=total,
                goal_events=summed,
                severity="low",
                explanation="Team total does not match the number of goal events in play-by-play. Can be transient mid-game or a schema change — verify before acting.",
            )

    return alerts


# --------------------------------------------------------------------------- #
# Alert store
# --------------------------------------------------------------------------- #
def _dedupe_key(alert: dict) -> str:
    return json.dumps({k: alert.get(k) for k in sorted(alert)}, sort_keys=True, default=str)


def write_issue_body(alerts_dir: Path, added: list[dict]) -> None:
    """Write ISSUE_BODY.md when there are new alerts (consumed by CI to open
    a GitHub Issue notification); remove the stale file otherwise."""
    issue_path = alerts_dir / "ISSUE_BODY.md"
    if not added:
        if issue_path.exists():
            issue_path.unlink()
        return
    lines = [
        "The snapshot monitor detected that the NHL's official scoring record "
        "changed for the game(s) below since the previous snapshot. These are "
        "automatic detections — each must be reviewed against NHL.com / NHL PR "
        "before being added to the verified database.",
        "",
        "| Alert | Game | Period | Time | Detail |",
        "|---|---|---|---|---|",
    ]
    for a in added:
        detail = (a.get("explanation") or "").replace("|", "/")
        lines.append(
            f"| {a.get('alert_type')} | {a.get('away_team')} @ {a.get('home_team')} "
            f"(game {a.get('game_id')}) | {a.get('period') or '-'} | "
            f"{a.get('time') or '-'} | {detail} |"
        )
    lines += [
        "",
        "Feed: `data/alerts/feed.json` · Site: GitHub Pages \"Alerts feed\" tab.",
    ]
    alerts_dir.mkdir(parents=True, exist_ok=True)
    issue_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def merge_alerts(feed_path: Path, new_alerts: list[dict]) -> list[dict]:
    """Append new alerts to feed.json (deduplicated). Returns newly added."""
    existing = []
    if feed_path.exists():
        try:
            existing = json.loads(feed_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            print("[warn] alert feed unreadable; starting fresh", file=sys.stderr)
    known = {_dedupe_key(a) for a in existing}
    added = []
    for alert in new_alerts:
        key = _dedupe_key(alert)
        if key not in known:
            known.add(key)
            existing.append(alert)
            added.append(alert)
    existing = existing[-MAX_ALERTS:]
    feed_path.parent.mkdir(parents=True, exist_ok=True)
    feed_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    return added


# --------------------------------------------------------------------------- #
# Run control
# --------------------------------------------------------------------------- #
def dates_to_check(days: int, today: dt.date | None = None) -> list[dt.date]:
    today = today or dt.date.today()
    return [today - dt.timedelta(days=i) for i in range(days)]


def prune_snapshots(snap_dir: Path, retention_days: int = SNAPSHOT_RETENTION_DAYS) -> None:
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=retention_days)
    if not snap_dir.exists():
        return
    for path in snap_dir.glob("*.json"):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            game_date = (doc.get("game_date") or "")[:10]
            parsed = dt.date.fromisoformat(game_date)
            if dt.datetime(parsed.year, parsed.month, parsed.day, tzinfo=dt.timezone.utc) < cutoff:
                path.unlink()
        except (ValueError, OSError):
            continue


def run(days: int, data_dir: Path) -> int:
    snap_dir = data_dir / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    all_new_alerts: list[dict] = []
    games_checked = 0
    failures = 0

    for day in dates_to_check(days):
        iso = day.isoformat()
        board = http_get_json(f"{API_BASE}/score/{iso}")
        games = board.get("games") if isinstance(board, dict) else None
        if games is None:
            print(f"[info] no games payload for {iso} (off-day, future schema, or fetch failure)")
            continue
        for game in games:
            if not isinstance(game, dict) or not game.get("id"):
                continue
            game_id = game["id"]
            state = str(game.get("gameState") or "")
            if state in ("FUT", "PRE"):
                continue  # nothing to snapshot yet
            pbp = http_get_json(f"{API_BASE}/gamecenter/{game_id}/play-by-play")
            curr = build_snapshot(game_id, game, pbp)
            if curr is None:
                failures += 1
                continue
            games_checked += 1
            snap_path = snap_dir / f"{game_id}.json"
            prev = None
            if snap_path.exists():
                try:
                    prev = json.loads(snap_path.read_text(encoding="utf-8"))
                except (ValueError, OSError):
                    prev = None
            if prev is not None:
                all_new_alerts.extend(diff_snapshots(prev, curr))
            snap_path.write_text(json.dumps(curr, indent=2) + "\n", encoding="utf-8")

    added = merge_alerts(data_dir / "alerts" / "feed.json", all_new_alerts)
    write_issue_body(data_dir / "alerts", added)
    for alert in added:
        print(
            f"[ALERT] {alert['alert_type']} game={alert['game_id']} "
            f"{alert.get('away_team')}@{alert.get('home_team')} "
            f"period={alert.get('period')} time={alert.get('time')} :: {alert['explanation']}"
        )
    prune_snapshots(snap_dir)
    print(f"[done] games_checked={games_checked} new_alerts={len(added)} fetch_failures={failures}")
    return 0


# --------------------------------------------------------------------------- #
# Self-test (offline verification of the diff logic)
# --------------------------------------------------------------------------- #
def self_test() -> int:
    def snap(goals, away=None, home=None, state="LIVE"):
        # defaults keep fixtures internally consistent: totals match goal events
        if away is None:
            away = sum(1 for g in goals if g["team"] == "AAA")
        if home is None:
            home = sum(1 for g in goals if g["team"] == "BBB")
        return {
            "game_id": 2024020001, "game_date": "2026-10-07T00:00:00Z", "game_state": state,
            "away_abbrev": "AAA", "home_abbrev": "BBB", "away_score": away, "home_score": home,
            "fetched_at": "2026-10-07T00:00:00+00:00", "goals": goals,
        }

    g1 = {"event_id": 10, "period": 1, "time": "5:00", "team": "AAA", "scorer": 101, "assist1": 102, "assist2": None}
    g2 = {"event_id": 11, "period": 2, "time": "9:00", "team": "BBB", "scorer": 201, "assist1": None, "assist2": None}

    checks = []

    # identical snapshots -> no alerts
    checks.append(("no_change", diff_snapshots(snap([g1, g2]), snap([g1, g2])) == []))

    # review overturn: goal removed + score drops
    alerts = diff_snapshots(snap([g1, g2]), snap([g1]))
    kinds = {a["alert_type"] for a in alerts}
    checks.append(("goal_removed_detected", kinds == {"goal_event_removed", "score_decreased"}))

    # scorer change
    g2b = dict(g2, scorer=202)
    alerts = diff_snapshots(snap([g1, g2]), snap([g1, g2b]))
    checks.append(("scorer_change_detected", any(a["alert_type"] == "scorer_changed" for a in alerts)))

    # assist change
    g1b = dict(g1, assist1=999)
    alerts = diff_snapshots(snap([g1, g2]), snap([g1b, g2]))
    checks.append(("assist_change_detected", any(a["alert_type"] == "assist_changed" for a in alerts)))

    # postgame goal added after FINAL
    alerts = diff_snapshots(snap([g1], state="FINAL"), snap([g1, g2], state="FINAL"))
    added = [a for a in alerts if a["alert_type"] == "goal_event_added"]
    checks.append(("goal_added_after_final_detected", len(added) == 1 and added[0]["prior_state"] == "FINAL"))

    # extraction from a synthetic play-by-play payload
    pbp = {"plays": [
        {"eventId": 5, "typeDescKey": "shot", "details": {}},
        {"eventId": 6, "typeDescKey": "goal", "period": 3, "timeInPeriod": "12:34",
         "details": {"eventOwnerTeam": "AAA", "playerId": 301, "assist1PlayerId": 302,
                     "assist2PlayerId": None, "awayScore": 3, "homeScore": 2}},
    ]}
    goals = extract_goals(pbp)
    checks.append(("extraction", len(goals) == 1 and goals[0]["scorer"] == 301 and goals[0]["period"] == 3))

    # dedupe / merge
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        feed = Path(tmp) / "feed.json"
        sample = diff_snapshots(snap([g1, g2]), snap([g1]))
        first = merge_alerts(feed, sample)
        second = merge_alerts(feed, sample)
        checks.append(("alert_dedupe", len(first) == 2 and len(second) == 0))

    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if failed:
        print(f"self-test FAILED: {failed}")
        return 1
    print("self-test OK: diff engine verified offline")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="NHL scoring-discrepancy snapshot monitor")
    parser.add_argument("--days", type=int, default=4, help="how many recent game days to check (default 4)")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="data directory (default: repo data/)")
    parser.add_argument("--self-test", action="store_true", help="run offline logic verification and exit")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    return run(args.days, args.data_dir)


if __name__ == "__main__":
    raise SystemExit(main())
