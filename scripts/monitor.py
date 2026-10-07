#!/usr/bin/env python3
"""NHL scoring-discrepancy monitor (standard library only).

Strategy: there is no official NHL "scoring corrections feed", so this script
snapshots official scoring state (scoreboard + play-by-play + boxscore) and
diffs it over time. Any change to goals/scorers/assists after a game first
appeared final is reported as a CANDIDATE discrepancy for human verification.

It never writes to docs/data/discrepancies.json by itself. Humans confirm each
candidate against an official source before it enters the database.

Usage:
    python scripts/monitor.py --check-recent 3        # re-check last 3 days
    python scripts/monitor.py --game 2024020204       # snapshot one game
    python scripts/monitor.py --self-test             # offline diff-logic test
"""

import argparse
import datetime as dt
import json
import os
import sys
import urllib.request
import urllib.error

API = "https://api-web.nhle.com/v1"
UA = {"User-Agent": "ScoringDiscrepNHL-monitor/0.1 (+https://github.com/buffedlizard55-lab/ScoringDiscrepNHL)"}

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SNAP_DIR = os.path.join(ROOT, "scripts", "snapshots")
DEFAULT_ALERTS = os.path.join(ROOT, "scripts", "alerts.json")


def get_json(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def score_for_date(date_str):
    """Return list of games from the scoreboard endpoint for YYYY-MM-DD."""
    data = get_json("%s/score/%s" % (API, date_str))
    games = []
    for day in data.get("games", []) or []:
        games.append(day)
    if not games and isinstance(data.get("gamesByDate"), list):
        for block in data["gamesByDate"]:
            games.extend(block.get("games", []) or [])
    return games


def extract_goals(pbp):
    """Normalize goal events from a play-by-play payload.

    Returns list of dicts: period, clock, scorer_id, assist_ids,
    away_score, home_score, event_id.
    """
    goals = []
    for play in pbp.get("plays", []) or []:
        if play.get("typeDescKey") != "goal":
            continue
        det = play.get("details", {}) or {}
        per = play.get("periodDescriptor", {}) or {}
        goals.append({
            "event_id": play.get("eventId"),
            "period": per.get("number"),
            "period_type": per.get("periodType"),
            "clock": play.get("timeInPeriod"),
            "scorer_id": det.get("scoringPlayerId"),
            "assist_ids": [det.get("assist1PlayerId"), det.get("assist2PlayerId")],
            "away_score": det.get("awayScore"),
            "home_score": det.get("homeScore"),
        })
    return goals


def snapshot_game(game_id):
    """Fetch live official state for one game and return a snapshot dict."""
    pbp = get_json("%s/gamecenter/%s/play-by-play" % (API, game_id))
    try:
        box = get_json("%s/gamecenter/%s/boxscore" % (API, game_id))
    except urllib.error.HTTPError as exc:
        box = {"_boxscore_error": "HTTP %s" % exc.code}
    game = pbp.get("game", {}) or {}
    return {
        "game_id": game_id,
        "fetched_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "game_state": game.get("gameState"),
        "away": (pbp.get("awayTeam") or {}).get("abbrev"),
        "home": (pbp.get("homeTeam") or {}).get("abbrev"),
        "goals": extract_goals(pbp),
        "linescore": box.get("linescore") if isinstance(box, dict) else None,
    }


def goal_key(g):
    return (g.get("period"), g.get("clock"), g.get("event_id"))


def diff_snapshots(old, new):
    """Diff two snapshots of the same game. Returns list of alert dicts."""
    alerts = []
    game_id = new.get("game_id")
    old_goals = {goal_key(g): g for g in old.get("goals", [])}
    new_goals = {goal_key(g): g for g in new.get("goals", [])}

    for key in sorted(set(new_goals) - set(old_goals), key=str):
        g = new_goals[key]
        alerts.append({
            "game_id": game_id,
            "alert_type": "GOAL_ADDED",
            "period": g.get("period"),
            "clock": g.get("clock"),
            "detail": "Goal now present (scorer_id=%s) that was absent in the previous snapshot." % g.get("scorer_id"),
            "old": None,
            "new": g,
        })
    for key in sorted(set(old_goals) - set(new_goals), key=str):
        g = old_goals[key]
        alerts.append({
            "game_id": game_id,
            "alert_type": "GOAL_REMOVED",
            "period": g.get("period"),
            "clock": g.get("clock"),
            "detail": "Goal present in previous snapshot (scorer_id=%s) is now absent." % g.get("scorer_id"),
            "old": g,
            "new": None,
        })
    for key in sorted(set(old_goals) & set(new_goals), key=str):
        o, n = old_goals[key], new_goals[key]
        if o.get("scorer_id") != n.get("scorer_id"):
            alerts.append({
                "game_id": game_id,
                "alert_type": "SCORER_CHANGED",
                "period": n.get("period"),
                "clock": n.get("clock"),
                "detail": "Scorer changed from %s to %s." % (o.get("scorer_id"), n.get("scorer_id")),
                "old": o,
                "new": n,
            })
        if o.get("assist_ids") != n.get("assist_ids"):
            alerts.append({
                "game_id": game_id,
                "alert_type": "ASSISTS_CHANGED",
                "period": n.get("period"),
                "clock": n.get("clock"),
                "detail": "Assists changed from %s to %s." % (o.get("assist_ids"), n.get("assist_ids")),
                "old": o,
                "new": n,
            })
        if (o.get("away_score"), o.get("home_score")) != (n.get("away_score"), n.get("home_score")):
            alerts.append({
                "game_id": game_id,
                "alert_type": "SCORE_STATE_CHANGED",
                "period": n.get("period"),
                "clock": n.get("clock"),
                "detail": "Score state changed from %s-%s to %s-%s." % (
                    o.get("away_score"), o.get("home_score"), n.get("away_score"), n.get("home_score")),
                "old": o,
                "new": n,
            })

    if alerts and str(new.get("game_state", "")).upper() in ("FINAL", "OFF"):
        for a in alerts:
            a["after_final"] = True
    return alerts


def load_snapshot(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return None


def save_snapshot(path, snap):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(snap, fh, indent=2, sort_keys=True)


def check_recent(days, snap_dir, alerts_out):
    """Snapshot all games from the last N days; diff vs stored snapshots."""
    today = dt.date.today()
    all_alerts = []
    checked = 0
    errors = []
    for back in range(days):
        day = (today - dt.timedelta(days=back)).isoformat()
        try:
            games = score_for_date(day)
        except Exception as exc:
            errors.append("%s: scoreboard fetch failed: %s" % (day, exc))
            continue
        for game in games:
            gid = game.get("id")
            if not gid:
                continue
            checked += 1
            path = os.path.join(snap_dir, "%s.json" % gid)
            old = load_snapshot(path)
            try:
                new = snapshot_game(gid)
            except Exception as exc:
                errors.append("%s: game fetch failed: %s" % (gid, exc))
                continue
            if old is not None:
                for alert in diff_snapshots(old, new):
                    alert["away"] = new.get("away")
                    alert["home"] = new.get("home")
                    alert["detected_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
                    all_alerts.append(alert)
            save_snapshot(path, new)

    result = {
        "checked_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "games_checked": checked,
        "alerts": all_alerts,
        "errors": errors,
    }
    with open(alerts_out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)
    print("Checked %d game-snapshots across last %d day(s)." % (checked, days))
    print("Alerts: %d. Errors: %d." % (len(all_alerts), len(errors)))
    for a in all_alerts:
        print("  [%s] game %s P%s %s: %s" % (
            a["alert_type"], a["game_id"], a.get("period"), a.get("clock"), a["detail"]))
    for e in errors:
        print("  [ERROR] %s" % e, file=sys.stderr)
    return result


def self_test():
    """Offline fixture test proving the diff logic works. No internet."""
    old = {
        "game_id": 2024020204,
        "game_state": "FINAL",
        "goals": [
            {"event_id": 101, "period": 3, "clock": "01:28", "scorer_id": 8471214,
             "assist_ids": [8470001, None], "away_score": 1, "home_score": 3},
            {"event_id": 102, "period": 2, "clock": "05:00", "scorer_id": 8470002,
             "assist_ids": [None, None], "away_score": 1, "home_score": 1},
        ],
    }
    new = {
        "game_id": 2024020204,
        "game_state": "FINAL",
        "goals": [
            {"event_id": 101, "period": 3, "clock": "01:28", "scorer_id": 8471214,
             "assist_ids": [8470001, 8470003], "away_score": 1, "home_score": 3},
            {"event_id": 103, "period": 1, "clock": "10:40", "scorer_id": 8470004,
             "assist_ids": [8470005, 8470006], "away_score": 0, "home_score": 1},
        ],
    }
    alerts = diff_snapshots(old, new)
    types = sorted(a["alert_type"] for a in alerts)
    assert "ASSISTS_CHANGED" in types, "missing ASSISTS_CHANGED: %s" % types
    assert "GOAL_ADDED" in types, "missing GOAL_ADDED: %s" % types
    assert "GOAL_REMOVED" in types, "missing GOAL_REMOVED: %s" % types
    assert all(a.get("after_final") for a in alerts), "after_final flag missing on FINAL game"
    n2 = json.loads(json.dumps(old))
    n2["goals"][0]["scorer_id"] = 8479999
    types2 = [a["alert_type"] for a in diff_snapshots(old, n2)]
    assert "SCORER_CHANGED" in types2, "missing SCORER_CHANGED: %s" % types2
    assert diff_snapshots(old, json.loads(json.dumps(old))) == [], "identical snapshots must not alert"
    print("self-test OK: ASSISTS_CHANGED, GOAL_ADDED, GOAL_REMOVED, SCORER_CHANGED detected; no false positives.")
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description="NHL scoring-discrepancy monitor")
    ap.add_argument("--check-recent", type=int, metavar="N",
                    help="snapshot + diff all games from the last N days")
    ap.add_argument("--game", type=int, help="snapshot a single game ID and print it")
    ap.add_argument("--snapshots-dir", default=DEFAULT_SNAP_DIR)
    ap.add_argument("--alerts-out", default=DEFAULT_ALERTS)
    ap.add_argument("--self-test", action="store_true", help="run offline diff-logic test")
    args = ap.parse_args(argv)

    if args.self_test:
        self_test()
        return 0
    if args.game:
        snap = snapshot_game(args.game)
        path = os.path.join(args.snapshots_dir, "%s.json" % args.game)
        old = load_snapshot(path)
        save_snapshot(path, snap)
        print(json.dumps(snap, indent=2)[:2000])
        if old is not None:
            alerts = diff_snapshots(old, snap)
            print("\nDiff vs previous snapshot: %d alert(s)." % len(alerts))
            for a in alerts:
                print("  [%s] P%s %s: %s" % (a["alert_type"], a.get("period"), a.get("clock"), a["detail"]))
        else:
            print("\nNo previous snapshot; stored baseline.")
        return 0
    if args.check_recent:
        check_recent(args.check_recent, args.snapshots_dir, args.alerts_out)
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
