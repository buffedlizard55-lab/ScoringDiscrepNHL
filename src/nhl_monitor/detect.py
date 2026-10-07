"""The detection engine: collect official state, compare, classify, emit records.

Nothing in here invents a fact. When a piece of the story is not present in an
official artifact, the corresponding field stays null and a flag is raised, so the
database can say "we do not know yet" instead of guessing.
"""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Tuple

from . import classify, sources, store
from .parse import parse_api_boxscore, parse_api_pbp, parse_gs_report, report_era
from .state import Change, GameState, diff_states

# ----------------------------------------------------------------------------- #
# Official change notes inside official documents
# ----------------------------------------------------------------------------- #

_NOTE_PATTERNS = (
    re.compile(r"[^.\n]{0,160}scoring change[^.\n]{0,200}", re.I),
    re.compile(r"[^.\n]{0,160}goal (?:was )?changed[^.\n]{0,200}", re.I),
    re.compile(r"[^.\n]{0,160}credited?[^.\n]{0,200}review[^.\n]{0,120}", re.I),
    re.compile(r"[^.\n]{0,160}review[^.\n]{0,160}credit[^.\n]{0,120}", re.I),
)


def extract_official_change_notes(html: str) -> List[str]:
    """Verbatim quotes from an official document that describe a change.

    If an official report states the change in words, that quote becomes the
    ``reason.text`` for the record with the document itself as the source. If no
    such text exists, the record is flagged instead of given an invented reason.
    """
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;?", " ", text)
    text = re.sub(r"\s+", " ", text)
    found: List[str] = []
    for pat in _NOTE_PATTERNS:
        for m in pat.finditer(text):
            snippet = m.group(0).strip()
            if snippet and snippet not in found:
                found.append(snippet)
    return found[:5]


# ----------------------------------------------------------------------------- #
# Fetch helpers
# ----------------------------------------------------------------------------- #

def fetch_pbp(game_id: int, *, cache_dir: Optional[str] = None) -> Tuple[GameState, dict]:
    url = sources.gamecenter_url("play-by-play", game_id)
    from .fetch import get_json

    payload, resp = get_json(url, cache_dir=cache_dir)
    state = parse_api_pbp(payload, url=url, retrieved_at=resp.retrieved_at)
    return state, resp.as_evidence()


def fetch_boxscore(game_id: int, *, cache_dir: Optional[str] = None) -> Tuple[GameState, dict]:
    url = sources.gamecenter_url("boxscore", game_id)
    from .fetch import get_json

    payload, resp = get_json(url, cache_dir=cache_dir)
    state = parse_api_boxscore(payload, url=url, retrieved_at=resp.retrieved_at)
    return state, resp.as_evidence()


def fetch_gs(game_id: int, *, cache_dir: Optional[str] = None) -> Tuple[GameState, dict]:
    parts = sources.split_game_id(game_id)
    url = sources.report_url(sources.season_folder(game_id), "GS", parts["game_type"], parts["game_no"])
    from .fetch import get_text

    html, resp = get_text(url, cache_dir=cache_dir, expect_status=(200, 404))
    if resp.status != 200:
        raise FileNotFoundError(f"official Game Summary unavailable ({resp.status}) at {url}")
    state = parse_gs_report(html, url=url, retrieved_at=resp.retrieved_at, game_id=game_id,
                            season=sources.season_folder(game_id))
    official_notes = extract_official_change_notes(html)
    if official_notes:
        state.evidence["official_change_notes"] = official_notes
    evidence = resp.as_evidence()
    evidence["official_change_notes"] = official_notes
    return state, evidence


# ----------------------------------------------------------------------------- #
# Record construction
# ----------------------------------------------------------------------------- #

def _player_blob(p) -> Optional[dict]:
    if p is None:
        return None
    return {"id": p.id, "name": p.name, "sweater": p.sweater}


def _side_blob(goal_dict: Optional[dict]) -> Optional[dict]:
    if not goal_dict:
        return None
    return {
        "ruling": "goal",
        "team": goal_dict.get("team"),
        "scorer": goal_dict.get("scorer"),
        "assists": goal_dict.get("assists", []),
        "strength": goal_dict.get("strength"),
        "own_goal": goal_dict.get("is_own_goal"),
    }


def record_id_for(game_id: int, seq: int = 1) -> str:
    season = sources.season_folder(game_id)
    parts = sources.split_game_id(game_id)
    return f"NHL-{season}-{parts['game_type']:02d}{parts['game_no']:04d}-{seq:02d}"


