"""Command line interface.

    python -m nhl_monitor probe                       # verify every official endpoint
    python -m nhl_monitor collect --game-id 2023020001
    python -m nhl_monitor monitor --date 2026-10-07
    python -m nhl_monitor backfill-era --season 20052006 --start 1 --end 25
    python -m nhl_monitor backfill-archive --game-id 2023020001
    python -m nhl_monitor verify --record-id NHL-20232024-020001-01
    python -m nhl_monitor export-csv --out data/exports/discrepancies.csv
    python -m nhl_monitor coverage --from-season 1999 --to-season 2025
    python -m nhl_monitor sources

Reachability, layout validation and coverage measurement are separate on purpose:
`probe` answers "can I read the sources and does the parser still understand them?",
`coverage` answers "which seasons exist and which of them still preserve the original
record?". Both are safe to run at any time; neither writes records.

Every command prints a JSON summary and writes artifacts into ``data/`` so the
result is reproducible from git history alone.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from typing import Dict, List, Optional

from . import alerts as alerts_mod
from . import archive, classify, detect, sources, store
from .fetch import FetchError, http_get
from .parse import report_era


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


# ----------------------------------------------------------------------------- #
# probe
# ----------------------------------------------------------------------------- #

def cmd_probe(args) -> int:
    """Touch every official source and record what actually worked.

    'No manual input' also means: the system must be able to prove at any time
    which sources it can currently read. The result is written to
    data/reference/probe_report.json.
    """
    report: Dict[str, object] = {"probed_at_utc": store.utcnow(), "results": {}}
    checks = [
        ("api.pbp", sources.gamecenter_url("play-by-play", args.game_id)),
        ("api.boxscore", sources.gamecenter_url("boxscore", args.game_id)),
        ("doc.GS", sources.report_url(sources.season_folder(args.game_id), "GS",
                                      sources.split_game_id(args.game_id)["game_type"],
                                      sources.split_game_id(args.game_id)["game_no"])),
        ("doc.RO", sources.report_url(sources.season_folder(args.game_id), "RO",
                                      sources.split_game_id(args.game_id)["game_type"],
                                      sources.split_game_id(args.game_id)["game_no"])),
        ("archive.cdx", sources.cdx_query(sources.report_url(
            sources.season_folder(args.game_id), "GS",
            sources.split_game_id(args.game_id)["game_type"],
            sources.split_game_id(args.game_id)["game_no"]), limit=5)),
    ]
    ok = 0
    for key, url in checks:
        try:
            resp = http_get(url, timeout=args.timeout, retries=1,
                            expect_status=(200, 404, 429))
            report["results"][key] = {"ok": resp.status == 200, **resp.as_evidence()}
            ok += 1 if resp.status == 200 else 0
        except (FetchError, Exception) as exc:  # noqa: B014
            report["results"][key] = {"ok": False, "url": url,
                                      "error": f"{type(exc).__name__}: {exc}"}
    # Layout validation: parse the LIVE game summary and prove that the parser
    # understands the current report format. If the league changes the layout the
    # parser must fail loudly here instead of silently returning zero goals.
    gs_url = sources.report_url(sources.season_folder(args.game_id), "GS",
                                sources.split_game_id(args.game_id)["game_type"],
                                sources.split_game_id(args.game_id)["game_no"])
    try:
        from .fetch import get_text
        from .parse import parse_gs_report, report_era

        html, resp = get_text(gs_url, timeout=args.timeout, retries=1, expect_status=(200, 404))
        if resp.status == 200:
            st = parse_gs_report(html, url=gs_url, retrieved_at=resp.retrieved_at,
                                 game_id=args.game_id, season=sources.season_folder(args.game_id))
            frozen, era_note = report_era(st.game_date, st.report_generated_at)
            report["layout_validation"] = {
                "url": gs_url,
                "game_date": st.game_date,
                "report_generated_at": st.report_generated_at,
                "report_is_frozen_original": frozen,
                "era_note": era_note,
                "goals_parsed": len([g for g in st.goals if g.period_type != "SO"]),
                "parse_warnings": st.parse_warnings,
                "verdict": ("parser OK" if st.goals and not st.parse_warnings
                            else "PARSER NEEDS ATTENTION - do not trust unparsed documents"),
            }
        else:
            report["layout_validation"] = {"url": gs_url, "error": f"HTTP {resp.status}"}
    except Exception as exc:
        report["layout_validation"] = {"url": gs_url, "error": f"{type(exc).__name__}: {exc}"}

    report["sources_ok"] = ok
    report["sources_checked"] = len(checks)
    report["verdict"] = ("all sources reachable" if ok == len(checks) else
                         "one or more official sources were NOT reachable - records relying on "
                         "them must be flagged, not filled in")
    path = os.path.join(store.DATA_DIR, "reference", "probe_report.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(report, fh, indent=2)
        fh.write("\n")
    _print(report)
    return 0 if ok == len(checks) else 1


# ----------------------------------------------------------------------------- #
# collect / monitor
# ----------------------------------------------------------------------------- #

def cmd_collect(args) -> int:
    results = []
    for game_id in args.game_id:
        res = detect.collect_game(game_id, cache_dir=args.cache_dir, dry_run=args.dry_run)
        emitted = [alerts_mod.build_alert(r) for r in res.get("records", [])]
        if emitted and not args.dry_run:
            alerts_mod.write_alerts(emitted)
            if args.github_issue:
                for a in emitted:
                    res.setdefault("issues", []).append(
                        alerts_mod.open_github_issue(a["title"], a["body_markdown"], repo=args.repo))
        res["alerts"] = emitted
        results.append(res)
    _print({"command": "collect", "results": results})
    return 0


def cmd_monitor(args) -> int:
    """Poll the official score endpoint and update every game in the window.

    Intended to be run by a scheduler every 2-5 minutes during game hours. Each run
    appends to the evidence timeline, so the project keeps a timestamped log of what
    the official record said and when - which is the artifact needed to reason about
    a settlement dispute.
    """
    from .fetch import get_json
    from .parse import parse_api_score

    date = args.date or store.utcnow()[:10]
    url = f"{sources.API_WEB}/v1/score/{date}"
    payload, resp = get_json(url, cache_dir=args.cache_dir)
    games = parse_api_score(payload)
    selected = []
    for g in games:
        state = (g.get("state") or "").upper()
        if args.states and state not in args.states:
            continue
        selected.append(g)
    summary = {"command": "monitor", "date": date, "score_url": url,
               "retrieved_at": resp.retrieved_at, "games_seen": len(games),
               "games_selected": len(selected), "results": []}
    for g in selected:
        if not g.get("id"):
            continue
        res = detect.collect_game(int(g["id"]), cache_dir=args.cache_dir, dry_run=args.dry_run)
        emitted = [alerts_mod.build_alert(r) for r in res.get("records", [])]
        if emitted and not args.dry_run:
            alerts_mod.write_alerts(emitted)
            if args.github_issue:
                for a in emitted:
                    res.setdefault("issues", []).append(
                        alerts_mod.open_github_issue(a["title"], a["body_markdown"], repo=args.repo))
        res["alerts"] = emitted
        summary["results"].append(res)
    _print(summary)
    return 0


# ----------------------------------------------------------------------------- #
# backfill
# ----------------------------------------------------------------------------- #

def cmd_backfill_era(args) -> int:
    """Census method 1 - frozen-era documents vs the league's current database.

    For seasons where the official HTML report was generated at game time (verified
    for 2005-06 and 2016-17, see docs/LIMITATIONS.md), the live document preserves
    the ORIGINAL ruling while the GameCenter API returns the CURRENT record. Any
    semantic difference between them is a scoring change, with both states coming
    from official NHL artifacts.
    """
    season_start = int(args.season[:4])
    produced, skipped, errors = [], [], []
    for game_no in range(args.start, args.end + 1):
        game_id = int(f"{season_start}{args.game_type:02d}{game_no:04d}")
        try:
            gs_state, _ev = detect.fetch_gs(game_id, cache_dir=args.cache_dir)
        except FileNotFoundError as exc:
            skipped.append({"game_id": game_id, "reason": str(exc)})
            continue
        except Exception as exc:
            errors.append({"game_id": game_id, "error": f"{type(exc).__name__}: {exc}"})
            continue
        frozen, note = report_era(gs_state.game_date, gs_state.report_generated_at)
        if frozen is False:
            skipped.append({"game_id": game_id, "reason":
                            f"report is regenerated, not frozen - the original state is NOT "
                            f"recoverable from the live document ({note})"})
            continue
        try:
            api_state, ev = detect.fetch_pbp(game_id, cache_dir=args.cache_dir)
        except Exception as exc:
            errors.append({"game_id": game_id, "error": f"api: {type(exc).__name__}: {exc}"})
            continue
        # name-only comparison: the frozen HTML reports carry no player ids
        records = detect.build_records(
            gs_state, api_state,
            {"gs": {"url": gs_state.source_url, "http_status": 200,
                    "retrieved_at_utc": gs_state.retrieved_at},
             "pbp": ev},
            detection_mode="backfill_frozen_vs_api",
        )
        for rec in records:
            rec["evidence_status"] = "verified_two_official_states" if frozen else "incomplete"
            rec["flags"].append("initial_state_from_frozen_official_document")
            rec["timing"]["when"] = "postgame_after_publication"
            rec["timing"]["reasoning"] = (
                "The frozen document is the record as generated on game night; the API state was "
                "retrieved years later, so the change necessarily occurred after publication.")
            rec["settlement"] = classify.settlement_assessment(rec["change"], rec["timing"]["when"])
            rec["completeness"] = store.completeness(rec)
            store.upsert_record(rec)
        produced.append({"game_id": game_id, "frozen_note": note, "records": len(records),
                         "changes": [c.as_dict() for c in (detect.diff_states(gs_state, api_state))]})
    _print({"command": "backfill-era", "season": args.season,
            "games_examined": args.end - args.start + 1, "with_records": produced,
            "skipped": skipped, "errors": errors})
    return 0


def cmd_backfill_archive(args) -> int:
    """Census method 2 - archived snapshots of an official document.

    Uses the CDX digests to find out whether the document ever changed, then
    downloads the distinct versions so both states can be compared. Note the
    documented limitation: if every snapshot was taken *after* the correction, both
    versions look identical and the change is invisible to this method.
    """
    parts = sources.split_game_id(args.game_id)
    url = sources.report_url(sources.season_folder(args.game_id), args.kind.upper(),
                             parts["game_type"], parts["game_no"])
    snaps = archive.snapshots_for(url, cache_dir=args.cache_dir)
    versions = archive.described_versions(snaps)
    result = {"command": "backfill-archive", "url": url, "snapshots": [s.as_dict() for s in snaps],
              "distinct_content_versions": versions, "comparison": None}
    if len(versions) >= 2:
        result["comparison"] = "multiple content versions exist - fetch the oldest and newest "
        result["note"] = ("Run `collect`/`verify` for this game and diff the archived version "
                          "against the live document to produce both states.")
    else:
        result["note"] = ("Only one content version is archived. This does NOT prove no change "
                          "occurred: a snapshot taken after a correction shows the corrected state.")
    _print(result)
    return 0


# ----------------------------------------------------------------------------- #
# verify / export
# ----------------------------------------------------------------------------- #

def cmd_coverage(args) -> int:
    """Measure official-report coverage per season.

    Answers the two questions the brief demands be *determined*, not assumed:

    * from which season do official reports exist at all? (existence probe)
    * in which season did reports stop being regenerated, i.e. from which season is the
      live document no longer the original record? (footer timestamp probe)

    The result is written to data/reference/coverage_report.json and quoted by the site.
    """
    from .fetch import get_text
    from .parse import parse_gs_report, report_era

    rows = []
    for year in range(args.from_season, args.to_season + 1):
        folder = f"{year}{year + 1}"
        url = sources.report_url(folder, args.kind.upper(), args.game_type, args.game_no)
        row = {"season": folder, "url": url}
        try:
            html, resp = get_text(url, timeout=args.timeout, retries=1, expect_status=(200, 404))
        except Exception as exc:
            row.update({"available": None, "error": f"{type(exc).__name__}: {exc}"})
            rows.append(row)
            continue
        row["http_status"] = resp.status
        if resp.status != 200:
            row["available"] = False
            rows.append(row)
            continue
        st = parse_gs_report(html, url=url, retrieved_at=resp.retrieved_at,
                             season=folder)
        frozen, note = report_era(st.game_date, st.report_generated_at)
        row.update({
            "available": True,
            "game_date": st.game_date,
            "report_generated_at": st.report_generated_at,
            "report_is_frozen_original": frozen,
            "era_note": note,
            "goals_parsed": len([g for g in st.goals if g.period_type != "SO"]),
            "parse_warnings": st.parse_warnings,
        })
        rows.append(row)

    available = [r for r in rows if r.get("available")]
    frozen = [r for r in available if r.get("report_is_frozen_original") is True]
    regenerated = [r for r in available if r.get("report_is_frozen_original") is False]
    report = {
        "probed_at_utc": store.utcnow(),
        "kind": args.kind.upper(),
        "game_type": args.game_type,
        "game_no": args.game_no,
        "seasons": rows,
        "earliest_season_with_report": min((r["season"] for r in available), default=None),
        "latest_frozen_original_season": max((r["season"] for r in frozen), default=None),
        "earliest_regenerated_season": min((r["season"] for r in regenerated), default=None),
        "interpretation": (
            "In frozen seasons the live document preserves the ORIGINAL game-night ruling, so it "
            "can be diffed against the current database to recover scoring changes with both "
            "states official. From the earliest regenerated season onward the original bytes are "
            "overwritten and only archived snapshots can reveal what changed."),
        "caveats": [
            "One game per season is probed: a season is only reported as frozen if that game's "
            "footer timestamp is on the game's own date.",
            "A missing report for a mid-season game does not prove the season is absent - re-run "
            "with a different --game-no before drawing a conclusion.",
        ],
    }
    path = os.path.join(store.DATA_DIR, "reference", "coverage_report.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    _print(report)
    return 0


def cmd_ingest(args) -> int:
    """Turn curated case files from the inbox into records.

    This is the path for corrections the league announced itself, or that happened
    before monitoring started. Each case file is parsed, cross-checked against the
    league's statement, validated, and flagged - see src/nhl_monitor/ingest.py.
    """
    from . import ingest

    files = ingest.case_files(args.inbox)
    if not files:
        print(f"no case files found in {args.inbox}")
        return 0
    built = ingest.ingest_cases(args.inbox, path=args.records, dry_run=args.dry_run,
                               verbose=args.verbose)
    print(f"{len(built)} case file(s) processed"
          + (" (dry run - nothing written)" if args.dry_run else ""))
    flagged = 0
    for rec in built:
        if rec.get("flags"):
            print(f"  FLAGGED {rec['record_id']}: " + "; ".join(rec["flags"]))
            flagged += 1
    print(f"{flagged} record(s) carry review flags - flagged is not the same as wrong, "
          "it means a named part of the evidence is missing")
    return 0


def cmd_verify(args) -> int:
    records = store.load_records()
    target = [r for r in records if r.get("record_id") == args.record_id]
    if not target:
        _print({"error": f"record {args.record_id} not found", "records": len(records)})
        return 1
    record = target[0]
    game_id = int(record["game"]["game_id"])
    out = {"command": "verify", "record_id": args.record_id, "checks": []}
    try:
        state, ev = detect.fetch_pbp(game_id, cache_dir=args.cache_dir)
        out["checks"].append({"source": "api.pbp", **ev,
                              "reported_state": record["corrected_state"],
                              "current_official_state": [
                                  g.as_dict() for g in state.sorted_goals()
                                  if g.clock == record["event"].get("clock")]})
    except Exception as exc:
        out["checks"].append({"source": "api.pbp", "error": f"{type(exc).__name__}: {exc}"})
    try:
        gs_state, ev = detect.fetch_gs(game_id, cache_dir=args.cache_dir)
        frozen, note = report_era(gs_state.game_date, gs_state.report_generated_at)
        out["checks"].append({"source": "doc.GS", **ev, "report_generated_at":
                              gs_state.report_generated_at, "report_is_frozen": frozen,
                              "era_note": note,
                              "current_official_state": [
                                  g.as_dict() for g in gs_state.sorted_goals()
                                  if g.clock == record["event"].get("clock")]})
    except Exception as exc:
        out["checks"].append({"source": "doc.GS", "error": f"{type(exc).__name__}: {exc}"})
    out["verdict"] = ("re-verified against current official artifacts" if not
                      any("error" in c for c in out["checks"]) else
                      "at least one official source could not be re-read - keep the record flagged")
    _print(out)
    return 0


def cmd_export_csv(args) -> int:
    records = store.load_records()
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    cols = ["record_id", "status", "evidence_status", "game_id", "season", "date", "away", "home",
            "period", "period_type", "clock", "strength", "team", "discrepancy_type",
            "affects_goal_total", "attribution_only", "timing_when", "settlement_level",
            "initial_scorer", "corrected_scorer", "reason_category", "flags", "sources"]
    with open(args.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in records:
            g, ev, ch = r.get("game", {}), r.get("event", {}), r.get("change", {})
            w.writerow({
                "record_id": r.get("record_id"), "status": r.get("status"),
                "evidence_status": r.get("evidence_status"),
                "game_id": g.get("game_id"), "season": g.get("season"), "date": g.get("date"),
                "away": (g.get("away") or {}).get("abbrev"), "home": (g.get("home") or {}).get("abbrev"),
                "period": ev.get("period"), "period_type": ev.get("period_type"),
                "clock": ev.get("clock"), "strength": ev.get("strength"), "team": ev.get("team"),
                "discrepancy_type": ch.get("discrepancy_type"),
                "affects_goal_total": ch.get("affects_goal_total"),
                "attribution_only": ch.get("attribution_only"),
                "timing_when": r.get("timing", {}).get("when"),
                "settlement_level": r.get("settlement", {}).get("level"),
                "initial_scorer": ((r.get("initial_state") or {}).get("scorer") or {}).get("name"),
                "corrected_scorer": ((r.get("corrected_state") or {}).get("scorer") or {}).get("name"),
                "reason_category": r.get("reason", {}).get("category"),
                "flags": "|".join(r.get("flags", [])),
                "sources": " | ".join(s.get("url", "") for s in r.get("sources", [])),
            })
    _print({"command": "export-csv", "out": args.out, "records": len(records)})
    return 0


def cmd_sources(args) -> int:
    _print(sources.registry_as_dict())
    return 0


# ----------------------------------------------------------------------------- #
# parser
# ----------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="nhl_monitor", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cache-dir", default=os.environ.get("NHL_MONITOR_CACHE", ".cache"),
                   help="optional HTTP cache directory (git-ignored); omit for fresh reads")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("probe", help="verify every official source endpoint")
    sp.add_argument("--game-id", type=int, default=2023020001)
    sp.add_argument("--timeout", type=float, default=30.0)
    sp.set_defaults(func=cmd_probe)

    sc = sub.add_parser("collect", help="capture + diff one or more games")
    sc.add_argument("--game-id", type=int, action="append", required=True)
    sc.add_argument("--dry-run", action="store_true")
    sc.add_argument("--github-issue", action="store_true",
                    help="also open a GitHub issue for each detected record")
    sc.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    sc.set_defaults(func=cmd_collect)

    sm = sub.add_parser("monitor", help="poll the official score endpoint and collect the slate")
    sm.add_argument("--date", default=None)
    sm.add_argument("--states", nargs="*", default=None,
                    help="restrict to game states, e.g. LIVE CRIT OFF")
    sm.add_argument("--dry-run", action="store_true")
    sm.add_argument("--github-issue", action="store_true")
    sm.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    sm.set_defaults(func=cmd_monitor)

    sb = sub.add_parser("backfill-era", help="frozen-era document vs current database census")
    sb.add_argument("--season", required=True, help="e.g. 20052006")
    sb.add_argument("--game-type", type=int, default=2)
    sb.add_argument("--start", type=int, default=1)
    sb.add_argument("--end", type=int, default=25)
    sb.set_defaults(func=cmd_backfill_era)

    sa = sub.add_parser("backfill-archive", help="archived-snapshot census for one document")
    sa.add_argument("--game-id", type=int, required=True)
    sa.add_argument("--kind", default="GS")
    sa.set_defaults(func=cmd_backfill_archive)

    sco = sub.add_parser("coverage", help="measure per-season report availability and era")
    sco.add_argument("--from-season", type=int, default=1999)
    sco.add_argument("--to-season", type=int, default=2025)
    sco.add_argument("--kind", default="GS")
    sco.add_argument("--game-type", type=int, default=2)
    sco.add_argument("--game-no", type=int, default=1)
    sco.add_argument("--timeout", type=float, default=30.0)
    sco.set_defaults(func=cmd_coverage)

    si = sub.add_parser("ingest", help="build records from curated official-statement case files")
    si.add_argument("--inbox", default=os.path.join(store.DATA_DIR, "inbox", "statements"),
                    help="directory of case files (default: data/inbox/statements)")
    si.add_argument("--records", default=store.RECORDS_PATH)
    si.add_argument("--dry-run", action="store_true")
    si.add_argument("--verbose", action="store_true")
    si.set_defaults(func=cmd_ingest)

    sv = sub.add_parser("verify", help="re-check a stored record against current official sources")
    sv.add_argument("--record-id", required=True)
    sv.set_defaults(func=cmd_verify)

    se = sub.add_parser("export-csv", help="export the database to CSV")
    se.add_argument("--out", default="data/exports/discrepancies.csv")
    se.set_defaults(func=cmd_export_csv)

    sub.add_parser("sources", help="print the source registry with verification status").set_defaults(
        func=cmd_sources)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    cache_dir = getattr(args, "cache_dir", None)
    if cache_dir == ".cache" and not os.environ.get("NHL_MONITOR_USE_CACHE"):
        # never let a stale cache masquerade as a fresh official record
        args.cache_dir = None
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:  # pragma: no cover
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
