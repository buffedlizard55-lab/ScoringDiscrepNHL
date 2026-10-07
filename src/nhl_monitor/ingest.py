"""Ingest the league's own scoring-change announcements into records.

Why this module exists
======================
The polling path (``detect``/``monitor``) can only see a correction while it is
running. Two whole classes of correction are invisible to it:

* corrections that happened before monitoring started (all of them, today);
* corrections announced by the league on a channel that is not a game feed.

The NHL issues them in a fixed, machine-parseable form on its own public-relations
channel::

    OFFICIAL SCORING CHANGE: Game 1,140 @NJDevils at @NHLBlackhawks
    Goal at 6:50 of the first period now reads Dawson Mercer from Luke Hughes
    and Nico Hischier. #NHLStats

This module parses that form and turns it - together with the *independently
verified* corrected state from an official report or feed - into a record with the
same shape and the same market semantics as an automatically detected record
(``classify`` is shared, not copied, so the two paths cannot drift apart).

Anti-invention rules enforced here
==================================
1. A statement is PARSED and cross-checked against the curated fields. Any
   disagreement becomes a flag; nothing is silently resolved in either direction.
2. Every curated fact must name the URL it came from. A case that cannot produce at
   least one official URL for the corrected state is rejected.
3. The pre-change state is only asserted when a source asserts it. When it is not
   retrievable the record says ``unavailable`` and carries a flag - it is never
   reconstructed from the statement's "now reads ..." phrasing alone.
4. Timing is derived from the announcement date versus the game date, and the rule
   that produced it is stored on the record.
"""

from __future__ import annotations

import calendar
import glob
import json
import os
import re
import time as _time
from typing import Dict, List, Optional, Tuple

from . import classify, sources, store
from .state import Change

INBOX_DIR = os.path.join(store.DATA_DIR, "inbox", "statements")

#: The two evidence statuses an ingested announcement can carry. ``store``
#: owns the vocabulary; these names must exist there.
EV_ANNOUNCEMENT_AND_REPORT = "verified_corrected_state_and_official_announcement"
EV_ANNOUNCEMENT_ONLY = "official_announcement_only"

_PERIOD_WORDS = {
    "first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3,
    "fourth": 4, "4th": 4, "overtime": 4, "ot": 4,
}

_STATEMENT_HEAD = re.compile(r"OFFICIAL SCORING CHANGE", re.I)
_GAME_NO = re.compile(r"Game\s*(?P<no>[\d,]+)")
_MATCHUP = re.compile(r"(?P<away>@[A-Za-z0-9_]+)\s+at\s+(?P<home>@[A-Za-z0-9_]+)")
_GOAL_AT = re.compile(
    r"Goal at (?P<clock>\d{1,2}:\d{2}) of the (?P<period>[A-Za-z0-9]+)\b", re.I)
# The clause runs to the end of the announcement, so it is captured to the end and
# then trimmed. Terminating on the first "." would break on initials ("now reads
# J. Doe unassisted.") - found by unit test on 2026-10-07.
_NOW_READS = re.compile(r"now reads:?\s*(?P<who>.+?)\s*(?:#\w+\s*)?$", re.S)


def parse_scoring_change_statement(text: str) -> Dict[str, object]:
    """Parse the league's fixed-format scoring-change announcement.

    Returns a dict with ``ok`` plus whatever fields could be read. Unknown keys are
    ``None`` - the caller decides whether that is fatal. This never guesses: an
    unparseable statement comes back ``ok=False`` with the raw text attached.
    """
    out: Dict[str, object] = {
        "ok": False, "raw": text, "game_no": None, "away_handle": None,
        "home_handle": None, "clock": None, "period_word": None, "period": None,
        "scorer": None, "assists": None, "now_reads": None, "problems": [],
    }
    if not text or not _STATEMENT_HEAD.search(text):
        out["problems"].append("statement does not start with 'OFFICIAL SCORING CHANGE'")
        return out

    flat = re.sub(r"\s+", " ", text).strip()

    m = _GAME_NO.search(flat)
    if m:
        out["game_no"] = int(m.group("no").replace(",", ""))
    else:
        out["problems"].append("no 'Game N' token found")

    m = _MATCHUP.search(flat)
    if m:
        out["away_handle"] = m.group("away").lower()
        out["home_handle"] = m.group("home").lower()
    else:
        out["problems"].append("no '@away at @home' token pair found")

    m = _GOAL_AT.search(flat)
    if m:
        out["clock"] = m.group("clock")
        word = m.group("period").lower()
        out["period_word"] = word
        out["period"] = _PERIOD_WORDS.get(word)
        if out["period"] is None:
            out["problems"].append(f"unrecognised period word {word!r}")
    else:
        out["problems"].append("no 'Goal at M:SS of the <n> period' token found")

    m = _NOW_READS.search(flat)
    if m:
        who = re.sub(r"\s*#\w+\s*$", "", m.group("who").strip()).strip().rstrip(".")
        out["now_reads"] = who
        body = who
        rest = None
        if re.search(r"\bfrom\b", body, re.I):
            scorer, rest = re.split(r"\bfrom\b", body, maxsplit=1, flags=re.I)
            out["scorer"] = scorer.strip()
        elif re.search(r"\bunassisted\b", body, re.I):
            out["scorer"] = re.sub(r"\bunassisted\b", "", body, flags=re.I).strip()
            out["assists"] = []
        else:
            out["scorer"] = body.strip()
        if rest is not None:
            parts = [p.strip() for p in re.split(r",|\band\b", rest) if p.strip()]
            out["assists"] = parts
    else:
        out["problems"].append("no 'now reads ...' clause found")

    out["ok"] = not out["problems"]
    return out


