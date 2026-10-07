"""The canonical record store.

One JSON file is the database (``data/discrepancies.json``); the CSV and the
site are generated views of it. ``record_id`` is a stable hash of the claim
itself (game + rule + goal key + field), so re-running the pipeline merges into
existing records instead of duplicating them, and a human edit to the evidence
block never mints a new id.

Validation is hand-rolled rather than ``jsonschema``-driven for two reasons: the
pipeline has to run on a bare runner with no pip install, and we want
*errors that name the field and the rule*, because a record that fails schema is
a record a human has to look at - not a record to drop silently.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import SCHEMA_VERSION
from .market import classify

REQUIRED_TOP = ["record_id", "schema_version", "status", "detected_by", "game", "discrepancy",
                "initial_state", "corrected_state", "sources", "verification"]

VALID_STATUS = {"verified", "flagged", "pending_review", "disputed", "retired"}
#: statuses that only a reader may set; machine runs must not overwrite them
HUMAN_STATUSES = {"verified", "disputed", "retired"}
VALID_DETECTED_BY = {"cross_source", "snapshot_diff", "integrity_check", "manual_research",
                     "prior_art_log", "league_statement"}
# "reference" = a link that documents a rule or format, not the event itself.
VALID_EVIDENCE = {"primary", "secondary", "reference", "none"}
VALID_WHEN = {"in_game", "intermission", "postgame", "next_day", "backfill_conflict",
              "unknown", "not_applicable"}
VALID_RISK = {"high", "medium", "low", "none"}
TRI = {"yes", "no", "possible", "unknown"}

CSV_COLUMNS = [
    "record_id", "status", "confidence", "detected_by", "game_date", "season", "game_id",
    "away_team", "home_team", "final_score", "period", "clock", "team", "rule", "rule_label",
    "change_type", "initial_scorer", "initial_assists", "corrected_scorer", "corrected_assists",
    "initial_total", "corrected_total", "total_changed", "attribution_only", "when_corrected",
    "video_review", "affects_game_total", "affects_player_props", "risk", "primary_source_url",
    "secondary_source_url", "flags", "summary", "updated_at",
]


def compute_record_id(game_id: str, check_id: str, field: str, goal_key: Optional[str]) -> str:
    basis = "|".join([str(game_id), str(check_id), str(field), str(goal_key or "")])
    return "SDN-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:10]


def normalize_player(player: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not player:
        return None
    name = player.get("name") or player.get("display") or ""
    return {
        "name": name,
        "surname": player.get("surname"),
        "initial": player.get("initial"),
        "player_id": player.get("player_id"),
        "sweater_number": player.get("sweater_number"),
        "season_counter": player.get("counter") if "counter" in player else player.get("season_counter"),
    }


def _state_from_goal(goal: Optional[Dict[str, Any]], side: str) -> Dict[str, Any]:
    if not goal:
        return {
            "artifact": side,
            "goal_present": False,
            "ruling": "absent_from_this_artifact",
            "scorer": None,
            "assists": [],
            "strength": None,
            "own_goal": None,
            "clock": None,
            "period": None,
            "score_after": None,
        }
    return {
        "artifact": side,
        "goal_present": True,
        "ruling": "goal",
        "scorer": normalize_player(goal.get("scorer")) if isinstance(goal.get("scorer"), dict) else {"name": goal.get("scorer")},
        "assists": [a if isinstance(a, dict) else {"name": a} for a in (goal.get("assists") or [])],
        "strength": goal.get("strength") or goal.get("strength_raw"),
        "own_goal": goal.get("own_goal"),
        "empty_net": goal.get("empty_net"),
        "period": goal.get("period"),
        "clock": goal.get("clock"),
        "clock_seconds": goal.get("clock_seconds"),
        "team": goal.get("team"),
        "score_after": {"away": goal.get("away_score"), "home": goal.get("home_score")},
        "event_id": goal.get("event_id"),
        "player_id": goal.get("player_id"),
        "shot_type": goal.get("shot_type"),
        "goal_modifier": goal.get("goal_modifier"),
        "awarded": goal.get("awarded"),
    }


def record_from_finding(finding: Any, *, game: Dict[str, Any], artifacts: Iterable[Dict[str, Any]],
                        detection: Optional[Dict[str, Any]] = None,
                        status: str = "flagged", confidence: str = "medium",
                        reason: Optional[str] = None) -> Dict[str, Any]:
    """Turn a machine finding into a database record.

    ``status`` defaults to ``flagged`` on purpose: a rule firing is not the same
    thing as a verified scoring correction, and the pipeline must not promote its
    own output. Promotion to ``verified`` happens in the verification pass, where
    a named source quote and the artifact hashes have to line up.
    """
    get = (lambda k, d=None: finding.get(k, d)) if isinstance(finding, dict) else (lambda k, d=None: getattr(finding, k, d))
    check_id = get("check_id", "")
    rule = get("rule", "")
    field = get("field", "") or ""
    goal_key = get("goal_key")
    left = get("left") or {}
    right = get("right") or {}
    evidence = get("evidence") or []
    left_side = left.get("source") or (evidence[0].get("source") if evidence else "") or "source_a"
    right_side = right.get("source") or (evidence[1].get("source") if len(evidence) > 1 else "") or "source_b"
    initial = _state_from_goal(left if left else None, left_side)
    corrected = _state_from_goal(right if right else None, right_side)
    # "initial" always means the earlier state and "corrected" the later one.
    # For a goal added between pulls the earlier artifact simply did not carry
    # the goal, so its state is recorded as absence - never as an invented
    # "no goal" ruling, because a sheet that omits a goal and a referee who
    # waves one off are different facts and only the second one is a ruling.
    if field == "goal_added":
        initial["goal_present"] = False
        initial["ruling"] = "not_recorded_by_this_artifact"
    elif field == "goal_removed":
        corrected["goal_present"] = False
        corrected["ruling"] = "not_recorded_by_this_artifact"
    if field in ("goal_added", "goal_removed"):
        absent = initial if field == "goal_added" else corrected
        absent["scorer"] = absent["scorer"] or None
        absent["assists"] = []
    market = classify(finding if isinstance(finding, dict) else _finding_dict(finding))
    ctx = get("context") or {}
    total_before = _total_from_score(initial.get("score_after"), initial.get("team"), game)
    total_after = _total_from_score(corrected.get("score_after"), corrected.get("team"), game)
    # Prefer what each artifact itself counts: goal rows are more reliable than a
    # header score, and the GS sheet has no running score at all.
    if ctx.get("left_goal_count") is not None:
        total_before = int(ctx["left_goal_count"])
    if ctx.get("right_goal_count") is not None:
        total_after = int(ctx["right_goal_count"])
    goal_delta = None
    if isinstance(total_before, int) and isinstance(total_after, int):
        goal_delta = total_after - total_before
    record_id = compute_record_id(game.get("game_id", ""), check_id, field, goal_key)
    changed = market["total_changed"]
    flags = _flags_for(get("detail", ""), field, evidence, initial, corrected, market)
    summary = _summary(get("detail", ""), game, initial, corrected)
    record = {
        "record_id": record_id,
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "confidence": confidence,
        "detected_by": _detected_by(check_id),
        "detection": {
            "check_id": check_id,
            "rule": rule,
            "rule_label": get("check_name", ""),
            "severity": get("severity", "low"),
            "tool_version": (detection or {}).get("tool_version", ""),
            "run_id": (detection or {}).get("run_id", ""),
            "detected_at": (detection or {}).get("detected_at", ""),
        },
        "game": {
            "game_id": game.get("game_id"),
            "season": game.get("season"),
            "game_type": game.get("game_type"),
            "date": game.get("date"),
            "away_team": game.get("away_team"),
            "home_team": game.get("home_team"),
            "venue": game.get("venue"),
            "final_score": game.get("final_score", {"away": None, "home": None}),
            "gamecenter_url": game.get("gamecenter_url"),
            "report_urls": game.get("report_urls", {}),
        },
        "discrepancy": {
            "period": get("period"),
            "clock": get("clock"),
            "team": get("team"),
            "field": field,
            "goal_key": goal_key,
            "change_type": rule,
            "summary": summary,
            "detail": get("detail", ""),
            "total_changed": changed,
            "attribution_only": changed is False,
            "goal_no_goal_change": bool(field in ("goal_added", "goal_removed") or
                                        rule == "goal_missing_from_one_source" or
                                        rule == "post_snapshot_goal_count_change"),
            "video_review": (detection or {}).get("video_review"),
            "when_corrected": (detection or {}).get("when_corrected", "unknown"),
            "timing_uncertain": _detected_by(check_id) == "cross_source",
            "market_impact": market,
            "reason": reason or _reason_guess(rule, get("detail", "")),
        },
        "initial_state": initial,
        "corrected_state": corrected,
        "totals": {
            "initial_game_goals": total_before,
            "corrected_game_goals": total_after,
            "goal_delta": goal_delta,
            "basis": "goal rows counted per artifact" if ctx else "running score in the source rows",
        },
        "sources": list(artifacts) or _sources_from_evidence(evidence),
        "verification": {
            "status": status,
            "evidence_grade": "primary" if _detected_by(check_id) in ("cross_source", "snapshot_diff",
                                                                       "integrity_check") else "secondary",
            "independently_checkable": True,
            "check_instructions": "Open each source URL and compare the goal line for "
                                  f"period {get('period')} at {get('clock')} ({get('team')}).",
            "verified_by": (detection or {}).get("verified_by", ""),
            "verified_at": (detection or {}).get("verified_at", ""),
        },
        "flags": flags,
        "notes": "",
    }
    return record


def _finding_dict(f: Any) -> Dict[str, Any]:
    return f.to_dict() if hasattr(f, "to_dict") else dict(f.__dict__)


def _detected_by(check_id: str) -> str:
    num = re.sub(r"^C", "", str(check_id))
    try:
        n = int(num)
    except ValueError:
        return "integrity_check"
    if n >= 20:
        return "snapshot_diff"
    if n >= 10:
        return "cross_source"
    return "integrity_check"


def _total_from_score(score_after: Optional[Dict[str, Any]], team: Optional[str], game: Dict[str, Any]) -> Optional[int]:
    if not score_after:
        return None
    away, home = score_after.get("away"), score_after.get("home")
    if away is None or home is None:
        return None
    return int(away) + int(home)


def _reason_guess(rule: str, detail: str) -> Dict[str, Any]:
    return {
        "stated_by_league": False,
        "text": ("Two official renderings of the same game disagree. The league publishes no public "
                 "correction notice, so no reason is on record." if rule.endswith("conflict") or
                 rule.startswith("post_snapshot") else ""),
        "rule_citation": None,
        "needs_human_read": True,
    }


def _flags_for(detail: str, field: str, evidence: List[Dict[str, Any]], initial: Dict[str, Any],
               corrected: Dict[str, Any], market: Dict[str, Any]) -> List[str]:
    flags: List[str] = []
    if market.get("total_changed") is None:
        flags.append("total_change_not_established")
    if field in ("goal_added", "goal_removed") or market.get("rule_class") == "structural":
        flags.append("parser_or_source_gap_must_rule_out")
    if not initial.get("goal_present") or not corrected.get("goal_present"):
        flags.append("missing_in_one_official_artifact")
    if len({e.get("sha256") for e in evidence if e.get("sha256")}) < 2:
        flags.append("single_artifact_evidence")
    flags.append("requires_human_verification")
    return flags


def _summary(detail: str, game: Dict[str, Any], initial: Dict[str, Any], corrected: Dict[str, Any]) -> str:
    who = (corrected.get("scorer") or {}).get("name") or (initial.get("scorer") or {}).get("name") or "unattributed"
    return f"{game.get('away_team')} at {game.get('home_team')} {game.get('date')}: {detail.strip() or who}"


def _sources_from_evidence(evidence: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for ev in evidence:
        if not ev.get("url"):
            continue
        out.append({
            "label": ev.get("source") or ev.get("url"),
            "url": ev.get("url"),
            "kind": "official_api" if "api-web.nhle.com" in ev.get("url", "") else "official_report",
            "retrieved_at": ev.get("retrieved_at"),
            "sha256": ev.get("sha256"),
            "evidence": "primary",
            "quote": ev.get("quote"),
        })
    return out


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------
def validate(record: Dict[str, Any]) -> List[str]:
    """Return a list of ``path: problem`` strings; empty means the record is clean."""
    errors: List[str] = []
    for key in REQUIRED_TOP:
        if key not in record:
            errors.append(f"{key}: required field missing")
    rid = record.get("record_id", "")
    if rid and not re.fullmatch(r"SDN-[0-9a-f]{10}", rid):
        errors.append(f"record_id: {rid!r} does not look like SDN-<10 hex>")
    status = record.get("status")
    if status not in VALID_STATUS:
        errors.append(f"status: {status!r} not in {sorted(VALID_STATUS)}")
    if record.get("detected_by") not in VALID_DETECTED_BY:
        errors.append(f"detected_by: {record.get('detected_by')!r} invalid")
    game = record.get("game") or {}
    gid = game.get("game_id")
    if gid and not re.fullmatch(r"\d{10}", str(gid)):
        errors.append(f"game.game_id: {gid!r} must be the official 10-digit id")
    if not game.get("date") and status in ("verified", "flagged"):
        # A pending record may legitimately sit in the queue with holes in it - that
        # is what the flag is for - but nothing verified may be missing its date.
        errors.append("game.date: required so records can be filtered chronologically")
    disc = record.get("discrepancy") or {}
    if not disc.get("change_type"):
        errors.append("discrepancy.change_type: required")
    if disc.get("total_changed") not in (True, False, None):
        errors.append("discrepancy.total_changed: must be true, false or null")
    when = disc.get("when_corrected")
    if when not in VALID_WHEN:
        errors.append(f"discrepancy.when_corrected: {when!r} not in {sorted(VALID_WHEN)}")
    mi = disc.get("market_impact") or {}
    for key in ("affects_game_total", "affects_player_props", "affects_result_markets"):
        if mi.get(key) not in TRI:
            errors.append(f"discrepancy.market_impact.{key}: {mi.get(key)!r} not in {sorted(TRI)}")
    if mi.get("risk") not in VALID_RISK:
        errors.append(f"discrepancy.market_impact.risk: {mi.get('risk')!r} invalid")
    if not record.get("initial_state") or not record.get("corrected_state"):
        errors.append("initial_state/corrected_state: both states must be preserved")
    sources = record.get("sources") or []
    if not sources:
        errors.append("sources: at least one source link is mandatory")
    for idx, src in enumerate(sources):
        url = src.get("url") or ""
        if not url.startswith("https://"):
            errors.append(f"sources[{idx}].url: must be an https link")
        if src.get("evidence") not in VALID_EVIDENCE:
            errors.append(f"sources[{idx}].evidence: {src.get('evidence')!r} must be one of {sorted(VALID_EVIDENCE)}")
    ver = record.get("verification") or {}
    if ver.get("status") != status:
        errors.append("verification.status: must mirror top-level status")
    if status == "verified":
        if not ver.get("verified_at"):
            errors.append("verification.verified_at: required before a record can be 'verified'")
        if not any(s.get("evidence") == "primary" for s in sources):
            errors.append("verification: a 'verified' record needs at least one primary official source")
    return errors


def load_db(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if isinstance(payload, list):
        payload = {"schema_version": SCHEMA_VERSION, "records": payload}
    payload.setdefault("records", [])
    return payload


def save_db(payload: Dict[str, Any], path: str) -> None:
    records = sorted(payload.get("records", []),
                     key=lambda r: ((r.get("game") or {}).get("date") or "", r.get("record_id") or ""))
    out = {
        "schema_version": payload.get("schema_version", SCHEMA_VERSION),
        "generated_by": "pipeline/nhl_scoring (db.py)",
        "record_count": len(records),
        "records": records,
    }
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False, sort_keys=False)
        fh.write("\n")


def upsert(existing: List[Dict[str, Any]], incoming: List[Dict[str, Any]],
           *, protect_manual: bool = True) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Merge new findings into the store, keeping human-set status sticky.

    A record a reviewer promoted to ``verified`` or demoted to ``disputed`` must
    survive the next machine run; otherwise the database degrades every night
    and nobody trusts it. Machine runs only update the evidence and detection
    blocks and record that they did.
    """
    by_id = {r.get("record_id"): r for r in existing if r.get("record_id")}
    stats = {"added": 0, "updated": 0, "unchanged": 0, "skipped_human": 0}
    for record in incoming:
        rid = record.get("record_id")
        cur = by_id.get(rid)
        if cur is None:
            record.setdefault("first_seen_at", (record.get("detection") or {}).get("detected_at"))
            record.setdefault("seen_count", 1)
            by_id[rid] = record
            stats["added"] += 1
            continue
        sighting = {
            "run_id": (record.get("detection") or {}).get("run_id"),
            "detected_at": (record.get("detection") or {}).get("detected_at"),
            "machine_status": record.get("status"),
        }
        # Only statuses a person (or an agent doing a documented read) chose are
        # protected. "flagged"/"pending_review" are machine states, so protecting
        # them would freeze the queue and make every re-run look like an override.
        human = protect_manual and cur.get("status") in HUMAN_STATUSES
        if human:
            merged = dict(cur)
            stats["skipped_human"] += 1
        else:
            merged = dict(record)
            merged["first_seen_at"] = cur.get("first_seen_at") \
                or (cur.get("detection") or {}).get("detected_at")
            if cur.get("notes") and not merged.get("notes"):
                merged["notes"] = cur["notes"]
            if cur.get("status") == "pending_review" and merged.get("status") == "flagged":
                # a machine sighting does not retire an open research request
                merged["status"] = "pending_review"
                merged["flags"] = sorted(set((merged.get("flags") or []) + ["machine_detected_too"]))
            stats["updated"] += 1
        # The re-sighting is recorded on every path: "this conflict is still there
        # three weeks later" is exactly the evidence a reviewer needs before acting.
        merged["detection_history"] = (cur.get("detection_history") or []) + [sighting]
        merged["seen_count"] = int(cur.get("seen_count") or 1) + 1
        merged["last_seen_at"] = sighting["detected_at"]
        by_id[rid] = merged
    records = list(by_id.values())
    for rec in records:
        rec.setdefault("first_seen_at", (rec.get("detection") or {}).get("detected_at"))
        rec.setdefault("seen_count", 1)
    return records, stats


