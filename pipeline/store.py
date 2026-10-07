"""Persistence for snapshots and database files (atomic JSON writes)."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from . import config


def load_json(path: Path, default):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: Path, obj) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# --- snapshots -----------------------------------------------------------------

def snapshot_path(game_pk) -> Path:
    return config.SNAPSHOT_DIR / f"{game_pk}.json"


def load_snapshot(game_pk) -> dict | None:
    return load_json(snapshot_path(game_pk), None)


def save_snapshot(game_pk, snap: dict) -> None:
    save_json(snapshot_path(game_pk), snap)


def list_snapshot_pks() -> list:
    if not config.SNAPSHOT_DIR.exists():
        return []
    pks = []
    for entry in config.SNAPSHOT_DIR.glob("*.json"):
        try:
            pks.append(int(entry.stem))
        except ValueError:
            continue
    return pks


# --- database ------------------------------------------------------------------

def load_discrepancies() -> dict:
    return load_json(config.DISCREPANCIES_PATH,
                     {"schema_version": 1, "generated_at": None, "generator": None,
                      "records": []})


def save_discrepancies(db: dict) -> None:
    save_json(config.DISCREPANCIES_PATH, db)


def load_alerts() -> dict:
    return load_json(config.ALERTS_PATH, {"schema_version": 1, "generated_at": None,
                                          "alerts": []})


def save_alerts(alerts: dict) -> None:
    save_json(config.ALERTS_PATH, alerts)


def load_notify_state() -> dict:
    return load_json(config.NOTIFY_STATE_PATH,
                     {"notified_record_ids": [], "notified_alert_hashes": []})


def save_notify_state(state: dict) -> None:
    save_json(config.NOTIFY_STATE_PATH, state)


def merge_evidence(existing: list[dict], incoming: list[dict]) -> list[dict]:
    """Merge evidence lists; identical (label, url) entries keep the newest data."""
    merged = list(existing)
    index = {(e.get("label"), e.get("url")): i for i, e in enumerate(merged)}
    for ev in incoming:
        key = (ev.get("label"), ev.get("url"))
        if key in index:
            merged[index[key]] = ev
        else:
            index[key] = len(merged)
            merged.append(ev)
    return merged


def upsert_record(db: dict, record: dict, now_iso: str) -> str:
    """Insert or update a record. Returns 'created' | 'updated' | 'unchanged'.

    The ORIGINAL state is always the earliest observed; later diffs refresh the
    corrected state, classification, evidence, and flags.
    """
    records = db.setdefault("records", [])
    for i, existing in enumerate(records):
        if existing.get("id") != record.get("id"):
            continue
        if (existing.get("corrected") == record.get("corrected")
                and existing.get("classification") == record.get("classification")):
            return "unchanged"
        merged = dict(existing)
        # keep earliest original + first detection
        merged["corrected"] = record["corrected"]
        merged["classification"] = record["classification"]
        merged["evidence"] = merge_evidence(existing.get("evidence", []),
                                            record.get("evidence", []))
        merged["flags"] = sorted(set(existing.get("flags", [])) | set(record.get("flags", [])))
        merged["revisions"] = existing.get("revisions", []) + [
            {"at": now_iso, "note": "corrected state updated by snapshot diff"}
        ]
        records[i] = merged
        return "updated"
    records.append(record)
    return "created"