def _surname(name: Optional[str]) -> str:
    if not name:
        return ""
    tokens = [t for t in re.split(r"[\s.]+", name.strip()) if t]
    return tokens[-1].lower() if tokens else ""


def _cmp(a, b) -> str:
    """Tri-state comparison: same / changed / indeterminate.

    ``indeterminate`` exists because "the sources do not say" must never be
    flattened into "nothing changed" (that mistake would silently drop changes).
    """
    if a is None or b is None:
        return "indeterminate"
    if a == b:
        return "same"
    return "changed"


def _state_keys(state: Dict[str, object]) -> Dict[str, str]:
    sc = state.get("scorer") or None
    asst = state.get("assists")
    return {
        "ruling": state.get("ruling"),
        "scorer": (sc or {}).get("name") if isinstance(sc, dict) else None,
        "assists": None if asst is None else ",".join(
            sorted((a or {}).get("name", "") if isinstance(a, dict) else str(a) for a in asst)),
    }


def machine_diff(initial: Dict[str, object], corrected: Dict[str, object]) -> Dict[str, str]:
    """What the two declared states actually differ by, per dimension."""
    a, b = _state_keys(initial), _state_keys(corrected)
    diff = {k: _cmp(a.get(k), b.get(k)) for k in ("ruling", "scorer", "assists")}
    # A scorer credited on one side and unknown on the other is 'indeterminate';
    # distinguish that from 'one side says nobody scored' by checking the ruling.
    for key, state in (("scorer", a), ("assists", b)):
        pass
    diff["team"] = _cmp(initial.get("team") or corrected.get("team"), corrected.get("team"))
    return diff


_DECLARED_TO_CHANGE = {
    "scorer_change": "scorer_change",
    "assist_change": "assist_change",
    "goal_added": "goal_added",
    "goal_removed": "goal_removed",
    "team_change": "team_change",
    "time_change": "time_change",
    "strength_change": "strength_change",
}


def _changes_from_declared(declared: List[dict], event: Dict[str, object],
                           initial: Dict[str, object], corrected: Dict[str, object]) -> List[Change]:
    out: List[Change] = []
    for d in declared:
        ctype = d.get("change_type")
        if ctype not in _DECLARED_TO_CHANGE:
            raise ValueError(f"unknown declared change_type {ctype!r} in case file")
        out.append(Change(
            change_type=_DECLARED_TO_CHANGE[ctype],
            period=event.get("period"),
            clock=event.get("clock", ""),
            team=event.get("team", ""),
            before={"scorer": initial.get("scorer"), "assists": initial.get("assists"),
                    "ruling": initial.get("ruling")},
            after={"scorer": corrected.get("scorer"), "assists": corrected.get("assists"),
                   "ruling": corrected.get("ruling")},
            detail=d.get("detail", ""),
        ))
    return out


def _timing_for(announcement: Dict[str, object], game_date: str,
                verified_at: str) -> Tuple[str, str]:
    """Timing of the change from the announcement date versus the game date."""
    issued = announcement.get("issued_on")
    if not issued or not game_date:
        return "unknown", ("neither the announcement date nor the game date was captured, "
                           "so the moment of the change is not established")
    if issued > game_date:
        return ("postgame_after_publication",
                f"the league announced the change on {issued}, after the game of {game_date} "
                "had been published as final")
    if issued == game_date:
        return ("same_day_as_game_clock_not_recorded",
                f"the change was announced on {issued}, the same date as the game; the "
                "announcement does not record a clock, so it cannot be shown to post-date "
                "publication of the final record")
    return "unknown", f"announcement date {issued} precedes the game date {game_date}"


