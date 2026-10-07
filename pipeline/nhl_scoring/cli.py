"""Command line entry point.

    python -m nhl_scoring.cli scan   --games 2000020001,2026020001 --out out/findings.json
    python -m nhl_scoring.cli snap   --date 2026-10-07 --live
    python -m nhl_scoring.cli merge  --findings out/findings.json
    python -m nhl_scoring.cli alerts --write
    python -m nhl_scoring.cli site            # writes index.html/app.js/styles.css/data.js at the repo root
    python -m nhl_scoring.cli probe   --out docs/source-probe.json
    python -m nhl_scoring.cli situation-room --mode incremental --apply

Nothing here writes to ``data/discrepancies.json`` unless you pass ``--apply``,
so a scan is always reviewable before it becomes part of the database.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import __version__, alerts as alerts_mod, db as db_mod, site as site_mod
from .notify import DEFAULT_REPO as notify_DEFAULT_REPO
from . import situation_room as sr_mod
from .checks import check_record, compare_sources
from .fetch import FetchResult, Fetcher, utcnow
from .parsers import parse_api_landing, parse_api_right_rail, parse_gs_report
from .snapshot import build_digest, find_temporal_findings, record_snapshot, read_snapshots
from .sources import GameRef, date_score_url, date_schedule_url

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_id() -> str:
    return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{__version__}"


def _load_game_ids(args: argparse.Namespace) -> List[str]:
    ids: List[str] = []
    if getattr(args, "games", None):
        ids += [g.strip() for g in re.split(r"[,\s]+", args.games) if g.strip()]
    if getattr(args, "games_file", None) and os.path.exists(args.games_file):
        with open(args.games_file, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.split("#", 1)[0].strip()
                if line:
                    ids.append(line)
    out: List[str] = []
    for gid in ids:
        if re.fullmatch(r"\d{10}", gid):
            out.append(gid)
        else:
            print(f"skipping {gid!r}: not a 10-digit game id", file=sys.stderr)
    seen, uniq = set(), []
    for gid in out:
        if gid not in seen:
            seen.add(gid)
            uniq.append(gid)
    return uniq


# --------------------------------------------------------------------------
def _fixture_pair(fixture_dir: str, gid: str):
    """Locate local GS/JSON artifacts for one game id, for offline scans.

    Fixture mode exists so the CLI is testable without a network (and so a
    reviewer can re-run the exact scan that produced a record). URLs are still
    reported as the official ones, because the *claim* is about the official
    document; the result is marked ``from_cache`` and the note says where the
    bytes came from. Provenance is never faked into "fetched live".
    """
    import datetime as _dt
    import hashlib
    import json as _json

    names = sorted(os.listdir(fixture_dir))
    gs_name = next((n for n in names
                    if gid in n and "gs" in n.lower() and n.lower().endswith((".htm", ".html"))), None)
    api_name = next((n for n in names
                     if gid in n and "api_landing" in n and n.lower().endswith(".json")), None)
    if not gs_name or not api_name:
        return None, None, None, None

    def _load(name):
        path = os.path.join(fixture_dir, name)
        with open(path, "rb") as fh:
            raw = fh.read()
        stamp = _dt.datetime.utcfromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return raw, path, stamp, hashlib.sha256(raw).hexdigest()

    api_raw, api_path, api_stamp, api_sha = _load(api_name)
    gs_raw, gs_path, gs_stamp, gs_sha = _load(gs_name)
    ref = GameRef(gid)
    try:
        landing = _json.loads(api_raw.decode("utf-8-sig"))
    except ValueError as exc:
        return None, None, None, {"error": f"fixture json invalid: {exc}"}
    markup = gs_raw.decode("latin-1", errors="replace")
    res_l = FetchResult(url=ref.gamecenter_landing, ok=True, status=200, retrieved_at=api_stamp,
                        sha256=api_sha, path=api_path, from_cache=True)
    res_g = FetchResult(url=ref.report_url("GS"), ok=True, status=200, retrieved_at=gs_stamp,
                        sha256=gs_sha, path=gs_path, from_cache=True)
    res_l.error = f"fixture:{api_path}"
    res_g.error = f"fixture:{gs_path}"
    return landing, markup, res_l, res_g


def scan(args: argparse.Namespace) -> int:
    game_ids = _load_game_ids(args)
    if not game_ids:
        print("no game ids to scan", file=sys.stderr)
        return 2
    fetcher = Fetcher(cache_dir=args.cache, offline=args.offline, throttle_s=args.throttle)
    findings: List[Dict[str, Any]] = []
    coverage: List[Dict[str, Any]] = []
    for gid in game_ids:
        ref = GameRef(gid)
        entry: Dict[str, Any] = {"game_id": gid, "ok": False, "notes": []}
        rail_info: Dict[str, Any] = {}
        reports: Dict[str, str] = {}
        if getattr(args, "fixtures", None):
            landing, markup, res_l, res_g = _fixture_pair(args.fixtures, gid)
            if landing is None:
                note = (res_g or {}).get("error") if isinstance(res_g, dict) else None
                entry["notes"].append(note or "no fixture files for this game id")
                coverage.append(entry)
                continue
            reports = {"GS": res_g.url}
            entry["notes"].append("fixture mode: bytes read from local files, not fetched live")
            api_rec = parse_api_landing(landing, game_id=gid, url=res_l.url,
                                       retrieved_at=res_l.retrieved_at, sha256=res_l.sha256)
            gs_rec = parse_gs_report(markup, game_id=gid, url=res_g.url,
                                     retrieved_at=res_g.retrieved_at, sha256=res_g.sha256)
            records = [api_rec, gs_rec]
            game_block = _game_block(ref, landing, rail_info, reports)
            if not api_rec.parse_ok:
                entry["notes"].extend(api_rec.parse_notes or ["api parse failed"])
            if not gs_rec.parse_ok:
                entry["notes"].extend(gs_rec.parse_notes or ["gs parse failed"])
            found = []
            if all(r.parse_ok for r in records):
                found += compare_sources(gs_rec, api_rec)
            for rec in records:
                found += check_record(rec)
            entry["ok"] = all(r.parse_ok for r in records)
            entry["findings"] = len(found)
            entry["goal_counts"] = {r.source: r.goal_count for r in records}
            coverage.append(entry)
            for finding in found:
                findings.append(db_mod.record_from_finding(
                    finding.to_dict(), game=game_block,
                    artifacts=_artifacts(res_l, res_g, ref, reports),
                    detection={"tool_version": __version__, "run_id": _run_id(), "detected_at": _now()},
                    status="flagged", confidence="medium",
                ))
            if args.verbose:
                print(f"{gid}: {len(found)} findings (fixture mode)")
            continue
        landing, res_l = fetcher.get_json(ref.gamecenter_landing)
        entry["api"] = {"url": res_l.url, "status": res_l.status, "sha256": res_l.sha256,
                        "retrieved_at": res_l.retrieved_at, "error": res_l.error}
        if landing is None:
            entry["notes"].append(f"api landing fetch failed: {res_l.error}")
            coverage.append(entry)
            continue
        api_rec = parse_api_landing(landing, game_id=gid, url=res_l.url,
                                    retrieved_at=res_l.retrieved_at, sha256=res_l.sha256)
        rail, res_r = fetcher.get_json(ref.gamecenter_right_rail)
        if rail is not None:
            rail_info = parse_api_right_rail(rail, ref)
            reports = rail_info.get("reports") or {}
        else:
            entry["notes"].append("right-rail unavailable; using constructed report URL")
        gs_url = reports.get("GS") or ref.report_url("GS")
        markup, res_g = fetcher.get_text(gs_url)
        entry["gs"] = {"url": res_g.url, "status": res_g.status, "sha256": res_g.sha256,
                       "retrieved_at": res_g.retrieved_at, "error": res_g.error}
        game_block = _game_block(ref, landing, rail_info, reports)
        records = [api_rec]
        if markup is None:
            entry["notes"].append(f"GS report fetch failed: {res_g.error}")
        else:
            gs_rec = parse_gs_report(markup, game_id=gid, url=res_g.url,
                                     retrieved_at=res_g.retrieved_at, sha256=res_g.sha256)
            records.append(gs_rec)
            if not gs_rec.parse_ok:
                entry["notes"].extend(gs_rec.parse_notes or ["gs parse failed"])
        if not api_rec.parse_ok:
            entry["notes"].extend(api_rec.parse_notes or ["api parse failed"])
        found = []
        if len(records) == 2 and all(r.parse_ok for r in records):
            found += compare_sources(records[1], records[0])       # GS vs API
            found += _linescore_findings(records[0], rail_info, ref)
        for rec in records:
            found += check_record(rec)
        entry["ok"] = all(r.parse_ok for r in records) and len(records) == 2
        entry["findings"] = len(found)
        entry["goal_counts"] = {r.source: r.goal_count for r in records}
        coverage.append(entry)
        for finding in found:
            finding_dict = finding.to_dict()
            record = db_mod.record_from_finding(
                finding_dict, game=game_block,
                artifacts=_artifacts(res_l, res_g, ref, reports),
                detection={"tool_version": __version__, "run_id": _run_id(), "detected_at": _now()},
                status="flagged", confidence="medium",
            )
            findings.append(record)
        if args.verbose:
            print(f"{gid}: {len(found)} findings, goals api={api_rec.goal_count} "
                  f"gs={(records[1].goal_count if len(records) > 1 else 'n/a')}")
    payload = {
        "generated_at": _now(), "tool_version": __version__, "run_id": _run_id(),
        "games_requested": len(game_ids),
        "games_scanned": len(coverage),
        "games_parsed": sum(1 for c in coverage if c["ok"]),
        "games_unreadable": sum(1 for c in coverage if not c["ok"]),
        "finding_count": len(findings),
        "coverage": coverage,
        "records": findings,
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    print(f"scan: {len(game_ids)} games -> {len(findings)} findings -> {args.out}")
    print(f"     parsed by both sources: {payload['games_parsed']}, unreadable: {payload['games_unreadable']}")
    if args.apply:
        return merge(argparse.Namespace(db=args.db, findings=args.out, apply=True, dry_run=False))
    return 0


def _game_block(ref: GameRef, landing: Dict[str, Any], rail_info: Dict[str, Any],
                reports: Dict[str, str]) -> Dict[str, Any]:
    away, home = landing.get("awayTeam") or {}, landing.get("homeTeam") or {}
    return {
        "game_id": ref.game_id, "season": str(landing.get("season") or ref.season_dir),
        "game_type": ref.game_type, "date": landing.get("gameDate"),
        "away_team": away.get("abbrev"), "home_team": home.get("abbrev"),
        "venue": (landing.get("venue") or {}).get("default") if isinstance(landing.get("venue"), dict) else landing.get("venue"),
        "final_score": {"away": away.get("score"), "home": home.get("score")},
        "gamecenter_url": ref.gamecenter_page,
        "report_urls": reports or {code: ref.report_url(code) for code in ("GS", "ES", "PL")},
        "linescore": rail_info.get("by_period") or [],
    }


def _artifacts(res_l, res_g, ref: GameRef, reports: Dict[str, str]) -> List[Dict[str, Any]]:
    out = [{
        "label": "NHL Game Center JSON (summary.scoring)",
        "url": res_l.url, "kind": "official_api", "retrieved_at": res_l.retrieved_at,
        "sha256": res_l.sha256, "http_status": res_l.status, "evidence": "primary",
    }]
    if res_g.ok:
        out.append({
            "label": "NHL official Game Summary report (SCORING SUMMARY)",
            "url": res_g.url, "kind": "official_report", "retrieved_at": res_g.retrieved_at,
            "sha256": res_g.sha256, "http_status": res_g.status, "evidence": "primary",
        })
    else:
        out.append({
            "label": "NHL official Game Summary report - UNAVAILABLE at scan time",
            "url": res_g.url, "kind": "official_report", "retrieved_at": res_g.retrieved_at,
            "sha256": None, "http_status": res_g.status, "evidence": "none",
            "note": f"fetch failed: {res_g.error}",
        })
    out.append({"label": "Game Center page (human view)", "url": ref.gamecenter_page,
                "kind": "official_page", "retrieved_at": "", "sha256": None, "evidence": "primary"})
    return out


def _linescore_findings(api_rec, rail_info: Dict[str, Any], ref: GameRef) -> List[Any]:
    """API goal list vs the league's own per-period line score."""
    from .checks import Finding
    out = []
    by_period = rail_info.get("by_period") or []
    if not by_period or api_rec.away_abbrev is None:
        return out
    for row in by_period:
        period = row.get("period")
        for side, abbrev, recorded in (("away", api_rec.away_abbrev, row.get("away")),
                                       ("home", api_rec.home_abbrev, row.get("home"))):
            counted = sum(1 for g in api_rec.goals if g.period == period and g.team == abbrev)
            if recorded is not None and counted != recorded:
                out.append(Finding(
                    "C2", ref.game_id, field="period_total", period=period, team=abbrev,
                    detail=(f"api linescore says {abbrev} scored {recorded} in period {period}, "
                            f"api goal list has {counted}"),
                    left={"linescore": recorded, "goal_list": counted},
                    evidence=[{"url": ref.gamecenter_right_rail, "source": "nhl_api_right_rail",
                               "note": "linescore.byPeriod"},
                              {"url": api_rec.url, "source": api_rec.source}]))
    return out


