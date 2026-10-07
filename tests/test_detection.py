"""Detection tests: cross-source, intra-source, temporal, market triage.

The most important test here is the boring one: on a game where both official
artifacts agree, the detector must return nothing. A discrepancy detector with a
false-positive problem is worse than no detector, because the reviewer stops
reading it.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "pipeline")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _path import fixture_json, fixture_text  # noqa: E402

from nhl_scoring import db as db_mod  # noqa: E402
from nhl_scoring.checks import check_record, compare_sources, diff_snapshots  # noqa: E402
from nhl_scoring.market import classify  # noqa: E402
from nhl_scoring.parsers import parse_api_landing, parse_gs_report  # noqa: E402
from nhl_scoring.snapshot import build_digest, record_snapshot, read_snapshots, find_temporal_findings  # noqa: E402


def _pair(game_id: str, gs_fixture: str, api_fixture: str):
    gs = parse_gs_report(fixture_text(gs_fixture), game_id=game_id,
                         url=f"https://www.nhl.com/scores/htmlreports/{game_id}/gs.htm")
    api = parse_api_landing(fixture_json(api_fixture), game_id=game_id,
                            url=f"https://api-web.nhle.com/v1/gamecenter/{game_id}/landing")
    return gs, api


class CrossSourceTests(unittest.TestCase):
    def test_real_discovery_deadmarsh_sakic(self):
        """The claim this repo is built on, asserted as a regression test.

        GS020001.HTM (2000-10-04) credits Deadmarsh's PP goal with one assist;
        gamecenter/2000020001/landing credits two. Two official artifacts of the
        same goal, one apart.
        """
        gs, api = _pair("2000020001", "official_2000020001_gs.htm",
                        "official_2000020001_api_landing_excerpt.json")
        findings = compare_sources(gs, api)
        self.assertEqual([f.check_id for f in findings], ["C11"])
        f = findings[0]
        self.assertEqual(f.rule, "assist_attribution_conflict")
        self.assertEqual(f.goal_key, "2|1111|COL")
        self.assertEqual(sorted(f.left["assists"]), ["C. DRURY"])
        self.assertEqual(sorted(f.right["assists"]), ["C. Drury", "J. Sakic"])
        self.assertIn("Drury", f.detail)
        self.assertIn("Sakic", f.detail)

    def test_control_pair_yields_nothing(self):
        gs, api = _pair("2000030162", "official_2000030162_gs.htm",
                        "official_2000030162_api_landing_excerpt.json")
        findings = compare_sources(gs, api)
        self.assertEqual(findings, [], f"false positives: {[f.detail for f in findings]}")

    def test_scorer_change_detected(self):
        gs, api = _pair("2000030162", "official_2000030162_gs.htm",
                        "official_2000030162_api_landing_excerpt.json")
        api.goals[2].player_id = 999
        api.goals[2].scorer.surname = "lapierre"
        api.goals[2].scorer.name = "P. Lapierre"
        api.goals[2].scorer.initial = "p"
        findings = [f for f in compare_sources(gs, api) if f.check_id == "C12"]
        self.assertEqual(len(findings), 1)
        self.assertIn("V. KOZLOV", findings[0].detail)
        self.assertIn("P. Lapierre", findings[0].detail)

    def test_goal_removed_between_sources_detected(self):
        gs, api = _pair("2000030162", "official_2000030162_gs.htm",
                        "official_2000030162_api_landing_excerpt.json")
        api.goals = api.goals[:3]
        api.away_score, api.home_score = 0, 3
        api.totals["DET"].goals = 3
        kinds = [f.check_id for f in compare_sources(gs, api)]
        self.assertIn("C10", kinds)
        # and the record built from it must say the total change is not established
        finding = [f for f in compare_sources(gs, api) if f.check_id == "C10"][0]
        market = classify(finding.to_dict())
        self.assertIsNone(market["total_changed"])
        self.assertEqual(market["affects_game_total"], "possible")
        self.assertEqual(market["risk"], "high")

    def test_clock_drift_matches_by_scorer_not_as_missing_goal(self):
        """A sheet and JSON that differ by one second must pair up, not double-report."""
        gs, api = _pair("2000020001", "official_2000020001_gs.htm",
                        "official_2000020001_api_landing_excerpt.json")
        api.goals[0].clock = "12:39"          # also keeps the assist conflict, ignore it
        kinds = [f.check_id for f in compare_sources(gs, api)]
        self.assertIn("C13", kinds)
        self.assertNotIn("C10", kinds)

    def test_final_score_conflict(self):
        gs, api = _pair("2000030162", "official_2000030162_gs.htm",
                        "official_2000030162_api_landing_excerpt.json")
        api.away_score = 1
        api.totals["LAK"].goals = 1
        findings = [f for f in compare_sources(gs, api) if f.check_id == "C17"]
        self.assertEqual(len(findings), 1)


class IntraSourceTests(unittest.TestCase):
    def test_goal_count_mismatch_detected(self):
        _gs, api = _pair("2000020001", "official_2000020001_gs.htm",
                         "official_2000020001_api_landing_excerpt.json")
        api.goals = api.goals[:2]
        findings = [f for f in check_record(api) if f.check_id == "C1"]
        self.assertTrue(findings)
        self.assertIn("COL", findings[0].detail)

    def test_period_total_mismatch_detected(self):
        _gs, api = _pair("2000020001", "official_2000020001_gs.htm",
                         "official_2000020001_api_landing_excerpt.json")
        api.totals["COL"].goals_by_period[2] = 5
        api.totals["COL"].goals = 5
        self.assertTrue([f for f in check_record(api) if f.check_id == "C2"])

    def test_duplicate_goal_detected(self):
        _gs, api = _pair("2000020001", "official_2000020001_gs.htm",
                         "official_2000020001_api_landing_excerpt.json")
        api.goals.append(copy.deepcopy(api.goals[0]))
        self.assertTrue([f for f in check_record(api) if f.check_id == "C5"])

    def test_non_monotonic_score_detected(self):
        _gs, api = _pair("2000020001", "official_2000020001_gs.htm",
                         "official_2000020001_api_landing_excerpt.json")
        api.goals[1].away_score = 7
        self.assertTrue([f for f in check_record(api) if f.check_id == "C4"])

    def test_unparsable_record_is_not_checked(self):
        rec = parse_gs_report("<html>404</html>", game_id="2000020001", url="x")
        self.assertEqual(check_record(rec), [])

    def test_clean_records_have_no_findings(self):
        gs, api = _pair("2000030162", "official_2000030162_gs.htm",
                        "official_2000030162_api_landing_excerpt.json")
        self.assertEqual(check_record(gs), [])
        self.assertEqual(check_record(api), [])


class SnapshotTests(unittest.TestCase):
    def test_state_change_then_diff(self):
        rec = parse_api_landing(fixture_json("official_2000030162_api_landing_excerpt.json"),
                               game_id="2000030162", url="https://api-web.nhle.com/v1/gamecenter/2000030162/landing")
        with tempfile.TemporaryDirectory() as tmp:
            first = record_snapshot(rec, root=tmp, game_state="OFF", captured_at="2001-04-14T23:00:00Z")
            self.assertTrue(first["written"])
            again = record_snapshot(rec, root=tmp, game_state="OFF", captured_at="2001-04-14T23:05:00Z")
            self.assertFalse(again["written"], "unchanged state must not append")

            # league edits the record overnight: assist removed
            mutated = parse_api_landing(fixture_json("official_2000030162_api_landing_excerpt.json"),
                                        game_id="2000030162", url=rec.url)
            del mutated.goals[3].assists[0]
            self.assertTrue(record_snapshot(mutated, root=tmp, game_state="OFF",
                                            captured_at="2001-04-15T09:00:00Z")["written"])
            snaps = read_snapshots("2000030162", tmp)
            self.assertEqual(len(snaps), 2)
            findings = find_temporal_findings("2000030162", root=tmp)
            self.assertEqual([f.check_id for f in findings], ["C20"])
            self.assertIn("2001-04-14T23:00:00Z", findings[0].detail)
            self.assertIn("2001-04-15T09:00:00Z", findings[0].detail)

    def test_goal_added_after_final_detected(self):
        base = {"game_id": "2026020001", "source": "nhl_api_landing", "away_score": 0, "home_score": 0,
                "goals": [], "captured_at": "2026-10-03T02:00:00Z", "sha256": "a" * 64, "url": "u"}
        after = copy.deepcopy(base)
        after["captured_at"] = "2026-10-03T03:30:00Z"
        after["away_score"] = 1
        after["goals"] = [{"match_key": "3|540|VAN", "period": 3, "clock": "09:00", "clock_seconds": 540,
                           "team": "VAN", "scorer": "L. Ohgren", "scorer_key": "id:1",
                           "assists": [], "assist_keys": [], "away_score": 1, "home_score": 0}]
        findings = diff_snapshots(base, after, game_id="2026020001", url="u")
        kinds = sorted(f.check_id for f in findings)
        self.assertIn("C21", kinds)
        added = [f for f in findings if f.field == "goal_added"][0]
        self.assertIn("no-goal/undecided -> goal", added.detail)
        self.assertTrue(classify(added.to_dict())["total_changed"])

    def test_digest_is_stable_and_ignores_noise(self):
        rec = parse_api_landing(fixture_json("official_2000030162_api_landing_excerpt.json"),
                               game_id="2000030162", url="x")
        d1 = build_digest(rec)
        d2 = build_digest(rec)
        self.assertEqual(d1["digest"], d2["digest"])
        self.assertEqual(len(d1["goals"]), 4)


class MarketTests(unittest.TestCase):
    def test_attribution_only_is_not_a_total_change(self):
        mi = classify({"rule": "assist_attribution_conflict", "field": "assists"})
        self.assertIs(mi["total_changed"], False)
        self.assertEqual(mi["affects_game_total"], "no")
        self.assertEqual(mi["affects_player_props"], "yes")
        self.assertEqual(mi["affects_result_markets"], "no")

    def test_snapshot_goal_change_is_high_risk(self):
        mi = classify({"rule": "post_snapshot_goal_count_change", "field": "goal_added"})
        self.assertIs(mi["total_changed"], True)
        self.assertEqual(mi["affects_game_total"], "yes")
        self.assertEqual(mi["risk"], "high")

    def test_settlement_caveat_always_present(self):
        for rule in ("assist_attribution_conflict", "post_snapshot_goal_count_change", "clock_invalid"):
            self.assertIn("source of record", classify({"rule": rule, "field": ""})["reason"])


class RecordBuildTests(unittest.TestCase):
    def test_record_from_finding_preserves_both_states(self):
        gs, api = _pair("2000020001", "official_2000020001_gs.htm",
                        "official_2000020001_api_landing_excerpt.json")
        finding = compare_sources(gs, api)[0].to_dict()
        game = {"game_id": "2000020001", "season": "20002001", "game_type": "REG",
                "date": "2000-10-04", "away_team": "COL", "home_team": "DAL",
                "final_score": {"away": 2, "home": 2},
                "report_urls": {"GS": "https://www.nhl.com/scores/htmlreports/20002001/GS020001.HTM"},
                "gamecenter_url": "https://www.nhl.com/gamecenter/2000020001"}
        artifacts = [
            {"label": "NHL official Game Summary report (SCORING SUMMARY)",
             "url": "https://www.nhl.com/scores/htmlreports/20002001/GS020001.HTM",
             "kind": "official_report", "retrieved_at": "2026-10-07T00:00:00Z",
             "sha256": "e" * 64, "evidence": "primary"},
            {"label": "NHL Game Center JSON (summary.scoring)",
             "url": "https://api-web.nhle.com/v1/gamecenter/2000020001/landing",
             "kind": "official_api", "retrieved_at": "2026-10-07T00:00:00Z",
             "sha256": "f" * 64, "evidence": "primary"},
        ]
        record = db_mod.record_from_finding(finding, game=game, artifacts=artifacts,
                                            detection={"detected_at": "2026-10-07T00:00:00Z",
                                                       "tool_version": "test", "run_id": "unit"})
        self.assertEqual(record["detected_by"], "cross_source")
        self.assertEqual(record["status"], "flagged")
        self.assertEqual([a["name"] for a in record["initial_state"]["assists"]], ["C. DRURY"])
        self.assertEqual([a["name"] for a in record["corrected_state"]["assists"]], ["C. Drury", "J. Sakic"])
        self.assertIs(record["discrepancy"]["total_changed"], False)
        self.assertTrue(record["discrepancy"]["attribution_only"])
        self.assertTrue(record["discrepancy"]["timing_uncertain"])
        self.assertEqual(record["totals"]["initial_game_goals"], 4)
        self.assertEqual(record["totals"]["corrected_game_goals"], 4)
        self.assertEqual(record["totals"]["goal_delta"], 0)
        self.assertEqual(record["totals"]["basis"], "goal rows counted per artifact")
        urls = " ".join(s["url"] for s in record["sources"])
        self.assertIn("nhl.com/scores/htmlreports/20002001/GS020001.HTM", urls)
        self.assertIn("api-web.nhle.com", urls)
        # deterministic identity: re-running must not mint a new record
        again = db_mod.record_from_finding(finding, game=game, artifacts=artifacts, detection={})
        self.assertEqual(record["record_id"], again["record_id"])
        self.assertEqual(db_mod.validate(record), [], db_mod.validate(record))

    def test_goal_added_record_marks_initial_absence(self):
        finding = {"check_id": "C21", "game_id": "2026020001", "rule": "post_snapshot_goal_count_change",
                   "field": "goal_added", "severity": "critical", "check_name": "x", "period": 3,
                   "clock": "09:00", "team": "VAN", "goal_key": "3|540|VAN", "detail": "d",
                   "left": None, "right": {"scorer": {"name": "L. Ohgren"}, "assists": [],
                                            "period": 3, "clock": "09:00", "team": "VAN", "source": "api"},
                   "evidence": [{"url": "u", "source": "snapshot_before"}, {"url": "u", "source": "snapshot_after"}]}
        rec = db_mod.record_from_finding(finding, game={"game_id": "2026020001", "date": "2026-10-03"},
                                         artifacts=[], detection={})
        self.assertFalse(rec["initial_state"]["goal_present"])
        self.assertTrue(rec["corrected_state"]["goal_present"])
        self.assertTrue(rec["discrepancy"]["goal_no_goal_change"])
        self.assertIs(rec["discrepancy"]["total_changed"], True)
        self.assertEqual(rec["initial_state"]["ruling"], "not_recorded_by_this_artifact")
        self.assertTrue(rec["corrected_state"]["goal_present"])


class UpsertSemanticsTests(unittest.TestCase):
    def _record(self, rid="SDN-0000000001", status="verified"):
        return {"record_id": rid, "schema_version": "1.0", "status": status, "confidence": "high",
                "detected_by": "cross_source",
                "detection": {"check_id": "C11", "rule": "assist_attribution_conflict",
                              "rule_label": "x", "severity": "medium",
                              "detected_at": "2026-10-07T00:00:00Z"},
                "game": {"game_id": "2000020001", "date": "2000-10-04", "season": "20002001"},
                "discrepancy": {"change_type": "assist_attribution_conflict", "total_changed": False,
                                "when_corrected": "unknown",
                                "market_impact": {"affects_game_total": "no", "affects_player_props": "yes",
                                                  "affects_result_markets": "no", "risk": "medium",
                                                  "reason": "x"}},
                "initial_state": {"assists": []}, "corrected_state": {"assists": []},
                "sources": [{"url": "https://www.nhl.com/x", "evidence": "primary", "label": "gs"}],
                "verification": {"status": status, "evidence_grade": "primary",
                                 "independently_checkable": True, "check_instructions": "",
                                 "verified_by": "agent", "verified_at": "2026-10-07"},
                "flags": []}

    def test_resighting_bumps_counter_without_touching_human_status(self):
        base = self._record(status="verified")
        again = json.loads(json.dumps(base))
        again["status"] = "flagged"
        again["verification"] = {"status": "flagged", "evidence_grade": "primary",
                                "independently_checkable": True, "check_instructions": "",
                                "verified_by": "", "verified_at": ""}
        recs, stats = db_mod.upsert([base], [again])
        self.assertEqual(stats["skipped_human"], 1)
        self.assertEqual(recs[0]["status"], "verified")
        self.assertEqual(recs[0]["seen_count"], 2)
        self.assertEqual(len(recs[0]["detection_history"]), 1)
        self.assertTrue(recs[0]["last_seen_at"])

    def test_machine_run_does_not_close_a_pending_research_record(self):
        base = self._record(status="pending_review")
        again = json.loads(json.dumps(base))
        again["status"] = "flagged"
        recs, stats = db_mod.upsert([base], [again])
        self.assertEqual(recs[0]["status"], "pending_review")
        self.assertIn("machine_detected_too", recs[0]["flags"])
        self.assertEqual(stats["updated"], 1)


class UpsertValidationTests(unittest.TestCase):
    def _record(self, rid="SDN-0000000001", status="flagged"):
        return {"record_id": rid, "schema_version": "1.0", "status": status, "confidence": "medium",
                "detected_by": "cross_source", "detection": {"check_id": "C11", "rule": "assist_attribution_conflict",
                                                              "rule_label": "x", "severity": "medium",
                                                              "detected_at": "2026-10-07T00:00:00Z"},
                "game": {"game_id": "2000020001", "date": "2000-10-04", "season": "20002001"},
                "discrepancy": {"change_type": "assist_attribution_conflict", "total_changed": False,
                                "when_corrected": "unknown",
                                "market_impact": {"affects_game_total": "no", "affects_player_props": "yes",
                                                  "affects_result_markets": "no", "risk": "medium", "reason": "x"}},
                "initial_state": {"assists": []}, "corrected_state": {"assists": []},
                "sources": [{"url": "https://www.nhl.com/x", "evidence": "primary", "label": "gs"}],
                "verification": {"status": status, "verified_at": ""},
                "flags": []}

    def test_validate_flags_missing_links_and_bad_enums(self):
        rec = self._record()
        self.assertEqual(db_mod.validate(rec), [])
        bad = self._record()
        bad["sources"] = []
        bad["status"] = "confirmed"
        bad["discrepancy"]["when_corrected"] = "tuesday"
        bad["discrepancy"]["market_impact"]["affects_game_total"] = "maybe"
        errors = db_mod.validate(bad)
        self.assertTrue(any("sources" in e for e in errors))
        self.assertTrue(any("status" in e for e in errors))
        self.assertTrue(any("when_corrected" in e for e in errors))
        self.assertTrue(any("affects_game_total" in e for e in errors))

    def test_verified_requires_primary_source_and_timestamp(self):
        rec = self._record(status="verified")
        rec["verification"]["status"] = "verified"
        rec["verified_at"] = "2026-10-07"
        errors = db_mod.validate(rec)
        self.assertTrue(any("verified_at" in e for e in errors))
        rec["verification"]["verified_at"] = "2026-10-07"
        self.assertEqual(db_mod.validate(rec), [])
        rec["sources"][0]["evidence"] = "secondary"
        self.assertTrue(any("primary" in e for e in db_mod.validate(rec)))

    def test_upsert_keeps_human_status(self):
        machine = self._record(status="flagged")
        human = self._record(status="verified")
        human["verification"]["verified_at"] = "2026-10-07"
        human["notes"] = "checked against the sheet by hand"
        merged, stats = db_mod.upsert([human], [machine])
        self.assertEqual(merged[0]["status"], "verified")
        self.assertEqual(merged[0]["notes"], "checked against the sheet by hand")
        self.assertEqual(stats["skipped_human"], 1)

    def test_upsert_adds_and_bumps_seen_count(self):
        a = self._record("SDN-000000000a")
        b = self._record("SDN-000000000b")
        merged, stats = db_mod.upsert([a], [dict(a), b])
        self.assertEqual(stats["added"], 1)
        self.assertEqual(stats["updated"], 1)
        self.assertEqual([m for m in merged if m["record_id"] == "SDN-000000000a"][0]["seen_count"], 2)

    def test_csv_roundtrip_and_save_order(self):
        recs = [self._record("SDN-000000000a"), self._record("SDN-000000000b")]
        table = db_mod.to_csv(recs)
        self.assertEqual(table[0], db_mod.CSV_COLUMNS)
        self.assertEqual(len(table), 3)
        self.assertEqual(table[1][db_mod.CSV_COLUMNS.index("game_id")], "2000020001")
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "data", "discrepancies.json")
            db_mod.save_db({"records": list(reversed(recs))}, db_path)
            with open(db_path) as fh:
                loaded = json.load(fh)
            self.assertEqual(loaded["record_count"], 2)
            self.assertEqual([r["record_id"] for r in loaded["records"]],
                             sorted(r["record_id"] for r in loaded["records"]))
            n = db_mod.write_csv(recs, os.path.join(tmp, "data", "discrepancies.csv"))
            self.assertEqual(n, 2)


if __name__ == "__main__":
    unittest.main()