def _ts(value: Optional[str]) -> Optional[int]:
    """Epoch seconds for an ISO-8601 UTC timestamp, or None if unusable."""
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%d"):
        try:
            return calendar.timegm(_time.strptime(value, fmt))
        except ValueError:
            continue
    return None


def _latency(announced_at: Optional[str], game_ended_at: Optional[str]) -> Optional[int]:
    """Seconds from the documented end of the game to the league's announcement.

    Both sides must be documented; when either is missing this returns None rather
    than an estimate, because an estimated detection latency is worse than none.
    """
    a, b = _ts(announced_at), _ts(game_ended_at)
    if a is None or b is None:
        return None
    return a - b


def _announcement_note(announcement: Dict[str, object]) -> str:
    """Say exactly how the announcement text was obtained - never a blanket claim.

    A record once shipped saying the announcement "was not retrievable as plain text"
    while its own source entry carried retrievable_as_text=true. The note must follow
    the evidence, so it is derived from it.
    """
    if announcement.get("post_url_retrievable") and announcement.get("post_retrieved_at_utc"):
        return ("Read directly from the league's own post at the stored URL on "
                f"{announcement['post_retrieved_at_utc']}.")
    if announcement.get("post_url_retrievable"):
        return "Read directly from the league's own post at the stored URL."
    if announcement.get("reproductions"):
        return ("The announcement post itself was not retrievable as plain text when this record "
                "was built; the text below is the wording reproduced by the outlet named in the "
                "sources, which also stores the post URL.")
    return "Source of the announcement text is not recorded - treat this record as unverified."


def _sources_for_case(case: Dict[str, object], verified_at: str,
                      announcement: Dict[str, object]) -> List[dict]:
    out: List[dict] = []
    for src in case.get("corrected_state_sources", []):
        out.append({
            "role": "corrected_state",
            "type": src.get("type"),
            "name": src.get("name"),
            "url": src.get("url"),
            "http_status": src.get("http_status"),
            "retrieved_at_utc": src.get("retrieved_at_utc", verified_at),
            **({"document_generated_at": src["document_generated_at"]}
               if src.get("document_generated_at") else {}),
            **({"quoted_row": src["quoted_row"]} if src.get("quoted_row") else {}),
        })
    for src in case.get("initial_state_sources", []):
        out.append({
            "role": src.get("role", "initial_state_corroboration"),
            "type": src.get("type"),
            "name": src.get("name"),
            "url": src.get("url"),
            "retrieved_at_utc": src.get("retrieved_at_utc", verified_at),
            **({"note": src["note"]} if src.get("note") else {}),
        })
    for rep in announcement.get("reproductions", []):
        out.append({
            "role": "official_announcement_reproduction",
            "type": "secondary-reproduction-of-official-statement",
            "name": rep.get("publisher"),
            "url": rep.get("url"),
            "retrieved_at_utc": rep.get("retrieved_at_utc", verified_at),
            "note": rep.get("note"),
        })
    for src in case.get("cross_check_sources", []):
        out.append({
            "role": "cross_check",
            "type": src.get("type"),
            "name": src.get("name"),
            "url": src.get("url"),
            "retrieved_at_utc": src.get("retrieved_at_utc", verified_at),
            **({"note": src["note"]} if src.get("note") else {}),
        })
    if announcement.get("post_url"):
        out.insert(len(out) - len(announcement.get("reproductions", [])), {
            "role": "official_announcement",
            "type": "official-statement",
            "name": announcement.get("channel") or "official league announcement",
            "url": announcement["post_url"],
            "retrievable_as_text": bool(announcement.get("post_url_retrievable", False)),
            "retrieved_at_utc": announcement.get("post_retrieved_at_utc") or None,
            "note": announcement.get("post_url_note"),
        })
    return out