# --------------------------------------------------------------------------
def snap(args: argparse.Namespace) -> int:
    """Poll the live endpoints for a date and append state-change digests."""
    fetcher = Fetcher(cache_dir=args.cache, offline=args.offline, throttle_s=args.throttle)
    dates = [args.date] if args.date else []
    if args.games:
        for gid in _load_game_ids(args):
            ref = GameRef(gid)
            landing, res = fetcher.get_json(ref.gamecenter_landing)
            if landing is None:
                print(f"{gid}: fetch failed {res.error}", file=sys.stderr)
                continue
            rec = parse_api_landing(landing, game_id=gid, url=res.url,
                                    retrieved_at=res.retrieved_at, sha256=res.sha256)
            state = landing.get("gameState") or ""
            clock = ((landing.get("clock") or {}).get("timeRemaining")) or ""
            period = ((landing.get("periodDescriptor") or {}).get("number"))
            result = record_snapshot(rec, root=args.snapshot_dir, game_state=state,
                                     period=period, clock=clock, captured_at=res.retrieved_at)
            print(f"{gid}: {result['reason']} (states={result['prior_states'] + (1 if result['written'] else 0)})")
        return 0
    written = 0
    for date_iso in dates:
        score, res = fetcher.get_json(date_score_url(date_iso))
        if score is None:
            print(f"{date_iso}: score fetch failed {res.error}", file=sys.stderr)
            continue
        for game in score.get("games") or []:
            gid = str(game.get("id"))
            ref = GameRef(gid)
            landing, res2 = fetcher.get_json(ref.gamecenter_landing)
            if landing is None:
                print(f"{gid}: landing fetch failed {res2.error}", file=sys.stderr)
                continue
            rec = parse_api_landing(landing, game_id=gid, url=res2.url,
                                    retrieved_at=res2.retrieved_at, sha256=res2.sha256)
            state = game.get("gameState") or landing.get("gameState") or ""
            period = (landing.get("periodDescriptor") or {}).get("number")
            clock = (landing.get("clock") or {}).get("timeRemaining") or ""
            out = record_snapshot(rec, root=args.snapshot_dir, game_state=state, period=period,
                                  clock=clock, captured_at=res2.retrieved_at)
            written += 1 if out["written"] else 0
            print(f"{gid} [{state}]: {out['reason']}")
    print(f"snap: {len(dates)} date(s), {written} state-change digests written to {args.snapshot_dir}")
    return 0


