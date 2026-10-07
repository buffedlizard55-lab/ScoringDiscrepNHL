"""Point-in-time digests of live endpoints, and diffs between them.

This module exists because of one fact established in docs/FEASIBILITY.md: the
NHL mutates its public game data in place and publishes no correction notice,
so a post-game scoring change is *only* observable if somebody held the prior
bytes. Git history of ``data/snapshots/`` is what makes those claims provable
rather than asserted - each line carries the UTC wall-clock time we pulled it
and the sha256 of the payload we pulled.

Append-only JSONL, one file per game, one line per *state change* (plus a
baseline). We deliberately do not write a line for every poll: a season of
30-second polling for 1312 games is hundreds of megabytes of "nothing
happened", and the unchanged-poll count is preserved in ``polls.json`` instead,
which is what the latency analysis actually needs.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from .checks import Finding, diff_snapshots
from .models import SourceRecord
from .sources import GameRef

SNAPSHOT_DIR = "data/snapshots"


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def goal_digest(goal) -> Dict[str, Any]:
    scorer = goal.scorer
    return {
        "match_key": goal.match_key,
        "order": goal.order,
        "period": goal.period,
        "clock": goal.clock,
        "clock_seconds": goal.clock_seconds,
        "team": goal.team,
        "strength": goal.strength,
        "strength_raw": goal.strength_raw,
        "own_goal": goal.own_goal,
        "empty_net": goal.empty_net,
        "scorer": scorer.name if scorer else None,
        "scorer_key": scorer.key if scorer else None,
        "assists": [a.name for a in goal.assists],
        "assist_keys": sorted(a.name_key for a in goal.assists),
        "away_score": goal.away_score,
        "home_score": goal.home_score,
    }


def build_digest(record: SourceRecord, *, game_state: str = "", period: Any = None,
                 clock: str = "") -> Dict[str, Any]:
    goals = [goal_digest(g) for g in record.goals]
    body = {
        "game_id": record.game_id,
        "source": record.source,
        "away_score": record.away_score,
        "home_score": record.home_score,
        "goals": goals,
    }
    digest = hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()[:16]
    body.update({
        "digest": digest,
        "url": record.url,
        "sha256": record.sha256,
        "goal_count": len(goals),
        "game_state": game_state,
        "period": period,
        "clock": clock,
        "parse_ok": record.parse_ok,
        "parse_notes": record.parse_notes,
    })
    return body


def snapshot_path(game_id: str, root: str = SNAPSHOT_DIR) -> str:
    return os.path.join(root, f"{game_id}.jsonl")


def read_snapshots(game_id: str, root: str = SNAPSHOT_DIR) -> List[Dict[str, Any]]:
    path = snapshot_path(game_id, root)
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def record_snapshot(game: SourceRecord, *, digest: Optional[Dict[str, Any]] = None,
                    root: str = SNAPSHOT_DIR, game_state: str = "", period: Any = None,
                    clock: str = "", captured_at: str = "") -> Dict[str, Any]:
    """Append the game's state if (and only if) it differs from the last line.

    Returns ``{"written": bool, "reason": ...}`` so callers can log honestly.
    """
    digest = digest or build_digest(game, game_state=game_state, period=period, clock=clock)
    digest["captured_at"] = captured_at or digest.get("captured_at") or ""
    os.makedirs(root, exist_ok=True)
    path = snapshot_path(digest["game_id"], root)
    prior = read_snapshots(digest["game_id"], root)
    counters_path = os.path.join(root, "polls.json")
    counters: Dict[str, Any] = {}
    if os.path.exists(counters_path):
        try:
            with open(counters_path, "r", encoding="utf-8") as fh:
                counters = json.load(fh)
        except (OSError, json.JSONDecodeError):
            counters = {}
    key = digest["game_id"]
    entry = counters.setdefault(key, {"polls": 0, "states": 0, "last_digest": None,
                                      "first_seen": digest.get("captured_at"),
                                      "last_seen": digest.get("captured_at")})
    entry["polls"] = int(entry.get("polls") or 0) + 1
    entry["last_seen"] = digest.get("captured_at")
    same_state = bool(prior) and prior[-1].get("digest") == digest.get("digest")
    if not same_state:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(_canonical(digest) + "\n")
        entry["states"] = int(entry.get("states") or 0) + 1
    entry["last_digest"] = digest.get("digest")
    tmp = counters_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(counters, fh, indent=1, sort_keys=True)
    os.replace(tmp, counters_path)
    return {"written": not same_state, "path": path, "prior_states": len(prior),
            "digest": digest.get("digest"),
            "reason": "unchanged" if same_state else "state_change"}


def snapshots_for_game(game_id: str, root: str = SNAPSHOT_DIR) -> List[Dict[str, Any]]:
    return read_snapshots(game_id, root)


def find_temporal_findings(game_id: str, *, root: str = SNAPSHOT_DIR,
                           max_pairs: int = 100) -> List[Finding]:
    """Diff every consecutive pair of snapshots for one game.

    All pairs, not just the last two: a game can be corrected twice (once in
    the third period, once the next morning) and each transition is its own
    discrepancy with its own before/after evidence.
    """
    snaps = [s for s in read_snapshots(game_id, root) if s.get("parse_ok", True)]
    findings: List[Finding] = []
    for before, after in list(zip(snaps, snaps[1:]))[:max_pairs]:
        if before.get("source") != after.get("source"):
            continue
        findings.extend(diff_snapshots(before, after, game_id=game_id, url=after.get("url", "")))
    return findings


def all_snapshot_games(root: str = SNAPSHOT_DIR) -> List[str]:
    if not os.path.isdir(root):
        return []
    return sorted(fn[:-6] for fn in os.listdir(root) if fn.endswith(".jsonl"))


def poll_summary(root: str = SNAPSHOT_DIR) -> Dict[str, Any]:
    """Aggregate of what the monitor actually saw - feeds the latency claims."""
    counters_path = os.path.join(root, "polls.json")
    if not os.path.exists(counters_path):
        return {"games": 0, "polls": 0, "states": 0, "games_with_changes": 0}
    with open(counters_path, "r", encoding="utf-8") as fh:
        counters = json.load(fh)
    polls = sum(int(v.get("polls") or 0) for v in counters.values())
    states = sum(int(v.get("states") or 0) for v in counters.values())
    changed = sum(1 for v in counters.values() if int(v.get("states") or 0) > 1)
    return {"games": len(counters), "polls": polls, "states": states,
            "games_with_changes": changed,
            "coverage_note": "polls counts state-change writes only if unchanged polls were "
                             "recorded; see data/snapshots/polls.json"}
