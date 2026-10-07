"""Discrepancy checks.

Three engines, in descending order of what they can prove:

``C10..C16`` **cross-source** - the same goal as recorded by two official
artifacts (live JSON vs the RTSS sheet). This is the only check that can expose
historical corrections without us having been watching the game, because the RTSS
sheet is a frozen post-game rendering while the JSON is mutated in place. Proven
to work: game 2000020001 credits ``C. DRURY`` alone in GS020001.HTM and
``C. DRURY + J. SAKIC`` in ``gamecenter/2000020001/landing``.

``C1..C9`` **intra-source** - arithmetic and structural consistency inside one
artifact (goal list vs period totals vs goalie goals-against, duplicates,
monotonic score sequence, goals-to-date counters). Cheap, always available, and
independent of any second source.

``C20..C22`` **temporal** - diff of two digests of the *same URL* taken at
different times. This is the only mechanism that can capture a silent post-game
correction *with its before-state*, and it only works if we polled before the
edit. See docs/FEASIBILITY.md.
"""

from __future__ import annotations

import dataclasses
import difflib
from typing import Any, Dict, List, Optional, Tuple

from .models import Goal, SourceRecord, clock_to_seconds
from .market import classify

CHECKS = {
    # --- intra-source ----------------------------------------------------
    "C1": ("goal_total_mismatch", "Goal list does not add up to the recorded team total"),
    "C2": ("period_total_mismatch", "Goals by period disagree with the period table"),
    "C3": ("goalie_goals_against_mismatch", "Goaltender goals-against disagrees with goals against"),
    "C4": ("score_sequence_mismatch", "Running score after goals is not monotonic or misses the final score"),
    "C5": ("duplicate_goal_entry", "Two identical goal entries (same team, period, clock, scorer)"),
    "C6": ("missing_goal_event", "Totals imply a goal that no goal line item supports"),
    "C7": ("counter_mismatch", "Goals/assists-to-date counter inconsistent within the artifact"),
    "C8": ("shot_total_mismatch", "Shot totals inconsistent with the per-period shot table"),
    "C9": ("clock_invalid", "Game clock outside the period length"),
    # --- cross-source ----------------------------------------------------
    "C10": ("goal_missing_from_one_source", "A goal exists in one official artifact and not the other"),
    "C11": ("assist_attribution_conflict", "Same goal, different assist credits between official artifacts"),
    "C12": ("scorer_attribution_conflict", "Same goal, different credited scorer between official artifacts"),
    "C13": ("goal_clock_conflict", "Same goal, different game clock between official artifacts"),
    "C14": ("goal_period_conflict", "Same goal, different period between official artifacts"),
    "C15": ("strength_conflict", "Same goal, different strength / empty-net state"),
    "C16": ("own_goal_classification_conflict", "Same goal, own-goal classification differs"),
    "C17": ("final_score_conflict", "Final score differs between official artifacts"),
    # C18 and C19 are deliberately not implemented: they were reserved for
    # "review overturned the call" and "challenge outcome" as first-class events.
    # No public NHL artifact exposes those events for historical games (see
    # docs/FEASIBILITY.md section 2), and inventing ids for checks we cannot run
    # would be worse than a gap in the numbering.
    # --- temporal (snapshot) ---------------------------------------------
    "C20": ("post_snapshot_attribution_change", "Scorer/assist credit changed between two pulls of the same endpoint"),
    "C21": ("post_snapshot_goal_count_change", "Goal count or score changed between two pulls of the same endpoint"),
    "C22": ("post_snapshot_clock_change", "Game clock for an existing goal changed between two pulls"),
}

SEVERITY = {
    "C1": "high", "C2": "medium", "C3": "medium", "C4": "high", "C5": "medium",
    "C6": "high", "C7": "low", "C8": "low", "C9": "medium",
    "C10": "high", "C11": "medium", "C12": "high", "C13": "low", "C14": "medium",
    "C15": "low", "C16": "medium", "C17": "high",
    "C20": "high", "C21": "critical", "C22": "low",
}