def snapfind(args: argparse.Namespace) -> int:
    """Turn accumulated snapshot history into findings."""
    game_ids = [args.game] if args.game else None
    if not game_ids:
        from .snapshot import all_snapshot_games
        game_ids = all_snapshot_games(args.snapshot_dir)
    found: List[Dict[str, Any]] = []
    for gid in game_ids or []:
        for finding in find_temporal_findings(gid, root=args.snapshot_dir):
            snaps = read_snapshots(gid, args.snapshot_dir)
            game = {"game_id": gid, "date": (snaps[0].get("captured_at") or "")[:10] if snaps else None,
                    "season": GameRef(gid).season_dir, "game_type": GameRef(gid).game_type,
                    "away_team": None, "home_team": None,
                    "gamecenter_url": GameRef(gid).gamecenter_page,
                    "report_urls": {}}
            # A temporal finding is a machine observation about our own captures.
            # It never self-promotes to "verified": validate() requires a reader who
            # opened the official artifact, and that is deliberately a human (or an
            # agent in an interactive session) decision, not this command's.
            artifacts = []
            for entry in (finding.evidence or []):
                url = entry.get("url") or GameRef(gid).gamecenter_landing
                if not url.startswith("https://"):
                    url = GameRef(gid).gamecenter_landing
                artifacts.append({"label": f"{entry.get('source') or 'snapshot'} digest",
                                  "url": url, "kind": "snapshot", "evidence": "primary",
                                  "retrieved_at": entry.get("retrieved_at"),
                                  "sha256": entry.get("sha256"),
                                  "note": "captured by this project, not by the league"})
            found.append(db_mod.record_from_finding(
                finding.to_dict(), game=game, artifacts=artifacts,
                detection={"tool_version": __version__, "run_id": _run_id(), "detected_at": _now(),
                           "when_corrected": _when_corrected(snaps, finding)},
                status="flagged", confidence="high",
            ))
    out = {"generated_at": _now(), "record_count": len(found), "records": found}
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)
    print(f"snapfind: {len(found)} temporal findings across {len(game_ids or [])} games -> {args.out}")
    return 0


