#!/usr/bin/env python3
"""Rebuild ``data/discrepancies.json`` from evidence, not from transcription.

The machine-detected record is produced by running the actual parser + detector
over the verbatim official fixtures, then stamping the verification block by
hand (a human/agent read both artifacts line by line on 2026-10-07). The two
current-season ruling changes are entered as *pending* records with the exact
call needed to resolve them, because we have secondary reporting but not the
official per-game artifact yet: this repository does not manufacture game ids.

Run:  python3 scripts/seed_records.py
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

from _path import fixture_json, fixture_text  # noqa: E402
from nhl_scoring import db as db_mod  # noqa: E402
from nhl_scoring.checks import compare_sources  # noqa: E402
from nhl_scoring.parsers import parse_api_landing, parse_gs_report  # noqa: E402

GS_URL_2000 = "https://www.nhl.com/scores/htmlreports/20002001/GS020001.HTM"
API_URL_2000 = "https://api-web.nhle.com/v1/gamecenter/2000020001/landing"


def cross_source_record() -> dict:
    gs = parse_gs_report(fixture_text("official_2000020001_gs.htm"), game_id="2000020001",
                         url=GS_URL_2000, retrieved_at="2026-10-07T04:36:00Z",
                         sha256="not-pinned-in-sandbox:re-fetch-to-hash")
    api = parse_api_landing(fixture_json("official_2000020001_api_landing_excerpt.json"),
                            game_id="2000020001", url=API_URL_2000,
                            retrieved_at="2026-10-07T04:36:00Z",
                            sha256="not-pinned-in-sandbox:re-fetch-to-hash")
    findings = compare_sources(gs, api)
    assert [f.check_id for f in findings] == ["C11"], [f.check_id for f in findings]
    game = {
        "game_id": "2000020001", "season": "20002001", "game_type": "REG", "date": "2000-10-04",
        "away_team": "COL", "home_team": "DAL", "venue": "Reunion Arena",
        "final_score": {"away": 2, "home": 2},
        "gamecenter_url": "https://www.nhl.com/gamecenter/2000020001",
        "report_urls": {"GS": GS_URL_2000,
                        "PL": "https://www.nhl.com/scores/htmlreports/20002001/PL020001.HTM",
                        "ES": "https://www.nhl.com/scores/htmlreports/20002001/ES020001.HTM"},
    }
    artifacts = [
        {"label": "Official NHL Game Summary, sheet GS020001.HTM (SCORING SUMMARY, goal 4)",
         "url": GS_URL_2000, "kind": "official_report", "evidence": "primary",
         "retrieved_at": "2026-10-07", "http_status": 200,
         "quote": "4 | 2 | 18:31 | COL | A. DEADMARSH (1) | C. DRURY (1) |  | 18 77 37 33 21 19 | "
                  "2 24 22 20 11 | PP",
         "note": "Report footer stamp 2000-10-04-22.14.20 - a single assist is credited on the sheet."},
        {"label": "Official NHL Game Center JSON, summary.scoring goal eventId 10060839",
         "url": API_URL_2000, "kind": "official_api", "evidence": "primary",
         "retrieved_at": "2026-10-07", "http_status": 200,
         "quote": '{"eventId":10060839,"strength":"pp","playerId":8459436,"firstName":{"default":"Adam"},'
                  '"lastName":{"default":"Deadmarsh"},"timeInPeriod":"18:31","assists":['
                  '{"playerId":8460562,"lastName":{"default":"Drury"},...},'
                  '{"playerId":8451101,"lastName":{"default":"Sakic"},...}]}',
         "note": "Two assists credited in the JSON record of the same goal."},
        {"label": "Game Center page (human view of the final box score)",
         "url": "https://www.nhl.com/gamecenter/col-vs-dal/2000/10/04/2000020001",
         "kind": "official_page", "evidence": "primary", "retrieved_at": ""},
    ]
    record = db_mod.record_from_finding(
        findings[0].to_dict(), game=game, artifacts=artifacts,
        detection={"tool_version": "0.4.0", "run_id": "seed-2026-10-07",
                   "detected_at": "2026-10-07T04:36:00Z", "when_corrected": "unknown"},
        status="verified", confidence="high",
        reason={
            "stated_by_league": False,
            "text": "No public correction notice exists for this game. The league's two official "
                    "renderings of the same goal disagree on the number of assists credited; which "
                    "one reflects the scorer's final decision cannot be established from public data "
                    "alone, because the JSON is edited in place while the sheet is a frozen post-game "
                    "artifact. The game itself ended 2-2 (OT, no further goals), so the discrepancy is "
                    "attribution-only and cannot move a goal total.",
            "rule_citation": "NHL Rule 78.2 (credits for goals and assists)",
            "needs_human_read": True,
        },
    )
    record["verification"].update({
        "verified_by": "line-by-line read of both official artifacts on 2026-10-07 (fixture excerpts "
                       "in tests/fixtures are transcribed verbatim from them)",
        "verified_at": "2026-10-07",
        "residual_uncertainty": "direction of the correction is unresolved; the conflict itself is not",
    })
    record["flags"] = sorted(set(record.get("flags", []) + [
        "which_artifact_is_final_unresolved",
        "pre_2007_no_video_or_clip_to_adjudicate",
    ]))
    record["notes"] = ("First record in this database. Found by the automated cross-source scan on the "
                       "same fixture pair that ships as the regression test, so the claim is "
                       "reproducible: python3 scripts/seed_records.py --print. Also worth noting as a "
                       "class: the sheet was generated 2000-10-04 22:14 and has apparently never been "
                       "regenerated, so 26 years of 'final' data still disagree with the JSON.")
    return record


def pending_ruling_change(*, record_seed, date, away, home, teams_note, detail, summary,
                          change_type, sources, reason_text, rule_citation, extra_flags,
                          market_game_total, total_changed, video_review=True, period=None,
                          clock=None, team=None, initial=None, corrected=None, notes=""):
    """A documented ruling change we have not yet tied to an official game artifact."""
    game_id = f"{record_seed}"
    record = {
        "record_id": db_mod.compute_record_id(game_id, "MANUAL", "goal_no_goal", f"{date}|{away}|{home}"),
        "schema_version": db_mod.SCHEMA_VERSION,
        "status": "pending_review",
        "confidence": "medium",
        "detected_by": "manual_research",
        "detection": {"check_id": "MANUAL", "rule": change_type,
                      "rule_label": "Ruling change reported; official per-game artifact not yet linked",
                      "severity": "high", "detected_at": "2026-10-07T05:00:00Z",
                      "run_id": "seed-2026-10-07", "tool_version": "0.4.0"},
        "game": {"game_id": game_id or None, "season": "20262027", "game_type": "REG", "date": date,
                 "away_team": away, "home_team": home, "venue": None,
                 "final_score": {"away": None, "home": None},
                 "gamecenter_url": None, "report_urls": {},
                 "teams_note": teams_note},
        "discrepancy": {"period": period, "clock": clock, "team": team, "field": "goal_no_goal",
                        "goal_key": None, "change_type": change_type, "summary": summary,
                        "detail": detail, "total_changed": total_changed,
                        "attribution_only": False, "goal_no_goal_change": True,
                        "video_review": video_review, "when_corrected": "in_game",
                        "timing_uncertain": False,
                        "market_impact": {
                            "total_changed": total_changed,
                            "affects_game_total": market_game_total,
                            "affects_period_total": market_game_total,
                            "affects_player_props": "yes",
                            "affects_result_markets": "possible" if market_game_total != "yes" else "yes",
                            "risk": "high",
                            "reason": "A goal that did not exist at one moment exists at the next, inside "
                                      "the same game: the number of goals a live game-total market is "
                                      "watching moved while the game was in progress.",
                            "rule_class": "total"},
                        "reason": {"stated_by_league": True, "text": reason_text,
                                   "rule_citation": rule_citation, "needs_human_read": True}},
        "initial_state": initial or {"artifact": "on-ice ruling", "goal_present": False,
                                     "ruling": "no_goal_on_ice", "scorer": None, "assists": [],
                                     "period": period, "clock": clock, "team": team},
        "corrected_state": corrected or {"artifact": "video review ruling", "goal_present": True,
                                         "ruling": "goal", "scorer": None, "assists": [],
                                         "period": period, "clock": clock, "team": team},
        "totals": {"initial_game_goals": None, "corrected_game_goals": None, "goal_delta": None,
                   "basis": "not yet read from an official artifact"},
        "sources": sources,
        "verification": {"status": "pending_review", "evidence_grade": "secondary",
                         "independently_checkable": True,
                         "check_instructions": "Resolve the game id with GET "
                         f"https://api-web.nhle.com/v1/score/{date} (match {away} at {home}), then "
                         "open gamecenter/{id}/landing and confirm the goal is present in "
                         "summary.scoring at the stated period and clock. Pull the GS/PL sheets from "
                         "right-rail gameReports for the frozen post-game rendering.",
                         "verified_by": "", "verified_at": ""},
        "flags": sorted(set(["requires_human_verification", "game_id_not_resolved",
                             "secondary_source_only"] + extra_flags)),
        "notes": notes,
    }
    return record


def _resolution_sources(date: str, away: str, home: str) -> list:
    """Links a reviewer needs: the official call that resolves the game id, then the artifacts."""
    return [
        {"label": "Official NHL daily scoreboard API (returns the game id for this date)",
         "url": f"https://api-web.nhle.com/v1/score/{date}", "kind": "official_api",
         "evidence": "primary", "retrieved_at": "",
         "note": f"Match {away} at {home} in the games array, then open "
                 f"api-web.nhle.com/v1/gamecenter/<id>/landing."},
        {"label": "Official NHL Game Center (human view)",
         "url": "https://www.nhl.com/schedule", "kind": "official_page",
         "evidence": "primary", "retrieved_at": "",
         "note": f"Set the date filter to {date} for the gamecenter link and box score."},
        {"label": "Scouting The Refs write-up of the ruling (third party, quotes the NHL)",
         "url": "", "kind": "secondary", "evidence": "secondary", "retrieved_at": "2026-10-07",
         "note": "URL is supplied per record below."},
    ]


def ohgren_record() -> dict:
    return pending_ruling_change(
        record_seed="", date="2026-10-03", away="CGY", home="VAN",
        teams_note="Reported as Calgary at Vancouver, Rogers Arena, third period.",
        notes=("Third-period goal-line review that changed both the period total and the game total; the "
               "strongest kind of settlement exposure in the feed. Entered from secondary reporting because "
               "the league publishes no machine-readable review record - the official artifact pull is the "
               "next step and is spelled out in check_instructions."),
        change_type="goal_awarded_after_goal_line_review",
        summary="Vancouver goal waived off on the ice, then awarded after Situation Room review; "
                "a 1-0 Calgary lead became part of a 4-1 Vancouver win",
        detail="Liam Ohgren's goal about 90 seconds into the third period was not initially counted; "
               "review of the white webbing in the goaltender's glove showed the puck crossing the line "
               "and the goal was awarded, changing the period and game goal count.",
        total_changed=None, market_game_total="yes",
        reason_text=("NHL Situation Room official Rod Pasma told Sportsnet the puck was seen moving in "
                     "Devlin Cooley's glove through the white webbing while behind the line, so the goal "
                     "was awarded; he added the call might have been ruled inconclusive had the webbing "
                     "been black. This is a rule 78.4/goal-line review outcome, not a scorer's decision."),
        rule_citation="78.4 / Rule 37.3 goal-line video review",
        sources=[{"label": "Official NHL daily scoreboard API (resolves the game id for 2026-10-03)",
                  "url": "https://api-web.nhle.com/v1/score/2026-10-03", "kind": "official_api",
                  "evidence": "primary", "retrieved_at": "",
                  "note": "Find CGY at VAN in games[], then re-read the record against "
                          "api-web.nhle.com/v1/gamecenter/<id>/landing and the GS sheet."},
                 {"label": "Scouting The Refs - report of the review decision and the NHL's words",
                  "url": "https://scoutingtherefs.com/2026/10/04/canucks-flames-ohgren-controversy/",
                  "kind": "secondary", "evidence": "secondary", "retrieved_at": "2026-10-07",
                  "quote": "the NHL saw the puck moving in Devlin Colley\'s glove through the white "
                           "webbing while behind the line of the goal and awarded it - the call would "
                           "have likely been ruled inconclusive if the webbing was black"},
                 {"label": "NHL Situation Room live blog (the official channel that documents such rulings)",
                  "url": "https://www.nhl.com/news/frozen-frenzy-nhl-situation-room-live-blog-october-22-2024",
                  "kind": "official_page", "evidence": "reference", "retrieved_at": "",
                  "note": "Example of the only official public format for Situation Room explanations; "
                          "no such page is published for every game."}],
        extra_flags=["period_and_game_total_impact", "goal_line_review_admitted_inconclusive_risk",
                     "total_change_reported_by_secondary_source_not_established"],
        period=3, clock="01:30", team="VAN",
        initial={"artifact": "on-ice ruling", "goal_present": False, "ruling": "no_goal_on_ice",
                 "scorer": {"name": "L. Ohgren"}, "assists": [], "period": 3, "clock": "01:30",
                 "team": "VAN", "score_after": {"away": 1, "home": 0}},
        corrected={"artifact": "Situation Room review outcome", "goal_present": True, "ruling": "goal",
                   "scorer": {"name": "L. Ohgren"}, "assists": [], "period": 3, "clock": "01:30",
                   "team": "VAN", "score_after": {"away": 1, "home": 1}},
    )


def rossie_record() -> dict:
    return pending_ruling_change(
        record_seed="", date="2026-10-01", away="EDM", home="VAN",
        teams_note="Reported as Edmonton at Vancouver, Rogers Arena, third period.",
        notes=("Three-state ruling sequence in one play (goal -> no goal -> goal). It is the cleanest "
               "available demonstration that goal/no-goal changes are invisible in the final published "
               "record: the box score shows one goal and no trace of the two reversals."),
        change_type="nogoal_reversed_to_goal_on_league_review",
        summary="Marco Rossi goal: called a goal on the ice, changed to no-goal by the referee, then "
                "reinstated by Situation Room review as a legal shoulder deflection",
        detail="Three states in one play: goal -> no goal (gloved puck) -> goal (deflected off the "
               "shoulder). The final record credits the goal; the two intermediate rulings leave no "
               "trace in the published box score, which is why this class is only catchable live.",
        total_changed=None, market_game_total="yes",
        reason_text=('NHL explanation as quoted by Scouting The Refs: "The Referee\'s initially ruled '
                     'that Marco Rossi batted the puck into the Edmonton net with his glove. The '
                     'Situation Room then initiated a video review to further examine the play and '
                     'determined that the puck deflected off Rossi\'s shoulder and entered the Edmonton '
                     'net in a legal fashion." Not a challengeable play; league-initiated under Rule 37.'),
        rule_citation="78.4 (deflection off body) with 37.3 (batted puck review)",
        sources=[{"label": "Official NHL daily scoreboard API (resolves the game id for 2026-10-01)",
                  "url": "https://api-web.nhle.com/v1/score/2026-10-01", "kind": "official_api",
                  "evidence": "primary", "retrieved_at": "",
                  "note": "Find EDM at VAN in games[], then re-read the record against the game center "
                          "landing JSON and the GS sheet for that game."},
                 {"label": "Scouting The Refs - quote of the NHL's own explanation",
                  "url": "https://scoutingtherefs.com/2026/10/02/nhl-oversight-goal-marco-rossi-canucks-oilers/",
                  "kind": "secondary", "evidence": "secondary", "retrieved_at": "2026-10-07",
                  "quote": "The Referee\'s initially ruled that Marco Rossi batted the puck into the "
                           "Edmonton net with his glove. The Situation Room then initiated a video review "
                           "to further examine the play and determined that the puck deflected off Rossi\'s "
                           "shoulder and entered the Edmonton net in a legal fashion."},
                 {"label": "NHL Rule 78.4 (goal scored by legal means) / 37.3 (batted puck)",
                  "url": "https://nhl.bamcontent.com/images/manual/NHL-Rulebook-2025-26.pdf",
                  "kind": "official_document", "evidence": "reference", "retrieved_at": "",
                  "note": "Rule text governs whether a deflection off the shoulder is legal; the cited "
                          "PDF is the current official rulebook."}],
        extra_flags=["three_state_ruling_sequence", "not_challengeable_league_initiated",
                     "total_change_reported_by_secondary_source_not_established"],
        period=3, clock=None, team="VAN",
        initial={"artifact": "on-ice ruling after referee's revision", "goal_present": False,
                 "ruling": "no_goal_gloved_puck", "scorer": {"name": "M. Rossi"}, "assists": [],
                 "period": 3, "clock": None, "team": "VAN"},
        corrected={"artifact": "Situation Room review outcome", "goal_present": True, "ruling": "goal",
                   "scorer": {"name": "M. Rossi"}, "assists": [], "period": 3, "clock": None,
                   "team": "VAN"},
    )


def _clock(period: int, game_seconds: int) -> str:
    """Period-relative clock displayed as MM:SS remaining (RTSS convention)."""
    remaining = (period - 1) * 1200 + 1200 - game_seconds
    return f"{remaining // 60:02d}:{remaining % 60:02d}"


PRIOR_ART_ROWS = [
    # (game_id, period, seconds_into_game_in_official_feed, corrected_value, game type)
    # Transcribed from aknodell/nhlPbpScrapeR data/manually_changed_api_events.csv,
    # which carries no license file - so five rows are cited as leads with attribution
    # and the bulk of the log is deliberately NOT copied into this repository.
    ("2019030232", 3, 3570, 3571, "playoffs"),
    ("2019021019", 2, 1805, 1806, "reg"),
    ("2018020443", 2, 1313, 1315, "reg"),
    ("2016020609", 3, 3535, 3540, "reg"),
    ("2015020557", 2, 1245, 1246, "reg"),
]


def prior_art_clock_records() -> list:
    """Sampled rows from a public audit log of NHL feed goal-clock errors.

    Source: github.com/aknodell/nhlPbpScrapeR - after_goal_corrections.md plus
    data/manually_changed_api_events.csv, which record 560 games where the
    official play-by-play put a goal at the wrong second or omitted the next
    faceoff. Imported as *leads*, one record per game: the log claims the
    official data is wrong, and only the official artifact plus video settles it.
    """
    out = []
    for game_id, period, old_sec, new_sec, kind in PRIOR_ART_ROWS:
        season = game_id[:4]
        season_dir = f"{season}{int(season) + 1}"
        code = "03" if kind == "playoffs" else "02"
        stem = f"{code}{game_id[-4:]}"
        clock, new_clock = _clock(period, old_sec), _clock(period, new_sec)
        record = {
            "record_id": db_mod.compute_record_id(game_id, "C22", "clock", f"{period}|{clock}"),
            "schema_version": db_mod.SCHEMA_VERSION,
            "status": "pending_review",
            "confidence": "low",
            "detected_by": "prior_art_log",
            "detection": {"check_id": "C22", "rule": "goal_clock_conflict",
                          "rule_label": "Goal clock in the official feed disputed by a public audit log",
                          "severity": "low", "detected_at": "2026-10-07T05:00:00Z",
                          "run_id": "seed-2026-10-07", "tool_version": "0.4.0"},
            "game": {"game_id": game_id, "season": season_dir,
                     "game_type": "PO" if kind == "playoffs" else "REG",
                     "date": None, "away_team": None, "home_team": None, "final_score": None,
                     "gamecenter_url": f"https://www.nhl.com/gamecenter/{game_id}",
                     "report_urls": {"GS": f"https://www.nhl.com/scores/htmlreports/{season_dir}/GS{stem}.HTM",
                                     "PL": f"https://www.nhl.com/scores/htmlreports/{season_dir}/PL{stem}.HTM"}},
            "discrepancy": {"period": period, "clock": clock, "team": None, "field": "clock",
                            "goal_key": None, "change_type": "goal_clock_conflict",
                            "summary": f"Game {game_id}: audit log states the period {period} goal at "
                                       f"{clock} should be {new_clock}",
                            "detail": "Third-party PBP audit log entry: 'Change GOAL from "
                                      f"{old_sec} to {new_sec}' (seconds from period start in the feed). "
                                      "Applied by the log's author to both the API and HTML feeds, i.e. "
                                      "the official records agree with each other and are both alleged to "
                                      "be off by one to five seconds.",
                            "total_changed": False, "attribution_only": False,
                            "goal_no_goal_change": False, "video_review": False,
                            "when_corrected": "not_applicable", "timing_uncertain": True,
                            "market_impact": {
                                "total_changed": False, "affects_game_total": "no",
                                "affects_player_props": "no", "affects_result_markets": "no",
                                "risk": "low",
                                "reason": "Clock precision does not change what was scored. It matters for "
                                          "period totals measured to the second, last-goal timing props, and "
                                          "anyone reconstructing the game from the feed.",
                                "rule_class": "timing"},
                            "reason": {"stated_by_league": False, "text": "",
                                       "rule_citation": None, "needs_human_read": True}},
            "initial_state": {"artifact": "official play-by-play feed", "goal_present": True,
                              "ruling": f"goal at {clock} of period {period}", "scorer": None,
                              "assists": [], "period": period, "clock": clock, "team": None},
            "corrected_state": {"artifact": "audit log assertion", "goal_present": True,
                                "ruling": f"goal at {new_clock} of period {period}", "scorer": None,
                                "assists": [], "period": period, "clock": new_clock, "team": None},
            "totals": {"initial_game_goals": None, "corrected_game_goals": None, "goal_delta": 0,
                       "basis": "timing only"},
            "sources": [
                {"label": f"Official GS sheet for game {game_id} (reviewer to read the SCORING SUMMARY row)",
                 "url": f"https://www.nhl.com/scores/htmlreports/{season_dir}/GS{stem}.HTM",
                 "kind": "official_report", "evidence": "primary", "retrieved_at": ""},
                {"label": "Official play-by-play sheet for the same game",
                 "url": f"https://www.nhl.com/scores/htmlreports/{season_dir}/PL{stem}.HTM",
                 "kind": "official_report", "evidence": "primary", "retrieved_at": ""},
                {"label": "aknodell/nhlPbpScrapeR - after_goal_corrections.md (third-party audit log)",
                 "url": "https://github.com/aknodell/nhlPbpScrapeR/blob/main/after_goal_corrections.md",
                 "kind": "third_party", "evidence": "secondary", "retrieved_at": "2026-10-07",
                 "quote": f"- {game_id}\n\t- Change GOAL from {old_sec} to {new_sec}"},
            ],
            "verification": {"status": "pending_review", "evidence_grade": "secondary",
                             "independently_checkable": True,
                             "check_instructions": "Open the two official sheets above, compare the goal "
                                                   "row with game time, and check video of the goal; the "
                                                   "clock value is only wrong if the feed disagrees with "
                                                   "the tape.",
                             "verified_by": "", "verified_at": ""},
            "flags": ["requires_human_verification", "third_party_claim_only",
                      "no_goal_count_or_attribution_impact"],
            "notes": "Kept in this database because it is the one class of official error that both "
                     "official artifacts share, so no cross-source check can ever find it. 560 games are "
                     "affected per that log; five are entered here as representatives.",
        }
        out.append(record)
    return out


def main() -> int:
    as_json = "--print" in sys.argv
    records = [cross_source_record(), ohgren_record(), rossie_record(), *prior_art_clock_records()]
    bad = {}
    for record in records:
        problems = db_mod.validate(record)
        if problems:
            bad[record["record_id"]] = problems
    if bad:
        for rid, problems in bad.items():
            print(f"{rid}: {problems}", file=sys.stderr)
        return 1
    if as_json:
        print(json.dumps({"records": records}, indent=2, ensure_ascii=False))
        return 0
    out_json = os.path.join(ROOT, "data", "discrepancies.json")
    db_mod.save_db({"schema_version": db_mod.SCHEMA_VERSION, "records": records}, out_json)
    rows = db_mod.load_db(out_json)["records"]
    csv_count = db_mod.write_csv(rows, os.path.join(ROOT, "data", "discrepancies.csv"))
    print(f"wrote {len(rows)} records -> {out_json} (+ {csv_count} csv rows)")
    print("alerts:", json.dumps(alerts_summary(rows)))
    return 0


def alerts_summary(rows):
    from nhl_scoring import alerts as alerts_mod
    triaged = alerts_mod.triage(rows)
    return {"total": len(triaged), "immediate": sum(1 for t in triaged if t["level"] == "immediate"),
            "review": sum(1 for t in triaged if t["level"] == "review"),
            "info": sum(1 for t in triaged if t["level"] == "info")}


if __name__ == "__main__":
    raise SystemExit(main())
