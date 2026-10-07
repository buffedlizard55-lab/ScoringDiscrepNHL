"""Pass-3 tests: the 2000-2004 report era, and the official-statement ingest path.

Two independent things are protected here.

1. The 2000-2004 Game Summary layout (on-ice skaters inside the scoring summary,
   strength column last, legacy footer timestamp). It matters because those reports
   are FROZEN at game time, which is what makes a 20-year-old correction detectable
   at all - if the parser cannot read them, the earliest detectable era silently
   shrinks.

2. The ingest path's anti-invention rules. Every test in ``TestIngestRules`` fails
   if the code starts filling a gap instead of flagging it.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest

from nhl_monitor import ingest, parse, store

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(name: str) -> str:
    with open(os.path.join(FIXTURES, name)) as fh:
        return fh.read()


def _case(filename: str) -> dict:
    with open(os.path.join(ingest.INBOX_DIR, filename)) as fh:
        return json.load(fh)


class TestEra2000To2004(unittest.TestCase):
    """The oldest era the official report host still serves."""

    def setUp(self):
        self.st = parse.parse_gs_report(
            _read("gs_20002001_020001.html"),
            url="https://www.nhl.com/scores/htmlreports/20002001/GS020001.HTM",
            retrieved_at="2026-10-07T00:00:00Z", game_id=2000020001, season="20002001")

    def test_goals_parse_with_the_on_ice_columns_present(self):
        self.assertEqual(len(self.st.goals), 4)
        self.assertEqual([g.clock for g in self.st.sorted_goals()],
                         ["12:40", "19:59", "2:00", "18:31"])
        self.assertEqual([g.team for g in self.st.sorted_goals()],
                         ["DAL", "DAL", "COL", "COL"])
        # strength is the LAST column in this era
        self.assertEqual([g.strength for g in self.st.sorted_goals()],
                         ["EV", "PP", "EV", "PP"])

    def test_scorers_assists_and_totals(self):
        goals = {g.clock: g for g in self.st.goals}
        self.assertEqual(goals["12:40"].scorer.name, "S. ZUBOV")
        self.assertEqual([a.name for a in goals["12:40"].assists], ["M. MODANO", "J. LEHTINEN"])
        self.assertEqual(goals["19:59"].scorer.name, "M. MODANO")
        self.assertEqual([a.name for a in goals["19:59"].assists], ["D. SYDOR"])
        self.assertEqual([a.name for a in goals["18:31"].assists], ["C. DRURY"])
        self.assertEqual(self.st.goal_count("COL"), 2)
        self.assertEqual(self.st.goal_count("DAL"), 2)

    def test_on_ice_digits_are_not_mistaken_for_players_or_goals(self):
        # the on-ice column is bare sweater numbers: it must add no players and no goals
        names = {g.scorer.name for g in self.st.goals}
        self.assertNotIn("21", names)
        self.assertNotIn("77", names)
        # Zubov 2 + Modano 1 + Podein 2 + Deadmarsh 1
        self.assertEqual(sum(len(g.assists) for g in self.st.goals), 6)

    def test_teams_come_from_the_logo_images_and_no_league_shield_in_this_era(self):
        # this era has no logocnhl.gif shield, so the ordering fallback must still work
        self.assertEqual((self.st.away.abbrev, self.st.home.abbrev), ("COL", "DAL"))
        self.assertEqual((self.st.away.score, self.st.home.score), (2, 2))

    def test_bench_penalty_row_does_not_create_a_player(self):
        blob = json.dumps([g.as_dict() for g in self.st.goals])
        self.assertNotIn("Team", blob)

    def test_legacy_footer_is_read_and_proves_the_report_is_frozen_at_game_time(self):
        self.assertEqual(self.st.game_date, "2000-10-04")
        self.assertEqual(self.st.report_generated_at, "2000-10-04 22:14:20")
        frozen, note = parse.report_era(self.st.game_date, self.st.report_generated_at)
        self.assertTrue(frozen, note)
        self.assertIn("frozen", note)


class TestStatementParser(unittest.TestCase):
    """The league's fixed announcement format must stay machine-readable."""

    REAL = [
        ("CS A",
         "OFFICIAL SCORING CHANGE: Game 1,140\n@NJDevils at @NHLBlackhawks\n\n"
         "Goal at 6:50 of the first period now reads Dawson Mercer from Luke Hughes "
         "and Nico Hischier. #NHLStats",
         1140, "6:50", 1, "Dawson Mercer", ["Luke Hughes", "Nico Hischier"]),
        ("CS B",
         "OFFICIAL SCORING CHANGE: Game 1238\n@NHLBruins at @NJDevils\n\n"
         "Goal at 9:38 of the first period now reads David Pastrnak from Morgan Geekie. #NHLStats",
         1238, "9:38", 1, "David Pastrnak", ["Morgan Geekie"]),
        ("CS C",
         "OFFICIAL SCORING CHANGE: Game 1185\n@PredsNHL at @BlueJacketsNHL\n\n"
         "Goal at 9:02 of the third period now reads Jordan Oesterle from Cole Smith "
         "and Michael McCarron. #NHLStats",
         1185, "9:02", 3, "Jordan Oesterle", ["Cole Smith", "Michael McCarron"]),
    ]

    def test_parses_every_real_announcement(self):
        for label, text, game_no, clock, period, scorer, assists in self.REAL:
            with self.subTest(label):
                got = ingest.parse_scoring_change_statement(text)
                self.assertTrue(got["ok"], got["problems"])
                self.assertEqual(got["game_no"], game_no)
                self.assertEqual(got["clock"], clock)
                self.assertEqual(got["period"], period)
                self.assertEqual(got["scorer"], scorer)
                self.assertEqual(got["assists"], assists)

    def test_handles_the_no_space_and_dash_renderings(self):
        got = ingest.parse_scoring_change_statement(
            "OFFICIAL SCORING CHANGE: Game 1,140@NJDevils at @NHLBlackhawks Goal at 6:50 of the "
            "first period now reads: Dawson Mercer from Luke Hughes and Nico Hischier. #NHLStats")
        self.assertTrue(got["ok"], got["problems"])
        self.assertEqual(got["game_no"], 1140)
        self.assertEqual(got["away_handle"], "@njdevils")
        self.assertEqual(got["assists"], ["Luke Hughes", "Nico Hischier"])

    def test_unassisted_and_overtime_words(self):
        got = ingest.parse_scoring_change_statement(
            "OFFICIAL SCORING CHANGE: Game 7 @A at @B Goal at 1:02 of the overtime period now reads "
            "J. Doe unassisted. #NHLStats")
        self.assertTrue(got["ok"], got["problems"])
        self.assertEqual(got["scorer"], "J. Doe")
        self.assertEqual(got["assists"], [])
        self.assertEqual(got["period"], 4)

    def test_rejects_text_that_is_not_a_scoring_change(self):
        got = ingest.parse_scoring_change_statement("NHL announces a fine for diving.")
        self.assertFalse(got["ok"])
        self.assertIsNone(got["game_no"])
        self.assertIn("OFFICIAL SCORING CHANGE", got["problems"][0])