def to_csv(rows: List[Dict[str, Any]]) -> List[List[str]]:
    import csv as _csv
    import io
    buf = io.StringIO()
    writer = _csv.writer(buf, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for r in rows:
        g = r.get("game") or {}
        d = r.get("discrepancy") or {}
        mi = d.get("market_impact") or {}
        ini = r.get("initial_state") or {}
        cor = r.get("corrected_state") or {}
        def names(state, key):
            value = state.get(key)
            if isinstance(value, dict):
                return value.get("name") or ""
            if isinstance(value, list):
                return "; ".join(v.get("name", "") if isinstance(v, dict) else str(v) for v in value)
            return value or ""
        src = r.get("sources") or []
        total_i = (r.get("totals") or {}).get("initial_game_goals")
        total_c = (r.get("totals") or {}).get("corrected_game_goals")
        writer.writerow([
            r.get("record_id"), r.get("status"), r.get("confidence"), r.get("detected_by"),
            g.get("date"), g.get("season"), g.get("game_id"), g.get("away_team"), g.get("home_team"),
            f"{(g.get('final_score') or {}).get('away')}-{(g.get('final_score') or {}).get('home')}",
            d.get("period"), d.get("clock"), d.get("team"), d.get("change_type"),
            (r.get("detection") or {}).get("rule_label"), d.get("change_type"),
            names(ini, "scorer"), names(ini, "assists"), names(cor, "scorer"), names(cor, "assists"),
            total_i, total_c,
            "" if d.get("total_changed") is None else str(bool(d.get("total_changed"))).lower(),
            str(bool(d.get("attribution_only"))).lower(), d.get("when_corrected"),
            "" if d.get("video_review") is None else str(bool(d.get("video_review"))).lower(),
            mi.get("affects_game_total"), mi.get("affects_player_props"), mi.get("risk"),
            (src[0].get("url") if src else ""), (src[1].get("url") if len(src) > 1 else ""),
            "; ".join(r.get("flags") or []), d.get("summary"), r.get("updated_at") or r.get("last_seen_at") or "",
        ])
    return list(_csv.reader(buf.getvalue().splitlines()))


def write_csv(rows: List[Dict[str, Any]], path: str) -> int:
    import csv as _csv
    table = to_csv(rows)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        _csv.writer(fh, lineterminator="\n").writerows(table)
    return len(table) - 1