@dataclasses.dataclass
class Finding:
    check_id: str
    game_id: str
    field: str = ""
    detail: str = ""
    left: Optional[Dict[str, Any]] = None
    right: Optional[Dict[str, Any]] = None
    goal_key: Optional[str] = None
    evidence: Optional[List[Dict[str, Any]]] = None
    period: Optional[int] = None
    clock: Optional[str] = None
    team: Optional[str] = None
    scorer: Optional[str] = None
    #: per-record context the database needs to state totals honestly: goal counts
    #: and stated totals from each artifact involved in the comparison.
    context: Dict[str, Any] = dataclasses.field(default_factory=dict)

    @property
    def rule(self) -> str:
        return CHECKS[self.check_id][0]

    @property
    def severity(self) -> str:
        return SEVERITY.get(self.check_id, "low")

    def to_dict(self) -> Dict[str, Any]:
        out = dataclasses.asdict(self)
        out.update({"rule": self.rule, "severity": self.severity,
                    "check_name": CHECKS[self.check_id][1]})
        return out


def _goal_line(goal: Goal, side: str) -> Dict[str, Any]:
    return {
        "source": side,
        "order": goal.order,
        "period": goal.period,
        "clock": goal.clock,
        "clock_seconds": goal.clock_seconds,
        "team": goal.team,
        "strength": goal.strength,
        "strength_raw": goal.strength_raw,
        "own_goal": goal.own_goal,
        "empty_net": goal.empty_net,
        "scorer": goal.scorer.name if goal.scorer else None,
        "scorer_key": goal.scorer.key if goal.scorer else None,
        "scorer_name_key": goal.scorer.name_key if goal.scorer else None,
        "scorer_counter": goal.scorer.counter if goal.scorer else None,
        "assists": [a.name for a in goal.assists],
        "assist_keys": sorted(a.name_key for a in goal.assists),
        "assist_counters": {a.name: a.counter for a in goal.assists if a.counter is not None},
        "away_score": goal.away_score,
        "home_score": goal.home_score,
        "event_id": goal.event_id,
        "player_id": goal.player_id,
        "shot_type": goal.shot_type,
        "goal_modifier": goal.goal_modifier,
        "awarded": goal.awarded,
    }


def _name_match(a, b) -> bool:
    """Player equality, tolerant of how each artifact formats a name.

    RTSS sheets never carry player ids, so id equality is impossible for most
    historical games. Rules, in order:

    * both ids present -> ids must be equal (the only high-confidence equality)
    * surname tails must match (``Van Riemsdyk`` == ``RIEMSDYK``)
    * first initials must match *when both sources state one*
    * sweater numbers must match *when both sources state one*

    Every weaker equality is a *candidate* for a reviewer to confirm, which is
    why records built from name-only matches carry a confidence of medium at
    best; db validation refuses to mark them verified without a quote.
    """
    if a is None or b is None:
        return a is b
    if a.player_id and b.player_id:
        return a.player_id == b.player_id
    if a.surname_tail != b.surname_tail:
        return False
    if a.initial and b.initial and a.initial != b.initial:
        return False
    if a.sweater_number and b.sweater_number and a.sweater_number != b.sweater_number:
        return False
    return True


