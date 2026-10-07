"""Record store: append-only, schema-checked, evidence-preserving.

Rules enforced by this module:

* a record is never rewritten in place - a correction to a record is appended as a
  new revision and the old bytes stay in the git history;
* every record must carry at least one official source URL, otherwise validation
  fails;
* missing optional-but-requested fields are reported by ``completeness()`` and are
  surfaced on the website as gaps instead of being filled with assumptions.
"""

from __future__ import annotations

import json
import os
import time
from typing import Dict, Iterable, List, Optional

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(REPO_ROOT, "data")
RECORDS_PATH = os.path.join(DATA_DIR, "records", "discrepancies.json")
EVIDENCE_DIR = os.path.join(DATA_DIR, "evidence")
GAMES_DIR = os.path.join(DATA_DIR, "games")

REQUIRED_FIELDS = [
    "record_id", "game.game_id", "game.date", "game.away.abbrev", "game.home.abbrev",
    "event.period", "event.clock", "initial_state.ruling", "corrected_state.ruling",
    "change.discrepancy_type", "change.affects_goal_total", "change.attribution_only",
    "timing.when", "evidence_status", "sources",
]

#: Fields the project charter asks for; absence is reported, never invented.
REQUESTED_FIELDS = REQUIRED_FIELDS + [
    "event.period_type", "event.strength", "reason.category", "reason.text",
    "game.final_score", "detection.detected_at_utc", "settlement.level",
]

EVIDENCE_STATUSES = {
    "verified_two_official_states": "Both the initial and corrected state are shown by official "
                                    "NHL artifacts, with timestamps for each.",
    "verified_corrected_state": "The corrected state is verified from an official artifact; the "
                                "initial state rests on an official artifact that has since been "
                                "overwritten, or on a documented official announcement.",
    "verified_corrected_state_and_official_announcement":
        "The corrected state is verified from an official report or game feed, and the league's own "
        "announcement states that the change was made. The pre-change scoring record was not "
        "retrievable, so the scope of the change before the correction rests on the announcement.",
    "official_announcement_only": "An official source states the change but the pre-change artifact "
                                  "is not retrievable.",
    "conflicting": "Two official artifacts disagree and the discrepancy has NOT been resolved.",
    "incomplete": "Evidence is missing for at least one required dimension of the change.",
    "unverifiable": "The change is claimed but no official source could be obtained.",
}


def utcnow() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _get(d: dict, path: str):
    cur = d
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def validate(record: dict) -> List[str]:
    errors = []
    for field in REQUIRED_FIELDS:
        if _get(record, field) in (None, "", []):
            errors.append(f"missing required field: {field}")
    sources = record.get("sources") or []
    if not any((s or {}).get("url") for s in sources):
        errors.append("no source with a URL")
    if record.get("evidence_status") not in EVIDENCE_STATUSES:
        errors.append(f"invalid evidence_status: {record.get('evidence_status')!r}")
    return errors


def completeness(record: dict) -> Dict[str, object]:
    missing = [f for f in REQUESTED_FIELDS if _get(record, f) in (None, "", [])]
    total = len(REQUESTED_FIELDS)
    return {
        "missing_requested_fields": missing,
        "fields_present": total - len(missing),
        "fields_requested": total,
        "percent_complete": round(100.0 * (total - len(missing)) / total, 1),
    }


def load_records(path: str = RECORDS_PATH) -> List[dict]:
    if not os.path.exists(path):
        return []
    with open(path) as fh:
        blob = json.load(fh)
    if isinstance(blob, dict):
        return blob.get("records", [])
    return blob


#: keys the store owns and always rewrites; every other top-level key in the file
#: (coverage reports, status notes, anything a future session adds) is PRESERVED.
_OWNED_KEYS = ("schema_version", "updated_at_utc", "count", "records")


def _preserved_metadata(path: str) -> dict:
    """Top-level metadata already in the file that the store must not delete.

    Discovered the hard way: the first monitor write would otherwise have silently
    dropped `coverage` and `status_note`, taking the site's coverage panel and the
    empty-state explanation with it.
    """
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as fh:
            previous = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(previous, dict):
        return {}
    return {k: v for k, v in previous.items() if k not in _OWNED_KEYS}


def save_records(records: Iterable[dict], path: str = RECORDS_PATH, **meta) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {"schema_version": "1.0", "updated_at_utc": utcnow(), "count": 0, "records": []}
    payload.update(_preserved_metadata(path))
    for r in records:
        if not r.get("completeness"):
            r["completeness"] = completeness(r)
        payload["records"].append(r)
    payload["count"] = len(payload["records"])
    payload.update(meta)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh, indent=2, sort_keys=False, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def _comparable(record: dict) -> dict:
    """Record content without volatile bookkeeping fields (revision counters)."""
    return {k: v for k, v in record.items() if k not in ("revision", "previous_revisions")}


def upsert_record(record: dict, path: str = RECORDS_PATH) -> str:
    """Insert or replace a record by ``record_id``. Returns 'inserted' or 'updated'."""
    errors = validate(record)
    if errors:
        raise ValueError("record failed validation: " + "; ".join(errors))
    record.setdefault("completeness", completeness(record))
    records = load_records(path)
    for i, existing in enumerate(records):
        if existing.get("record_id") == record["record_id"]:
            if _comparable(existing) != _comparable(record):
                record["revision"] = existing.get("revision", 1) + 1
                # keep the superseded version for auditability, without nesting history
                previous = {k: v for k, v in existing.items() if k != "previous_revisions"}
                record.setdefault("previous_revisions", []).append(previous)
                records[i] = record
                save_records(records, path)
                return "updated"
            return "unchanged"
    records.append(record)
    record.setdefault("revision", 1)
    save_records(records, path)
    return "inserted"


# ----------------------------------------------------------------------------- #
# Evidence log: every captured official state, timestamped (never deleted)
# ----------------------------------------------------------------------------- #

def append_evidence(game_id: int, state_dict: dict, *, root: str = EVIDENCE_DIR) -> str:
    """Append a captured state to the per-game evidence timeline (JSONL)."""
    d = os.path.join(root, str(game_id))
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "states.jsonl")
    with open(path, "a") as fh:
        fh.write(json.dumps(state_dict, sort_keys=True, ensure_ascii=False) + "\n")
    return path


def read_evidence(game_id: int, *, root: str = EVIDENCE_DIR) -> List[dict]:
    path = os.path.join(root, str(game_id), "states.jsonl")
    if not os.path.exists(path):
        return []
    out = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def append_finding(game_id: int, finding: dict, *, root: str = EVIDENCE_DIR) -> str:
    """Persist a cross-check discrepancy (two official renderings disagreeing).

    Findings are *not* discrepancy records: they are unresolved observations that a
    human (or a later automated pass) must resolve. Keeping them out of the record
    store is deliberate - a record must never be created from an unresolved conflict.
    """
    d = os.path.join(root, str(game_id))
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "crosschecks.jsonl")
    payload = dict(finding)
    payload.setdefault("observed_at_utc", utcnow())
    payload.setdefault("game_id", game_id)
    with open(path, "a") as fh:
        fh.write(json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n")
    return path


def save_game_state(state_dict: dict, *, root: str = GAMES_DIR) -> str:
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, f"{state_dict['game_id']}.json")
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state_dict, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)
    return path


def load_game_state(game_id: int, *, root: str = GAMES_DIR) -> Optional[dict]:
    path = os.path.join(root, f"{game_id}.json")
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        return json.load(fh)
