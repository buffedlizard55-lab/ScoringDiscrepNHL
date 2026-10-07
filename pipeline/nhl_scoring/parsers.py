"""Parsers: official artifact -> :class:`~ NHL_scoring.models.SourceRecord`.

Two independent renderings of the same game are produced by the league:

1. ``api-web.nhl.com`` Game Center JSON (lives, mutated in place).
2. ``nhl.com/scores/htmlreports`` RTSS sheets (generated after the fact, then
   effectively frozen).

Neither is versioned or annotated with corrections, so all discrepancy logic
lives downstream of these parsers. Both parsers are strict about *not* guessing:
anything they cannot read is recorded in ``parse_notes`` and makes the game
"unreadable" for the affected check rather than quietly empty. That is what
keeps the resulting database defensible.
"""

from __future__ import annotations

import html
import json
import re
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .models import (
    Goal,
    Player,
    SourceRecord,
    TeamTotals,
    ascii_fold,
    clock_to_seconds,
    norm_strength,
    parse_report_player,
)
from .sources import GameRef

PARSER_VERSION = "3"
ABBREV_RE = re.compile(r"\b([A-Z]{2,3})\b")
TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
GEN_TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2})[- ](\d{1,2})\.(\d{2})\.(\d{2})")


# --------------------------------------------------------------------------
# shared helpers
# --------------------------------------------------------------------------
def norm_period(cell: str) -> Tuple[Optional[int], str]:
    """``'3'`` -> (3,'REG'); ``'OT'`` -> (4,'OT'); ``'2OT'`` -> (5,'OT'); ``'SO'`` -> (5,'SO')."""
    text = (cell or "").strip().upper()
    if not text:
        return None, ""
    if text.isdigit():
        n = int(text)
        return n, "REG" if n <= 3 else "OT"
    m = re.fullmatch(r"(\d)OT", text)
    if m:
        return 3 + int(m.group(1)), "OT"
    if text == "OT":
        return 4, "OT"
    if "SO" in text or "SHOOTOUT" in text or text.startswith("B SO"):
        return 5, "SO"
    return None, text


def _cells_of(row: Iterable[str]) -> List[str]:
    return [c for c in (cell.strip() for cell in row)]


def player_from_api(obj: Optional[Dict[str, Any]], counter_key: str = "") -> Optional[Player]:
    if not obj:
        return None
    first = ""
    names = obj.get("name") or {}
    if isinstance(names, dict):
        first = names.get("default") or ""
    full = first or " ".join(
        x for x in (obj.get("firstName", {}).get("default") if isinstance(obj.get("firstName"), dict) else None,
                    obj.get("lastName", {}).get("default") if isinstance(obj.get("lastName"), dict) else None)
        if x
    )
    last = obj.get("lastName", {}).get("default", "") if isinstance(obj.get("lastName"), dict) else ""
    fn = obj.get("firstName", {}).get("default", "") if isinstance(obj.get("firstName"), dict) else ""
    initial = ascii_fold(fn[:1]) if fn else ""
    if not last and full:
        parts = full.replace(".", " ").split()
        if parts:
            last = parts[-1]
            initial = initial or ascii_fold(parts[0][:1])
    counter = None
    if counter_key:
        raw = obj.get(counter_key)
        if isinstance(raw, int):
            counter = raw
    return Player(
        name=full or last,
        surname=ascii_fold(last or full),
        initial=initial,
        player_id=obj.get("playerId"),
        sweater_number=obj.get("sweaterNumber"),
        counter=counter,
    )


