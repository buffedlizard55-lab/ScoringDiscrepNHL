"""Parser, diff, classification and store tests.

Fixtures are documented in the fixture files themselves - cell text is verbatim from
official NHL documents retrieved 2026-10-07; the surrounding markup is a harness
reconstruction (see the fixture headers). Live-layout validation is a job for
``python -m nhl_monitor probe``, which parses the real document at runtime.
"""

from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from nhl_monitor import archive, classify, parse, state, store  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _read(name: str) -> str:
    with open(os.path.join(FIXTURES, name)) as fh:
        return fh.read()


class TestPlayerCellParsing(unittest.TestCase):
    def test_modern_cell(self):
        p = parse.parse_player_cell("86 N.KUCHEROV(1)")
        self.assertEqual(p.sweater, 86)
        self.assertEqual(p.name, "N.KUCHEROV")

    def test_legacy_cell_with_space(self):
        p = parse.parse_player_cell("J. BULIS (1)")
        self.assertIsNone(p.sweater)
        self.assertEqual(p.name, "J. BULIS")

    def test_unassisted_and_penalty_shot_are_not_players(self):
        for raw in ("unassisted", "Penalty Shot", "", "  "):
            self.assertIsNone(parse.parse_player_cell(raw), raw)

    def test_captaincy_marker_stripped(self):
        p = parse.parse_player_cell("59 R.JOSI(C)")
        self.assertEqual(p.name, "R.JOSI")


class TestFooterTimestamp(unittest.TestCase):
    def test_modern_regenerated_footer(self):
        html = "<p>&copy; Copyright 2024, National Hockey League<br> 2024-02-06 11.19.44</p>"
        self.assertEqual(parse.extract_report_generated_at(html), "2024-02-06 11:19:44")

    def test_legacy_frozen_footer(self):
        html = "<p>&copy; Copyright 2005, National Hockey League | 2005-10-05-21.40.47</p>"
        self.assertEqual(parse.extract_report_generated_at(html), "2005-10-05 21:40:47")

    def test_missing_footer_returns_empty(self):
        self.assertEqual(parse.extract_report_generated_at("<html><body>x</body></html>"), "")


class TestReportEra(unittest.TestCase):
    def test_frozen_when_generated_same_night(self):
        frozen, note = parse.report_era("2005-10-05", "2005-10-05 21:40:47")
        self.assertTrue(frozen)
        self.assertIn("frozen", note)

    def test_regenerated_months_later(self):
        frozen, note = parse.report_era("2023-10-10", "2024-02-06 11:19:44")
        self.assertFalse(frozen)
        self.assertIn("REGENERATED", note)

    def test_toronto_october_dst_boundary_is_handled(self):
        # A 19:00 local (EDT) game on 2023-10-10 ends ~22:00 same UTC day.
        frozen, _ = parse.report_era("2023-10-10", "2023-10-10 22:05:00")
        self.assertTrue(frozen)

    def test_missing_inputs_are_unknown_not_false(self):
        frozen, _ = parse.report_era("", "2023-10-10 22:05:00")
        self.assertIsNone(frozen)