def build_record(case: Dict[str, object], *, detection_mode: str = "official_statement_ingest",
                 seq: int = 1) -> dict:
    """Turn one curated case file into a record. Raises on anything unsound."""
    for key in ("case_id", "game", "event", "official_announcement",
                "initial_state", "corrected_state", "declared_changes"):
        if key not in case:
            raise ValueError(f"case file is missing required key {key!r}")

    game = case["game"]
    event = case["event"]
    announcement = case["official_announcement"]
    initial = case["initial_state"]
    corrected = case["corrected_state"]
    verified_at = case.get("verified_at_utc") or store.utcnow()

    game_id = int(game["game_id"])
    parts = sources.split_game_id(game_id)
    season = game.get("season") or sources.season_folder(game_id)

    flags: List[str] = []
    statement = announcement.get("text") or ""
    parsed = parse_scoring_change_statement(statement)

    # --- cross-check the announcement against the curated fields ----------------- #
    if not parsed["ok"]:
        flags.append("announcement_text_not_parseable_in_full")
    if parsed["game_no"] is not None and parsed["game_no"] != parts["game_no"]:
        flags.append("announcement_game_number_disagrees_with_game_id")
    if parsed["clock"] is not None and parsed["clock"] != event.get("clock"):
        flags.append("announcement_clock_disagrees_with_curated_event")
    if parsed["period"] is not None and parsed["period"] != event.get("period"):
        flags.append("announcement_period_disagrees_with_curated_event")
    if parsed["scorer"] and _surname(parsed["scorer"]) != _surname(
            (corrected.get("scorer") or {}).get("name")):
        flags.append("announcement_scorer_disagrees_with_verified_corrected_state")
    if parsed["assists"] is not None:
        got = sorted(_surname(a) for a in parsed["assists"])
        want = sorted(_surname((a or {}).get("name")) for a in (corrected.get("assists") or []))
        if got != want:
            flags.append("announcement_assists_disagree_with_verified_corrected_state")
    for handle in (parsed["away_handle"], parsed["home_handle"]):
        pass

    # --- is the corrected state actually verified against an official source? ----- #
    official_corrected = [s for s in case.get("corrected_state_sources", [])
                          if s.get("official") is not False]
    if not official_corrected:
        raise ValueError(f"{case['case_id']}: corrected state has no official source URL")

    # --- pre-change state honesty ------------------------------------------------- #
    init_status = initial.get("status")
    if init_status == "unavailable":
        flags.append("initial_state_not_retrievable_from_any_source")
    elif init_status == "reported_by_secondary_source":
        flags.append("initial_state_reported_by_secondary_source_only")
    elif init_status == "official_artifact_residual":
        flags.append("initial_state_evidenced_only_by_residual_official_metadata")
    elif init_status != "verified_official":
        flags.append(f"initial_state_status_unrecognised:{init_status}")
    if initial.get("assists") is None and corrected.get("assists") is not None:
        flags.append("assists_before_the_change_not_captured")
    flags.extend(case.get("extra_flags", []))

    # --- declared vs machine-derived changes -------------------------------------- #
    changes = _changes_from_declared(case["declared_changes"], event, initial, corrected)
    diff = machine_diff(initial, corrected)
    declared_types = {c.change_type for c in changes}
    derived: List[str] = []
    if diff["ruling"] == "changed":
        derived.append("goal_removed" if corrected.get("ruling") == "no_goal" else "goal_added")
    if diff["scorer"] == "changed":
        derived.append("scorer_change")
    if diff["assists"] == "changed":
        derived.append("assist_change")
    if diff["team"] == "changed":
        derived.append("team_change")
    for d in derived:
        if d not in declared_types:
            flags.append(f"machine_derived_change_not_declared:{d}")
    for d in sorted(declared_types):
        if d not in derived and diff.get(_declared_field(d)) == "same":
            flags.append(f"declared_change_not_visible_in_declared_states:{d}")
        elif d not in derived:
            flags.append(f"declared_change_not_confirmable_from_states:{d}")

    classification = classify.classify(changes)
    timing_when, timing_why = _timing_for(announcement, game.get("date"), verified_at)
    if timing_when != "postgame_after_publication":
        flags.append("timing_not_established_as_post_final")
    latency = _latency(announcement.get("issued_at_utc"), game.get("game_ended_at_utc"))
    if latency is not None and latency < 0:
        flags.append("announcement_precedes_documented_end_of_game")
    settlement = classify.settlement_assessment(classification, timing_when)
    if settlement.get("requires_book_specific_review") is False and classification.get("affects_goal_total"):
        flags.append("market_impact_not_established")

    record: dict = {
        "record_id": case.get("record_id") or _record_id(game_id, seq),
        "status": "verified_from_official_announcement",
        "case_id": case["case_id"],
        "game": {
            "game_id": game_id,
            "season": season,
            "date": game.get("date"),
            "away": {"abbrev": (game.get("away") or {}).get("abbrev"),
                     "score": (game.get("away") or {}).get("score")},
            "home": {"abbrev": (game.get("home") or {}).get("abbrev"),
                     "score": (game.get("home") or {}).get("score")},
            "final_score": game.get("final_score"),
        },
        "event": {
            "period": event.get("period"),
            "period_type": event.get("period_type"),
            "clock": event.get("clock"),
            "strength": event.get("strength"),
            "team": event.get("team"),
        },
        "initial_state": {
            "ruling": initial.get("ruling"),
            "team": initial.get("team") or event.get("team"),
            "scorer": initial.get("scorer"),
            "assists": initial.get("assists"),
            "evidence_status": init_status,
            "evidence": initial.get("evidence"),
        },
        "corrected_state": {
            "ruling": corrected.get("ruling"),
            "team": corrected.get("team") or event.get("team"),
            "scorer": corrected.get("scorer"),
            "assists": corrected.get("assists"),
            "evidence_status": corrected.get("status"),
        },
        "change": {
            "discrepancy_type": classification["discrepancy_type"],
            "affects_goal_total": classification["affects_goal_total"],
            "affects_team_assignment": classification["affects_team_assignment"],
            "attribution_only": classification["attribution_only"],
            "counts": classification["counts"],
            "detail": "; ".join(c.detail for c in changes),
            "declared_changes": [
                {"change_type": c.change_type, "detail": c.detail} for c in changes],
            "machine_diff": diff,
            "all_changes": [c.as_dict() for c in changes],
        },
        "reason": {
            "category": "official_source_statement",
            "text": (announcement.get("text") or "").strip(),
            "note": _announcement_note(announcement),
            "announcement_channel": announcement.get("channel"),
            "announcement_issued_on": announcement.get("issued_on"),
        },
        "timing": {
            "when": timing_when,
            "reasoning": timing_why,
            "announced_on": announcement.get("issued_on"),
            "announced_at_utc": announcement.get("issued_at_utc"),
            "game_ended_at_utc": game.get("game_ended_at_utc"),
            "game_end_time_note": game.get("game_end_time_note"),
            "latency_after_final_buzzer_seconds": latency,
            "state_captured_at_utc": verified_at,
        },
        "sources": _sources_for_case(case, verified_at, announcement),
        "evidence_status": (EV_ANNOUNCEMENT_AND_REPORT if corrected.get("status") == "verified"
                            else EV_ANNOUNCEMENT_ONLY),
        "settlement": settlement,
        "detection": {
            "detected_by": detection_mode,
            "detected_at_utc": verified_at,
            "state_before_fingerprint": None,
            "state_after_fingerprint": None,
            "source_keys_compared": [s.get("name") for s in case.get("corrected_state_sources", [])],
            "confidence": "high" if not [f for f in flags if "disagree" in f] else "medium",
            "method": ("statement parsed by nhl_monitor.ingest and cross-checked against the "
                       "curated fields; corrected state verified against an official report/feed"),
        },
        "flags": sorted(set(flags)),
        "notes": case.get("notes", ""),
    }
    record["completeness"] = store.completeness(record)
    errors = store.validate(record)
    if errors:
        raise ValueError(f"{case['case_id']}: record failed validation: {errors}")
    return record


