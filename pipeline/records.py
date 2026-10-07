"""Build discrepancy records from snapshot diffs.

Every record keeps BOTH states (original and corrected), carries at least one
official evidence link, and starts life as ``pending_review`` with a
``needs_human_review`` flag — automation detects, humans (or corroborating
official documents) confirm.
"""

from __future__ import annotations

from . import __version__, config


def _utcnow_iso(now_iso: str) -> str:
    return now_iso


def goal_state(goal: dict | None, ruling: str) -> dict:
    """Project a snapshot goal into the record's goal_state shape."""
    if goal is None:
        return {"ruling": ruling, "scorer": None, "assists": [], "strength": None,
                "empty_net": None, "clock": None, "description": None}
    return {
        "ruling": ruling,
        "scorer": goal.get("scorer"),
        "assists": list(goal.get("assists") or []),
        "strength": goal.get("strength"),
        "empty_net": goal.get("empty_net"),
        "clock": goal.get("clock"),
        "description": goal.get("description"),
    }


def record_id(game_pk, period, team, ordinal, family) -> str:
    team_code = (team or "UNK").upper()[:4]
    return f"{game_pk}#P{period}#{team_code}#{ordinal}#{family}"


def _review_evidence_for(change: dict, new_snap: dict) -> dict | None:
    """Find a review event in the new snapshot plausibly tied to this change."""
    for review in new_snap.get("reviews") or []:
        if review.get("period") != change.get("period"):
            continue
        if change["op"] == "removed" and review.get("mentions_overturn"):
            return review
        if change["op"] == "added" and review.get("mentions_overturn"):
            return review
    return None


def classify_timing(old_snap: dict, new_snap: dict) -> tuple[str, str]:
    """Heuristic timing classification. Returns (timing, confidence)."""
    old_final = bool(old_snap.get("final"))
    new_final = bool(new_snap.get("final"))
    old_state = old_snap.get("feed_state") or {}
    new_state = new_snap.get("feed_state") or {}

    if old_final:
        return "postgame", "direct" if new_final else "heuristic"
    if old_state.get("in_intermission") and not new_state.get("in_intermission") and not new_final:
        return "intermission", "heuristic"
    if not new_final:
        return "in_game", "heuristic"
    # old not final, new final: change became visible at/by final
    return "in_game", "heuristic"


