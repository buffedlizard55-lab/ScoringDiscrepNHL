"""Official artifact addresses.

Every record in this database must be re-verifiable by a human clicking one
link, so URL construction lives in exactly one place and is unit-tested.

Verified live on 2026-10-07 (see docs/SOURCES.md for the probe evidence):
  * ``https://api-web.nhle.com/v1/...`` serves the Game Center JSON, back to at
    least the 1999-00 season (``gamecenter/1999020001/landing`` is 200 OK).
  * ``https://www.nhl.com/scores/htmlreports/{season}/{CODE}{gameNumber}.HTM``
    serves the official RTSS game sheets, back to 2000-01 (1999-2000 probes for
    GS020001/GS020002/GS030001 were 404; 2000-01 GS020001 is 200 OK).
  * ``gamecenter/{id}/right-rail`` exposes ``gameReports`` with absolute URLs
    for all nine report codes, which is what we prefer over guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Optional

API_BASE = "https://api-web.nhle.com/v1"
REPORT_BASE = "https://www.nhl.com/scores/htmlreports"

#: Official RTSS report codes and what they contain. Sizes are from the
#: 2025-26 sample noted in the right-rail discovery work; PL is the monster.
REPORT_CODES: Dict[str, str] = {
    "GS": "Game Summary (scoring summary, on-ice for each goal, penalties, goalies, officials)",
    "ES": "Event Summary (per-player box score with EV/PP/SH splits, faceoffs)",
    "PL": "Play By Play (every event, with on-ice players for each event)",
    "FS": "Faceoff Summary (player x zone x strength)",
    "FC": "Faceoff Comparison (center-vs-center matrix)",
    "RO": "Playing Roster (dressings, scratches, coaches, officials)",
    "SS": "Shot Summary (shots by period x strength x player)",
    "TV": "Time on Ice, away team (every shift)",
    "TH": "Time on Ice, home team (every shift)",
}

#: Official NHL game id: 4-digit season start year + 2-digit game type + 4-digit
#: game number, e.g. ``2000020001`` (2000-01, regular season, game 0001). The
#: last six digits are the RTSS report filename stem (``020001``).
GAME_ID_RE = re.compile(r"^\d{4}(0[1-9]|1[0-2])\d{4}$")

#: gameType digits used by the NHL game id, as observed in official payloads.
GAME_TYPE_NAMES = {
    "01": "PRE",   # preseason
    "02": "REG",   # regular season
    "03": "PO",    # Stanley Cup playoffs
    "04": "ASC",   # All-Star / showcase events
    "05": "OG",    # other/olympic-adjacent
    "06": "PNL",
    "07": "CSC",
    "08": "UNKN",
    "09": "AHL?",   # never expected; kept so parsing never guesses
    "10": "DTO",
    "11": "DFN",
    "12": "FUT",
}


@dataclass(frozen=True)
class GameRef:
    """A game addressed by its official 10-digit NHL game id."""

    game_id: str

    def __post_init__(self) -> None:
        if not GAME_ID_RE.match(self.game_id):
            raise ValueError(
                f"game_id {self.game_id!r} is not an official 10-digit NHL game id "
                f"(SSSSGTNNNN, e.g. 2000020001)"
            )

    @property
    def season(self) -> str:
        """Start year of the season, e.g. ``'2000'`` for 2000-01."""
        return self.game_id[:4]

    @property
    def season_dir(self) -> str:
        """The directory name used by the htmlreports tree, e.g. ``20002001``."""
        start = int(self.season)
        return f"{start}{start + 1}"

    @property
    def game_type_code(self) -> str:
        return self.game_id[4:6]

    @property
    def game_type(self) -> str:
        return GAME_TYPE_NAMES.get(self.game_type_code, f"UNKNOWN_{self.game_type_code}")

    @property
    def game_number(self) -> str:
        """Last six digits, i.e. the RTSS filename stem suffix."""
        return self.game_id[-6:]

    # ---- addresses -------------------------------------------------------
    def report_url(self, code: str) -> str:
        if code not in REPORT_CODES:
            raise ValueError(f"unknown report code {code!r}; expected one of {sorted(REPORT_CODES)}")
        return f"{REPORT_BASE}/{self.season_dir}/{code}{self.game_number}.HTM"

    @property
    def gamecenter_landing(self) -> str:
        return f"{API_BASE}/gamecenter/{self.game_id}/landing"

    @property
    def gamecenter_boxscore(self) -> str:
        return f"{API_BASE}/gamecenter/{self.game_id}/boxscore"

    @property
    def gamecenter_play_by_play(self) -> str:
        return f"{API_BASE}/gamecenter/{self.game_id}/play-by-play"

    @property
    def gamecenter_right_rail(self) -> str:
        return f"{API_BASE}/gamecenter/{self.game_id}/right-rail"

    @property
    def gamecenter_page(self) -> str:
        """Human-facing Game Center page (the link a reviewer should click)."""
        return f"https://www.nhl.com/gamecenter/{self.game_id}"

    @property
    def stats_page(self) -> str:
        return f"https://www.nhl.com/stats/statscenter?id={self.game_id}"


def game_ref(game_id: str) -> GameRef:
    return GameRef(str(game_id))


def date_score_url(date_iso: str) -> str:
    """Daily scoreboard JSON (has the live goal list while a game is in play)."""
    return f"{API_BASE}/score/{date_iso}"


def date_schedule_url(date_iso: str) -> str:
    return f"{API_BASE}/schedule/{date_iso}"


def season_game_ids(season_start_year: int, game_type_codes=("02", "03")) -> list:
    """Candidate game ids for a season, in the range the NHL numbers games.

    The NHL does not publish an index of report files, so backfill has to
    enumerate ids and accept the 404s. Regular season runs 1..1312 and
    playoffs 1..~240 depending on era; we return the candidate space and let
    the caller prune with the schedule endpoints (cheaper and authoritative).
    """
    out = []
    year = int(season_start_year)
    maxes = {"01": 40, "02": 1320, "03": 250, "04": 20}
    for code in game_type_codes:
        for n in range(1, maxes.get(code, 1320) + 1):
            out.append(f"{year}{code}{n:04d}")
    return out


def parse_report_urls(right_rail_json: dict) -> Dict[str, str]:
    """Extract the official per-game report links from a right-rail payload.

    We prefer these over :meth:`GameRef.report_url` because they are what the
    league itself advertises for the game, so a 404 here is meaningful.
    """
    reports = (right_rail_json or {}).get("gameReports") or {}
    key_map = {
        "gameSummary": "GS",
        "eventSummary": "ES",
        "playByPlay": "PL",
        "faceoffSummary": "FS",
        "faceoffComparison": "FC",
        "rosters": "RO",
        "shotSummary": "SS",
        "toiAway": "TV",
        "toiHome": "TH",
    }
    out: Dict[str, str] = {}
    for key, code in key_map.items():
        url = reports.get(key)
        if isinstance(url, str) and url.startswith("http"):
            out[code] = url
    return out


def season_from_date(date_iso: str) -> Optional[str]:
    """Return the htmlreports season directory for a calendar date, if inferable.

    NHL seasons straddle new year, so ``2026-09-29`` is in ``20262027`` while
    ``2027-01-21`` is still ``20262027``. Callers that know the season should
    pass it; this is only a convenience for ad-hoc lookups.
    """
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", date_iso or "")
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    # Sept-Dec -> season starts this year; Jan-Aug -> season started last year.
    start = year if month >= 7 else year - 1
    return f"{start}{start + 1}"