class TestGameSummaryParser(unittest.TestCase):
    def test_modern_report(self):
        html = _read("gs_20232024_020001.html")
        st = parse.parse_gs_report(
            html, url="https://www.nhl.com/scores/htmlreports/20232024/GS020001.HTM",
            retrieved_at="2026-10-07T00:00:00Z", game_id=2023020001, season="20232024")
        self.assertEqual(st.game_date, "2023-10-10")
        self.assertEqual(len(st.goals), 8)
        self.assertEqual(st.goal_count("TBL"), 5)
        self.assertEqual(st.goal_count("NSH"), 3)
        first = st.sorted_goals()[0]
        self.assertEqual(first.period, 1)
        self.assertEqual(first.clock, "9:48")
        self.assertEqual(first.team, "TBL")
        self.assertEqual(first.strength, "EV")
        self.assertEqual(first.scorer.sweater, 86)
        self.assertEqual(first.scorer.name, "N.KUCHEROV")
        self.assertEqual(st.away.abbrev, "NSH")      # league shield logo must not become "NHL"
        self.assertEqual(st.home.abbrev, "TBL")
        self.assertEqual([a.name for a in first.assists], ["V.HEDMAN", "B.POINT"])
        # the penalty-shot goal has a merged assist cell and no assists
        ps = [g for g in st.goals if g.clock == "3:07"][0]
        self.assertEqual(ps.assists, [])
        self.assertTrue(ps.is_penalty_shot)
        # empty net goal keeps its strength marker
        en = [g for g in st.goals if g.clock == "19:58"][0]
        self.assertEqual(en.strength, "EV-EN")
        self.assertEqual(en.assists[0].name, "N.PAUL")
        self.assertEqual(st.report_generated_at, "2024-02-06 11:19:44")
        self.assertEqual(st.parse_warnings, [])

    def test_legacy_report_strength_column_last(self):
        html = _read("gs_20052006_020001.html")
        st = parse.parse_gs_report(
            html, url="https://www.nhl.com/scores/htmlreports/20052006/GS020001.HTM",
            retrieved_at="2026-10-07T00:00:00Z", game_id=2005020001, season="20052006")
        self.assertEqual(st.game_date, "2005-10-05")
        self.assertEqual(len(st.goals), 3)
        self.assertEqual([g.strength for g in st.sorted_goals()], ["EV", "EV", "PP"])
        self.assertEqual(st.goal_count("MTL"), 2)
        self.assertEqual(st.goal_count("BOS"), 1)
        ryder = [g for g in st.goals if g.clock == "19:48"][0]
        self.assertEqual(ryder.team, "MTL")
        self.assertEqual(ryder.scorer.name, "M. RYDER")
        self.assertEqual([a.name for a in ryder.assists], ["S. KOIVU", "A. KOVALEV"])
        frozen, _ = parse.report_era(st.game_date, st.report_generated_at)
        self.assertTrue(frozen)
        self.assertEqual((st.away.abbrev, st.home.abbrev), ("MTL", "BOS"))
        self.assertEqual((st.away.score, st.home.score), (2, 1))

    def test_unparsable_document_warns_instead_of_inventing_goals(self):
        st = parse.parse_gs_report("<html><body><table><tr><td>hello</td></tr></table></body></html>",
                                   url="https://example.invalid/x", retrieved_at="now", game_id=1)
        self.assertEqual(st.goals, [])
        self.assertTrue(any("SCORING SUMMARY table not found" in w for w in st.parse_warnings))


class TestPlayByPlayParser(unittest.TestCase):
    def _payload(self, events):
        return {
            "id": 2023020001, "gameDate": "2023-10-10", "season": 20232024, "gameState": "OFF",
            "awayTeam": {"id": 18, "abbrev": "NSH", "score": 3, "sog": 31, "commonName": {"default": "Predators"}},
            "homeTeam": {"id": 14, "abbrev": "TBL", "score": 5, "sog": 34, "commonName": {"default": "Lightning"}},
            "periodDescriptor": {"number": 3}, "clock": {"inIntermission": False},
            "plays": events,
        }

    def test_shootout_goals_do_not_count_and_no_final_score_is_invented(self):
        html = _read("gs_20232024_020001.html").replace(
            "<tr><td>8</td><td>3</td><td>19:58</td>",
            "<tr><td>9</td><td>SO</td><td>0:00</td><td>PS</td><td>TBL</td>"
            "<td>86 N.KUCHEROV(3)</td><td>unassisted</td><td></td><td></td><td></td></tr>"
            "<tr><td>8</td><td>3</td><td>19:58</td>", 1)
        st = parse.parse_gs_report(html, url="u", retrieved_at="t", game_id=2023020001)
        self.assertEqual(len([g for g in st.goals if g.period_type == "SO"]), 1)
        self.assertEqual(st.goal_count("TBL"), 5)          # shootout goal excluded from the count
        self.assertIsNone(st.away.score)                   # no invented final score
        self.assertTrue(any("shootout" in w for w in st.parse_warnings))

    def test_goal_event_verbatim_fixture(self):
        blob = json.loads(_read("pbp_2023020001_goal_event.json"))
        payload = self._payload([blob["event"]])
        st = parse.parse_api_pbp(payload, url="https://api-web.nhle.com/v1/gamecenter/2023020001/play-by-play",
                                 retrieved_at="2026-10-07T00:00:00Z")
        self.assertEqual(len(st.goals), 1)
        g = st.goals[0]
        self.assertEqual(g.event_id, 154)
        self.assertEqual(g.clock, "09:48")
        self.assertEqual(g.team, "TBL")           # eventOwnerTeamId 14 == home team id
        self.assertEqual(g.scorer.id, 8476453)    # Kucherov (cross-checked against GS/PL reports)
        self.assertEqual([a.id for a in g.assists], [8475167, 8478010])
        self.assertEqual(g.strength, "EV")
        self.assertEqual((g.away_score_after, g.home_score_after), (0, 1))

    def test_shootout_events_are_not_counted_as_goals(self):
        event = {
            "eventId": 999, "periodDescriptor": {"number": 5, "periodType": "SO"},
            "timeInPeriod": "00:00", "typeCode": 505, "typeDescKey": "goal",
            "details": {"scoringPlayerId": 1, "eventOwnerTeamId": 14},
        }
        st = parse.parse_api_pbp(self._payload([event]), url="u", retrieved_at="t")
        self.assertEqual(st.goal_count(), 0)
        self.assertEqual(len(st.goals), 1)  # kept, but excluded from goal counts


