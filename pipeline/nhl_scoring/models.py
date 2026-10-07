"""Normalized representation of one game's scoring record, per source.

Both the JSON endpoints and the RTSS HTML reports are projected onto this model
so that "compare the two official records of the same game" becomes a
field-by-field diff instead of a text diff. Everything is deliberately dumb
dataclasses: records get serialized into the database, and being able to dump
one to JSON without custom encoders keeps the audit trail simple.
"""

from __future__ import annotations

import dataclasses
import re
import unicodedata
from typing import Any, Dict, List, Optional


# --------------------------------------------------------------------------
# name handling
# --------------------------------------------------------------------------
def ascii_fold(value: str) -> str:
    """``Lidström`` -> ``lidstrom``, ``BRIND'AMOUR`` -> ``brindamour``."""
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", value)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^A-Za-z0-9]+", "", text)
    return text.lower()


def display_name(value: str) -> str:
    """Canonical ``First Last`` display form from either ``M. PACIORETTY`` or
    ``{firstName: Max, lastName: Pacioretty}`` inputs."""
    return " ".join(part for part in (value or "").split() if part)


@dataclasses.dataclass
class Player:
    name: str                      # display name, source's own formatting
    surname: str = ""              # ascii-folded surname
    initial: str = ""              # ascii-folded first initial ("" if unknown)
    player_id: Optional[int] = None
    sweater_number: Optional[int] = None
    counter: Optional[int] = None  # goals/assists to date carried by the source

    @property
    def surname_tail(self) -> str:
        """Last whitespace-delimited token of the surname, folded.

        This exists for one reason: the RTSS sheets write ``J.VAN RIEMSDYK``
        (which yields the token ``RIEMSDYK``) while the JSON writes the full
        ``Van Riemsdyk``. Matching on whole surnames would report those as two
        different players and fabricate a scoring discrepancy, so comparison runs
        on the tail and the human-readable ``surname`` is kept untouched.
        """
        parts = [p for p in re.split(r"\s+", self.surname or "") if p]
        return parts[-1] if parts else (self.surname or "")

    @property
    def key(self) -> str:
        """Match key used to line the same player up across sources.

        Names alone are risky (two brothers on one roster is rare but real), so
        ``player_id`` wins whenever the source carries it. When it does not
        (RTSS reports never carry ids) we fall back to surname+initial and let
        the caller treat a name-only match as *medium* confidence.
        """
        if self.player_id:
            return f"id:{self.player_id}"
        return f"name:{self.surname}:{self.initial}"

    @property
    def name_key(self) -> str:
        """Cross-source identity key: surname tail + first initial.

        Deliberately id-free so a name-space (RTSS) and an id-space (JSON) list
        of assists can be compared in the same namespace.
        """
        return f"{self.surname_tail}:{self.initial}"

    @property
    def number(self) -> Optional[int]:
        return self.sweater_number

    def to_dict(self) -> Dict[str, Any]:
        out = dataclasses.asdict(self)
        out["key"] = self.key
        return out


def parse_report_player(cell: str) -> Optional[Player]:
    """Parse an RTSS scoring-summary player cell.

    Confirmed shapes (fetched 2026-10-07):

    * legacy 2000-01:  ``S. FEDOROV (2)``            (no sweater number)
    * modern 2015-16+: ``67 M.PACIORETTY(1)``         number, ``INITIAL.LAST``
    * own goals:        ``55 J.SMOINS (OWN GOAL)`` / trailing ``OWN GOAL``
    * awarded goals may read ``TEAM NAME (AWARDED)`` (handled by caller)
    """
    text = (cell or "").strip()
    if not text or text in {"-", "--"}:
        return None
    own = bool(re.search(r"\(?\bOWN GOAL\b\)?", text, re.I))
    cleaned = re.sub(r"\(?\bOWN GOAL\b\)?", "", text, flags=re.I).strip()
    counter = None
    m = re.search(r"\((\d+)\)\s*$", cleaned)
    if m:
        counter = int(m.group(1))
        cleaned = cleaned[: m.start()].strip()
    number = None
    m = re.match(r"^(\d{1,2})\s+(.*)$", cleaned)
    if m and m.group(2)[:1].isalpha():
        number = int(m.group(1))
        cleaned = m.group(2).strip()
    parts = cleaned.split()
    if not parts:
        return None
    surname = parts[-1]
    if not re.search(r"[A-Za-z]", surname):
        # Cells such as "3 39 33 15 10" (shots by period) or "11, 23, 45"
        # (on-ice jersey numbers) must not be mistaken for a player name.
        return None
    initial = ""
    if len(parts) > 1:
        head = " ".join(parts[:-1])
        head = re.sub(r"[^A-Za-z]", "", head)
        initial = ascii_fold(head[:1]) if head else ""
    elif "." in surname:                      # ``M.PACIORETTY`` with no space
        head, _, tail = surname.partition(".")
        initial = ascii_fold(head[:1])
        surname = tail or head
    return Player(
        name=display_name(" ".join(parts)),
        surname=ascii_fold(surname),
        initial=initial,
        sweater_number=number,
        counter=counter,
    )