def _pair_goals(left: SourceRecord, right: SourceRecord) -> Tuple[List[Tuple[Goal, Goal]], List[Goal], List[Goal]]:
    """Pair goals across two sources: exact clock key first, then relaxed fallbacks.

    Bookkeeping is by index into ``right.goals``. Marking "used" by the index
    inside a per-key bucket instead (an earlier bug here) silently freed already
    matched goals back into the unmatched pool, which manufactured
    goal-missing findings on games that actually agree.
    """
    right_by_key: Dict[str, List[int]] = {}
    for idx, goal in enumerate(right.goals):
        right_by_key.setdefault(goal.match_key, []).append(idx)
    used: set = set()
    pairs: List[Tuple[Goal, Goal]] = []
    pending: List[Goal] = []
    for lg in left.goals:
        free = [i for i in right_by_key.get(lg.match_key, []) if i not in used]
        if free:
            used.add(free[0])
            pairs.append((lg, right.goals[free[0]]))
        else:
            pending.append(lg)
    remaining = [g for i, g in enumerate(right.goals) if i not in used]

    # Fallback 1: same period + team + scorer, clock drifted by seconds.
    still: List[Goal] = []
    for lg in pending:
        hit = next((rg for rg in remaining if rg.period == lg.period and rg.team == lg.team
                    and _name_match(lg.scorer, rg.scorer)), None)
        if hit is not None:
            pairs.append((lg, hit))
            remaining.remove(hit)
        else:
            still.append(lg)
    # Fallback 2: same period + team, nearest clock within 120s -> attribution moved.
    left_only: List[Goal] = []
    for lg in still:
        lsec = clock_to_seconds(lg.clock) or 0
        best: Optional[Tuple[int, Goal]] = None
        for rg in remaining:
            if rg.period != lg.period or rg.team != lg.team:
                continue
            delta = abs((clock_to_seconds(rg.clock) or 0) - lsec)
            if delta <= 120 and (best is None or delta < best[0]):
                best = (delta, rg)
        if best is not None:
            pairs.append((lg, best[1]))
            remaining.remove(best[1])
        else:
            left_only.append(lg)
    return pairs, left_only, remaining


def _totals_context(left: SourceRecord, right: SourceRecord) -> Dict[str, Any]:
    return {
        "left_goal_count": left.goal_count,
        "right_goal_count": right.goal_count,
        "left_goals_by_team": left.goals_by_team(),
        "right_goals_by_team": right.goals_by_team(),
        "left_stated_total": {a: (t.goals if t else None) for a, t in (left.totals or {}).items()},
        "right_stated_total": {a: (t.goals if t else None) for a, t in (right.totals or {}).items()},
    }


