"""Parsers that turn official NHL artifacts into :class:`GameState` objects.

Three parsers:

* ``parse_api_pbp``      - GameCenter play-by-play JSON (event level)
* ``parse_api_boxscore`` - GameCenter boxscore JSON (player totals)
* ``parse_gs_report``    - official "Game Summary" HTML document

The HTML parser is header-driven and colspan-aware on purpose: the official report
layout changed between eras (bilingual 2013-14 headers, strength column first in
modern reports, last in 2005-06 reports, "unassisted" merged cells). Positional
parsing would silently mis-read old reports, which is exactly the kind of error
this project must not make. Anything the parser cannot understand is appended to
``parse_warnings`` so the record can be flagged instead of quietly filled in.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple

from .state import GameState, GoalEvent, PlayerRef, TeamState

# ----------------------------------------------------------------------------- #
# Minimal, colspan-aware HTML table extractor
# ----------------------------------------------------------------------------- #


class _TableExtractor(HTMLParser):
    """Collect every <table> as a grid of text cells, expanding rowspan/colspan."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: List[List[List[str]]] = []
        self._table_stack: List[List[List[str]]] = []
        self._row: Optional[List[str]] = None
        self._cell: Optional[List[str]] = None
        self._cell_span: Tuple[int, int] = (1, 1)
        self._pending: Dict[int, Tuple[int, str]] = {}  # col -> (rows_left, text)

    # -- tags ----------------------------------------------------------------- #
    def handle_starttag(self, tag: str, attrs):
        a = dict(attrs)
        if tag == "table":
            self._table_stack.append([])
        elif tag == "tr" and self._table_stack:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
            try:
                colspan = max(1, int(a.get("colspan", 1)))
            except (TypeError, ValueError):
                colspan = 1
            try:
                rowspan = max(1, int(a.get("rowspan", 1)))
            except (TypeError, ValueError):
                rowspan = 1
            self._cell_span = (colspan, rowspan)
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag: str):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            text = re.sub(r"\s+", " ", "".join(self._cell)).strip()
            colspan, rowspan = self._cell_span
            for _ in range(colspan):
                self._row.append(text)
            if rowspan > 1:
                pos = len(self._row) - colspan
                for i in range(colspan):
                    self._pending[pos + i] = (rowspan - 1, text)
            self._cell = None
        elif tag == "tr" and self._table_stack and self._row is not None:
            row = self._row
            # re-inject rowspans from previous rows
            if self._pending:
                expanded: List[str] = []
                col = 0
                pending = {k: v for k, v in self._pending.items()}
                width = max(len(row) + len(pending), max(pending) + 1 if pending else 0)
                while col < width:
                    if col in pending:
                        expanded.append(pending[col][1])
                    elif row:
                        expanded.append(row.pop(0))
                    col += 1
                expanded.extend(row)
                row = expanded
                new_pending = {}
                for k, (left, text) in self._pending.items():
                    if left - 1 > 0:
                        new_pending[k] = (left - 1, text)
                self._pending = new_pending
            self._table_stack[-1].append(row)
            self._row = None
        elif tag == "table" and self._table_stack:
            self.tables.append(self._table_stack.pop())
            self._pending = {}

    def handle_data(self, data: str):
        if self._cell is not None:
            self._cell.append(data)


def extract_tables(html: str) -> List[List[List[str]]]:
    p = _TableExtractor()
    p.feed(html)
    p.close()
    return p.tables


def _norm(text: str) -> str:
    return re.sub(r"[^a-z]", "", (text or "").lower())


# ----------------------------------------------------------------------------- #
# Footer / generation timestamp
# ----------------------------------------------------------------------------- #

_FOOTER_MODERN = re.compile(r"(\d{4}-\d{2}-\d{2})\s+(\d{2}\.\d{2}\.\d{2})")
_FOOTER_LEGACY = re.compile(r"(\d{4}-\d{2}-\d{2})-(\d{2}\.\d{2}\.\d{2})")


def extract_report_generated_at(html: str) -> str:
    """Return the document generation timestamp as 'YYYY-MM-DD HH:MM:SS', or ''.

    Examples observed in official reports (2026-10-07):
      '2024-02-06 11.19.44'   (modern, regenerated long after the game)
      '2005-10-05-21.40.47'   (legacy, generated at game time)
      '2016-10-12-22.08.17'   (legacy, generated at game time)
    """
    text = re.sub(r"<[^>]+>", " ", html)
    tail = text[-1500:]
    m = _FOOTER_MODERN.search(tail)
    if m:
        return f"{m.group(1)} {m.group(2).replace('.', ':')}"
    m = _FOOTER_LEGACY.search(tail)
    if m:
        return f"{m.group(1)} {m.group(2).replace('.', ':')}"
    # fall back to anywhere in the document
    m = _FOOTER_MODERN.search(text)
    if m:
        return f"{m.group(1)} {m.group(2).replace('.', ':')}"
    m = _FOOTER_LEGACY.search(text)
    if m:
        return f"{m.group(1)} {m.group(2).replace('.', ':')}"
    return ""