class TestIngestRules(unittest.TestCase):
    """The ingest path must flag gaps, never fill them."""

    def test_all_shipped_case_files_build_cleanly(self):
        built = ingest.ingest_cases(dry_run=True)
        self.assertEqual(len(built), 3)
        for rec in built:
            self.assertEqual(store.validate(rec), [])
            self.assertEqual(rec["game"]["season"], "20242025")
            self.assertEqual(rec["change"]["affects_goal_total"], False)
            self.assertEqual(rec["change"]["attribution_only"], True)
            self.assertEqual(rec["settlement"]["could_affect_game_total_market"], False)
            self.assertEqual(rec["settlement"]["could_affect_player_props"], True)
            self.assertEqual(rec["evidence_status"],
                             "verified_corrected_state_and_official_announcement")
            self.assertEqual(rec["timing"]["when"], "postgame_after_publication")

    def test_record_ids_come_from_the_game_id_and_statement_numbers_agree(self):
        built = {r["case_id"]: r for r in ingest.ingest_cases(dry_run=True)}
        self.assertEqual(built["CS-2025-03-26-NJD-AT-CHI-G1140"]["record_id"],
                         "NHL-20242025-021140-01")
        self.assertEqual(built["CS-2025-04-08-BOS-AT-NJD-G1238"]["record_id"],
                         "NHL-20242025-021238-01")
        self.assertEqual(built["CS-2025-04-01-NSH-AT-CBJ-G1185"]["record_id"],
                         "NHL-20242025-021185-01")

    def test_latency_is_measured_only_from_documented_times(self):
        built = {r["case_id"]: r for r in ingest.ingest_cases(dry_run=True)}
        # 2025-03-27T02:02:00Z (end) -> 2025-03-27T04:51:19Z (announcement)
        self.assertEqual(
            built["CS-2025-03-26-NJD-AT-CHI-G1140"]["timing"]["latency_after_final_buzzer_seconds"],
            10159)
        self.assertEqual(
            built["CS-2025-04-08-BOS-AT-NJD-G1238"]["timing"]["latency_after_final_buzzer_seconds"],
            12212)
        # no documented end time -> no number at all
        case = _case("2025-03-26-njd-at-chi-g1140.json")
        case["game"].pop("game_ended_at_utc")
        self.assertIsNone(ingest.build_record(case)["timing"]["latency_after_final_buzzer_seconds"])

    def test_unavailable_initial_state_is_flagged_not_invented(self):
        case = _case("2025-04-01-nsh-at-cbj-g1185.json")
        rec = ingest.build_record(case)
        self.assertIsNone(rec["initial_state"]["assists"])
        self.assertIn("initial_state_not_retrievable_from_any_source", rec["flags"])
        self.assertIn("assists_before_the_change_not_captured", rec["flags"])
        self.assertEqual(rec["change"]["machine_diff"]["assists"], "indeterminate")

    def test_a_corrected_state_without_an_official_source_is_rejected(self):
        case = _case("2025-04-08-bos-at-njd-g1238.json")
        case["corrected_state_sources"] = []
        with self.assertRaises(ValueError):
            ingest.build_record(case)

    def test_disagreeing_announcement_is_flagged_not_silently_resolved(self):
        case = _case("2025-04-08-bos-at-njd-g1238.json")
        case["official_announcement"]["text"] = case["official_announcement"]["text"].replace(
            "9:38", "11:38")
        rec = ingest.build_record(case)
        self.assertIn("announcement_clock_disagrees_with_curated_event", rec["flags"])

    def test_scorer_disagreement_is_flagged(self):
        case = _case("2025-03-26-njd-at-chi-g1140.json")
        case["corrected_state"]["scorer"]["name"] = "Someone Else"
        rec = ingest.build_record(case)
        self.assertIn("announcement_scorer_disagrees_with_verified_corrected_state", rec["flags"])

    def test_a_change_the_states_do_not_show_is_flagged(self):
        case = _case("2025-04-08-bos-at-njd-g1238.json")
        case["corrected_state"]["assists"] = copy.deepcopy(case["initial_state"]["assists"])
        rec = ingest.build_record(case)
        self.assertTrue(any(f.startswith("declared_change_not_visible_in_declared_states")
                            for f in rec["flags"]), rec["flags"])

    def test_undocumented_change_present_in_the_states_is_flagged(self):
        case = _case("2025-04-08-bos-at-njd-g1238.json")
        case["declared_changes"] = []
        rec = ingest.build_record(case)
        self.assertIn("machine_derived_change_not_declared:assist_change", rec["flags"])

    def test_announcement_before_the_game_end_is_flagged(self):
        case = _case("2025-04-08-bos-at-njd-g1238.json")
        case["official_announcement"]["issued_at_utc"] = "2025-04-08T01:00:00Z"
        rec = ingest.build_record(case)
        self.assertIn("announcement_precedes_documented_end_of_game", rec["flags"])

    def test_same_day_announcement_is_not_claimed_to_be_post_final(self):
        case = _case("2025-04-08-bos-at-njd-g1238.json")
        case["official_announcement"]["issued_on"] = "2025-04-08"
        rec = ingest.build_record(case)
        self.assertEqual(rec["timing"]["when"], "same_day_as_game_clock_not_recorded")
        self.assertIn("timing_not_established_as_post_final", rec["flags"])

    def test_unknown_declared_change_type_is_rejected(self):
        case = _case("2025-04-08-bos-at-njd-g1238.json")
        case["declared_changes"] = [{"change_type": "vibes_change", "detail": "nope"}]
        with self.assertRaises(ValueError):
            ingest.build_record(case)

    def test_every_record_carries_the_statement_url_and_a_corrected_state_url(self):
        for rec in ingest.ingest_cases(dry_run=True):
            urls = [s.get("url") or "" for s in rec["sources"]]
            self.assertTrue(any("x.com/NHLPR/status/" in u for u in urls), urls)
            self.assertTrue(any("nhl.com/scores/htmlreports/" in u for u in urls), urls)
            self.assertTrue(any(s.get("type") == "official-document" for s in rec["sources"]))

    def test_ingest_is_idempotent_and_keeps_revisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "records.json")
            first = ingest.ingest_cases(path=path)
            self.assertEqual(len(first), 3)
            with open(path) as fh:
                blob = json.load(fh)
            self.assertEqual(blob["count"], 3)
            self.assertTrue(all(r.get("revision") == 1 for r in blob["records"]))
            again = ingest.ingest_cases(path=path)
            self.assertEqual(len(again), 3)
            with open(path) as fh:
                blob2 = json.load(fh)
            self.assertEqual(blob2["count"], 3)
            self.assertTrue(all(r.get("revision") == 1 for r in blob2["records"]),
                            "re-running the ingest must not churn revisions")
            self.assertEqual([r["record_id"] for r in blob["records"]],
                             [r["record_id"] for r in blob2["records"]])

    def test_shipped_database_is_reproducible_from_the_inbox(self):
        """The committed records must equal what the committed case files produce."""
        shipped = {r["record_id"]: r for r in store.load_records()}
        self.assertEqual(len(shipped), 3, "the shipped database should hold the 3 seeded records")
        for rec in ingest.ingest_cases(dry_run=True):
            self.assertIn(rec["record_id"], shipped)
            self.assertEqual(store._comparable(rec), store._comparable(shipped[rec["record_id"]]))

    def test_no_record_claims_a_game_total_change_without_a_goal_change(self):
        for rec in ingest.ingest_cases(dry_run=True):
            self.assertFalse(rec["change"]["affects_goal_total"])
            self.assertFalse(rec["settlement"]["could_affect_game_total_market"])
            self.assertTrue(rec["settlement"]["requires_book_specific_review"],
                            "an attribution-only change still needs book-specific review")


if __name__ == "__main__":
    unittest.main()