# --------------------------------------------------------------------------
# cross-source
# --------------------------------------------------------------------------
def compare_sources(left: SourceRecord, right: SourceRecord) -> List[Finding]:
    """Findings for one game given two official views of it."""
    findings: List[Finding] = []
    gid = left.game_id or right.game_id
    if not left.parse_ok or not right.parse_ok:
        return findings
    pairs, left_only, right_only = _pair_goals(left, right)
    ctx = _totals_context(left, right)

    def ev(pair_l: Optional[Goal], pair_r: Optional[Goal]) -> List[Dict[str, Any]]:
        out = []
        for rec, goal in ((left, pair_l), (right, pair_r)):
            entry = {"url": rec.url, "source": rec.source, "retrieved_at": rec.retrieved_at,
                     "sha256": rec.sha256}
            if goal is not None:
                entry["goal"] = _goal_line(goal, rec.source)
            else:
                entry["goal"] = None
                entry["note"] = "no corresponding goal line in this artifact"
            out.append(entry)
        return out

    for lg, rg in pairs:
        if lg.scorer and rg.scorer and not _name_match(lg.scorer, rg.scorer):
            findings.append(Finding(
                "C12", gid, field="scorer", goal_key=lg.match_key, period=lg.period,
                clock=lg.clock, team=lg.team, scorer=rg.scorer.name,
                detail=(f"{left.source} credits {lg.scorer.name!r}; {right.source} credits "
                        f"{rg.scorer.name!r} for the same goal"),
                left=_goal_line(lg, left.source), right=_goal_line(rg, right.source),
                evidence=ev(lg, rg), context=ctx))
            continue
        if lg.clock_seconds != rg.clock_seconds:
            findings.append(Finding(
                "C13", gid, field="clock", goal_key=lg.match_key, period=lg.period,
                clock=lg.clock, team=lg.team, scorer=lg.scorer.name if lg.scorer else None,
                detail=f"clock {lg.clock!r} in {left.source} vs {rg.clock!r} in {right.source}",
                left=_goal_line(lg, left.source), right=_goal_line(rg, right.source),
                evidence=ev(lg, rg), context=ctx))
        if lg.period != rg.period:
            findings.append(Finding(
                "C14", gid, field="period", goal_key=lg.match_key, period=lg.period,
                clock=lg.clock, team=lg.team, scorer=lg.scorer.name if lg.scorer else None,
                detail=f"period {lg.period} in {left.source} vs {rg.period} in {right.source}",
                left=_goal_line(lg, left.source), right=_goal_line(rg, right.source),
                evidence=ev(lg, rg), context=ctx))
        if sorted(a.name_key for a in lg.assists) != sorted(a.name_key for a in rg.assists):
            findings.append(Finding(
                "C11", gid, field="assists", goal_key=lg.match_key, period=lg.period,
                clock=lg.clock, team=lg.team, scorer=lg.scorer.name if lg.scorer else None,
                detail=(f"assists {[a.name for a in lg.assists]} in {left.source} vs "
                        f"{[a.name for a in rg.assists]} in {right.source}"),
                left=_goal_line(lg, left.source), right=_goal_line(rg, right.source),
                evidence=ev(lg, rg), context=ctx))
        if (lg.strength or "") != (rg.strength or ""):
            findings.append(Finding(
                "C15", gid, field="strength", goal_key=lg.match_key, period=lg.period,
                clock=lg.clock, team=lg.team, scorer=lg.scorer.name if lg.scorer else None,
                detail=f"strength {lg.strength_raw or lg.strength!r} vs {rg.strength!r}",
                left=_goal_line(lg, left.source), right=_goal_line(rg, right.source),
                evidence=ev(lg, rg), context=ctx))
        if (lg.own_goal in (True, False)) and (rg.own_goal in (True, False)) and lg.own_goal != rg.own_goal:
            findings.append(Finding(
                "C16", gid, field="own_goal", goal_key=lg.match_key, period=lg.period,
                clock=lg.clock, team=lg.team, scorer=lg.scorer.name if lg.scorer else None,
                detail=f"own-goal flag {lg.own_goal} vs {rg.own_goal}",
                left=_goal_line(lg, left.source), right=_goal_line(rg, right.source),
                evidence=ev(lg, rg), context=ctx))

    for lg in left_only:
        findings.append(Finding(
            "C10", gid, field="goal_presence", goal_key=lg.match_key, period=lg.period,
            clock=lg.clock, team=lg.team, scorer=lg.scorer.name if lg.scorer else None,
            detail=(f"goal present in {left.source} but not in {right.source}: "
                    f"{lg.team} {lg.period} {lg.clock} {lg.scorer.name if lg.scorer else '?'}"),
            left=_goal_line(lg, left.source), right=None, evidence=ev(lg, None), context=ctx))
    for rg in right_only:
        findings.append(Finding(
            "C10", gid, field="goal_presence", goal_key=rg.match_key, period=rg.period,
            clock=rg.clock, team=rg.team, scorer=rg.scorer.name if rg.scorer else None,
            detail=(f"goal present in {right.source} but not in {left.source}: "
                    f"{rg.team} {rg.period} {rg.clock} {rg.scorer.name if rg.scorer else '?'}"),
            left=None, right=_goal_line(rg, right.source), evidence=ev(None, rg), context=ctx))

    # Stated game totals per club, compared in both directions: the JSON states a
    # final score, the sheet states a TOT goals column. Either can be the wrong
    # one, so the finding reports both numbers and lets the reviewer decide.
    comparisons = []
    for side, rec, other in (("left", left, right), ("right", right, left)):
        stated = {rec.away_abbrev: rec.away_score, rec.home_abbrev: rec.home_score}
        for abbrev, final in stated.items():
            if not abbrev:
                continue
            other_total = (other.totals.get(abbrev).goals if other.totals.get(abbrev) else None)
            other_counted = other.goals_by_team().get(abbrev, 0)
            if final is not None and other_total is not None and final != other_total:
                comparisons.append((abbrev, f"{side} states {final}", f"{other.source} totals {other_total}"))
            if final is not None and other_total is None and final != other_counted:
                comparisons.append((abbrev, f"{side} states {final}", f"{other.source} rows {other_counted}"))
    for abbrev, a_txt, b_txt in comparisons:
        findings.append(Finding(
            "C17", gid, field="final_score", team=abbrev,
            detail=f"{abbrev}: {a_txt} but {b_txt}",
            left={"total": ctx.get("left_stated_total") or ctx.get("left_goals_by_team")},
            right={"total": ctx.get("right_stated_total") or ctx.get("right_goals_by_team")},
            evidence=ev(None, None), context=ctx))
    return findings


