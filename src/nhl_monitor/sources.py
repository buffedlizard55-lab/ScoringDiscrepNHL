"""Registry of official NHL data sources used by the monitor.

Every source in this file is either (a) VERIFIED, meaning this project fetched it
successfully and cross-checked its contents against another official artifact, or
(b) UNVERIFIED, meaning it is implemented defensively and the pipeline must confirm
it at runtime before any record relies on it.

VERIFICATION RULES (project charter)
------------------------------------
1. A source may only be marked ``verified`` with a date, a URL and the exact
   observation that verified it (see ``VERIFIED_ON`` / ``EVIDENCE`` below).
2. No record in the database may cite a source whose ``status`` is not
   ``verified`` or ``reachable_at_runtime``.
3. ``reachable_at_runtime`` means: the endpoint family is verified, but that
   specific game's URL/document must be fetched and validated before use.

Errors are never silently swallowed: callers receive the HTTP status code and the
URL so an "unavailable / conflicting" flag can be attached to the record.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional
from datetime import date

# ----------------------------------------------------------------------------- #
# Constants
# ----------------------------------------------------------------------------- #

PROJECT_STARTED = "2026-10-07"
"""Date this project began collecting. Anything before this is 'historical'."""

API_WEB = "https://api-web.nhle.com"
HTML_REPORTS = "https://www.nhl.com/scores/htmlreports"
WAYBACK_CDX = "http://web.archive.org/cdx/search/cdx"
WAYBACK_RAW = "https://web.archive.org/web"

#: Report families that actually exist on the official report host.
#: SC020001.HTM was probed on 2026-10-07 and returned 404 -> there is no "SC" family.
REPORT_KINDS: Dict[str, str] = {
    "GS": "Game Summary (scoring summary, penalties, by-period totals, officials)",
    "ES": "Event Summary (per-player goals/assists/TOI, shots and faceoff summaries)",
    "PL": "Play-by-Play (chronological events with on-ice skaters)",
    "RO": "Club Playing Roster (lineups, scratches, coaches, game officials)",
}


@dataclass
class Source:
    key: str
    name: str
    kind: str  # "official-api" | "official-document" | "official-archive"
    url_template: str
    status: str  # "verified" | "reachable_at_runtime" | "unverified"
    verified_on: Optional[str] = None
    evidence: str = ""
    notes: str = ""
    authoritative_for: List[str] = field(default_factory=list)

    def url(self, **kw) -> str:
        return self.url_template.format(**kw)

    def as_dict(self) -> dict:
        return asdict(self)


# ----------------------------------------------------------------------------- #
# Verified sources
# ----------------------------------------------------------------------------- #

SOURCES: Dict[str, Source] = {
    "api.pbp": Source(
        key="api.pbp",
        name="NHL GameCenter play-by-play (api-web)",
        kind="official-api",
        url_template=API_WEB + "/v1/gamecenter/{game_id}/play-by-play",
        status="verified",
        verified_on=PROJECT_STARTED,
        evidence=(
            "Fetched 2026-10-07 for game 2023020001 (2023-10-10 NSH@TBL). The goal event "
            "for TBL goal #1 carried scoringPlayerId=8476453 (Kucherov), assist1PlayerId=8475167 "
            "(Hedman), assist2PlayerId=8478010 (Point), awayScore=0 homeScore=1 at 09:48 of P1, "
            "which matches the official Game Summary GS020001.HTM line "
            "'86 N.KUCHEROV(1) | 77 V.HEDMAN(1) | 21 B.POINT(1)' and the Play-by-Play report "
            "PL020001.HTM. Player ids were independently cross-checked against PL020001.HTM "
            "text ('NSH #2 SCHENN HIT TBL #86 KUCHEROV' -> 8476453)."
        ),
        notes=(
            "Chunked/chunk-free JSON. Goals are events with typeDescKey == 'goal' (typeCode 505). "
            "Shootout attempts use periodType 'SO' and are NOT goals for record purposes."
        ),
        authoritative_for=["goal attribution", "event times", "video-review-adjacent events", "final score"],
    ),
    "api.boxscore": Source(
        key="api.boxscore",
        name="NHL GameCenter boxscore (api-web)",
        kind="official-api",
        url_template=API_WEB + "/v1/gamecenter/{game_id}/boxscore",
        status="verified",
        verified_on=PROJECT_STARTED,
        evidence=(
            "Fetched 2026-10-07 for 2023020001 and 2005020001. For 2005020001 (2005-10-05 MTL@BOS) "
            "the per-player goal/assist totals (Bulis 1G, Ryder 1G, Koivu 1A, Kovalev 1A, Bonk 1A, "
            "Sundstrom 1A) and the team scores (MTL 2 - BOS 1) and shots (21/30) match the frozen "
            "official report GS020001.HTM for 20052006, which was generated at game time "
            "(footer '2005-10-05-21.40.47')."
        ),
        notes="Smallest useful payload for change detection; per-player goals/assists/points.",
        authoritative_for=["player goal/assist totals", "team score", "shots on goal"],
    ),
    "doc.GS": Source(
        key="doc.GS",
        name="Official Game Summary report (HTML)",
        kind="official-document",
        url_template=HTML_REPORTS + "/{season}/{kind}{game_type:02d}{game_no:04d}.HTM",
        status="reachable_at_runtime",
        verified_on=PROJECT_STARTED,
        evidence=(
            "Fetched 2026-10-07: 20232024/GS020001.HTM (footer '2024-02-06 11.19.44' - report "
            "regenerated months after the game), 20052006/GS020001.HTM (footer '2005-10-05-21.40.47' "
            "- frozen at game time), 20162017/GS020001.HTM (footer '2016-10-12-22.08.17' - frozen), "
            "20132014/GS020001.HTM (exists; bilingual format). 19992000/GS020001.HTM returned 404."
        ),
        notes=(
            "Carries the SCORING SUMMARY. The trailing generation timestamp is the key signal for "
            "whether the document is frozen at game time or regenerated later - see docs/LIMITATIONS.md."
        ),
        authoritative_for=["original scoring record (when frozen)", "current scoring record (when regenerated)"],
    ),
    "doc.ES": Source(
        key="doc.ES",
        name="Official Event Summary report (HTML)",
        kind="official-document",
        url_template=HTML_REPORTS + "/{season}/{kind}{game_type:02d}{game_no:04d}.HTM",
        status="reachable_at_runtime",
        verified_on=PROJECT_STARTED,
        evidence=(
            "Fetched 2026-10-07: 20232024/ES020001.HTM (per-player G/A/P table, shots and faceoff "
            "summaries; 2 chunks) and 20052006/ES010025.HTM (pre-season format without G/A columns)."
        ),
        notes="Layout changed over the years; the parser is header-driven and reports unparsed tables.",
        authoritative_for=["per-player totals cross-check"],
    ),
    "doc.PL": Source(
        key="doc.PL",
        name="Official Play-by-Play report (HTML)",
        kind="official-document",
        url_template=HTML_REPORTS + "/{season}/{kind}{game_type:02d}{game_no:04d}.HTM",
        status="reachable_at_runtime",
        verified_on=PROJECT_STARTED,
        evidence="Fetched 2026-10-07: 20232024/PL020001.HTM (event list with on-ice skaters).",
        notes="Useful for reconstructing what happened around a corrected event.",
        authoritative_for=["event reconstruction"],
    ),
    "doc.RO": Source(
        key="doc.RO",
        name="Official Club Playing Roster report (HTML)",
        kind="official-document",
        url_template=HTML_REPORTS + "/{season}/{kind}{game_type:02d}{game_no:04d}.HTM",
        status="reachable_at_runtime",
        verified_on=PROJECT_STARTED,
        evidence=(
            "Fetched 2026-10-07: 20232024/RO020001.HTM - includes scratches, coaches and game "
            "officials (referees Rooney/Brenk, linespersons Alphonso/Brisebois)."
        ),
        notes="Provides officials and lineups for the record; not a scoring source.",
        authoritative_for=["officials", "lineups"],
    ),
    "archive.cdx": Source(
        key="archive.cdx",
        name="Wayback Machine CDX index (content digests of official documents)",
        kind="official-archive",
        url_template=WAYBACK_CDX,
        status="verified",
        verified_on=PROJECT_STARTED,
        evidence=(
            "Queried 2026-10-07. GS020001.HTM (20232024) -> exactly one snapshot, statuscode 200, "
            "digest TE24NPUUMSEV3LQEBNQE2TN3NO5GNATJ, timestamp 20250125005135. Prefix queries for "
            "20242025/ and 20052006/ returned per-document digests. 2006-era captures of 20052006 "
            "documents are HTTP 302 redirects with the empty digest 3I42H3S6NNFQ2MSVX7XZKYAYSCX5QBYJ."
        ),
        notes=(
            "The digest field lets us detect THAT a document changed without downloading both "
            "versions. Always filter statuscode=='200' and reject redirect/empty digests."
        ),
        authoritative_for=["evidence of document change", "snapshot timestamps"],
    ),
    "archive.snapshot": Source(
        key="archive.snapshot",
        name="Wayback Machine archived copy of an official document",
        kind="official-archive",
        url_template=WAYBACK_RAW + "/{timestamp}id_/{url}",
        status="verified",
        verified_on=PROJECT_STARTED,
        evidence=(
            "Fetched 2026-10-07: 20250125005135id_/https://www.nhl.com/scores/htmlreports/20232024/"
            "GS020001.HTM returned the archived official Game Summary. Its scoring summary and footer "
            "timestamp are identical to the live document fetched the same day (negative control: "
            "for this game no scoring change occurred - see data/reference/verified_facts.json)."
        ),
        notes="Always use the `id_` modifier to get the unmodified archived bytes.",
        authoritative_for=["original state (when the snapshot predates the change)"],
    ),
}

UNVERIFIED_SOURCES: Dict[str, str] = {
    # Documented, deliberately not implemented because unverified. Do not cite.
    "situation-room-web": "No official machine-readable Situation Room feed was located. "
                          "Promises of review outcomes must come from the official documents/API.",
    "nhl-stats-sabremetrics": "Third-party; never cite as evidence.",
    "media-reports": "Secondary. May be used ONLY in the `reason`/`notes` field of a record whose "
                     "states both come from official sources, or to flag a candidate that still "
                     "requires official verification.",
}


def gamecenter_url(endpoint: str, game_id: int) -> str:
    """Return a verified GameCenter URL for a game."""
    return f"{API_WEB}/v1/gamecenter/{int(game_id)}/{endpoint}"


def report_url(season: int, kind: str, game_type: int, game_no: int) -> str:
    """Return the official HTML report URL.

    ``season`` is the season *folder* (e.g. 20232024), ``game_type`` is the leading
    digit pair of the game id (1 pre-season, 2 regular season, 3 playoffs) and
    ``game_no`` the 4-digit game number.
    """
    kind = kind.upper()
    if kind not in REPORT_KINDS:
        raise ValueError(f"unknown report kind {kind!r}; known: {sorted(REPORT_KINDS)}")
    return f"{HTML_REPORTS}/{season}/{kind}{int(game_type):02d}{int(game_no):04d}.HTM"


def split_game_id(game_id: int) -> Dict[str, int]:
    """Split a modern NHL game id into season / game_type / game_no."""
    s = str(int(game_id))
    if len(s) != 10:
        raise ValueError(f"unexpected game id {game_id!r}")
    return {"season_start": int(s[:4]), "game_type": int(s[4:6]), "game_no": int(s[6:])}


def season_folder(game_id: int) -> str:
    """Season folder used by the report host, e.g. 2023020001 -> '20232024'."""
    parts = split_game_id(game_id)
    start = parts["season_start"]
    return f"{start}{start + 1}"


def cdx_query(original_url: str, *, limit: int = 50, collapse: Optional[str] = "digest",
              fields: str = "timestamp,original,statuscode,mimetype,digest,length") -> str:
    """Build an exact-URL CDX query (one document, all snapshots)."""
    from urllib.parse import quote

    q = f"?url={quote(original_url, safe='')}&output=json&fl={fields}&limit={int(limit)}"
    if collapse:
        q += f"&collapse={collapse}"
    return WAYBACK_CDX + q


def cdx_prefix_query(url_prefix: str, *, limit: int = 100, collapse: Optional[str] = "digest",
                     fields: str = "original,digest,timestamp,statuscode") -> str:
    from urllib.parse import quote

    q = (f"?url={quote(url_prefix, safe='')}&matchType=prefix&output=json&fl={fields}"
         f"&limit={int(limit)}")
    if collapse:
        q += f"&collapse={collapse}"
    return WAYBACK_CDX + q


def snapshot_url(timestamp: str, original_url: str) -> str:
    """Raw (unmodified) archived bytes of an official document."""
    return f"{WAYBACK_RAW}/{timestamp}id_/{original_url}"


def registry_as_dict() -> dict:
    return {
        "generated_for_date": date.today().isoformat(),
        "sources": {k: v.as_dict() for k, v in SOURCES.items()},
        "unverified_and_deliberately_not_used": UNVERIFIED_SOURCES,
    }