def _when_corrected(snaps: List[Dict[str, Any]], finding) -> str:
    """Classify when a change happened from the states we captured."""
    states = [s.get("game_state") for s in snaps]
    if "LIVE" in states:
        return "in_game"
    if "FINAL" in states or "OFF" in states:
        return "postgame"
    return "unknown"


# --------------------------------------------------------------------------
def merge(args: argparse.Namespace) -> int:
    payload = _read_findings(args)
    if payload is None:
        return 2
    incoming = payload.get("records") or []
    errors: Dict[str, List[str]] = {}
    for record in incoming:
        problems = db_mod.validate(record)
        if problems:
            errors[record.get("record_id", "?")] = problems
    if errors and args.strict:
        print(f"{len(errors)} record(s) failed validation:", file=sys.stderr)
        for rid, problems in list(errors.items())[:20]:
            print(f"  {rid}: {'; '.join(problems)}", file=sys.stderr)
        return 1
    if args.dry_run or not args.apply:
        print(f"merge: {len(incoming)} incoming records, {len(errors)} with validation warnings "
              f"(dry run - pass --apply to write)")
        return 0
    existing_payload = db_mod.load_db(args.db) if os.path.exists(args.db) else {"records": []}
    merged, stats = db_mod.upsert(existing_payload.get("records", []), incoming)
    db_mod.save_db({"schema_version": existing_payload.get("schema_version", "1.0"), "records": merged}, args.db)
    csv_path = os.path.join(os.path.dirname(args.db) or ".", "discrepancies.csv")
    count = db_mod.write_csv(merged, csv_path)
    print(f"merge: {stats} -> {args.db} ({len(merged)} records) and {csv_path} ({count} rows)")
    return 0


