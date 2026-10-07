"""Turn proven archive changes into original-vs-corrected records.

The archive layer can prove *that* an official document was rewritten, and bracket
*when*. It cannot say what was rewritten. This module closes that gap: it downloads
the two bracketing captures, parses both with the same Game Summary parser the live
monitor uses, and hands the pair to the same record builder the live monitor uses.

One parser, one classifier, one record builder for both detection paths - so the two
paths cannot drift apart and a record produced from two archived official captures is
directly comparable with a record produced by polling the live endpoint.

Honesty rules enforced here (see docs/BACKFILL.md and docs/LIMITATIONS.md):

* Capture order does NOT decide which state is the original. A document regenerated
  for an unrelated reason can change twice; the pair is only turned into a record when
  the *content comparison* shows a scoring change.
* A pair whose only difference is the document footer (regeneration) produces a
  finding, never a record.
* The correction time is recorded as the capture bracket, and the timing is labelled
  ``postgame`` with ``heuristic`` confidence, because a Game Summary cannot be edited
  before it exists - but the archive cannot show the edit itself.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from . import archive, detect, sources, store
from .parse import parse_gs_report

#: Report kinds whose content carries the scoring record and can be compared row by row.
COMPARABLE_KINDS = ("GS",)


def _parse_capture(snapshot: archive.Snapshot, *, canonical_url: str, game_id: int,
                   season: str, fetched_at: str, http_status: Optional[int]) -> Tuple[object, dict]:
    """Download one archived capture and parse it into a GameState."""
    resp = archive.fetch_snapshot(snapshot.timestamp, snapshot.original)
    state = parse_gs_report(resp.text, url=resp.url, retrieved_at=fetched_at,
                            game_id=game_id, season=season)
    state.evidence["archived_capture"] = {
        "snapshot_timestamp_utc": snapshot.timestamp,
        "snapshot_digest": snapshot.digest,
        "archived_url": resp.url,
        "canonical_url_now": canonical_url,
        "archived_url_differs_from_canonical": snapshot.original != canonical_url,
        "http_status": http_status,
        "content_length": snapshot.length,
    }
    evidence = {
        "url": resp.url,
        "http_status": http_status,
        "retrieved_at_utc": fetched_at,
        "snapshot_captured_at_utc": _iso_from_timestamp(snapshot.timestamp),
        "snapshot_digest": snapshot.digest,
        "canonical_url_now": canonical_url,
    }
    return state, evidence


def _iso_from_timestamp(timestamp: str) -> str:
    """Wayback stamps are YYYYMMDDhhmmss in UTC - render them as ISO, or pass through."""
    if len(timestamp) == 14 and timestamp.isdigit():
        return (f"{timestamp[0:4]}-{timestamp[4:6]}-{timestamp[6:8]}T"
                f"{timestamp[8:10]}:{timestamp[10:12]}:{timestamp[12:14]}Z")
    return timestamp


def compare_captures(game_id: int, kind: str, older: archive.Snapshot, newer: archive.Snapshot,
                     *, cache_dir: Optional[str] = None, timeout: float = 45.0
                     ) -> Dict[str, object]:
    """Compare two archived captures of one official document.

    Returns ``{"states_differ", "scoring_diff", "records", "finding", "errors"}``. A
    record is produced only when both states parse, the document is a Game Summary and
    the comparison finds a scoring change. Everything else is returned as a finding so
    it can be reviewed instead of guessed at.
    """
    kind = kind.upper()
    parts = sources.split_game_id(game_id)
    season = sources.season_folder(game_id)
    canonical = sources.report_url(season, kind, parts["game_type"], parts["game_no"])
    out: Dict[str, object] = {"game_id": game_id, "kind": kind, "canonical_url": canonical,
                              "older_capture": older.as_dict(), "newer_capture": newer.as_dict(),
                              "states_differ": None, "scoring_diff": [], "records": [],
                              "finding": None, "errors": []}
    if kind not in COMPARABLE_KINDS:
        out["finding"] = (f"report kind {kind} is not comparable row by row; only "
                          f"{', '.join(COMPARABLE_KINDS)} carries the scoring record in a form "
                          f"this comparison can attribute to a goal")
        return out

    fetched_at = store.utcnow()
    try:
        before, ev_old = _parse_capture(older, canonical_url=canonical, game_id=game_id,
                                       season=season, fetched_at=fetched_at, http_status=200)
        after, ev_new = _parse_capture(newer, canonical_url=canonical, game_id=game_id,
                                      season=season, fetched_at=fetched_at, http_status=200)
    except Exception as exc:
        out["errors"].append(f"{type(exc).__name__}: {exc}")
        return out

    changes = detect.diff_states(before, after)
    footer_only = _footer_only(before, after, changes)
    out["states_differ"] = bool(changes) or before.report_generated_at != after.report_generated_at
    if not changes:
        # Documents are rewritten in place for reasons that have nothing to do with
        # scoring (regeneration, re-render, format change). Those are NOT corrections.
        out["finding"] = {
            "kind": "regeneration_without_scoring_change",
            "detail": ("the two captures differ (or their generation timestamps do) but the "
                       "scoring record is identical, so this is not a scoring correction"),
            "older_generated_at": before.report_generated_at,
            "newer_generated_at": after.report_generated_at,
            "footer_only_difference": footer_only,
        }
        return out

    evidence = {"doc.GS": ev_new, "archived_older_capture": ev_old}
    records = detect.build_records(before, after, evidence, detected_at=fetched_at,
                                  detection_mode="backfill_archive_diff")
    for rec in records:
        rec.setdefault("flags", []).extend([
            "original_state_from_archived_capture",
            "corrected_state_from_archived_capture",
            "correction_time_bounded_not_known",
        ])
        if older.original != canonical:
            rec["flags"].append("archived_url_differs_from_canonical")
        rec["timing"] = {
            "when": "postgame",
            "confidence": "heuristic",
            "reasoning": (
                "A Game Summary is generated after the game, so content that differs between "
                "two captures of it was written after the game. The archive brackets the "
                "rewrite between the two capture timestamps and cannot narrow it further."),
            "change_bracket_utc": [_iso_from_timestamp(older.timestamp),
                                   _iso_from_timestamp(newer.timestamp)],
        }
        rec["evidence_status"] = "verified_two_official_states"
        rec["classification"] = rec.get("classification") or {}
        rec["classification"]["timing"] = "postgame"
        rec["classification"]["timing_confidence"] = "heuristic"
        _annotate_sources(rec, ev_old, ev_new, older, newer)
        rec["completeness"] = store.completeness(rec)
    out["records"] = records
    out["scoring_diff"] = [c.as_dict() for c in changes]
    return out


def _annotate_sources(record: dict, ev_old: dict, ev_new: dict, older: archive.Snapshot,
                      newer: archive.Snapshot) -> None:
    """Stamp each source line with the capture it actually came from.

    Without this, an archived document's ``retrieved_at_utc`` (when *we* downloaded the
    capture) would be mistaken for the moment the league's record said what it says. The
    two are different facts and the record keeps both.
    """
    for entry in record.get("sources", []):
        url = entry.get("url") or ""
        for snap, ev in ((older, ev_old), (newer, ev_new)):
            if url == ev.get("url"):
                entry.setdefault("snapshot_captured_at_utc", _iso_from_timestamp(snap.timestamp))
                entry.setdefault("snapshot_digest", snap.digest)
                entry.setdefault("canonical_url_now", ev.get("canonical_url_now"))
                if snap.original != ev.get("canonical_url_now"):
                    entry.setdefault("note",
                                     "the archived capture was taken from this URL, which is "
                                     "not the canonical URL the league serves today")


def _footer_only(before, after, changes) -> bool:
    if changes:
        return False
    return before.report_generated_at != after.report_generated_at


def compare_change_windows(game_id: int, kind: str, windows: List[dict], *,
                           cache_dir: Optional[str] = None, timeout: float = 45.0
                           ) -> List[Dict[str, object]]:
    """Compare every proven change window of one document."""
    out = []
    for window in windows:
        older = archive.Snapshot.from_dict(window["older_capture"])
        newer = archive.Snapshot.from_dict(window["newer_capture"])
        try:
            out.append(compare_captures(game_id, kind, older, newer, cache_dir=cache_dir,
                                        timeout=timeout))
        except Exception as exc:
            out.append({"game_id": game_id, "kind": kind, "errors": [f"{type(exc).__name__}: {exc}"],
                        "older_capture": older.as_dict(), "newer_capture": newer.as_dict(),
                        "records": [], "finding": None, "scoring_diff": []})
    return out


def scan_and_compare(urls: Dict[str, str], kind: str, *, cache_dir: Optional[str] = None,
                     timeout: float = 45.0, compare: bool = True, limit: int = 200,
                     on_result=None) -> Dict[str, object]:
    """Full census step: find documents that changed, then compare the changed ones.

    ``urls`` maps a label that must be a game id (e.g. ``"2023020001"``) to the official
    document URL, so a proven change can be resolved into a comparison.
    """
    scan = archive.scan_urls(urls, cache_dir=cache_dir, timeout=timeout, limit=limit,
                             on_result=on_result)
    summary = archive.summarise_scan(scan)
    comparisons: List[dict] = []
    if compare:
        for row in scan:
            if not row.get("change_windows"):
                continue
            try:
                game_id = int(str(row["label"]).strip())
            except (TypeError, ValueError):
                continue
            comparisons.extend(compare_change_windows(game_id, kind, row["change_windows"],
                                                      cache_dir=cache_dir, timeout=timeout))
    summary["comparisons"] = comparisons
    summary["records_found"] = sum(len(c.get("records") or []) for c in comparisons)
    summary["regenerations"] = sum(1 for c in comparisons if c.get("finding"))
    return summary