def build_records(before: Optional[GameState], after: GameState,
                  evidence: Dict[str, dict], *, detected_at: Optional[str] = None,
                  detection_mode: str = "auto_poll") -> List[dict]:
    """Turn a state transition into zero or more discrepancy records."""
    detected_at = detected_at or store.utcnow()
    if before is None:
        return []
    changes = diff_states(before, after)
    if not changes:
        return []

    classification = classify.classify(changes)
    timing_when, timing_why = classify.infer_timing(before, after)
    settlement = classify.settlement_assessment(classification, timing_when)

    # group changes per goal in time order, one record per goal touched
    by_goal: Dict[Tuple, List[Change]] = {}
    for ch in changes:
        key = (ch.period_type if hasattr(ch, "period_type") else "", ch.period, ch.clock, ch.team)
        by_goal.setdefault(key, []).append(ch)

    records: List[dict] = []
    for seq, (key, group) in enumerate(sorted(by_goal.items(), key=lambda kv: str(kv[0])), start=1):
        first = group[0]
        group_class = classify.classify(group)
        g_timing, g_why = classify.infer_timing(before, after)
        g_settlement = classify.settlement_assessment(group_class, g_timing)
        notes = (after.evidence.get("official_change_notes")
                 or before.evidence.get("official_change_notes") or [])
        reason_text = notes[0] if notes else None
        flags: List[str] = []
        if not reason_text:
            flags.append("reason_not_stated_in_official_source")
        if classification.get("needs_manual_review"):
            flags.append("non_scoring_metadata_changed_requires_manual_review")
        if timing_when == "unknown":
            flags.append("timing_not_derivable_from_feed")
        if after.parse_warnings or before.parse_warnings:
            flags.append("parser_warnings_present")

        record = {
            "record_id": record_id_for(after.game_id, seq),
            "status": "auto_detected",
            "game": {
                "game_id": after.game_id,
                "season": after.season or sources.season_folder(after.game_id),
                "date": after.game_date or before.game_date,
                "away": {"abbrev": (after.away.abbrev if after.away else ""),
                         "score": after.away.score if after.away else None},
                "home": {"abbrev": (after.home.abbrev if after.home else ""),
                         "score": after.home.score if after.home else None},
                "final_score": _final_score(after),
            },
            "event": {
                "period": first.period,
                "period_type": _period_type_of(group),
                "clock": first.clock,
                "strength": (first.after or first.before or {}).get("strength"),
                "team": first.team,
            },
            "initial_state": _blob_for(group, "before"),
            "corrected_state": _blob_for(group, "after"),
            "change": {
                "discrepancy_type": group_class["discrepancy_type"],
                "affects_goal_total": group_class["affects_goal_total"],
                "attribution_only": group_class["attribution_only"],
                "counts": group_class["counts"],
                "detail": "; ".join(c.detail for c in group),
                "all_changes": [c.as_dict() for c in changes],
            },
            "reason": {
                "category": "official_source_statement" if reason_text else "unknown",
                "text": reason_text,
                "note": None if reason_text else
                        "No official statement of the reason was found in the retrieved artifacts. "
                        "This field must not be filled by inference.",
            },
            "timing": {
                "when": g_timing,
                "reasoning": g_why,
                "previous_state_captured_at_utc": before.retrieved_at,
                "new_state_captured_at_utc": after.retrieved_at,
            },
            "sources": _sources_for(group, evidence),
            "evidence_status": _evidence_status(group, evidence, before, after),
            "settlement": g_settlement,
            "detection": {
                "detected_by": detection_mode,
                "detected_at_utc": detected_at,
                "state_before_fingerprint": before.fingerprint(),
                "state_after_fingerprint": after.fingerprint(),
                "source_keys_compared": [before.source_key, after.source_key],
                "confidence": _confidence(group),
            },
            "flags": flags,
            "notes": "",
        }
        record["completeness"] = store.completeness(record)
        records.append(record)
    return records


def _period_type_of(group: List[Change]) -> str:
    for ch in group:
        for blob in (ch.before, ch.after):
            if blob and blob.get("period_type"):
                return blob["period_type"]
    return "REG"


def _final_score(state: GameState) -> str:
    if state.away and state.home and state.away.score is not None and state.home.score is not None:
        return f"{state.away.score}-{state.home.score}"
    return ""


def _blob_for(group: List[Change], side: str) -> dict:
    for ch in group:
        blob = ch.before if side == "before" else ch.after
        if blob:
            out = _side_blob(blob) or {}
            if side == "before" and ch.change_type == "goal_added":
                out = {"ruling": "no_goal", "team": ch.team, "scorer": None, "assists": []}
            if side == "after" and ch.change_type == "goal_removed":
                out = {"ruling": "no_goal", "team": ch.team, "scorer": None, "assists": []}
            return out
    # pure addition / removal handled above; fallback keeps the structure valid
    return {"ruling": "unknown", "team": group[0].team if group else None}