def build_records_for_changes(changes: list[dict], old_snap: dict, new_snap: dict,
                              now_iso: str, report_changes: list[dict] | None = None) -> list[dict]:
    """Turn diff output into discrepancy record dicts."""
    game_pk = (new_snap.get("game") or {}).get("game_pk")
    season = (new_snap.get("game") or {}).get("season")
    game_type = (new_snap.get("game") or {}).get("game_type")
    game_date = (new_snap.get("game") or {}).get("date")
    teams = new_snap.get("teams") or {}
    feed_url = (new_snap.get("source") or {}).get("live_feed")
    old_feed_url = (old_snap.get("source") or {}).get("live_feed")
    timing, timing_conf = classify_timing(old_snap, new_snap)

    records: list[dict] = []
    for change in changes:
        period = change.get("period") or 0
        team = change.get("team")
        op = change["op"]

        if op == "removed":
            family = "total"
            ordinal = change.get("old_ordinal") or 0
            original = goal_state(change["old"], "goal")
            corrected = goal_state(change["old"], "no_goal")
            types = ["goal_to_no_goal"]
            changes_total = True
        elif op == "added":
            family = "total"
            ordinal = change.get("new_ordinal") or 0
            original = goal_state(change["new"], "no_goal")
            corrected = goal_state(change["new"], "goal")
            types = ["no_goal_to_goal"]
            changes_total = True
        else:  # changed
            family = "attrib"
            ordinal = change.get("new_ordinal") or 0
            original = goal_state(change["old"], "goal")
            corrected = goal_state(change["new"], "goal")
            fields = change.get("fields_changed") or {}
            types = []
            if "scorer" in fields:
                types.append("scorer_change")
            if "assists" in fields:
                types.append("assist_change")
            if "strength" in fields or "empty_net" in fields:
                types.append("strength_change")
            if not types:
                types.append("other")
            changes_total = False

        # Video-review corroboration -----------------------------------------
        review = _review_evidence_for(change, new_snap) if op in ("removed", "added") else None
        reason = None
        if review is not None:
            if op == "removed":
                types.append("video_review_overturn")
                if "challenge" in (review.get("description") or "").lower():
                    types.append("coach_challenge")
            else:
                types.append("video_review_overturn")
            reason = review.get("description")
        types = list(dict.fromkeys(types))  # dedupe, preserve order

        flags = ["needs_human_review"]  # every automated record starts flagged
        if timing_conf == "heuristic":
            flags.append("timing_heuristic")

        evidence = [
            {
                "label": "Official live feed — capture AFTER change",
                "url": feed_url,
                "kind": "live_feed",
                "status": "verified",
                "captured_at": new_snap.get("captured_at"),
                "archive_url": None,
                "note": f"Snapshot captured {new_snap.get('captured_at')}",
            },
            {
                "label": "Official live feed — capture BEFORE change",
                "url": old_feed_url or feed_url,
                "kind": "live_feed",
                "status": "verified",
                "captured_at": old_snap.get("captured_at"),
                "archive_url": None,
                "note": f"Snapshot captured {old_snap.get('captured_at')}",
            },
        ]
        if review is not None:
            evidence.append({
                "label": "Video review event in official play-by-play",
                "url": feed_url,
                "kind": "live_feed",
                "status": "verified",
                "captured_at": new_snap.get("captured_at"),
                "archive_url": None,
                "note": review.get("description"),
            })
            evidence.append({
                "label": "NHL Situation Room (search for this game's review post)",
                "url": config.SITUATION_ROOM_URL,
                "kind": "situation_room",
                "status": "incomplete",
                "captured_at": None,
                "archive_url": None,
                "note": "Specific post not yet auto-linked; verify manually.",
            })

        source_goal = change["new"] if change["new"] is not None else change["old"]
        rec = {
            "id": record_id(game_pk, period, team, ordinal, family),
            "status": "pending_review",
            "game": {
                "game_pk": game_pk,
                "season": season,
                "game_type": game_type,
                "date": game_date,
                "away": teams.get("away") or {"tri": None, "name": None},
                "home": teams.get("home") or {"tri": None, "name": None},
                "venue": (new_snap.get("game") or {}).get("venue"),
                "links": {"live_feed": feed_url},
            },
            "event": {
                "period": period,
                "period_type": (source_goal or {}).get("period_type"),
                "team": team,
                "goal_ordinal": ordinal or None,
                "description": (source_goal or {}).get("description"),
            },
            "original": original,
            "corrected": corrected,
            "classification": {
                "changes_game_total": changes_total,
                "attribution_only": not changes_total,
                "types": types,
                "timing": timing,
                "timing_confidence": timing_conf,
                "reason": reason,
                "settlement_risk": changes_total,
            },
            "detection": {
                "method": "review_marker" if review is not None and changes_total else "snapshot_diff",
                "first_detected_at": now_iso,
                "detector_version": __version__,
            },
            "evidence": evidence,
            "flags": flags,
            "revisions": [{"at": now_iso, "note": "created by snapshot diff"}],
        }
        records.append(rec)

    # Official-report hash changes: flag-only records (human review requested).
    for rc in report_changes or []:
        # Unique per game AND per report type (GS/ES): code them into the id.
        type_slot = ("RP" + str(rc["report"])[:2]).upper()[:4]
        rec_id = f"{game_pk}#P0#{type_slot}#0#official_report_changed"
        records.append({
            "id": rec_id,
            "status": "pending_review",
            "game": {
                "game_pk": game_pk,
                "season": season,
                "game_type": game_type,
                "date": game_date,
                "away": teams.get("away") or {"tri": None, "name": None},
                "home": teams.get("home") or {"tri": None, "name": None},
                "venue": None,
                "links": {"report": rc.get("url")},
            },
            "event": {
                "period": 0,
                "period_type": None,
                "team": None,
                "goal_ordinal": None,
                "description": f"Official {rc['report']} report file changed after initial capture.",
            },
            "original": {"ruling": "unknown", "scorer": None, "assists": [], "strength": None,
                         "empty_net": None, "clock": None,
                         "description": "Report content at first capture (hash recorded in snapshot)."},
            "corrected": {"ruling": "unknown", "scorer": None, "assists": [], "strength": None,
                          "empty_net": None, "clock": None,
                          "description": "Report content changed; text diff pending human review."},
            "classification": {
                "changes_game_total": False,
                "attribution_only": False,
                "types": ["official_report_changed"],
                "timing": "postgame",
                "timing_confidence": "direct",
                "reason": None,
                "settlement_risk": False,
            },
            "detection": {"method": "report_hash_change", "first_detected_at": now_iso,
                          "detector_version": __version__},
            "evidence": [{
                "label": f"Official {rc['report']} report (current copy)",
                "url": rc.get("url"),
                "kind": "official_report",
                "status": "incomplete",
                "captured_at": new_snap.get("captured_at"),
                "archive_url": None,
                "note": "Content diff not yet extracted; verify what changed manually.",
            }],
            "flags": ["needs_human_review", "report_content_diff_pending"],
            "revisions": [{"at": now_iso, "note": "created by report hash change"}],
        })

    return records