# --------------------------------------------------------------------------
# 1. api-web Game Center JSON
# --------------------------------------------------------------------------
def parse_api_landing(payload: Dict[str, Any], *, game_id: str, url: str,
                      retrieved_at: str = "", sha256: Optional[str] = None) -> SourceRecord:
    """Project ``gamecenter/{id}/landing`` (or the scoreboard ``goals`` list) onto the model."""
    ref = GameRef(game_id)
    rec = SourceRecord(source="nhl_api_landing", game_id=ref.game_id, url=url,
                       retrieved_at=retrieved_at, sha256=sha256, parser_version=PARSER_VERSION)
    notes: List[str] = []
    rec.parse_notes = notes
    if payload.get("limitedScoring"):
        # The league flags games whose detail is withheld. Treating that as
        # "no goals scored" would invent a discrepancy, so it is a gap instead.
        rec.parse_ok = False
        notes.append("payload flags limitedScoring=true: scoring detail may be withheld by the league")
    for side, key in (("away", "awayTeam"), ("home", "homeTeam")):
        team = payload.get(key) or {}
        abbrev = team.get("abbrev")
        totals = TeamTotals(abbrev=abbrev or side.upper(), goals=team.get("score"), shots=team.get("sog"))
        if side == "away":
            rec.away_abbrev, rec.away_score, rec.away_team = abbrev, team.get("score"), totals
        else:
            rec.home_abbrev, rec.home_score, rec.home_team = abbrev, team.get("score"), totals
        if abbrev:
            rec.totals[abbrev] = totals
    summary = payload.get("summary") or {}
    blocks = summary.get("scoring")
    if blocks is None and isinstance(payload.get("goals"), list):
        blocks = [{"periodDescriptor": {"number": g.get("period"), "periodType": "REG"},
                   "goals": [g]} for g in payload.get("goals") or []]
        notes.append("derived from scoreboard goals[] (one block per goal; period type not asserted)")
    order = 0
    for block in blocks or []:
        pd = block.get("periodDescriptor") or {}
        blk_period = pd.get("number")
        for raw in block.get("goals") or []:
            order += 1
            assists = [a for a in (player_from_api(x, "assistsToDate") for x in (raw.get("assists") or [])) if a]
            modifier = raw.get("goalModifier") or "none"
            strength_raw = raw.get("strength") or ""
            period = raw.get("period") if raw.get("period") is not None else blk_period
            goal = Goal(
                order=order,
                period=int(period) if period is not None else -1,
                clock=raw.get("timeInPeriod") or "",
                team=(raw.get("teamAbbrev") or {}).get("default") if isinstance(raw.get("teamAbbrev"), dict) else raw.get("teamAbbrev") or "",
                is_home=raw.get("isHome"),
                strength=norm_strength(strength_raw),
                strength_raw=strength_raw,
                scorer=player_from_api(raw, "goalsToDate"),
                assists=assists,
                away_score=raw.get("awayScore"),
                home_score=raw.get("homeScore"),
                player_id=raw.get("playerId"),
                event_id=raw.get("eventId"),
                shot_type=raw.get("shotType"),
                goal_modifier=modifier,
                own_goal=str(modifier).lower().startswith("own"),
                empty_net=True if "empty" in str(modifier).lower() else None,
            )
            if goal.empty_net is None and "empty" in " ".join(str(v) for v in raw.values()).lower():
                goal.empty_net = True
            rec.goals.append(goal)
    # goals per period per team, counted from the goal list (the totals table is
    # filled from the header score, not from this count, so the two can disagree)
    for goal in rec.goals:
        tot = rec.totals.get(goal.team)
        if tot is not None and goal.period is not None:
            tot.goals_by_period[goal.period] = tot.goals_by_period.get(goal.period, 0) + 1
    if not rec.goals:
        notes.append("zero goals parsed from summary.scoring")
    return rec


