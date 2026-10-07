"""Schema + integrity validation for the database files.

Deliberately stdlib-only (a focused validator, not full JSON Schema), so CI has
zero dependencies. Enforces the promises the charter makes: both states present,
evidence links present and well-formed, no mutually exclusive classifications.
"""

from __future__ import annotations

import json
import re

from . import config, store

RULINGS = {"goal", "no_goal", "unknown"}
TIMINGS = {"in_game", "intermission", "postgame", "unknown"}
TYPES = {"goal_to_no_goal", "no_goal_to_goal", "video_review_overturn",
         "coach_challenge", "scorer_change", "assist_change", "strength_change",
         "official_report_changed", "other"}
EVIDENCE_KINDS = {"live_feed", "official_report", "situation_room", "schedule",
                  "archive", "secondary", "other"}
EVIDENCE_STATUS = {"verified", "incomplete", "conflicting", "unavailable"}
METHODS = {"snapshot_diff", "review_marker", "report_hash_change", "manual_verified"}
URL_RE = re.compile(r"^https?://")
ID_RE = re.compile(r"^[0-9]+#P[0-9]+#[A-Z]{2,4}#[0-9]+#[a-z_]+$")
DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def _goal_state_errors(state: dict, where: str) -> list[str]:
    errors = []
    if not isinstance(state, dict):
        return [f"{where}: must be an object"]
    if state.get("ruling") not in RULINGS:
        errors.append(f"{where}.ruling: invalid value {state.get('ruling')!r}")
    assists = state.get("assists")
    if assists is not None and not isinstance(assists, list):
        errors.append(f"{where}.assists: must be a list")
    return errors


def validate_record(rec: dict) -> list[str]:
    errors: list[str] = []
    rid = rec.get("id", "<missing id>")

    for field in ("id", "status", "game", "event", "original", "corrected",
                  "classification", "detection", "evidence", "flags"):
        if field not in rec:
            errors.append(f"{rid}: missing required field '{field}'")
    if errors:
        return errors

    if not ID_RE.match(rec.get("id", "")):
        errors.append(f"{rid}: id does not match pattern")
    if rec.get("status") not in {"pending_review", "confirmed", "conflicting"}:
        errors.append(f"{rid}: invalid status")

    game = rec.get("game") or {}
    if not isinstance(game.get("game_pk"), int):
        errors.append(f"{rid}: game.game_pk must be an integer")
    if not (isinstance(game.get("season"), str) and re.match(r"^[0-9]{8}$", game.get("season"))):
        errors.append(f"{rid}: game.season must be YYYYYYYY (e.g. 20262027)")
    if not (isinstance(game.get("date"), str) and DATE_RE.match(game.get("date"))):
        errors.append(f"{rid}: game.date must be YYYY-MM-DD")
    for side in ("away", "home"):
        team = game.get(side)
        if not isinstance(team, dict) or "tri" not in team or "name" not in team:
            errors.append(f"{rid}: game.{side} must contain tri and name")

    event = rec.get("event") or {}
    if not isinstance(event.get("period"), int) or event["period"] < 0:
        errors.append(f"{rid}: event.period must be an integer >= 0")

    errors.extend(_goal_state_errors(rec.get("original") or {}, f"{rid}: original"))
    errors.extend(_goal_state_errors(rec.get("corrected") or {}, f"{rid}: corrected"))

    cls = rec.get("classification") or {}
    total = cls.get("changes_game_total")
    attrib = cls.get("attribution_only")
    if not isinstance(total, bool) or not isinstance(attrib, bool):
        errors.append(f"{rid}: classification flags must be booleans")
    elif total and attrib:
        errors.append(f"{rid}: changes_game_total and attribution_only are mutually exclusive")
    types = cls.get("types")
    if not isinstance(types, list) or not types or not set(types) <= TYPES:
        errors.append(f"{rid}: classification.types invalid: {types!r}")
    if cls.get("timing") not in TIMINGS:
        errors.append(f"{rid}: classification.timing invalid")
    if cls.get("timing_confidence") not in {"direct", "heuristic", "unknown"}:
        errors.append(f"{rid}: classification.timing_confidence invalid")
    if not isinstance(cls.get("settlement_risk"), bool):
        errors.append(f"{rid}: settlement_risk must be a boolean")
    if total is True and cls.get("settlement_risk") is False:
        errors.append(f"{rid}: a total-changing discrepancy must carry settlement_risk=true")

    det = rec.get("detection") or {}
    if det.get("method") not in METHODS:
        errors.append(f"{rid}: detection.method invalid")
    if not det.get("first_detected_at"):
        errors.append(f"{rid}: detection.first_detected_at required")

    evidence = rec.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        errors.append(f"{rid}: at least one evidence entry is required")
    else:
        for i, ev in enumerate(evidence):
            where = f"{rid}.evidence[{i}]"
            for field in ("label", "url", "kind", "status"):
                if not ev.get(field):
                    errors.append(f"{where}: missing {field}")
            if ev.get("url") and not URL_RE.match(ev["url"]):
                errors.append(f"{where}: url must be absolute http(s)")
            if ev.get("kind") not in EVIDENCE_KINDS:
                errors.append(f"{where}: invalid kind")
            if ev.get("status") not in EVIDENCE_STATUS:
                errors.append(f"{where}: invalid status")

    if not isinstance(rec.get("flags"), list):
        errors.append(f"{rid}: flags must be a list")

    # Evidence integrity: any non-verified evidence must be flagged for review.
    statuses = {ev.get("status") for ev in (evidence or []) if isinstance(ev, dict)}
    if statuses & {"incomplete", "conflicting", "unavailable"} and \
            "needs_human_review" not in rec.get("flags", []):
        errors.append(f"{rid}: non-verified evidence requires 'needs_human_review' flag")
    return errors