# --------------------------------------------------------------------------
# scoring events
# --------------------------------------------------------------------------
STRENGTH_ALIASES = {
    "ev": "EV", "even": "EV", "5v5": "EV", "e": "EV", "ev-en": "EV",
    "pp": "PP", "power play": "PP", "p": "PP",
    "sh": "SH", "short-handed": "SH", "shorty": "SH",
    "ps": "PS", "penalty shot": "PS", "so": "SO", "shootout": "SO",
    "ts": "SO", "bw": "BW", "none": "EV",
}


def norm_strength(raw: Optional[str]) -> str:
    key = (raw or "").strip().lower()
    return STRENGTH_ALIASES.get(key, key.upper() or "EV")


def clock_to_seconds(clock: Optional[str]) -> Optional[int]:
    if not clock:
        return None
    m = re.match(r"^(\d{1,2}):(\d{2})", clock.strip())
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


@dataclasses.dataclass
class Goal:
    """One goal as some official artifact records it."""

    order: int                      # 1-based sequence in the source document
    period: int
    clock: str                      # "MM:SS" remaining
    team: str                       # club abbrev of the scoring team
    is_home: Optional[bool] = None
    strength: str = "EV"            # normalized EV/PP/SH/PS/SO
    strength_raw: str = ""          # verbatim, e.g. "EV-EN"
    empty_net: Optional[bool] = None
    own_goal: Optional[bool] = None
    scorer: Optional[Player] = None
    assists: List[Player] = dataclasses.field(default_factory=list)
    away_score: Optional[int] = None
    home_score: Optional[int] = None
    player_id: Optional[int] = None      # scorer id when the source carries it
    event_id: Optional[int] = None
    shot_type: Optional[str] = None
    goal_modifier: Optional[str] = None
    awarded: bool = False

    @property
    def clock_seconds(self) -> Optional[int]:
        return clock_to_seconds(self.clock)

    @property
    def match_key(self) -> str:
        """Identity used to pair the same goal across two sources.

        Period + clock + team is the only triple both artifacts always carry.
        Scorer is *not* part of it: a changed scorer is exactly what we look
        for, so baking it into the key would hide the cases that matter.

        The clock is normalised to seconds because the RTSS sheets write
        ``2:00`` and the JSON writes ``02:00`` for the same goal; comparing the
        strings would fabricate a missing-goal finding for every early-minute
        goal in a historical game.
        """
        secs = self.clock_seconds
        return f"{self.period}|{secs if secs is not None else self.clock}|{self.team}"

    def to_dict(self) -> Dict[str, Any]:
        out = dataclasses.asdict(self)
        out["clock_seconds"] = self.clock_seconds
        out["match_key"] = self.match_key
        out["scorer"] = self.scorer.to_dict() if self.scorer else None
        out["assists"] = [a.to_dict() for a in self.assists]
        return out


@dataclasses.dataclass
class TeamTotals:
    abbrev: str
    goals: Optional[int] = None
    shots: Optional[int] = None
    goals_by_period: Dict[int, int] = dataclasses.field(default_factory=dict)
    pp_goals: Optional[int] = None
    pp_opportunities: Optional[int] = None
    goalie_goals_against: Dict[int, int] = dataclasses.field(default_factory=dict)
    goalie_shots_against: Dict[int, int] = dataclasses.field(default_factory=dict)
    shots_by_period: Dict[int, int] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class SourceRecord:
    """Everything one artifact says about one game."""

    source: str                     # 'nhl_api_landing' | 'nhl_gs_report' | ...
    game_id: str
    url: str
    retrieved_at: str = ""
    sha256: Optional[str] = None
    parser_version: str = "1"
    parse_ok: bool = True
    parse_notes: List[str] = dataclasses.field(default_factory=list)
    game_date: Optional[str] = None
    season: Optional[str] = None
    game_type: Optional[str] = None
    away_abbrev: Optional[str] = None
    home_abbrev: Optional[str] = None
    away_team: Optional[TeamTotals] = None
    home_team: Optional[TeamTotals] = None
    away_score: Optional[int] = None
    home_score: Optional[int] = None
    goals: List[Goal] = dataclasses.field(default_factory=list)
    #: per-team totals as the artifact itself states them (keyed by club abbrev)
    totals: Dict[str, TeamTotals] = dataclasses.field(default_factory=dict)
    generated_at: Optional[str] = None   # report footer timestamp, when present
    extra: Dict[str, Any] = dataclasses.field(default_factory=dict)

    @property
    def goal_count(self) -> int:
        return len(self.goals)

    def goals_by_team(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for goal in self.goals:
            out[goal.team] = out.get(goal.team, 0) + 1
        return out

    def by_team(self, abbrev: Optional[str]) -> Optional[TeamTotals]:
        if not abbrev:
            return None
        if self.away_team and self.away_team.abbrev == abbrev:
            return self.away_team
        if self.home_team and self.home_team.abbrev == abbrev:
            return self.home_team
        return None

    def to_dict(self) -> Dict[str, Any]:
        out = dataclasses.asdict(self)
        out["goals"] = [g.to_dict() for g in self.goals]
        out["goal_count"] = self.goal_count
        out["goals_by_team"] = self.goals_by_team()
        return out