class TestDiffEngine(unittest.TestCase):
    def _state(self, goals, away_score, home_score, state_name="OFF", retrieved="2026-10-07T00:00:00Z"):
        st = state.GameState(game_id=2023020001, source_key="api.pbp", source_url="u",
                             retrieved_at=retrieved, game_date="2023-10-10", season="20232024",
                             game_state=state_name, period=3)
        st.away = state.TeamState(abbrev="NSH", score=away_score)
        st.home = state.TeamState(abbrev="TBL", score=home_score)
        for g in goals:
            st.goals.append(state.GoalEvent(**g))
        return st

    def _goal(self, clock="9:48", team="TBL", scorer=("Kucherov", 86), assists=("Hedman", "Point"), strength="EV"):
        return dict(period=1, clock=clock, team=team,
                    scorer=state.PlayerRef(id=None, name=scorer[0], sweater=scorer[1]) if scorer else None,
                    assists=[state.PlayerRef(id=None, name=a, sweater=None) for a in assists],
                    strength=strength)

    def test_no_change_produces_no_changes(self):
        a = self._state([self._goal()], 3, 5)
        b = self._state([self._goal()], 3, 5, retrieved="2026-10-07T01:00:00Z")
        self.assertEqual(state.diff_states(a, b), [])
        self.assertEqual(a.fingerprint(), b.fingerprint())

    def test_scorer_change_is_attribution_only(self):
        a = self._state([self._goal()], 3, 5)
        b = self._state([self._goal(scorer=("Hagel", 38))], 3, 5)
        changes = state.diff_states(a, b)
        self.assertEqual([c.change_type for c in changes], ["scorer_change"])
        self.assertFalse(state.affects_goal_total(changes))
        self.assertTrue(state.attribution_only(changes))
        cls = classify.classify(changes)
        self.assertEqual(cls["discrepancy_type"], "scorer_change")
        self.assertFalse(cls["affects_goal_total"])
        self.assertTrue(cls["attribution_only"])

    def test_goal_removed_changes_total(self):
        a = self._state([self._goal(), self._goal(clock="10:52")], 3, 5)
        b = self._state([self._goal()], 3, 4)
        changes = state.diff_states(a, b)
        self.assertEqual([c.change_type for c in changes], ["goal_removed"])
        cls = classify.classify(changes)
        self.assertEqual(cls["discrepancy_type"], "goal_to_no_goal")
        self.assertTrue(cls["affects_goal_total"])
        self.assertFalse(cls["attribution_only"])

    def test_goal_added_changes_total(self):
        a = self._state([self._goal()], 3, 4)
        b = self._state([self._goal(), self._goal(clock="10:52")], 3, 5)
        cls = classify.classify(state.diff_states(a, b))
        self.assertEqual(cls["discrepancy_type"], "no_goal_to_goal")
        self.assertTrue(cls["affects_goal_total"])

    def test_assist_change_detected(self):
        a = self._state([self._goal(assists=("Hedman", "Point"))], 3, 5)
        b = self._state([self._goal(assists=("Hedman",))], 3, 5)
        changes = state.diff_states(a, b)
        self.assertEqual([c.change_type for c in changes], ["assist_change"])
        self.assertIn("Assists changed", changes[0].detail)

    def test_goal_time_correction_is_not_a_goal_total_change(self):
        """A corrected goal time must never look like a removed + added goal."""
        a = self._state([self._goal(clock="9:48")], 3, 5)
        b = self._state([self._goal(clock="12:31")], 3, 5)
        changes = state.diff_states(a, b)
        self.assertEqual([c.change_type for c in changes], ["time_change"])
        self.assertFalse(state.affects_goal_total(changes))
        self.assertFalse(state.attribution_only(changes))
        cls = classify.classify(changes)
        self.assertEqual(cls["discrepancy_type"], "time_change")
        self.assertFalse(cls["affects_goal_total"])
        self.assertEqual(classify.settlement_assessment(cls, "postgame_after_publication")["level"], "low")

    def test_team_reassignment_is_flagged_as_market_relevant(self):
        """An own-goal re-attribution keeps the game total but can flip the winner."""
        a = self._state([self._goal(team="TBL")], 3, 5)
        b = self._state([self._goal(team="NSH")], 3, 5)
        changes = state.diff_states(a, b)
        self.assertEqual([c.change_type for c in changes], ["team_change"])
        self.assertFalse(state.affects_goal_total(changes))
        self.assertTrue(state.affects_team_assignment(changes))
        cls = classify.classify(changes)
        self.assertEqual(cls["discrepancy_type"], "team_change")
        out = classify.settlement_assessment(cls, "postgame_after_publication")
        self.assertFalse(out["could_affect_game_total_market"])   # over/under unchanged
        self.assertTrue(out["could_affect_team_markets"])          # team totals / puck line / winner
        self.assertEqual(out["level"], "high")

    def test_clock_drift_within_three_seconds_still_matches(self):
        a = self._state([self._goal(clock="9:48")], 3, 5)
        b = self._state([self._goal(clock="9:46")], 3, 5)
        changes = state.diff_states(a, b)
        self.assertEqual([c.change_type for c in changes], [])

    def test_score_only_movement_is_flagged_not_silently_accepted(self):
        a = self._state([self._goal()], 3, 5)
        b = self._state([self._goal()], 4, 5)
        changes = state.diff_states(a, b)
        self.assertEqual([c.change_type for c in changes], ["metadata_change"])
        self.assertTrue(classify.classify(changes)["needs_manual_review"])

    def test_state_roundtrip_and_fingerprint_stability(self):
        a = self._state([self._goal()], 3, 5)
        blob = json.loads(json.dumps(a.as_dict()))
        b = state.GameState.from_dict(blob)
        self.assertEqual(a.fingerprint(), b.fingerprint())