def parse_api_right_rail(payload: Dict[str, Any], ref: GameRef) -> Dict[str, Any]:
    """Linescore + official report links, which only live on the right-rail."""
    out: Dict[str, Any] = {"reports": {}, "by_period": [], "shots_by_period": [], "team_stats": []}
    reports = payload.get("gameReports") or {}
    key_map = {"gameSummary": "GS", "eventSummary": "ES", "playByPlay": "PL",
               "faceoffSummary": "FS", "faceoffComparison": "FC", "rosters": "RO",
               "shotSummary": "SS", "toiAway": "TV", "toiHome": "TH"}
    for key, code in key_map.items():
        if isinstance(reports.get(key), str):
            out["reports"][code] = reports[key]
    for row in ((payload.get("linescore") or {}).get("byPeriod") or []):
        pd = row.get("periodDescriptor") or {}
        out["by_period"].append({"period": pd.get("number"), "period_type": pd.get("periodType"),
                                 "away": row.get("away"), "home": row.get("home")})
    for row in (payload.get("shotsByPeriod") or []):
        pd = row.get("periodDescriptor") or {}
        out["shots_by_period"].append({"period": pd.get("number"), "away": row.get("away"),
                                       "home": row.get("home")})
    for row in (payload.get("teamGameStats") or []):
        out["team_stats"].append({"category": row.get("category"), "away": row.get("awayValue"),
                                  "home": row.get("homeValue")})
    out["game_id"] = ref.game_id
    out["url"] = ref.gamecenter_right_rail
    return out