def _read_findings(args: argparse.Namespace) -> Optional[Dict[str, Any]]:
    if not args.findings or not os.path.exists(args.findings):
        print(f"findings file not found: {args.findings}", file=sys.stderr)
        return None
    with open(args.findings, "r", encoding="utf-8") as fh:
        return json.load(fh)


def validate_cmd(args: argparse.Namespace) -> int:
    payload = db_mod.load_db(args.db)
    bad = 0
    for record in payload.get("records", []):
        problems = db_mod.validate(record)
        if problems:
            bad += 1
            print(f"{record.get('record_id')}:")
            for problem in problems:
                print(f"   - {problem}")
    print(f"validate: {len(payload.get('records', []))} records, {bad} invalid")
    return 1 if bad else 0


def alerts_cmd(args: argparse.Namespace) -> int:
    payload = db_mod.load_db(args.db)
    triaged = alerts_mod.triage(payload.get("records", []))
    since = args.since
    if getattr(args, "recent_days", None):
        # Backfills create hundreds of historical records in one run. Alerts are
        # for what is new to a subscriber, so the digest is bounded by game date.
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(days=args.recent_days)).strftime("%Y-%m-%d")
        since = max(since or "", cutoff)
    if since:
        triaged = [t for t in triaged
                   if ((t["record"].get("game") or {}).get("date") or "") >= since]
    print(f"alerts: {len(triaged)} alert(s)")
    for item in triaged[: args.limit]:
        game = item["record"].get("game") or {}
        disc = item["record"].get("discrepancy") or {}
        print(f"  [{item['level']:9}] {game.get('date')} {game.get('away_team')}@{game.get('home_team')} "
              f"{disc.get('change_type')} - {(disc.get('summary') or '')[:90]}")
    if args.write:
        out = alerts_mod.write_alerts(triaged, args.out_dir, date_str=_now()[:10], run_id=_run_id())
        print(f"alerts: wrote {out}")
        # The published site reads data/alerts.json, not the date-stamped digest, so
        # every alert this engine raises is projected there too. Without this the
        # Alerts tab stays on "No alerts yet" however many alerts exist.
        feed = alerts_mod.write_site_feed(triaged, REPO_ROOT, now=_now())
        print(f"alerts: site feed -> {feed['json']} ({feed['count']} alerts) + {feed['rss']}")
    if args.webhook:
        import urllib.request
        body = json.dumps(alerts_mod.webhook_payload(triaged)).encode("utf-8")
        req = urllib.request.Request(args.webhook, data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                print(f"alerts: webhook -> HTTP {resp.getcode()}")
        except Exception as exc:
            print(f"alerts: webhook failed: {exc}", file=sys.stderr)
            return 1
    return 0


def notify_cmd(args: argparse.Namespace) -> int:
    """Deliver the alerts that are new since the last delivery.

    This is the step that turns detection into a notification. It reads the
    *published* feed (``data/alerts.json``) so what a subscriber receives is
    always what the website shows, consults ``data/notifications_state.json`` so
    an unchanged alert is never sent twice, and writes a report next to the data
    so a notification outage is visible in git rather than silent.
    """
    from . import notify as notify_mod

    if args.describe:
        print(json.dumps(notify_mod.describe_channels(), indent=2, ensure_ascii=False))
        return 0

    alerts, meta = notify_mod.read_feed(args.feed)
    if meta.get("error"):
        print(f"notify: cannot read the alert feed {args.feed}: {meta['error']}", file=sys.stderr)
        return 1
    state = notify_mod.load_state(args.state)
    now = _now()
    run_label = args.run_label or os.environ.get("GITHUB_RUN_ID") or f"manual-{now}"
    channels = [c.strip() for c in (args.channels or "").split(",") if c.strip()]
    unknown = [c for c in channels if c not in notify_mod.CHANNELS]
    if unknown:
        print(f"notify: unknown channel(s) {', '.join(unknown)}; known: {', '.join(notify_mod.CHANNELS)}",
              file=sys.stderr)
        return 2

    if args.prime:
        count = notify_mod.prime(alerts, state, now=now, channel="feed")
        if not args.dry_run:
            notify_mod.save_state(args.state, state)
        print(f"notify: primed {count} alert(s) from the committed feed "
              f"({'dry run - state not written' if args.dry_run else args.state})")
        return 0

    if not alerts:
        print(f"notify: the alert feed {args.feed} is empty - nothing to deliver "
              "(the feed is written by: nhl_scoring.cli alerts --write)")
        return 0

    parts = notify_mod.partition(alerts, state)
    # --all re-delivers the whole feed (used to re-announce after a channel is
    # fixed); the normal path is new + revised alerts only.
    pending = alerts if args.all else parts["new"] + parts["updated"]
    print(f"notify: feed has {len(alerts)} alert(s) - {len(parts['new'])} new, "
          f"{len(parts['updated'])} updated, {len(parts['unchanged'])} already delivered")
    report = notify_mod.deliver(
        pending, state=state, channels=channels,
        updated_ids=[a.get("id") for a in parts["updated"]],
        now=now, run_label=run_label, repo=args.repo,
        token=args.token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "",
        webhook_url=args.webhook or os.environ.get("SDN_WEBHOOK_URL") or os.environ.get("SDN_WEBHOOK") or "",
        smtp_config={"host": os.environ.get("SDN_SMTP_HOST", ""),
                     "port": os.environ.get("SDN_SMTP_PORT", "587"),
                     "user": os.environ.get("SDN_SMTP_USER", ""),
                     "password": os.environ.get("SDN_SMTP_PASSWORD", ""),
                     "from": os.environ.get("SDN_SMTP_FROM", ""),
                     "to": os.environ.get("SDN_SMTP_TO", "")},
        dry_run=args.dry_run, max_issues=args.max_issues,
        unchanged=0 if args.all else len(parts["unchanged"]), min_severity=args.min_severity)
    report["feed"] = meta
    report["state_path"] = args.state
    for delivery in report["deliveries"]:
        print(f"  [{delivery['channel']:8}] {delivery['status']:8} "
              f"{len(delivery['alert_ids'])} alert(s) -> {delivery['target']}"
              + (f" ({delivery['url']})" if delivery.get("url") else "")
              + (f" - {delivery['error']}" if delivery.get("error") else ""))
    if not args.dry_run:
        notify_mod.save_state(args.state, state)
        os.makedirs(os.path.dirname(args.report) or ".", exist_ok=True)
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        print(f"notify: report -> {args.report}; state -> {args.state}")
    else:
        print("notify: dry run - no state written, nothing sent")
    if report["failed_channels"] and not args.allow_failure:
        print(f"notify: delivery failed on {', '.join(sorted(set(report['failed_channels'])))}",
              file=sys.stderr)
        return 1
    if report["failed_channels"]:
        print(f"notify: WARNING delivery failed on {', '.join(sorted(set(report['failed_channels'])))} "
              "(--allow-failure: continuing)")
    return 0


def site_cmd(args: argparse.Namespace) -> int:
    result = site_mod.build(args.out, db_path=args.db, repo_root=REPO_ROOT,
                            coverage_path=args.coverage)
    print(f"site: wrote {len(result)} files to {args.out}")
    return 0


def probe_cmd(args: argparse.Namespace) -> int:
    """Re-verify the coverage/availability claims this repo makes about sources.

    Every documented claim about what does or does not exist is derived from a
    live probe here rather than from memory, so the claim can rot visibly.
    """
    fetcher = Fetcher(cache_dir=args.cache, offline=args.offline, throttle_s=0.35)
    probes = [
        ("api_landing_1999_2000", GameRef("1999020001").gamecenter_landing, 200),
        ("api_landing_1998_1999", GameRef("1998020001").gamecenter_landing, None),
        ("gs_report_2000_01", GameRef("2000020001").report_url("GS"), 200),
        ("gs_report_1999_00", GameRef("1999020001").report_url("GS"), 404),
        ("gs_report_1994_95", GameRef("1994020001").report_url("GS"), 404),
        ("pl_report_2000_01", GameRef("2000020001").report_url("PL"), 200),
        ("gs_report_current_opener", GameRef("2026020001").report_url("GS"), 200),
        ("right_rail_reports", GameRef("2026020001").gamecenter_right_rail, 200),
        ("no_correction_feed_v1", "https://api-web.nhle.com/v1/corrections", 404),
        ("no_correction_feed_v2", "https://api-web.nhle.com/v1/gamecenter/2026020001/situations", 404),
        # api-web has no Situation Room endpoint - but that is NOT "no feed": the
        # official statements ARE published, as tagged stories on the league
        # content API (verified 2026-10-07; see situation_room.py / docs/SITUATION_ROOM.md).
        ("api_web_has_no_situation_room_endpoint", "https://api-web.nhle.com/v1/situation-room", 404),
        ("situation_room_feed", "https://forge-dapi.d3.nhle.com/v2/content/en-us/stories?tags.slug=situation-room&$limit=1", 200),
    ]
    results = []
    for name, url, expect in probes:
        res = fetcher.get_bytes(url)
        results.append({"probe": name, "url": url, "status": res.status, "ok": res.ok,
                        "expected_any_of": expect if isinstance(expect, list) else expect,
                        "sha256": res.sha256, "bytes": None, "error": res.error,
                        "probed_at": utcnow()})
        print(f"  {res.status}  {name}")
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"probed_at": utcnow(), "tool_version": __version__, "probes": results},
                  fh, indent=2, ensure_ascii=False)
    print(f"probe: wrote {args.out}")
    return 0


