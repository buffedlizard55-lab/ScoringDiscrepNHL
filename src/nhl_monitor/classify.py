"""Classification: turn raw diffs into a typed discrepancy record.

Everything here is derived from the observed official data - no heuristics are
allowed to invent facts. Where the data does not tell us something (for example the
exact wall-clock time a correction was published), the field is left ``null`` and a
flag is raised instead.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .state import Change, GameState, GoalEvent


# ----------------------------------------------------------------------------- #
# Taxonomy
# ----------------------------------------------------------------------------- #

#: Every discrepancy type the system can *prove* from official artifacts.
DISCREPANCY_TYPES = {
    "goal_to_no_goal": "A goal that appeared in the official record was later removed.",
    "no_goal_to_goal": "A goal absent from the official record was later added.",
    "scorer_change": "The credited goal scorer changed (goal count unchanged).",
    "assist_change": "The credited assists changed (goal count unchanged).",
    "strength_change": "The recorded strength (EV/PP/SH) of a goal changed.",
    "own_goal_flag_change": "The own-goal annotation of a goal changed.",
    "time_change": "The recorded clock of an existing goal moved (goal count unchanged).",
    "team_change": "The goal was reassigned to the other team - team totals, puck line and the "
                   "winner can change even though the game total cannot.",
    "multi_change": "More than one category of change on the same goal.",
    "metadata_change": "Non-scoring metadata changed (flagged for manual review).",
}

TIMING_VALUES = {
    "in_game": "Changed while the game was still in progress.",
    "intermission": "Changed between periods (feed reports the game in an intermission).",
    "postgame_before_validation": "Changed after the final horn but while the record was still being validated.",
    "postgame_after_publication": "Changed after the game record had been published as final.",
    "unknown": "Timing could not be established from the available evidence.",
}

#: Raw *change* types that move the number of goals (a game total, puck line,
#: moneyline or team total). NOTE: these are change-level names, not the
#: record-level ``DISCREPANCY_TYPES`` names - mixing them up silently disables
#: the whole total-impact logic (caught by the unit tests on 2026-10-07).
TOTAL_AFFECTING = {"goal_removed", "goal_added"}


def classify(changes: List[Change]) -> Dict[str, object]:
    """Reduce a change list to a single discrepancy classification."""
    kinds = [c.change_type for c in changes]
    structural = [k for k in kinds if k in ("goal_removed", "goal_added")]
    attribution = [k for k in kinds if k in ("scorer_change", "assist_change")]
    team_reassignment = [k for k in kinds if k == "team_change"]
    other = [k for k in kinds if k not in structural + attribution + team_reassignment]

    if not changes:
        dtype = "no_change"
    elif len(set(kinds)) > 1 and (structural or attribution or team_reassignment or other):
        dtype = "multi_change"
    elif "goal_removed" in kinds:
        dtype = "goal_to_no_goal"
    elif "goal_added" in kinds:
        dtype = "no_goal_to_goal"
    elif "scorer_change" in kinds:
        dtype = "scorer_change"
    elif "assist_change" in kinds:
        dtype = "assist_change"
    elif "strength_change" in kinds:
        dtype = "strength_change"
    elif "own_goal_flag_change" in kinds:
        dtype = "own_goal_flag_change"
    elif "team_change" in kinds:
        dtype = "team_change"
    elif "time_change" in kinds:
        dtype = "time_change"
    else:
        dtype = "metadata_change"

    return {
        "discrepancy_type": dtype,
        "counts": {
            "goals_removed": kinds.count("goal_removed"),
            "goals_added": kinds.count("goal_added"),
            "scorer_changes": kinds.count("scorer_change"),
            "assist_changes": kinds.count("assist_change"),
            "other_changes": len(other),
            "team_reassignments": len(team_reassignment),
        },
        "affects_goal_total": any(k in TOTAL_AFFECTING for k in kinds),
        "affects_team_assignment": bool(team_reassignment),
        "attribution_only": bool(changes) and not any(k in TOTAL_AFFECTING for k in kinds)
        and not other and not team_reassignment and not attribution_absent(changes),
        "needs_manual_review": bool(other),
    }


def attribution_absent(changes: List[Change]) -> bool:
    """True when nothing about who is credited changed (e.g. a time correction)."""
    return not any(c.change_type in ("scorer_change", "assist_change") for c in changes)


def infer_timing(before: Optional[GameState], after: GameState) -> Tuple[str, str]:
    """Best-effort timing of a correction, with the reasoning that produced it."""
    if before is None:
        return "unknown", "no previous official state was captured, so timing cannot be derived"
    st = (before.game_state or "").upper()
    if st in {"LIVE", "CRIT"} or (before.period and not _is_final(before)):
        if before.in_intermission:
            return "intermission", "previous capture shows the game in an intermission"
        return "in_game", f"previous capture shows an in-progress game (state={st or 'unknown'})"
    if _is_final(before):
        return ("postgame_after_publication",
                "previous capture already showed a completed game, so the change was published "
                "after the record was final")
    return "unknown", f"previous capture state {st or 'unknown'} is not interpretable"


def _is_final(state: GameState) -> bool:
    st = (state.game_state or "").upper()
    if st in {"OFF", "FINAL"}:
        return True
    return (state.game_state or "").upper() in {"", "OFF"} and bool(state.goals) and state.period in (3, 4, 5)


def settlement_assessment(classification: Dict[str, object], timing: str) -> Dict[str, object]:
    """Flag whether a correction *could* touch a settled market.

    This is an analytical flag, not a statement about any bookmaker's house rules.
    The reasoning is deliberately shown so a user can audit it. Book-specific
    settlement rules must be verified separately - see docs/LIMITATIONS.md.
    """
    affects_total = bool(classification.get("affects_goal_total"))
    re_teamed = bool(classification.get("affects_team_assignment"))
    if (affects_total or re_teamed) and timing in {"postgame_after_publication", "unknown"}:
        level = "high"
        why = (("The number of goals changed" if affects_total else
                "The goal was reassigned between the two teams")
               + " AND the change appeared after the game record had been published as final, so "
                 "game-total / team-total / puck-line grading could have been performed on the "
                 "superseded value.")
    elif affects_total or re_teamed:
        level = "medium"
        why = ("The number of goals changed, but the change appeared while the game was still "
               "in progress, so markets were normally graded from the final official record.")
    elif classification.get("attribution_only"):
        level = "attribution"
        why = ("Only player attribution changed. This cannot move a game total, but it can move "
               "goal-scorer / assist player-prop markets.")
    else:
        level = "low"
        why = "No scoring or attribution change was detected."
    return {
        "level": level,
        # over/under markets: only a goal being added or removed moves the game total
        "could_affect_game_total_market": affects_total,
        # team totals, puck line, moneylines: a re-teamed goal can flip the winner too
        "could_affect_team_markets": affects_total or re_teamed,
        "could_affect_player_props": bool(classification.get("counts", {}).get("scorer_changes"))
        or bool(classification.get("counts", {}).get("assist_changes")),
        "reasoning": why,
        "requires_book_specific_review": level in {"high", "attribution"},
    }


# ----------------------------------------------------------------------------- #
# Cross-source verification
# ----------------------------------------------------------------------------- #

def player_totals_from_goals(state: GameState) -> Dict[str, Dict[str, int]]:
    """Derive per-player goal/assist totals from a goal list."""
    totals: Dict[str, Dict[str, int]] = {}
    for g in state.goals:
        if g.period_type.upper().startswith("SO"):
            continue
        if g.scorer:
            key = _key(g.scorer.id, g.scorer.name)
            totals.setdefault(key, {"goals": 0, "assists": 0})["goals"] += 1
        for a in g.assists:
            key = _key(a.id, a.name)
            totals.setdefault(key, {"goals": 0, "assists": 0})["assists"] += 1
    return totals


def _key(pid: Optional[int], name: str) -> str:
    return f"id:{pid}" if pid else f"name:{name.strip().upper()}"


def crosscheck_player_totals(goal_state: GameState, box_state: GameState) -> List[dict]:
    """Compare per-player totals derived from goals with the official boxscore.

    Mismatches are *findings*, not errors: they mean two official renderings of the
    same game disagree and a human (or a later automated pass) must resolve it.
    """
    derived = player_totals_from_goals(goal_state)
    official = {}
    for p in box_state.evidence.get("player_totals", []) or []:
        official[_key(p.get("player_id"), p.get("name", ""))] = {
            "goals": int(p.get("goals") or 0),
            "assists": int(p.get("assists") or 0),
            "name": p.get("name"),
            "team": p.get("team"),
            "sweater": p.get("sweater"),
        }
    findings = []
    for key, off in official.items():
        der = derived.get(key)
        if der is None:
            if off["goals"] or off["assists"]:
                findings.append({
                    "player": off.get("name"), "team": off.get("team"), "sweater": off.get("sweater"),
                    "field": "goals+assists", "official": f"{off['goals']}G/{off['assists']}A",
                    "derived": "0G/0A", "note": "official totals exist but no goal event credits "
                                                "this player - possible attribution difference",
                })
            continue
        if der["goals"] != off["goals"] or der["assists"] != off["assists"]:
            findings.append({
                "player": off.get("name"), "team": off.get("team"), "sweater": off.get("sweater"),
                "field": "goals/assists",
                "official": f"{off['goals']}G/{off['assists']}A",
                "derived": f"{der['goals']}G/{der['assists']}A",
                "note": "play-by-play and boxscore disagree",
            })
    for key, der in derived.items():
        if key not in official and (der["goals"] or der["assists"]):
            findings.append({
                "player": key, "team": None, "sweater": None, "field": "goals/assists",
                "official": "0G/0A", "derived": f"{der['goals']}G/{der['assists']}A",
                "note": "play-by-play credits a player the boxscore does not list",
            })
    return findings


def team_total_crosscheck(goal_state: GameState, box_state: GameState) -> List[dict]:
    """Do the goal count and the published team score agree for the same source pair?"""
    findings = []
    for side in ("away", "home"):
        g = getattr(goal_state, side)
        b = getattr(box_state, side)
        if not g or not b:
            continue
        if g.score is not None and b.score is not None and g.score != b.score:
            findings.append({"team": g.abbrev, "field": "team_score",
                             "official": b.score, "derived": g.score,
                             "note": "goal count and published team score disagree"})
    return findings