class TestSettlementAssessment(unittest.TestCase):
    def test_postgame_total_change_is_high_risk(self):
        cls = {"affects_goal_total": True, "attribution_only": False, "discrepancy_type": "goal_to_no_goal",
               "counts": {}}
        out = classify.settlement_assessment(cls, "postgame_after_publication")
        self.assertEqual(out["level"], "high")
        self.assertTrue(out["could_affect_game_total_market"])
        self.assertTrue(out["requires_book_specific_review"])

    def test_in_game_total_change_is_medium(self):
        cls = {"affects_goal_total": True, "attribution_only": False, "discrepancy_type": "goal_to_no_goal",
               "counts": {}}
        self.assertEqual(classify.settlement_assessment(cls, "in_game")["level"], "medium")

    def test_attribution_change_never_touches_game_total(self):
        cls = {"affects_goal_total": False, "attribution_only": True, "discrepancy_type": "scorer_change",
               "counts": {"scorer_changes": 1}}
        out = classify.settlement_assessment(cls, "postgame_after_publication")
        self.assertEqual(out["level"], "attribution")
        self.assertFalse(out["could_affect_game_total_market"])
        self.assertTrue(out["could_affect_props"] if "could_affect_props" in out else out["could_affect_player_props"])


class TestTiming(unittest.TestCase):
    def test_live_previous_state_is_in_game(self):
        st = state.GameState(game_id=1, source_key="api.pbp", source_url="u", retrieved_at="t",
                             game_state="LIVE", period=2)
        self.assertEqual(classify.infer_timing(st, st)[0], "in_game")

    def test_intermission_detected(self):
        st = state.GameState(game_id=1, source_key="api.pbp", source_url="u", retrieved_at="t",
                             game_state="LIVE", period=1, in_intermission=True)
        self.assertEqual(classify.infer_timing(st, st)[0], "intermission")

    def test_finished_previous_state_is_postgame(self):
        st = state.GameState(game_id=1, source_key="api.pbp", source_url="u", retrieved_at="t",
                             game_state="OFF", period=3)
        self.assertEqual(classify.infer_timing(st, st)[0], "postgame_after_publication")

    def test_no_previous_state_is_unknown(self):
        self.assertEqual(classify.infer_timing(None, None)[0], "unknown")