def situation_room_cmd(args: argparse.Namespace) -> int:
    """Ingest the official Situation Room feed into the ledger and the database."""
    fetcher = Fetcher(cache_dir=args.cache, offline=args.offline, throttle_s=args.throttle)
    result = sr_mod.ingest(
        fetcher, ledger_path=args.ledger, mode=args.mode, max_pages=args.max_pages,
        page_size=args.page_size, start_skip=args.start_skip, crosscheck=not args.no_crosscheck,
        max_crosscheck=args.max_crosscheck, run_id=_run_id(), verbose=args.verbose,
        resolve_ids=not args.no_resolve_ids,
    )
    stats, records = result["stats"], result["records"]
    summary = result["summary"]
    print(f"situation-room: {stats}")
    print(f"situation-room: ledger {summary['rulings']} rulings "
          f"{summary['earliest_statement']} -> {summary['latest_statement']}; outcomes {summary['by_outcome']}; "
          f"cross-check {summary['overturned_crosscheck']}")
    payload = {"generated_at": _now(), "tool_version": __version__, "run_id": _run_id(),
               "source": "situation_room", "record_count": len(records), "records": records}
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    print(f"situation-room: {len(records)} record(s) for overturned rulings -> {args.out}")
    bad = {r["record_id"]: db_mod.validate(r) for r in records if db_mod.validate(r)}
    if bad:
        print(f"situation-room: {len(bad)} record(s) failed validation; not merged", file=sys.stderr)
        for rid, problems in list(bad.items())[:10]:
            print(f"  {rid}: {'; '.join(problems)}", file=sys.stderr)
        return 1
    if args.apply:
        existing = db_mod.load_db(args.db) if os.path.exists(args.db) else {"records": []}
        merged, mstats = db_mod.upsert(existing.get("records", []), records)
        retired = sr_mod.retire_stale_records(merged, result.get("stale") or [])
        mstats["retired_stale"] = retired
        db_mod.save_db({"schema_version": existing.get("schema_version", "1.0"), "records": merged}, args.db)
        csv_path = os.path.join(os.path.dirname(args.db) or ".", "discrepancies.csv")
        count = db_mod.write_csv(merged, csv_path)
        print(f"situation-room: merge {mstats} -> {args.db} ({len(merged)} records), {csv_path} ({count} rows)")
    else:
        print("situation-room: dry run - pass --apply to merge into the database")
    return 0


# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="nhl_scoring", description="NHL scoring discrepancy detector")
    p.add_argument("--cache", default=os.environ.get("SDN_CACHE", "cache/raw"))
    p.add_argument("--throttle", type=float, default=float(os.environ.get("SDN_THROTTLE", "0.25")))
    p.add_argument("--offline", action="store_true", help="never touch the network (fixtures only)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="cross-source + integrity scan of specific games")
    s.add_argument("--games", help="comma/space separated 10-digit game ids")
    s.add_argument("--games-file")
    s.add_argument("--out", default="out/findings.json")
    s.add_argument("--db", default=os.path.join(REPO_ROOT, "data", "discrepancies.json"))
    s.add_argument("--apply", action="store_true", help="merge straight into the database")
    s.add_argument("--verbose", action="store_true")
    s.add_argument("--fixtures", help="directory of local artifacts named *<game_id>*gs*.htm "
                                      "and *<game_id>*api_landing*.json; skips the network")
    s.set_defaults(func=scan)

    s = sub.add_parser("snap", help="poll live endpoints and record state digests")
    s.add_argument("--date", help="YYYY-MM-DD to poll the scoreboard for")
    s.add_argument("--games", help="specific game ids to poll")
    s.add_argument("--games-file")
    s.add_argument("--snapshot-dir", default=os.path.join(REPO_ROOT, "data", "snapshots"))
    s.set_defaults(func=snap)

    s = sub.add_parser("snapfind", help="derive findings from recorded snapshot history")
    s.add_argument("--game")
    s.add_argument("--snapshot-dir", default=os.path.join(REPO_ROOT, "data", "snapshots"))
    s.add_argument("--out", default="out/temporal.json")
    s.set_defaults(func=snapfind)

    s = sub.add_parser("merge", help="merge a findings payload into the database")
    s.add_argument("--findings", default="out/findings.json")
    s.add_argument("--db", default=os.path.join(REPO_ROOT, "data", "discrepancies.json"))
    s.add_argument("--apply", action="store_true")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--strict", action="store_true")
    s.set_defaults(func=merge)

    s = sub.add_parser("validate", help="validate the database against the schema rules")
    s.add_argument("--db", default=os.path.join(REPO_ROOT, "data", "discrepancies.json"))
    s.set_defaults(func=validate_cmd)

    s = sub.add_parser("alerts", help="render the alert set from the database")
    s.add_argument("--db", default=os.path.join(REPO_ROOT, "data", "discrepancies.json"))
    s.add_argument("--since", help="only alert on games on/after this date")
    s.add_argument("--recent-days", type=int, default=0,
                   help="only alert on games in the last N days (bounds backfill noise; 0 = no bound)")
    s.add_argument("--limit", type=int, default=25)
    s.add_argument("--write", action="store_true")
    s.add_argument("--out-dir", default=os.path.join(REPO_ROOT, "data", "alerts"))
    s.add_argument("--webhook", default=os.environ.get("SDN_WEBHOOK") or None)
    s.set_defaults(func=alerts_cmd)

    s = sub.add_parser("notify", help="deliver new alerts to subscribers (issue / webhook / email / feed)")
    s.add_argument("--feed", default=os.path.join(REPO_ROOT, "data", "alerts.json"),
                   help="the published alert feed to deliver from")
    s.add_argument("--state", default=os.path.join(REPO_ROOT, "data", "notifications_state.json"),
                   help="deliver-once state; committed so a schedule cannot re-send an old alert")
    s.add_argument("--report", default=os.path.join(REPO_ROOT, "data", "notifications", "last_run.json"),
                   help="delivery report written after a real run")
    s.add_argument("--channels", default="feed,issue,webhook,email",
                   help="comma-separated subset of " + ",".join(("feed", "issue", "webhook", "email")))
    s.add_argument("--min-severity", choices=("high", "medium", "low"), default="low",
                   help="drop everything below this severity (high = goal-total changes only)")
    s.add_argument("--max-issues", type=int, default=10,
                   help="cap on per-alert issues per run; the rest go into one digest")
    s.add_argument("--all", action="store_true", help="re-deliver the whole feed, not just what is new")
    s.add_argument("--prime", action="store_true",
                   help="mark the current feed as already delivered (switch-on helper; sends nothing)")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--allow-failure", action="store_true",
                   help="exit 0 even if a channel failed (the report still records it)")
    s.add_argument("--describe", action="store_true", help="print the channel table as JSON and exit")
    s.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY") or notify_DEFAULT_REPO)
    s.add_argument("--token", default="", help="defaults to $GITHUB_TOKEN / $GH_TOKEN")
    s.add_argument("--webhook", default="", help="defaults to $SDN_WEBHOOK_URL / $SDN_WEBHOOK")
    s.add_argument("--run-label", default="")
    s.set_defaults(func=notify_cmd)

    s = sub.add_parser("site", help="build the GitHub Pages site from the database (repo root = what Pages serves)")
    s.add_argument("--out", default=REPO_ROOT)
    s.add_argument("--db", default=os.path.join(REPO_ROOT, "data", "discrepancies.json"))
    s.add_argument("--coverage", default="out/findings.json")
    s.set_defaults(func=site_cmd)

    s = sub.add_parser("probe", help="re-verify documented source-availability claims")
    s.add_argument("--out", default=os.path.join(REPO_ROOT, "docs", "source-probe.json"))
    s.set_defaults(func=probe_cmd)

    s = sub.add_parser("situation-room", help="ingest the official NHL Situation Room statement feed")
    s.add_argument("--mode", choices=("incremental", "full", "reparse"), default="incremental",
                   help="incremental stops at the first page with nothing new; full walks --max-pages from --start-skip; "
                        "reparse re-runs the parser over the raw statements already in the ledger (no feed fetch)")
    s.add_argument("--max-pages", type=int, default=2)
    s.add_argument("--page-size", type=int, default=sr_mod.DEFAULT_PAGE_SIZE)
    s.add_argument("--start-skip", type=int, default=0)
    s.add_argument("--no-crosscheck", action="store_true", help="skip the play-by-play cross-check")
    s.add_argument("--max-crosscheck", type=int, default=150, help="play-by-play fetches allowed this run")
    s.add_argument("--no-resolve-ids", action="store_true", help="do not look up untagged statements on the scoreboard")
    s.add_argument("--ledger", default=os.path.join(REPO_ROOT, "data", "situation_room", "rulings.json"))
    s.add_argument("--db", default=os.path.join(REPO_ROOT, "data", "discrepancies.json"))
    s.add_argument("--out", default="out/situation_room_findings.json")
    s.add_argument("--apply", action="store_true", help="merge the records into the database")
    s.add_argument("--verbose", action="store_true")
    s.set_defaults(func=situation_room_cmd)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