def report_era(game_date: str, generated_at: str, *, tolerance_hours: int = 24
               ) -> Tuple[Optional[bool], str]:
    """Is a report frozen at game time (=> original record) or regenerated later?

    Returns ``(is_frozen, note)``. ``is_frozen`` is None when it cannot be decided.
    """
    if not game_date or not generated_at:
        return None, "missing game date or report generation timestamp"
    try:
        from datetime import datetime

        gd = datetime.strptime(game_date, "%Y-%m-%d")
        ga = datetime.strptime(generated_at, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None, f"unparseable dates (game={game_date!r}, generated={generated_at!r})"
    delta_h = (ga - gd).total_seconds() / 3600.0
    if delta_h <= tolerance_hours:
        return True, (f"report generated {delta_h:.1f}h after the game date -> frozen at game time; "
                      f"content is the ORIGINAL record unless the league edited it in place")
    return False, (f"report generated {delta_h / 24:.0f} days after the game date -> the document "
                   f"has been REGENERATED and carries the CURRENT record")


# ----------------------------------------------------------------------------- #
# Player cell parsing
# ----------------------------------------------------------------------------- #

_PLAYER_RE = re.compile(
    r"^\s*(?:(?P<sweater>\d{1,2})\s+)?(?P<name>[^\d()]+?)\s*(?:\((?P<total>\d+)\))?\s*$"
)


def parse_player_cell(cell: str) -> Optional[PlayerRef]:
    """Parse '86 N.KUCHEROV(1)', 'J. BULIS (1)', 'M. RYDER', 'D.PHANEUF'."""
    if not cell:
        return None
    text = re.sub(r"\s+", " ", cell).strip()
    if not text or _norm(text) in {"unassisted", "none", "na", "penaltyshot", "ps"}:
        return None
    text = text.replace("(A)", "").replace("(C)", "")  # captaincy markers
    m = _PLAYER_RE.match(text)
    if not m:
        return PlayerRef(id=None, name=text, sweater=None)
    name = (m.group("name") or "").strip(" .")
    if not name:
        return None
    sweater = int(m.group("sweater")) if m.group("sweater") else None
    return PlayerRef(id=None, name=name, sweater=sweater)


def _is_unassisted(cell: str) -> bool:
    return _norm(cell).startswith("unassisted") or _norm(cell) in {"none", "na"}


# ----------------------------------------------------------------------------- #
# Official Game Summary (HTML) parser
# ----------------------------------------------------------------------------- #

_HEADER_KEYS = {
    "goal": ("scorer",),
    "assist": ("assist",),
    "per": ("per",),
    "time": ("time", "temps"),
    "team": ("team", "club"),
    "strength": ("str",),
    "number": ("g",),
}


def _header_map(row: List[str]) -> Dict[str, List[int]]:
    """Map semantic column names to indices, tolerating bilingual headers."""
    out: Dict[str, List[int]] = {}
    for idx, raw in enumerate(row):
        n = _norm(raw)
        if not n:
            continue
        if "scorer" in n or n in {"butgoal", "goal"}:
            out.setdefault("scorer", []).append(idx)
        elif "assist" in n or "aide" in n:
            out.setdefault("assist", []).append(idx)
        elif n.startswith("per") or n == "period":
            out.setdefault("per", []).append(idx)
        elif "temps" in n or "time" in n:
            out.setdefault("time", []).append(idx)
        elif "team" in n or "club" in n:
            out.setdefault("team", []).append(idx)
        elif n in {"str", "sitstr", "strength"} or n.endswith("str"):
            out.setdefault("strength", []).append(idx)
        elif n in {"g", "bg", "no"}:
            out.setdefault("number", []).append(idx)
    return out


def parse_gs_report(html: str, *, url: str, retrieved_at: str,
                    game_id: Optional[int] = None, season: str = "") -> GameState:
    """Parse an official Game Summary document into a :class:`GameState`."""
    state = GameState(
        game_id=int(game_id) if game_id else 0,
        source_key="doc.GS",
        source_url=url,
        retrieved_at=retrieved_at,
        season=season,
    )
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;?", " ", text)
    state.report_generated_at = extract_report_generated_at(html)

    m = re.search(r"(?:Game|Match/Game)\s+(\d{4})", text)
    if m and not game_id:
        state.parse_warnings.append("no game id supplied; report header game number "
                                   f"{m.group(1)} was found but a full id cannot be derived")
    m = re.search(r"([A-Z][a-z]+day,\s+[A-Z][a-z]+\s+\d{1,2},\s+\d{4})", text)
    if m:
        from datetime import datetime

        try:
            state.game_date = datetime.strptime(m.group(1).replace(",", ""), "%A %B %d %Y").strftime("%Y-%m-%d")
        except ValueError:
            state.parse_warnings.append(f"could not parse game date {m.group(1)!r}")
    if not state.game_date:
        m2 = re.search(r"(\d{4}-\d{2}-\d{2})-\d{2}\.\d{2}\.\d{2}", html)
        if m2:
            state.game_date = m2.group(1)

    tables = extract_tables(html)
    scoring_table = None
    header_row = None
    for table in tables:
        for row in table:
            n = _norm(" ".join(row))
            if "scorer" in n and ("assist" in n or "aide" in n) and ("per" in n):
                scoring_table, header_row = table, row
                break
        if scoring_table is not None:
            break

    if scoring_table is None:
        state.parse_warnings.append(
            "SCORING SUMMARY table not found - document may use an unsupported layout; "
            "no goals were extracted"
        )
        return state

    cmap = _header_map(header_row)
    missing = [k for k in ("scorer", "per", "time", "team") if k not in cmap]
    if missing:
        state.parse_warnings.append(f"scoring summary header missing expected columns: {missing}")

    def cell(row: List[str], key: str, pos: int = 0) -> str:
        idxs = cmap.get(key, [])
        if pos >= len(idxs):
            return ""
        idx = idxs[pos]
        return row[idx].strip() if idx < len(row) else ""

    header_idx = scoring_table.index(header_row)
    for row in scoring_table[header_idx + 1:]:
        if not any(c.strip() for c in row):
            continue
        period_raw = cell(row, "per")
        time_raw = cell(row, "time")
        team_raw = cell(row, "team")
        scorer_raw = cell(row, "scorer")
        if ":" not in time_raw:
            continue
        if not _norm(period_raw) and not scorer_raw:
            continue
        period_text = _norm(period_raw)          # letters only, for OT/SO keywords
        period_type = "REG"
        period_num: Optional[int] = None
        if period_text.startswith("ot") or "overtime" in period_text:
            period_type, period_num = "OT", 4
        elif period_text in {"so", "shootout", "soot"}:
            period_type, period_num = "SO", 5
        else:
            # NOTE: must search the RAW cell - _norm() strips digits
            m = re.search(r"\d+", period_raw)
            if m:
                period_num = int(m.group(0))
        if period_num is None:
            state.parse_warnings.append(f"skipped scoring row with unreadable period {period_raw!r}")
            continue

        strength = cell(row, "strength").upper().replace(" ", "")
        scorer = parse_player_cell(scorer_raw)
        assists: List[PlayerRef] = []
        for pos in (0, 1):
            raw = cell(row, "assist", pos)
            if not raw or _is_unassisted(raw):
                continue
            p = parse_player_cell(raw)
            if p:
                assists.append(p)
        goal = GoalEvent(
            period=period_num,
            clock=time_raw,
            team=team_raw.upper() or (state.away.abbrev if state.away else ""),
            scorer=scorer,
            assists=assists,
            strength=strength,
            period_type=period_type,
            is_own_goal=bool(re.search(r"\bOG\b", scorer_raw)) or "owngoal" in _norm(scorer_raw),
            is_penalty_shot="PS" in strength or "penaltyshot" in _norm(scorer_raw),
        )
        if goal.period_type == "SO":
            state.parse_warnings.append("shootout row present in scoring summary (kept, not a goal)")
        state.goals.append(goal)

    # ---- team identity ---------------------------------------------------- #
    # The report header carries team logos in document order (visitor first, then
    # the home team). The league shield (logo(cnhl)) appears between them and MUST be
    # filtered out: an earlier version of this parser happily reported the home team
    # as "NHL". Verified against 20232024/GS020001.HTM, 20052006/GS020001.HTM and
    # 20132014/GS020001.HTM on 2026-10-07.
    logos = _team_abbrevs_from_logos(html)
    goal_teams: List[str] = []
    for g in state.goals:
        if g.team and g.team.upper() not in goal_teams:
            goal_teams.append(g.team.upper())

    away_ab: Optional[str] = None
    home_ab: Optional[str] = None
    if len(logos) >= 2:
        away_ab, home_ab = logos[0], logos[1]
        unexpected = [t for t in goal_teams if t not in (away_ab, home_ab)]
        if unexpected:
            state.parse_warnings.append(
                f"logo-derived teams {away_ab}/{home_ab} do not cover the teams named in the "
                f"scoring summary ({', '.join(goal_teams)}) - the home/away order may be wrong")
    elif len(goal_teams) == 2:
        away_ab, home_ab = goal_teams
        state.parse_warnings.append(
            "no team logo markers found; home/away order was inferred from the scoring summary "
            "and must be confirmed before the record is trusted")
    elif len(goal_teams) == 1:
        away_ab = home_ab = None
        state.parse_warnings.append(
            "only one team appears in the scoring summary and no logo markers were found; "
            "away/home cannot be established from this document alone")

    if away_ab and home_ab:
        state.away = state.away or TeamState(abbrev=away_ab)
        state.home = state.home or TeamState(abbrev=home_ab)
        if any(g.period_type.upper() == "SO" for g in state.goals):
            # In a shootout game the scoring summary shows regulation + OT goals only,
            # so the goal counts are NOT the final score (the official final adds the
            # shootout-deciding goal to the winner). Refuse to invent it.
            state.parse_warnings.append(
                "shootout goals are present: goal counts exclude the shootout winner, so no "
                "final score is derived from this document (use the GameCenter API instead)")
        else:
            state.away.score = state.goal_count(state.away.abbrev)
            state.home.score = state.goal_count(state.home.abbrev)
    return state


#: Logo tokens that are not clubs (league shield, all-star formats, conference marks).
_NON_TEAM_LOGOS = {"nhl", "nfo", "eas", "wes", "all", "ast"}


def _team_abbrevs_from_logos(html: str) -> List[str]:
    """Team abbreviations in document order, derived from the official logo filenames.

    The official reports reference ``.../images/logo<C><abbr>.gif`` (e.g. ``logocnsh.gif``,
    ``logoctor.gif``, ``logoccbj.gif``). Non-club tokens are filtered out and duplicates
    removed, leaving the visitor team first and the home team second.
    """
    out: List[str] = []
    for token in re.findall(r"logo(c[a-z0-9]+)\.gif", html, flags=re.I):
        token = token.lower()
        if len(token) < 4:
            continue
        abbr = token[1:4].upper()
        if abbr.lower() in _NON_TEAM_LOGOS or not re.fullmatch(r"[A-Z]{3}", abbr):
            continue
        if abbr not in out:
            out.append(abbr)
    return out


# ----------------------------------------------------------------------------- #
# GameCenter play-by-play parser
# ----------------------------------------------------------------------------- #

def parse_api_pbp(payload: dict, *, url: str, retrieved_at: str) -> GameState:
    away_t = payload.get("awayTeam", {}) or {}
    home_t = payload.get("homeTeam", {}) or {}
    state = GameState(
        game_id=int(payload.get("id", 0)),
        source_key="api.pbp",
        source_url=url,
        retrieved_at=retrieved_at,
        game_date=payload.get("gameDate", ""),
        season=str(payload.get("season", "")),
        game_state=payload.get("gameState", ""),
    )
    state.away = TeamState(abbrev=(away_t.get("abbrev") or "").upper(),
                           name=(away_t.get("commonName") or {}).get("default", ""),
                           score=away_t.get("score"), shots=away_t.get("sog"))
    state.home = TeamState(abbrev=(home_t.get("abbrev") or "").upper(),
                           name=(home_t.get("commonName") or {}).get("default", ""),
                           score=home_t.get("score"), shots=home_t.get("sog"))
    state.period = (payload.get("periodDescriptor") or {}).get("number")
    state.in_intermission = bool((payload.get("clock") or {}).get("inIntermission"))

    for ev in payload.get("plays", []) or []:
        if ev.get("typeDescKey") != "goal":
            continue
        d = ev.get("details", {}) or {}
        pd = ev.get("periodDescriptor", {}) or {}
        ptype = pd.get("periodType", "REG")
        owner_id = d.get("eventOwnerTeamId")
        scoring_is_home = (owner_id is not None and owner_id == home_t.get("id"))
        goal = GoalEvent(
            period=int(pd.get("number", 0) or 0),
            clock=ev.get("timeInPeriod", ""),
            team="",
            event_id=ev.get("eventId"),
            period_type=ptype,
            strength=strength_from_situation(ev, d, scoring_team_is_home=scoring_is_home),
            is_own_goal=bool(d.get("ownGoal")) or bool(d.get("isOwnGoal")),
            away_score_after=d.get("awayScore"),
            home_score_after=d.get("homeScore"),
        )
        if owner_id is not None and state.away and state.home:
            goal.team = state.home.abbrev if scoring_is_home else state.away.abbrev
        goal.scorer = PlayerRef(id=d.get("scoringPlayerId"), name="")
        for slot in ("assist1PlayerId", "assist2PlayerId"):
            pid = d.get(slot)
            if pid:
                goal.assists.append(PlayerRef(id=pid, name=""))
        if not goal.scorer.id:
            state.parse_warnings.append(f"goal event {ev.get('eventId')} has no scoringPlayerId")
        state.goals.append(goal)
    if not state.game_date:
        state.parse_warnings.append("play-by-play payload had no gameDate")
    return state


def strength_from_situation(ev: dict, details: dict, *, scoring_team_is_home: bool) -> str:
    """Derive EV / PP / SH / -EN / PS from the official ``situationCode``.

    In api-web the four digits are awayGoalie, awaySkaters, homeSkaters, homeGoalie
    (verified 2026-10-07 on 2023020001: a 5-on-5 goal carried '1551'). The strength
    depends on which team scored, so the caller must say whose goal it is. A zero in
    the *opponent's* goalie digit means the opponent had pulled the goalie.
    """
    if (details.get("shotType") or "") == "penalty-shot":
        return "PS"
    code = str(ev.get("situationCode", "") or "")
    if len(code) != 4 or not code.isdigit():
        return ""
    away_goalie, away_sk, home_sk, home_goalie = (int(c) for c in code)
    opp_goalie = home_goalie if scoring_team_is_home else away_goalie
    own_sk = home_sk if scoring_team_is_home else away_sk
    opp_sk = away_sk if scoring_team_is_home else home_sk
    strength = "EV"
    if own_sk > opp_sk:
        strength = "PP"
    elif own_sk < opp_sk:
        strength = "SH"
    if opp_goalie == 0:
        strength += "-EN"
    return strength


# ----------------------------------------------------------------------------- #
# GameCenter boxscore parser
# ----------------------------------------------------------------------------- #

def parse_api_boxscore(payload: dict, *, url: str, retrieved_at: str) -> GameState:
    away_t = payload.get("awayTeam", {}) or {}
    home_t = payload.get("homeTeam", {}) or {}
    state = GameState(
        game_id=int(payload.get("id", 0)),
        source_key="api.boxscore",
        source_url=url,
        retrieved_at=retrieved_at,
        game_date=payload.get("gameDate", ""),
        season=str(payload.get("season", "")),
        game_state=payload.get("gameState", ""),
    )
    state.away = TeamState(abbrev=(away_t.get("abbrev") or "").upper(),
                           name=(away_t.get("commonName") or {}).get("default", ""),
                           score=away_t.get("score"), shots=away_t.get("sog"))
    state.home = TeamState(abbrev=(home_t.get("abbrev") or "").upper(),
                           name=(home_t.get("commonName") or {}).get("default", ""),
                           score=home_t.get("score"), shots=home_t.get("sog"))
    totals = []
    for side_key, team_state in (("awayTeam", state.away), ("homeTeam", state.home)):
        side = (payload.get("playerByGameStats") or {}).get(side_key, {}) or {}
        for group in ("forwards", "defense", "goalies"):
            for p in side.get(group, []) or []:
                totals.append({
                    "player_id": p.get("playerId"),
                    "name": (p.get("name") or {}).get("default", ""),
                    "sweater": p.get("sweaterNumber"),
                    "team": team_state.abbrev if team_state else "",
                    "position": p.get("position", ""),
                    "goals": p.get("goals", 0),
                    "assists": p.get("assists", 0),
                    "points": p.get("points", 0),
                })
    state.evidence["player_totals"] = totals
    return state


def parse_api_score(payload: dict) -> List[dict]:
    """Extract the list of games from a ``/v1/score/{date}`` payload."""
    games = []
    for day in payload.get("gamesByDate", []) or []:
        for g in day.get("games", []) or []:
            games.append({
                "id": g.get("id"),
                "date": day.get("date"),
                "state": g.get("gameState"),
                "start_utc": g.get("startTimeUTC"),
                "away": (g.get("awayTeam") or {}).get("abbrev"),
                "home": (g.get("homeTeam") or {}).get("abbrev"),
                "away_score": (g.get("awayTeam") or {}).get("score"),
                "home_score": (g.get("homeTeam") or {}).get("score"),
                "period": (g.get("periodDescriptor") or {}).get("number"),
            })
    return games