def _sources_for(group: List[Change], evidence: Dict[str, dict]) -> List[dict]:
    out: List[dict] = []
    for ch in group:
        for side, state_key in (("initial_state", ch.before), ("corrected_state", ch.after)):
            if not state_key:
                continue
            src = evidence.get("pbp") if "pbp" in evidence else None
            if src and not any(s["url"] == src["url"] and s["role"] == side for s in out):
                out.append({"role": side, "type": "official-api", "name": "NHL GameCenter play-by-play",
                            **src})
        break
    for key, ev in (evidence or {}).items():
        if key in {"pbp", "boxscore", "gs"} and ev and ev.get("url"):
            role = {"pbp": "corrected_state", "boxscore": "cross_check", "gs": "cross_check"}.get(key, "cross_check")
            if not any(s["url"] == ev["url"] for s in out):
                out.append({"role": role, "type": "official-api" if key != "gs" else "official-document",
                            "name": {"pbp": "NHL GameCenter play-by-play",
                                     "boxscore": "NHL GameCenter boxscore",
                                     "gs": "Official Game Summary (HTML)"}[key], **ev})
    return out


def _evidence_status(group: List[Change], evidence: Dict[str, dict],
                     before: GameState, after: GameState) -> str:
    same_source = before.source_key == after.source_key
    has_two_states = bool(before.retrieved_at and after.retrieved_at)
    if same_source and has_two_states and evidence.get("pbp"):
        return "verified_two_official_states"
    if has_two_states:
        return "verified_corrected_state"
    return "incomplete"


def _confidence(group: List[Change]) -> str:
    kinds = {c.change_type for c in group}
    if kinds <= {"scorer_change", "assist_change", "goal_removed", "goal_added"}:
        return "high"
    return "medium"


# ----------------------------------------------------------------------------- #
# One full collection cycle for a game
# ----------------------------------------------------------------------------- #

def collect_game(game_id: int, *, cache_dir: Optional[str] = None, dry_run: bool = False
                 ) -> Dict[str, object]:
    """Capture the official state of one game and compare it with the stored state.

    Returns a summary dict: {game_id, captured, changes, records, findings, errors}.
    """
    result: Dict[str, object] = {"game_id": game_id, "captured": [], "records": [],
                                 "findings": [], "errors": []}
    evidence: Dict[str, dict] = {}
    pbp_state = None
    box_state = None
    try:
        pbp_state, ev = fetch_pbp(game_id, cache_dir=cache_dir)
        evidence["pbp"] = ev
        result["captured"].append(pbp_state.as_dict())
    except Exception as exc:
        result["errors"].append({"source": "pbp", "error": f"{type(exc).__name__}: {exc}"})
    try:
        box_state, ev = fetch_boxscore(game_id, cache_dir=cache_dir)
        evidence["boxscore"] = ev
    except Exception as exc:
        result["errors"].append({"source": "boxscore", "error": f"{type(exc).__name__}: {exc}"})
    try:
        gs_state, ev = fetch_gs(game_id, cache_dir=cache_dir)
        evidence["gs"] = ev
    except Exception as exc:
        result["errors"].append({"source": "gs", "error": f"{type(exc).__name__}: {exc}"})

    if pbp_state is None:
        return result

    if box_state is not None:
        result["findings"] = (classify.crosscheck_player_totals(pbp_state, box_state)
                              + classify.team_total_crosscheck(pbp_state, box_state))

    previous = store.load_game_state(game_id)
    before = GameState.from_dict(previous) if previous else None
    records = build_records(before, pbp_state, evidence)

    if not dry_run:
        store.save_game_state(pbp_state.as_dict())
        store.append_evidence(game_id, {
            "retrieved_at": pbp_state.retrieved_at,
            "fingerprint": pbp_state.fingerprint(),
            "game_state": pbp_state.game_state,
            "period": pbp_state.period,
            "in_intermission": pbp_state.in_intermission,
            "away_score": pbp_state.away.score if pbp_state.away else None,
            "home_score": pbp_state.home.score if pbp_state.home else None,
            "goals": [g.as_dict() for g in pbp_state.sorted_goals()],
            "evidence": evidence,
        })
        for rec in records:
            store.upsert_record(rec)
    result["records"] = records
    result["previous_state_captured_at"] = before.retrieved_at if before else None
    return result