class TestCrossCheck(unittest.TestCase):
    def test_disagreement_between_pbp_and_boxscore_is_reported(self):
        goals = state.GameState(game_id=1, source_key="api.pbp", source_url="u", retrieved_at="t")
        goals.goals.append(state.GoalEvent(period=1, clock="9:48", team="TBL",
                                           scorer=state.PlayerRef(id=111, name="A"),
                                           assists=[], strength="EV"))
        box = state.GameState(game_id=1, source_key="api.boxscore", source_url="u2", retrieved_at="t")
        box.evidence["player_totals"] = [
            {"player_id": 111, "name": "A", "sweater": 1, "team": "TBL", "goals": 1, "assists": 0},
            {"player_id": 222, "name": "B", "sweater": 2, "team": "TBL", "goals": 1, "assists": 0},
        ]
        findings = classify.crosscheck_player_totals(goals, box)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["player"], "B")

    def test_agreement_produces_no_findings(self):
        goals = state.GameState(game_id=1, source_key="api.pbp", source_url="u", retrieved_at="t")
        goals.goals.append(state.GoalEvent(period=1, clock="9:48", team="TBL",
                                           scorer=state.PlayerRef(id=111, name="A"),
                                           assists=[state.PlayerRef(id=222, name="B")], strength="EV"))
        box = state.GameState(game_id=1, source_key="api.boxscore", source_url="u2", retrieved_at="t")
        box.evidence["player_totals"] = [
            {"player_id": 111, "name": "A", "goals": 1, "assists": 0},
            {"player_id": 222, "name": "B", "goals": 0, "assists": 1},
        ]
        self.assertEqual(classify.crosscheck_player_totals(goals, box), [])


class TestArchive(unittest.TestCase):
    def test_redirect_and_error_digests_are_not_evidence(self):
        snaps = [
            archive.Snapshot("20060112073230", "http://nhl.com:80/x/ES010004.HTM", "302",
                             archive.REDIRECT_DIGEST, "unk", "292"),
            archive.Snapshot("20250125005135", "https://www.nhl.com/x/GS020001.HTM", "200",
                             "TE24NPUUMSEV3LQEBNQE2TN3NO5GNATJ", "text/html", "4435"),
        ]
        usable = [s for s in snaps if s.usable]
        self.assertEqual(len(usable), 1)
        self.assertEqual(len(archive.content_versions(snaps)), 1)

    def test_cdx_payload_parsing_and_version_grouping(self):
        payload = [
            ["urlkey", "timestamp", "original", "mimetype", "statuscode", "digest", "length"],
            ["k", "20240101000000", "https://www.nhl.com/a.HTM", "text/html", "200", "AAA", "100"],
            ["k", "20240201000000", "https://www.nhl.com/a.HTM", "text/html", "200", "BBB", "120"],
            ["k", "20240301000000", "https://www.nhl.com/a.HTM", "text/html", "200", "BBB", "120"],
        ]
        snaps = archive.parse_cdx(payload)
        self.assertEqual(len(snaps), 3)
        versions = archive.content_versions(snaps)
        self.assertEqual(len(versions), 2)          # two distinct contents = a change happened
        described = archive.described_versions(snaps)
        self.assertEqual(described[0]["first_seen"], "20240101000000")
        self.assertEqual(described[0]["snapshot_count"], 1)
        self.assertEqual(described[1]["snapshot_count"], 2)

    def test_single_version_does_not_prove_absence_of_change(self):
        payload = [
            ["timestamp", "original", "statuscode", "digest", "mimetype", "length"],
            ["20250125005135", "https://www.nhl.com/a.HTM", "200", "AAA", "text/html", "10"],
        ]
        self.assertEqual(len(archive.content_versions(archive.parse_cdx(payload))), 1)