# --------------------------------------------------------------------------
# intra-source
# --------------------------------------------------------------------------
def check_record(rec: SourceRecord) -> List[Finding]:
    """Arithmetic and structural consistency inside a single official artifact.

    These checks never need a second source, so they run on every game the
    monitor touches, including games with only a JSON payload or only a sheet.
    A check only fires when the artifact actually states both numbers it is
    comparing - absence of data is reported as a gap by the coverage job, never
    as a discrepancy.
    """
    findings: List[Finding] = []
    if not rec.parse_ok:
        return findings
    gid = rec.game_id

    def add(check_id: str, detail: str, **kw) -> None:
        findings.append(Finding(check_id, gid, detail=detail,
                                evidence=[{"url": rec.url, "source": rec.source,
                                          "retrieved_at": rec.retrieved_at, "sha256": rec.sha256}], **kw))

    counted = rec.goals_by_team()
    known_teams = ({rec.away_abbrev, rec.home_abbrev} | set(rec.totals or {})) - {None, ""}
    for goal in rec.goals:
        if known_teams and goal.team not in known_teams:
            add("C1", f"goal line credits team {goal.team!r}, which is neither "
                      f"{rec.away_abbrev!r} nor {rec.home_abbrev!r}",
                field="team", period=goal.period, clock=goal.clock, team=goal.team,
                left=_goal_line(goal, rec.source))
        sec = goal.clock_seconds
        if sec is None or sec < 0 or sec > 60 * 20:
            add("C9", f"implausible game clock {goal.clock!r}",
                field="clock", period=goal.period, clock=goal.clock, team=goal.team,
                left=_goal_line(goal, rec.source))

    # per-team totals as the artifact states them
    for abbrev, tot in sorted((rec.totals or {}).items()):
        if tot.goals is not None and counted.get(abbrev, 0) != tot.goals:
            add("C1", f"{abbrev} totals line says {tot.goals} goals but the scoring summary "
                      f"lists {counted.get(abbrev, 0)}",
                field="goal_count", team=abbrev,
                left={"recorded_total": tot.goals, "counted": counted.get(abbrev, 0)})
        period_goal_sum = 0
        for pnum, listed in sorted((tot.goals_by_period or {}).items()):
            period_goal_sum += listed
            mine = sum(1 for g in rec.goals if g.period == pnum and g.team == abbrev)
            if listed != mine:
                add("C2", f"{abbrev} BY PERIOD says {listed} goal(s) in period {pnum}, the goal "
                          f"list has {mine}",
                    period=pnum, team=abbrev,
                    left={"by_period_table": listed, "goal_list": mine})
        if tot.goals is not None and period_goal_sum and period_goal_sum != tot.goals:
            add("C2", f"{abbrev} period goal columns sum to {period_goal_sum} but the total row "
                      f"says {tot.goals}", team=abbrev, field="period_sum",
                left={"sum_of_periods": period_goal_sum, "total_row": tot.goals})
        shot_sum = sum((tot.shots_by_period or {}).values())
        if tot.shots is not None and shot_sum and shot_sum != tot.shots:
            add("C8", f"{abbrev} shots by period sum to {shot_sum} but the total says {tot.shots}",
                team=abbrev, field="shot_sum",
                left={"sum_of_periods": shot_sum, "total_row": tot.shots})

    # the JSON's own header score, when present
    for side, abbrev, final in (("away", rec.away_abbrev, rec.away_score),
                                ("home", rec.home_abbrev, rec.home_score)):
        if final is None or not abbrev:
            continue
        if counted.get(abbrev, 0) != final:
            add("C1", f"{side} header score {final} for {abbrev} disagrees with "
                      f"{counted.get(abbrev, 0)} goal line item(s)",
                field="goal_count", team=abbrev,
                left={"header_score": final, "counted": counted.get(abbrev, 0)})

    # duplicates
    seen: Dict[str, Goal] = {}
    for goal in rec.goals:
        key = f"{goal.period}|{goal.clock_seconds or goal.clock}|{goal.team}|" \
              f"{goal.scorer.name_key if goal.scorer else ''}"
        if key in seen:
            add("C5", f"goal rows {seen[key].order} and {goal.order} are identical "
                      f"({goal.team} {goal.period} {goal.clock})",
                goal_key=goal.match_key, period=goal.period, clock=goal.clock, team=goal.team,
                left=_goal_line(seen[key], rec.source), right=_goal_line(goal, rec.source))
        seen[key] = goal

    # running score must be non-decreasing per team and land on the final score
    run = {"away": 0, "home": 0}
    for goal in rec.goals:
        if goal.away_score is None or goal.home_score is None:
            continue
        if goal.away_score < run["away"] or goal.home_score < run["home"]:
            add("C4", f"score after goal {goal.order} ({goal.away_score}-{goal.home_score}) runs "
                      f"backwards from ({run['away']}-{run['home']})",
                goal_key=goal.match_key, period=goal.period, clock=goal.clock, team=goal.team,
                left=_goal_line(goal, rec.source))
        run = {"away": goal.away_score, "home": goal.home_score}
    if rec.away_score is not None and rec.goals and run != {"away": rec.away_score, "home": rec.home_score}:
        add("C4", f"last goal line score {run['away']}-{run['home']} != final "
                  f"{rec.away_score}-{rec.home_score}", field="final_score",
            left=dict(run), right={"away": rec.away_score, "home": rec.home_score})
    return findings


