"""Normalised game state + the diff engine.

The whole detection system rests on one idea: every official source is rendered
into the SAME normalised structure (:class:`GameState`). A discrepancy is then any
semantic difference between two GameStates for the same game - never a guess.

Both states are kept. Nothing is overwritten.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple


# ----------------------------------------------------------------------------- #
# Player reference
# ----------------------------------------------------------------------------- #

@dataclass
class PlayerRef:
    id: Optional[int] = None
    name: str = ""
    sweater: Optional[int] = None

    def label(self) -> str:
        if self.sweater is not None and self.name:
            return f"{self.sweater} {self.name}"
        return self.name or (f"id:{self.id}" if self.id else "unknown")

    def same_player(self, other: "PlayerRef") -> bool:
        """Identity comparison that does not depend on spelling."""
        if self.id is not None and other.id is not None:
            return int(self.id) == int(other.id)
        return self.name.strip().upper() == other.name.strip().upper()

    def as_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "sweater": self.sweater}


# ----------------------------------------------------------------------------- #
# Goal
# ----------------------------------------------------------------------------- #

@dataclass
class GoalEvent:
    period: int
    clock: str                      # "MM:SS" elapsed in period
    team: str                       # scoring team abbreviation
    scorer: Optional[PlayerRef] = None
    assists: List[PlayerRef] = field(default_factory=list)
    strength: str = ""              # EV / PP / SH / EV-EN / EV-PS ...
    event_id: Optional[int] = None
    period_type: str = "REG"
    is_own_goal: bool = False
    is_penalty_shot: bool = False
    away_score_after: Optional[int] = None
    home_score_after: Optional[int] = None

    # -- identity ------------------------------------------------------------- #
    def natural_key(self) -> Tuple[str, int, str, str]:
        return (self.period_type, int(self.period), self.clock, self.team.upper())

    def as_dict(self) -> dict:
        d = asdict(self)
        d["scorer"] = self.scorer.as_dict() if self.scorer else None
        d["assists"] = [a.as_dict() for a in self.assists]
        return d

    def describe(self) -> str:
        who = self.scorer.label() if self.scorer else "unknown"
        parts = [f"P{self.period} {self.clock} {self.team}", who]
        if self.assists:
            parts.append("assists: " + ", ".join(a.label() for a in self.assists))
        else:
            parts.append("unassisted")
        if self.strength:
            parts.append(self.strength)
        return " | ".join(parts)


# ----------------------------------------------------------------------------- #
# Team
# ----------------------------------------------------------------------------- #

@dataclass
class TeamState:
    abbrev: str
    name: str = ""
    score: Optional[int] = None
    shots: Optional[int] = None

    def as_dict(self) -> dict:
        return asdict(self)


# ----------------------------------------------------------------------------- #
# Game state
# ----------------------------------------------------------------------------- #

@dataclass
class GameState:
    game_id: int
    source_key: str                 # "api.pbp" | "doc.GS" | "api.boxscore" ...
    source_url: str
    retrieved_at: str
    game_date: str = ""
    season: str = ""
    away: Optional[TeamState] = None
    home: Optional[TeamState] = None
    goals: List[GoalEvent] = field(default_factory=list)
    game_state: str = ""            # FUT / LIVE / OFF / FINAL
    period: Optional[int] = None
    in_intermission: bool = False
    report_generated_at: str = ""   # footer timestamp of an HTML report, when present
    report_is_frozen: Optional[bool] = None
    parse_warnings: List[str] = field(default_factory=list)
    evidence: Dict[str, object] = field(default_factory=dict)

    # -- helpers -------------------------------------------------------------- #
    def goal_count(self, team: Optional[str] = None) -> int:
        gs = [g for g in self.goals if not g.period_type.upper().startswith("SO")]
        if team:
            return sum(1 for g in gs if g.team.upper() == team.upper())
        return len(gs)

    def team(self, abbrev: str) -> Optional[TeamState]:
        for t in (self.away, self.home):
            if t and t.abbrev.upper() == abbrev.upper():
                return t
        return None

    def sorted_goals(self) -> List[GoalEvent]:
        order = {"REG": 0, "OT": 1, "SO": 9}
        return sorted(self.goals, key=lambda g: (order.get(g.period_type.upper(), 3), g.period, g.clock, g.team))

    def as_dict(self) -> dict:
        return {
            "game_id": self.game_id,
            "source_key": self.source_key,
            "source_url": self.source_url,
            "retrieved_at": self.retrieved_at,
            "game_date": self.game_date,
            "season": self.season,
            "away": self.away.as_dict() if self.away else None,
            "home": self.home.as_dict() if self.home else None,
            "game_state": self.game_state,
            "period": self.period,
            "in_intermission": self.in_intermission,
            "report_generated_at": self.report_generated_at,
            "report_is_frozen": self.report_is_frozen,
            "goals": [g.as_dict() for g in self.goals],
            "parse_warnings": list(self.parse_warnings),
            "evidence": dict(self.evidence),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "GameState":
        state = cls(
            game_id=int(d["game_id"]),
            source_key=d.get("source_key", ""),
            source_url=d.get("source_url", ""),
            retrieved_at=d.get("retrieved_at", ""),
            game_date=d.get("game_date", ""),
            season=d.get("season", ""),
            game_state=d.get("game_state", ""),
            period=d.get("period"),
            in_intermission=bool(d.get("in_intermission", False)),
            report_generated_at=d.get("report_generated_at", ""),
            report_is_frozen=d.get("report_is_frozen"),
            parse_warnings=list(d.get("parse_warnings", [])),
            evidence=dict(d.get("evidence", {})),
        )
        for side in ("away", "home"):
            blob = d.get(side)
            if blob:
                setattr(state, side, TeamState(**blob))
        for g in d.get("goals", []):
            state.goals.append(GoalEvent(
                period=int(g["period"]),
                clock=g["clock"],
                team=g["team"],
                scorer=PlayerRef(**g["scorer"]) if g.get("scorer") else None,
                assists=[PlayerRef(**a) for a in g.get("assists", [])],
                strength=g.get("strength", ""),
                event_id=g.get("event_id"),
                period_type=g.get("period_type", "REG"),
                is_own_goal=bool(g.get("is_own_goal", False)),
                is_penalty_shot=bool(g.get("is_penalty_shot", False)),
                away_score_after=g.get("away_score_after"),
                home_score_after=g.get("home_score_after"),
            ))
        return state

    def fingerprint(self) -> str:
        """Stable, human-diffable digest of the scoring record (not the whole file)."""
        import hashlib

        lines = [f"game={self.game_id}", f"state={self.game_state}"]
        for t in (self.away, self.home):
            if t:
                lines.append(f"{t.abbrev}:{t.score}")
        for g in self.sorted_goals():
            lines.append("|".join([
                g.period_type, str(g.period), g.clock, g.team.upper(),
                (g.scorer.label() if g.scorer else "-"),
                "/".join(a.label() for a in g.assists) or "-",
                g.strength or "-",
                "OG" if g.is_own_goal else "",
            ]))
        return hashlib.sha256("\n".join(lines).encode()).hexdigest()[:32]


# ----------------------------------------------------------------------------- #
# Change objects
# ----------------------------------------------------------------------------- #

CHANGE_TYPES = (
    "goal_removed",      # goal -> no goal (total changes)
    "goal_added",        # no goal -> goal (total changes)
    "scorer_change",     # attribution only
    "assist_change",     # attribution only
    "strength_change",   # goal properties changed
    "own_goal_flag_change",
    "metadata_change",   # score/state updated with no structural change
)


@dataclass
class Change:
    change_type: str
    period: Optional[int]
    clock: str
    team: str
    before: Optional[dict]
    after: Optional[dict]
    detail: str

    def as_dict(self) -> dict:
        return asdict(self)


# ----------------------------------------------------------------------------- #
# Diff engine
# ----------------------------------------------------------------------------- #

def _clock_seconds(clock: str) -> int:
    try:
        mm, ss = clock.split(":")
        return int(mm) * 60 + int(ss)
    except Exception:
        return -1


def _match_goals(before: List[GoalEvent], after: List[GoalEvent]
                 ) -> Tuple[List[Tuple[GoalEvent, GoalEvent]], List[GoalEvent], List[GoalEvent]]:
    """Match goals across two states.

    Pass 1 exact natural key, pass 2 same period+team with clock within 3 seconds.
    Unmatched goals are reported as added/removed rather than silently re-paired.
    """
    matched: List[Tuple[GoalEvent, GoalEvent]] = []
    remaining_after = list(after)
    unmatched_before: List[GoalEvent] = []

    for gb in before:
        hit = None
        for ga in remaining_after:
            if ga.natural_key() == gb.natural_key():
                hit = ga
                break
        if hit is None:
            for ga in remaining_after:
                if (ga.period_type, ga.period, ga.team.upper()) == (gb.period_type, gb.period, gb.team.upper()) \
                        and abs(_clock_seconds(ga.clock) - _clock_seconds(gb.clock)) <= 3:
                    hit = ga
                    break
        if hit is None:
            unmatched_before.append(gb)
        else:
            remaining_after.remove(hit)
            matched.append((gb, hit))
    return matched, unmatched_before, remaining_after


def diff_states(before: GameState, after: GameState) -> List[Change]:
    """Return the semantic differences between two official renderings of a game."""
    changes: List[Change] = []
    b_goals = [g for g in before.goals if not g.period_type.upper().startswith("SO")]
    a_goals = [g for g in after.goals if not g.period_type.upper().startswith("SO")]

    matched, removed, added = _match_goals(b_goals, a_goals)

    for g in removed:
        changes.append(Change(
            change_type="goal_removed",
            period=g.period, clock=g.clock, team=g.team,
            before=g.as_dict(), after=None,
            detail=f"Goal no longer present in the official record: {g.describe()}",
        ))
    for g in added:
        changes.append(Change(
            change_type="goal_added",
            period=g.period, clock=g.clock, team=g.team,
            before=None, after=g.as_dict(),
            detail=f"Goal now present in the official record: {g.describe()}",
        ))

    for gb, ga in matched:
        if (gb.scorer is None) != (ga.scorer is None) or (
                gb.scorer and ga.scorer and not gb.scorer.same_player(ga.scorer)):
            changes.append(Change(
                change_type="scorer_change",
                period=ga.period, clock=ga.clock, team=ga.team,
                before=gb.as_dict(), after=ga.as_dict(),
                detail=(f"Goal scorer changed from {gb.scorer.label() if gb.scorer else 'unknown'} "
                        f"to {ga.scorer.label() if ga.scorer else 'unknown'}"),
            ))
        b_names = [a.label() for a in gb.assists]
        a_names = [a.label() for a in ga.assists]
        if sorted(b_names) != sorted(a_names):
            changes.append(Change(
                change_type="assist_change",
                period=ga.period, clock=ga.clock, team=ga.team,
                before=gb.as_dict(), after=ga.as_dict(),
                detail=(f"Assists changed from [{', '.join(b_names) or 'none'}] "
                        f"to [{', '.join(a_names) or 'none'}]"),
            ))
        if (gb.strength or "").upper() != (ga.strength or "").upper():
            changes.append(Change(
                change_type="strength_change",
                period=ga.period, clock=ga.clock, team=ga.team,
                before=gb.as_dict(), after=ga.as_dict(),
                detail=f"Strength changed from {gb.strength!r} to {ga.strength!r}",
            ))
        if bool(gb.is_own_goal) != bool(ga.is_own_goal):
            changes.append(Change(
                change_type="own_goal_flag_change",
                period=ga.period, clock=ga.clock, team=ga.team,
                before=gb.as_dict(), after=ga.as_dict(),
                detail=f"Own-goal flag changed from {gb.is_own_goal} to {ga.is_own_goal}",
            ))

    # Score-only movement (e.g. a goal was added/removed for a team) is implied by
    # the goal changes; record it explicitly only when goal sets are identical.
    if not removed and not added:
        for side in ("away", "home"):
            tb, ta = getattr(before, side), getattr(after, side)
            if tb and ta and tb.score is not None and ta.score is not None and tb.score != ta.score:
                changes.append(Change(
                    change_type="metadata_change",
                    period=None, clock="", team=ta.abbrev,
                    before={"score": tb.score}, after={"score": ta.score},
                    detail=f"{ta.abbrev} team score changed {tb.score} -> {ta.score} with no "
                           f"goal-set change (inconsistent feed: verify manually)",
                ))
    return changes


def affects_goal_total(changes: List[Change]) -> bool:
    return any(c.change_type in ("goal_removed", "goal_added") for c in changes)


def attribution_only(changes: List[Change]) -> bool:
    return bool(changes) and not affects_goal_total(changes)