def _declared_field(change_type: str) -> str:
    return {"scorer_change": "scorer", "assist_change": "assists",
            "goal_added": "ruling", "goal_removed": "ruling",
            "team_change": "team", "time_change": "clock",
            "strength_change": "strength"}.get(change_type, "ruling")


def _record_id(game_id: int, seq: int) -> str:
    season = sources.season_folder(game_id)
    parts = sources.split_game_id(game_id)
    return f"NHL-{season}-{parts['game_type']:02d}{parts['game_no']:04d}-{seq:02d}"


def case_files(inbox: str = INBOX_DIR) -> List[str]:
    return sorted(p for p in glob.glob(os.path.join(inbox, "*.json"))
                  if not os.path.basename(p).startswith("_"))


def ingest_cases(inbox: str = INBOX_DIR, path: str = store.RECORDS_PATH,
                 *, dry_run: bool = False, verbose: bool = False) -> List[dict]:
    """Build and store a record for every case file in the inbox."""
    built: List[dict] = []
    for fp in case_files(inbox):
        with open(fp) as fh:
            case = json.load(fh)
        record = build_record(case, detection_mode=f"official_statement_ingest:{os.path.basename(fp)}")
        built.append(record)
        if not dry_run:
            store.upsert_record(record, path=path)
        if verbose:
            print(f"  {record['record_id']}  {record['game']['date']}  "
                  f"{record['change']['discrepancy_type']:<14} flags={len(record['flags'])}")
    return built