# --------------------------------------------------------------------------
# 2. RTSS HTML reports
# --------------------------------------------------------------------------
class _TableExtractor(HTMLParser):
    """Flatten a legacy HTML report into rows of text cells, in document order.

    The reports nest tables inside table cells (the modern format is built that
    way), so we keep a stack and emit every ``<tr>`` we see. Column ownership is
    resolved later by shape matching, which is what makes this tolerant of the
    2000-01 vs 2015-16 layout change we observed.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: List[Tuple[int, List[str]]] = []   # (depth, cells)
        self._depth = 0
        self._cell_parts: List[str] | None = None
        self._row: Optional[List[str]] = None
        self._in_img_alt: bool = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "table":
            self._depth += 1
        elif tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell_parts = []
        elif tag == "img":
            alt = dict(attrs).get("alt")
            if alt and self._cell_parts is not None:
                self._cell_parts.append(" " + alt + " ")

    def handle_endtag(self, tag: str) -> None:
        if tag == "table":
            self._depth = max(0, self._depth - 1)
        elif tag == "tr" and self._row is not None:
            cells = _cells_of(self._row)
            if any(cells):
                self.rows.append((self._depth, cells))
            self._row = None
        elif tag in ("td", "th") and self._cell_parts is not None:
            if self._row is not None:
                self._row.append(html.unescape(" ".join(self._cell_parts)))
            self._cell_parts = None

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts.append(data)


def extract_rows(markup: str) -> List[List[str]]:
    parser = _TableExtractor()
    parser.feed(markup)
    parser.close()
    return [cells for _depth, cells in parser.rows]


def _is_player_cell(cell: str) -> bool:
    return parse_report_player(cell) is not None


SCORING_HEADER_TOKENS = {"goal scorer", "scorer"}


def parse_gs_report(markup: str, *, game_id: str, url: str, retrieved_at: str = "",
                    sha256: Optional[str] = None) -> SourceRecord:
    """Parse the scoring summary out of an official Game Summary (GS) report.

    Supported layouts, both captured from the live site on 2026-10-07:

    * legacy (1999/2000-01 through the 2000s)::

        | G | Per | Time | Team | Goal Scorer | Assist | Assist | L.A | DET | STR |

    * modern (2015-16 onward, still current in 2026-27)::

        | G | Per | Time | Str | Team | Goal Scorer | Assist | Assist | FLA on Ice | CAR on Ice |
    """
    ref = GameRef(game_id)
    rec = SourceRecord(source="nhl_gs_report", game_id=ref.game_id, url=url,
                       retrieved_at=retrieved_at, sha256=sha256, parser_version=PARSER_VERSION)
    notes: List[str] = []
    rec.parse_notes = notes   # same list object: late parse steps append through rec
    rows = extract_rows(markup)
    if not rows:
        rec.parse_ok = False
        notes.append("no table rows found: markup layout changed, or the report is an error page")
        return rec

    m = GEN_TS_RE.search(markup)
    if m:
        rec.generated_at = f"{m.group(1)}T{int(m.group(2)):02d}:{m.group(3)}:{m.group(4)}"
    else:
        notes.append("no report generation timestamp in footer; as-of bound unknown")

    # --- header: date, teams, final score -------------------------------
    text_blob = " ".join(" ".join(r) for r in rows[:12])
    m = re.search(r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+"
                  r"([A-Z][a-z]+)\s+(\d{1,2}),\s+(\d{4})\b", text_blob)
    if m:
        month = {"January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6,
                 "July": 7, "August": 8, "September": 9, "October": 10, "November": 11,
                 "December": 12}[m.group(2)]
        rec.game_date = f"{int(m.group(4))}-{month:02d}-{int(m.group(3)):02d}"
    else:
        notes.append("game date not found in header")
    names = re.findall(r"\b([A-Z][A-Z .'/-]{3,30}?(?:S|H))\b", text_blob)
    full_names = sorted({n.strip() for n in re.findall(r"[A-Z][A-Za-z .'/-]{3,28}\s+[A-Z][A-Za-z]{2,}", text_blob)})
    rec.extra["header_names"] = full_names[:8]

    # --- locate the scoring-summary rows --------------------------------
    header_row_idx: Optional[int] = None
    for idx, cells in enumerate(rows):
        lowered = [c.lower() for c in cells]
        if any(tok in lowered for tok in SCORING_HEADER_TOKENS) and "per" in lowered and "time" in lowered:
            header_row_idx = idx
            rec.extra["scoring_header"] = cells
            break
    if header_row_idx is None:
        rec.parse_ok = False
        notes.append("scoring summary header row not found; refusing to guess goal rows")
        return rec

    header = [c.lower() for c in rows[header_row_idx]]
    team_col = None
    for idx, cell in enumerate(header):
        if cell == "team":
            team_col = idx
            break
    if team_col is None:
        rec.parse_ok = False
        notes.append("no 'Team' column in scoring summary header")
        return rec
    # Layout discriminator: the modern sheet carries a 'Str' column immediately
    # before 'Team'; the legacy sheet has no such column (its strength code sits
    # at the far right of the row, after both teams' on-ice/shots columns).
    layout = "modern" if team_col >= 1 and header[team_col - 1] == "str" else "legacy"
    rec.extra["layout"] = layout
    if team_col < (2 if layout == "modern" else 1):
        rec.parse_ok = False
        notes.append("scoring summary header is malformed: 'Team' column too far left")
        return rec

    order = 0
    for cells in rows[header_row_idx + 1:]:
        if not cells:
            continue
        first = cells[0].strip()
        if not first.isdigit():
            if order:
                break
            continue
        if team_col >= len(cells):
            notes.append(f"row for goal {first} is shorter than the header; skipped")
            continue
        team_cell = cells[team_col].strip()
        if not re.fullmatch(r"[A-Z]{2,3}(\.[A-Z]{1,3})?", team_cell.replace(".", ".")):
            if order:
                break
            continue
        order += 1
        # Column offsets, verified against real sheets:
        #   legacy  G | Per | Time | Team | Scorer | A1 | A2 | <away on ice> | <home on ice> | STR
        #   modern  G | Per | Time | Str  | Team | Scorer | A1 | A2 | <away on Ice> | <home on Ice>
        if layout == "legacy":
            per_cell, time_cell = cells[team_col - 2], cells[team_col - 1]
            strength_cell = ""
            for cell in reversed(cells):
                if re.fullmatch(r"(EV|PP|SH|PS|SO|EV-EN|PP-EN|SH-EN|GWG)", cell.strip()):
                    strength_cell = cell.strip()
                    break
        else:
            per_cell, time_cell = cells[team_col - 3], cells[team_col - 2]
            strength_cell = cells[team_col - 1]
        scorer_cell = cells[team_col + 1] if team_col + 1 < len(cells) else ""
        tail = cells[team_col + 2:team_col + 4]
        period, ptype = norm_period(per_cell)
        team_abbrev = team_cell.upper().replace(".", "")
        if team_abbrev == "LA":
            team_abbrev = "LAK"
        awarded = "award" in scorer_cell.lower()
        goal = Goal(
            order=order,
            period=period if period is not None else -1,
            clock=time_cell.strip(),
            team=team_abbrev,
            strength=norm_strength(strength_cell or ""),
            strength_raw=(strength_cell or "").strip(),
            scorer=parse_report_player(scorer_cell),
            assists=[p for p in (parse_report_player(c) for c in tail) if p],
            awarded=awarded,
        )
        goal.scorer = goal.scorer or None
        if goal.scorer and "own goal" in scorer_cell.lower():
            goal.own_goal = True
        elif goal.scorer:
            goal.own_goal = False
        if "(EN)" in (strength_cell or "").upper() or "EMPTY NET" in " ".join(cells).upper():
            goal.empty_net = True
        if period is None:
            goal.period = -1
            rec.extra.setdefault("unparsed_periods", []).append({"order": order, "raw": per_cell, "type": ptype})
        rec.goals.append(goal)

    if order == 0:
        notes.append("scoring summary present but contained zero goal rows")
    # --- BY PERIOD tables (modern layout) --------------------------------
    _parse_modern_by_period(rows, rec)
    _parse_legacy_totals(rows, rec)
    return rec


def _scoring_header_abbrevs(rec: SourceRecord) -> List[str]:
    """Team abbrevs as the GS header names them, in column order.

    Modern sheets title the last two scoring columns ``MTL on Ice`` / ``TOR on
    Ice``; legacy sheets title the two shot columns with the club abbreviations
    (``L.A``, ``DET``). Both give the same thing: the ordered pair of abbrevs,
    which is what lets us bind the BY PERIOD tables to a team instead of
    assuming "first table is the away team".
    """
    header = rec.extra.get("scoring_header") or []
    out: List[str] = []
    for cell in header:
        m = re.search(r"([A-Z]{2,3})\.?\s+on\s+[Ii]ce", cell)
        if m and m.group(1) not in out:
            out.append(m.group(1))
    if len(out) >= 2:
        return out[:2]
    for cell in header:
        token = cell.strip().upper().replace(".", "")
        if re.fullmatch(r"[A-Z]{2,3}", token) and token not in {"G", "PER", "STR", "T", "TOT"}:
            if token not in out and token != "TEAM":
                out.append(token)
    return out[:2]


def _bind_totals(rec: SourceRecord, totals: Dict[str, TeamTotals]) -> None:
    """Attach per-team totals, then cross-check them against the goal rows.

    If the binding we inferred does not agree with the scoring summary we cannot
    trust it, so we keep the raw table, record the doubt, and skip the totals
    checks for that game rather than emitting a discrepancy that is really a
    parsing error. This is the single most important guard in the GS parser.
    """
    counted: Dict[str, int] = {}
    for goal in rec.goals:
        counted[goal.team] = counted.get(goal.team, 0) + 1
    if not totals:
        rec.parse_notes.append("no per-team totals table parsed; goal-count checks skipped")
        return
    trusted: Dict[str, TeamTotals] = {}
    for abbrev, tot in totals.items():
        if tot.goals is not None and counted.get(abbrev, 0) != tot.goals:
            rec.parse_notes.append(
                f"BY PERIOD table implies {abbrev} scored {tot.goals} but scoring summary has "
                f"{counted.get(abbrev, 0)}; team binding unverified, totals checks skipped for this game"
            )
            continue
        trusted[abbrev] = tot
    if not trusted:
        return
    rec.totals = trusted
    # Deliberate: we never label a GS team "away" or "home" from row order,
    # because the sheets do not state it in a form we can prove. Totals stay
    # keyed by club abbrev, which is all the checks actually need.
    rec.extra["gs_teams"] = sorted(trusted)


def _parse_modern_by_period(rows: List[List[str]], rec: SourceRecord) -> None:
    """Modern layout: one ``Per | Goals | Shots | PN | PIM`` table per team."""
    tables: List[List[List[str]]] = []
    current: Optional[List[List[str]]] = None
    for cells in rows:
        is_header = len(cells) >= 4 and cells[0].strip().lower() == "per" and \
            cells[1].strip().lower() == "goals"
        if is_header:
            if current:
                tables.append(current)
            current = []
            continue
        if current is None:
            continue
        first = cells[0].strip().upper() if cells else ""
        if len(cells) >= 4 and (first.isdigit() or first in {"OT", "TOT", "SO"}):
            current.append(cells)
        elif len(current) and len(cells) < 2:
            tables.append(current)
            current = None
    if current:
        tables.append(current)
    if not tables:
        return
    rec.extra["by_period_tables"] = [
        [{"period": r[0].strip(), "goals": _int_or_none(r[1]), "shots": _int_or_none(r[2]),
          "pn": _int_or_none(r[3]), "pim": _int_or_none(r[4])} for r in t]
        for t in tables
    ]
    abbrevs = _scoring_header_abbrevs(rec)
    totals: Dict[str, TeamTotals] = {}
    for idx, table in enumerate(rec.extra["by_period_tables"]):
        if idx >= len(abbrevs):
            break
        abbrev = abbrevs[idx]
        tot = TeamTotals(abbrev=abbrev)
        for row in table:
            if row["period"].upper() == "TOT":
                tot.goals, tot.shots = row["goals"], row["shots"]
                continue
            pnum, _ = norm_period(row["period"])
            if pnum is None:
                continue
            if row["goals"] is not None:
                tot.goals_by_period[pnum] = row["goals"]
            if row["shots"] is not None:
                tot.shots_by_period[pnum] = row["shots"]
        totals[abbrev] = tot
    _bind_totals(rec, totals)


def _parse_legacy_totals(rows: List[List[str]], rec: SourceRecord) -> None:
    """Legacy layout: ``Per | awayGoals | homeGoals | Per | awayShots | homeShots``.

    The team for each column comes from the sub-header row that repeats the club
    abbreviations, so the binding is read rather than assumed.
    """
    header_idx = None
    for idx, cells in enumerate(rows):
        compact = re.sub(r"[^A-Z]", "", " ".join(cells).upper())
        if "GOALSBYPER" in compact:
            header_idx = idx
            break
    if header_idx is None:
        return
    block = rows[header_idx + 1:]
    if not block:
        return
    sub = [c.strip().upper().replace(".", "") for c in block[0]]
    abbrevs = [c for c in sub if re.fullmatch(r"[A-Z]{2,3}", c) and c not in {"PER", "T"}]
    if len(abbrevs) < 2:
        return
    away, home = abbrevs[0], abbrevs[1]
    if away == "LA":
        away = "LAK"
    totals = {away: TeamTotals(abbrev=away), home: TeamTotals(abbrev=home)}
    for cells in block[1:]:
        vals = [c.strip() for c in cells]
        if not vals or not (vals[0].isdigit() or vals[0].upper() in {"T", "TOT"}):
            continue
        label = vals[0].upper()
        # Positional read: Per | awayGoals | homeGoals | Per(again) | awayShots | homeShots.
        # The repeated period column is why this cannot be "all the numbers".
        if len(vals) < 6 or not all(re.fullmatch(r"\d+", vals[i] or "x") for i in (1, 2, 4, 5)):
            continue
        goals_away, goals_home = int(vals[1]), int(vals[2])
        shots_away, shots_home = int(vals[4]), int(vals[5])
        if label in {"T", "TOT"}:
            totals[away].goals, totals[home].goals = goals_away, goals_home
            totals[away].shots, totals[home].shots = shots_away, shots_home
            continue
        pnum, _ = norm_period(label)
        if pnum is None:
            continue
        totals[away].goals_by_period[pnum] = goals_away
        totals[home].goals_by_period[pnum] = goals_home
        totals[away].shots_by_period[pnum] = shots_away
        totals[home].shots_by_period[pnum] = shots_home
    rec.extra["legacy_totals"] = {k: {"goals": v.goals, "shots": v.shots,
                                      "goals_by_period": v.goals_by_period,
                                      "shots_by_period": v.shots_by_period} for k, v in totals.items()}
    _bind_totals(rec, totals)


def _int_or_none(value: str) -> Optional[int]:
    text = (value or "").strip()
    return int(text) if re.fullmatch(r"-?\d+", text) else None