class TestStore(unittest.TestCase):
    def _record(self, **over):
        rec = {
            "record_id": "NHL-20232024-020001-01",
            "status": "auto_detected",
            "game": {"game_id": 2023020001, "season": "20232024", "date": "2023-10-10",
                     "away": {"abbrev": "NSH", "score": 3}, "home": {"abbrev": "TBL", "score": 5}},
            "event": {"period": 1, "period_type": "REG", "clock": "9:48", "strength": "EV", "team": "TBL"},
            "initial_state": {"ruling": "goal", "scorer": {"name": "N.KUCHEROV"}},
            "corrected_state": {"ruling": "goal", "scorer": {"name": "B.HAGEL"}},
            "change": {"discrepancy_type": "scorer_change", "affects_goal_total": False,
                       "attribution_only": True, "counts": {}, "detail": "scorer changed"},
            "reason": {"category": "unknown", "text": None},
            "timing": {"when": "postgame_after_publication", "reasoning": "previous capture was final"},
            "sources": [{"role": "corrected_state", "type": "official-api",
                         "name": "NHL GameCenter play-by-play", "url": "https://api-web.nhle.com/v1/gamecenter/2023020001/play-by-play",
                         "http_status": 200, "retrieved_at_utc": "2026-10-07T00:00:00Z"}],
            "evidence_status": "verified_two_official_states",
            "settlement": {"level": "attribution", "could_affect_game_total_market": False,
                           "could_affect_player_props": True, "reasoning": "attribution only",
                           "requires_book_specific_review": True},
            "detection": {"detected_by": "auto_poll", "detected_at_utc": "2026-10-07T00:00:00Z",
                          "confidence": "high"},
            "flags": [], "notes": "",
        }
        rec.update(over)
        return rec

    def test_validation_passes_for_complete_record(self):
        self.assertEqual(store.validate(self._record()), [])

    def test_record_without_sources_fails_validation(self):
        errs = store.validate(self._record(sources=[]))
        self.assertTrue(any("source" in e for e in errs))

    def test_invalid_evidence_status_fails(self):
        errs = store.validate(self._record(evidence_status="looks-fine-to-me"))
        self.assertTrue(any("evidence_status" in e for e in errs))

    def test_completeness_reports_missing_reason_rather_than_filling_it(self):
        c = store.completeness(self._record())
        self.assertIn("reason.text", c["missing_requested_fields"])
        self.assertLess(c["percent_complete"], 100)

    def test_writing_records_preserves_hand_maintained_metadata(self):
        """The first pipeline write must not delete the coverage panel."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "records.json")
            with open(path, "w") as fh:
                json.dump({"schema_version": "1.0", "count": 0, "records": [],
                           "coverage": {"season_coverage_measured": {"20052006": "frozen"}},
                           "status_note": ["why the database is empty"]}, fh)
            store.save_records([self._record()], path=path)
            with open(path) as fh:
                blob = json.load(fh)
            self.assertEqual(blob["count"], 1)
            self.assertIn("coverage", blob)
            self.assertEqual(blob["status_note"], ["why the database is empty"])

    def test_upsert_insert_update_and_revision(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "records.json")
            rec = self._record()
            self.assertEqual(store.upsert_record(rec, path=path), "inserted")
            self.assertEqual(store.upsert_record(self._record(), path=path), "unchanged")
            changed = self._record()
            changed["notes"] = "reviewed"
            self.assertEqual(store.upsert_record(changed, path=path), "updated")
            loaded = store.load_records(path)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["revision"], 2)
            self.assertEqual(len(loaded[0]["previous_revisions"]), 1)
            self.assertEqual(loaded[0]["previous_revisions"][0]["revision"], 1)


class TestAlerts(unittest.TestCase):
    def test_severity_and_markdown(self):
        from nhl_monitor import alerts

        rec = TestStore()._record()
        rec["change"]["affects_goal_total"] = True
        rec["change"]["discrepancy_type"] = "goal_to_no_goal"
        rec["change"]["attribution_only"] = False
        rec["settlement"]["level"] = "high"
        rec["settlement"]["could_affect_game_total_market"] = True
        self.assertEqual(alerts.severity_for(rec), "critical")
        alert = alerts.build_alert(rec)
        self.assertIn("CRITICAL", alert["title"])
        self.assertIn("- Type: `goal_to_no_goal`", alert["body_markdown"])
        self.assertIn("https://api-web.nhle.com", alert["body_markdown"])
        self.assertIn("Official sources", alert["body_markdown"])

    def test_missing_reason_is_stated_explicitly(self):
        from nhl_monitor import alerts

        rec = TestStore()._record()
        body = alerts.format_record_markdown(rec)
        self.assertIn("No official statement of the reason was found", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
