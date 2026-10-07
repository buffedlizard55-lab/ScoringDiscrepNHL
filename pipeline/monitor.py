"""Orchestration: schedule scan -> snapshot -> diff -> records -> alerts."""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timedelta, timezone

from . import alerts as alerts_mod
from . import config, httpclient, livefeed, store, validate
from .diff import diff_goals, diff_report_hashes
from .records import build_records_for_changes


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_final_games(schedule: dict) -> list[dict]:
    games = []
    for day in schedule.get("dates") or []:
        for g in day.get("games") or []:
            status = ((g.get("status") or {}).get("detailedState") or "")
            if status not in config.FINAL_STATES:
                continue
            if g.get("gameType") not in config.MONITORED_GAME_TYPES:
                continue
            teams = g.get("teams") or {}

            def side(key):
                s = teams.get(key) or {}
                team = s.get("team") or {}
                return {
                    "tri": team.get("abbreviation") or team.get("teamCode"),
                    "name": team.get("name"),
                    "score": s.get("score"),
                }

            games.append({
                "game_pk": g.get("gamePk"),
                "season": g.get("season"),
                "game_type": g.get("gameType"),
                "date": day.get("date"),
                "status": status,
                "away": side("away"),
                "home": side("home"),
            })
    return games


def report_url(season: str, rtype: str, game_pk) -> str | None:
    """Build the official PDF report URL for a game, or None if not derivable."""
    if not season or not game_pk:
        return None
    pk = str(game_pk)
    if len(pk) < 10:
        return None
    report_number = pk[4:]  # e.g. 2026020001 -> 020001
    return config.REPORT_URL.format(season=season, rtype=rtype, report=report_number)


def fetch_report_hashes(season: str, game_pk) -> dict:
    hashes = {}
    for rtype in config.MONITORED_REPORT_TYPES:
        url = report_url(season, rtype, game_pk)
        if not url:
            hashes[rtype] = {"url": None, "ok": False, "missing": False,
                             "error": "report url not derivable"}
            continue
        try:
            body = httpclient.fetch(url)
            hashes[rtype] = {"url": url, "ok": True,
                             "sha256": hashlib.sha256(body).hexdigest(),
                             "bytes": len(body)}
        except httpclient.NotFound:
            hashes[rtype] = {"url": url, "ok": False, "missing": True}
        except httpclient.SourceError as exc:
            hashes[rtype] = {"url": url, "ok": False, "missing": False,
                             "error": str(exc.reason)[:200]}
        time.sleep(config.REQUEST_DELAY_SECONDS)
    return hashes


def process_game(game_pk: int, now_iso: str, stats: dict, force_rebaseline: bool) -> list[dict]:
    """Fetch + snapshot + diff one game. Returns new/updated records."""
    url = livefeed.feed_url(game_pk)
    try:
        feed = httpclient.fetch_json(url)
    except httpclient.SourceError as exc:
        stats["fetch_errors"] += 1
        stats["errors"].append(str(exc))
        return []

    snap = livefeed.normalize_live_feed(feed, now_iso, url)
    season = (snap.get("game") or {}).get("season")
    snap["report_hashes"] = fetch_report_hashes(season, game_pk)

    prev = store.load_snapshot(game_pk)
    store.save_snapshot(game_pk, snap)

    if prev is None:
        stats["baselined"] += 1
        return []
    if force_rebaseline:
        stats["rebaselined"] += 1
        return []

    changes = diff_goals(prev.get("goals") or [], snap.get("goals") or [])
    report_changes = diff_report_hashes(prev, snap)
    if not changes and not report_changes:
        stats["unchanged"] += 1
        return []

    if snap.get("warnings"):
        stats["warnings"].extend(f"game {game_pk}: {w}" for w in snap["warnings"])

    stats["games_with_changes"] += 1
    return build_records_for_changes(changes, prev, snap, now_iso, report_changes)