def _period(cell: str) -> Tuple[Optional[int], str]:
    from .parsers import norm_period
    return norm_period(cell)


# --------------------------------------------------------------------------
# temporal (snapshot diff)
# --------------------------------------------------------------------------
def _snapshot_context(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    return {"left_goal_count": len(before.get("goals") or []),
            "right_goal_count": len(after.get("goals") or []),
            "left_stated_total": {"away": before.get("away_score"), "home": before.get("home_score")},
            "right_stated_total": {"away": after.get("away_score"), "home": after.get("home_score")},
            "before_captured_at": before.get("captured_at"),
            "after_captured_at": after.get("captured_at")}


def diff_snapshots(before: Dict[str, Any], after: Dict[str, Any], *, game_id: str,
                   url: str) -> List[Finding]:
    """Compare two digests of the same endpoint taken at different times.

    ``before``/``after`` are the ``digest`` blocks written by
    :mod:`nhl_scoring.snapshot`. The value of this engine is that each side
    carries the league's own state *plus the wall-clock time we captured it*,
    so the initial ruling survives even after the league edits the record.
    """
    findings: List[Finding] = []
    ctx = _snapshot_context(before, after)
    b_goals = {g["match_key"]: g for g in before.get("goals", [])}
    a_goals = {g["match_key"]: g for g in after.get("goals", [])}
    common = set(b_goals) & set(a_goals)
    for key in sorted(common):
        b, a = b_goals[key], a_goals[key]
        if (b.get("scorer_key"), b.get("assist_keys")) != (a.get("scorer_key"), a.get("assist_keys")):
            findings.append(Finding(
                "C20", game_id, field="attribution", goal_key=key,
                period=a.get("period"), clock=a.get("clock"), team=a.get("team"),
                scorer=a.get("scorer"),
                detail=(f"attribution changed between {before.get('captured_at')} and "
                        f"{after.get('captured_at')}: scorer {b.get('scorer')}->{a.get('scorer')}, "
                        f"assists {b.get('assists')}->{a.get('assists')}"),
                left=b, right=a,
                evidence=[{"url": url, "source": "snapshot_before", "sha256": before.get("sha256"),
                           "retrieved_at": before.get("captured_at")},
                          {"url": url, "source": "snapshot_after", "sha256": after.get("sha256"),
                           "retrieved_at": after.get("captured_at")}], context=ctx))
        if b.get("clock_seconds") != a.get("clock_seconds"):
            findings.append(Finding(
                "C22", game_id, field="clock", goal_key=key, period=a.get("period"),
                clock=a.get("clock"), team=a.get("team"), scorer=a.get("scorer"),
                detail=f"clock {b.get('clock')} -> {a.get('clock')}", left=b, right=a,
                evidence=[{"url": url, "source": "snapshot", "retrieved_at": after.get("captured_at")}]))
    for key in sorted(set(b_goals) - set(a_goals)):
        b = b_goals[key]
        findings.append(Finding(
            "C21", game_id, field="goal_removed", goal_key=key, period=b.get("period"),
            clock=b.get("clock"), team=b.get("team"), scorer=b.get("scorer"),
            detail=(f"goal present at {before.get('captured_at')} is gone by "
                    f"{after.get('captured_at')}: {b.get('team')} {b.get('period')} "
                    f"{b.get('clock')} {b.get('scorer')} (initial ruling -> no goal)"),
            left=b, right=None,
            evidence=[{"url": url, "source": "snapshot_before", "sha256": before.get("sha256"),
                       "retrieved_at": before.get("captured_at")},
                      {"url": url, "source": "snapshot_after", "sha256": after.get("sha256"),
                       "retrieved_at": after.get("captured_at")}]))
    for key in sorted(set(a_goals) - set(b_goals)):
        a = a_goals[key]
        findings.append(Finding(
            "C21", game_id, field="goal_added", goal_key=key, period=a.get("period"),
            clock=a.get("clock"), team=a.get("team"), scorer=a.get("scorer"),
            detail=(f"goal absent at {before.get('captured_at')} appears by "
                    f"{after.get('captured_at')}: {a.get('team')} {a.get('period')} "
                    f"{a.get('clock')} {a.get('scorer')} (no-goal/undecided -> goal)"),
            left=None, right=a,
            evidence=[{"url": url, "source": "snapshot_before", "sha256": before.get("sha256"),
                       "retrieved_at": before.get("captured_at")},
                      {"url": url, "source": "snapshot_after", "sha256": after.get("sha256"),
                       "retrieved_at": after.get("captured_at")}]))
    for field in ("away_score", "home_score"):
        if before.get(field) != after.get(field):
            findings.append(Finding(
                "C21", game_id, field=field,
                detail=f"{field} {before.get(field)} -> {after.get(field)}",
                left={field: before.get(field)}, right={field: after.get(field)},
                evidence=[{"url": url, "source": "snapshot", "retrieved_at": after.get("captured_at")}]))
    return findings


def describe_market(finding: Finding) -> Dict[str, Any]:
    """Attach the market-impact verdict for a finding."""
    return classify(finding)


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()
