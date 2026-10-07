"""Market-impact triage.

The question the project has to answer for every record is not "was the ruling
wrong" but "could this change a settled or settling market". Those are
different claims and they need different evidence:

* Only a change in the **number of goals** can move a game-total / period-total
  market. Attribution edits cannot.
* An attribution-only edit *can* move player props (anytime goal scorer,
  points, assists) and season-leader/award style markets.
* A goal that was scored and stayed scored, but whose credit moved, leaves the
  result markets (money line, puck line, head-to-head) untouched.

We therefore separate ``total_changed`` (a fact about the record) from
``market_risk`` (a judgement about consequence), and never imply a market was
actually mis-settled - sportsbooks settle off their own source of record, which
is not the NHL box score. That caveat is part of the record, not a footnote.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

#: rules where the number of goals in the game is the thing in dispute
TOTAL_AFFECTING_RULES = {
    "goal_missing_from_one_source",
    "post_snapshot_goal_count_change",
    "goal_total_mismatch",
    "missing_goal_event",
    "final_score_conflict",
    "final_score_mismatch",
    "score_sequence_mismatch",
}

#: rules where the goal stands but the credit moved
ATTRIBUTION_ONLY_RULES = {
    "assist_attribution_conflict",
    "scorer_attribution_conflict",
    "post_snapshot_attribution_change",
    "own_goal_classification_conflict",
    "counter_mismatch",
}

#: rules about when the goal happened
CLOCK_RULES = {"goal_clock_conflict", "post_snapshot_clock_change", "clock_invalid"}


def _rule(finding: Any) -> str:
    return getattr(finding, "rule", None) or (finding or {}).get("rule", "")


def _field(finding: Any) -> str:
    return getattr(finding, "field", None) or (finding or {}).get("field", "")


def _get(finding: Any, name: str, default: Any = None) -> Any:
    return getattr(finding, name, default) if not isinstance(finding, dict) else finding.get(name, default)


def classify(finding: Any) -> Dict[str, Any]:
    """Return the market-impact block for a finding or a stored record."""
    rule = _rule(finding)
    field = _field(finding)
    total_changed: Optional[bool] = None
    if rule == "post_snapshot_goal_count_change":
        total_changed = True
    elif rule == "goal_missing_from_one_source":
        # One official artifact carries the goal, the other does not. Whether
        # the league's settlement-facing total moved is not knowable from the
        # two documents alone, so this is 'possible', not True.
        total_changed = None
    elif rule in ATTRIBUTION_ONLY_RULES:
        total_changed = False
    elif rule in CLOCK_RULES:
        total_changed = False
    if field == "final_score" or field == "goal_count":
        total_changed = None if rule == "goal_total_mismatch" else True
    if field in ("goal_removed", "goal_added"):
        total_changed = True

    game_total = "possible" if total_changed is None else ("yes" if total_changed else "no")
    props = "yes" if rule in ATTRIBUTION_ONLY_RULES or field == "attribution" else (
        "possible" if rule in TOTAL_AFFECTING_RULES else "no")
    result_markets = "yes" if game_total == "yes" else ("possible" if game_total == "possible" else "no")

    notes = []
    if game_total == "yes":
        notes.append("Goal count in dispute or changed: a 3-goal line could settle differently "
                     "than the 2-goal or 4-goal state.")
    elif game_total == "possible":
        notes.append("Two official records disagree on the existence of a goal. Until the league's "
                     "final box score is reconciled, a game-total market on this game is exposed.")
    else:
        notes.append("Goal total unaffected: the number of goals is identical in both records; only "
                     "credit or timing moved.")
    if props == "yes":
        notes.append("Player-prop exposure: anytime-scorer / points / assist markets turn on who is "
                     "credited, not on how many goals were scored.")
    notes.append("NHL box scores are not a sportsbook source of record. This is an exposure flag for "
                 "review, not a claim that any market was mis-settled.")

    risk = "high"
    if rule in ("post_snapshot_goal_count_change",) or (game_total == "yes" and rule in TOTAL_AFFECTING_RULES):
        risk = "high"
    elif game_total == "possible":
        risk = "high" if rule == "goal_missing_from_one_source" else "medium"
    elif props == "yes":
        risk = "medium"
    elif rule in CLOCK_RULES:
        risk = "low"
    else:
        risk = "low"

    return {
        "total_changed": total_changed,
        "affects_game_total": game_total,
        "affects_period_total": game_total,
        "affects_player_props": props,
        "affects_result_markets": result_markets,
        "risk": risk,
        "reason": " ".join(notes),
        "rule_class": ("total" if rule in TOTAL_AFFECTING_RULES
                       else "attribution" if rule in ATTRIBUTION_ONLY_RULES
                       else "timing" if rule in CLOCK_RULES
                       else "structural"),
    }