def _games_in_window(days: int) -> tuple[list[dict], list[str]]:
    """Fetch the schedule for the lookback window. Returns (games, errors)."""
    today = datetime.now(timezone.utc).date()
    start = (today - timedelta(days=days)).isoformat()
    end = today.isoformat()
    url = config.SCHEDULE_URL.format(start=start, end=end)
    try:
        schedule = httpclient.fetch_json(url)
        return _parse_final_games(schedule), []
    except httpclient.SourceError as exc:
        return [], [f"schedule fetch failed: {exc}"]


def update(days: int | None = None, max_games: int | None = None,
           force_rebaseline: bool = False) -> dict:
    """Run one monitor cycle. Returns a stats dict."""
    now_iso = utcnow_iso()
    days = days if days is not None else config.DEFAULT_LOOKBACK_DAYS
    stats = {"ran_at": now_iso, "baselined": 0, "rebaselined": 0, "unchanged": 0,
             "games_with_changes": 0, "records_created": 0, "records_updated": 0,
             "fetch_errors": 0, "errors": [], "warnings": [], "games_checked": []}

    games, errors = _games_in_window(days)
    stats["errors"].extend(errors)

    # Also re-check games already in the snapshot store that are still inside the
    # postgame correction window (catches corrections days after final).
    seen_pks = {g["game_pk"] for g in games}
    extra_pks = []
    for pk in store.list_snapshot_pks():
        if pk in seen_pks:
            continue
        snap = store.load_snapshot(pk)
        game_date_str = ((snap or {}).get("game") or {}).get("date")
        try:
            game_date = datetime.strptime(game_date_str, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            continue
        if (datetime.now(timezone.utc).date() - game_date).days <= config.STABLE_DAYS:
            extra_pks.append(pk)

    db = store.load_discrepancies()
    new_alerts: list[dict] = []

    work: list[int] = [g["game_pk"] for g in games if g.get("game_pk")]
    work.extend(extra_pks)
    if max_games:
        work = work[:max_games]

    for game_pk in work:
        records = process_game(game_pk, now_iso, stats, force_rebaseline)
        stats["games_checked"].append(game_pk)
        for record in records:
            # Schema-drift guard: a record that fails our own charter rules is
            # NEVER written. Surface it as an alert for human review instead.
            record_errors = validate.validate_record(record)
            if record_errors:
                stats["warnings"].append(
                    f"game {game_pk}: blocked invalid record {record.get('id')}: "
                    + "; ".join(record_errors[:5]))
                new_alerts.append(alerts_mod.make_alert(
                    "schema_drift",
                    f"Record blocked by validation for game {game_pk}",
                    "The monitor detected a change but could not build a record that "
                    "satisfies the data charter (both states + evidence). Blocked "
                    "errors:\n" + "\n".join(record_errors),
                    severity="warn", now_iso=now_iso))
                continue
            outcome = store.upsert_record(db, record, now_iso)
            if outcome == "created":
                stats["records_created"] += 1
                title, body = alerts_mod.describe_record(record)
                new_alerts.append(alerts_mod.make_alert(
                    "discrepancy_new", title, body, record_id=record["id"],
                    links=[e.get("url") for e in record.get("evidence", []) if e.get("url")],
                    now_iso=now_iso))
            elif outcome == "updated":
                stats["records_updated"] += 1
                title, body = alerts_mod.describe_record(record)
                new_alerts.append(alerts_mod.make_alert(
                    "discrepancy_updated", "UPDATED: " + title, body,
                    record_id=record["id"],
                    links=[e.get("url") for e in record.get("evidence", []) if e.get("url")],
                    now_iso=now_iso))
        time.sleep(config.REQUEST_DELAY_SECONDS)

    db["generated_at"] = now_iso
    db["generator"] = f"ScoringDiscrepNHL pipeline (monitor.update)"
    store.save_discrepancies(db)

    added = alerts_mod.append_alerts(new_alerts, now_iso)
    for alert in added:
        alerts_mod.queue_issue(alert, now_iso)

    if errors and not work:
        degraded = alerts_mod.make_alert(
            "monitor_degraded", "Monitor cycle degraded: official sources unreachable",
            "\n".join(errors), severity="warn", now_iso=now_iso)
        degraded_added = alerts_mod.append_alerts([degraded], now_iso)
        added = added + degraded_added

    stats["alerts_emitted"] = len(added)
    return stats