def validate_database() -> tuple[list[str], dict]:
    errors: list[str] = []
    db = store.load_discrepancies()
    # The database holds two record shapes since the two lines were consolidated:
    # this line's (integer schema_version, "id") and the engine line's (string
    # "1.0", "record_id"). Rather than copy the engine's rules here - a second
    # implementation is how two validators start disagreeing - engine-shaped
    # records are handed to the engine's own validator.
    engine_validate = None
    if any(isinstance(r, dict) and "record_id" in r and "id" not in r for r in (db.get("records") or [])):
        try:
            from .nhl_scoring import db as _engine_db
            engine_validate = _engine_db.validate
        except Exception as exc:  # pragma: no cover - import failure is itself a finding
            errors.append(f"database: engine validator unavailable ({exc})")
    if db.get("schema_version") not in (1, "1.0"):
        errors.append("database: schema_version must be 1")
    records = db.get("records")
    if not isinstance(records, list):
        errors.append("database: records must be a list")
        records = []

    seen_ids = set()
    for rec in records:
        rid = rec.get("id") or rec.get("record_id")
        if "id" not in rec and "record_id" in rec and engine_validate is not None:
            errors.extend(f"{rid}: {problem}" for problem in engine_validate(rec))
        else:
            errors.extend(validate_record(rec))
        if rid in seen_ids:
            errors.append(f"{rid}: duplicate record id")
        seen_ids.add(rid)

    # alerts.json sanity
    alerts = store.load_alerts()
    if not isinstance(alerts.get("alerts"), list):
        errors.append("alerts.json: alerts must be a list")

    # schema file itself parses
    try:
        with open(config.SCHEMA_PATH, "r", encoding="utf-8") as fh:
            json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"docs/schema.json: unreadable: {exc}")

    stats = {"records": len(records), "errors": len(errors),
             "pending_review": sum(1 for r in records if r.get("status") == "pending_review"),
             "confirmed": sum(1 for r in records if r.get("status") == "confirmed")}
    return errors, stats
