"""Parser tests.

These are not decoration. Every claim this project makes on nhl.com data flows
through a parser, and a parser that silently mis-reads a column would produce a
database full of confident nonsense. So the tests are pinned to real,
transcribed official values (see the provenance note in each fixture), and the
assertions are about specific names, times and credits rather than counts.
"""

from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "pipeline")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from _path import fixture_json, fixture_text  # noqa: E402

from nhl_scoring.models import ascii_fold, clock_to_seconds, parse_report_player  # noqa: E402
from nhl_scoring.parsers import (  # noqa: E402
    extract_rows,
    norm_period,
    parse_api_landing,
    parse_api_right_rail,
    parse_gs_report,
)
from nhl_scoring.sources import GameRef, REPORT_CODES  # noqa: E402


class NameTests(unittest.TestCase):
    def test_folding(self):
        self.assertEqual(ascii_fold("Lidström"), "lidstrom")
        self.assertEqual(ascii_fold("BRIND'AMOUR"), "brindamour")
        self.assertEqual(ascii_fold("ÖHGREN"), "ohgren")
        self.assertEqual(ascii_fold(""), "")

    def test_legacy_cell(self):
        p = parse_report_player("S. FEDOROV (2)")
        self.assertIsNotNone(p)
        self.assertEqual((p.surname, p.initial, p.counter, p.sweater_number),
                         ("fedorov", "s", 2, None))

    def test_modern_cell_with_number(self):
        p = parse_report_player("67 M.PACIORETTY(1)")
        self.assertEqual((p.surname, p.initial, p.counter, p.sweater_number),
                         ("pacioretty", "m", 1, 67))

    def test_multiword_surname_matches_json_form(self):
        gs = parse_report_player("21 J.VAN RIEMSDYK(1)")
        self.assertEqual(gs.surname_tail, "riemsdyk")

    def test_non_players_are_rejected(self):
        # on-ice lists and the shots-by-period column must never look like a name
        for cell in ("11, 14, 31, 67, 76, 79", "3 39 33 15 10", "", "-", "8, 23, 25, 42"):
            self.assertIsNone(parse_report_player(cell), f"should not parse: {cell!r}")

    def test_own_goal_cell(self):
        p = parse_report_player("55 J.SMOINS (OWN GOAL)")
        self.assertIsNotNone(p)
        self.assertEqual(p.surname, "smoins")


class ClockAndPeriodTests(unittest.TestCase):
    def test_clock(self):
        self.assertEqual(clock_to_seconds("2:00"), 120)
        self.assertEqual(clock_to_seconds("02:00"), 120)
        self.assertEqual(clock_to_seconds("19:59"), 1199)
        self.assertIsNone(clock_to_seconds("bad"))

    def test_period(self):
        self.assertEqual(norm_period("3"), (3, "REG"))
        self.assertEqual(norm_period("OT"), (4, "OT"))
        self.assertEqual(norm_period("2OT"), (5, "OT"))
        self.assertEqual(norm_period("SO"), (5, "SO"))
        self.assertEqual(norm_period("1"), (1, "REG"))


class GameRefTests(unittest.TestCase):
    def test_report_url_matches_official_scheme(self):
        ref = GameRef("2000020001")
        self.assertEqual(ref.report_url("GS"),
                         "https://www.nhl.com/scores/htmlreports/20002001/GS020001.HTM")
        self.assertEqual(ref.season_dir, "20002001")
        self.assertEqual(ref.game_type, "REG")
        self.assertEqual(GameRef("2000030162").game_type, "PO")
        self.assertEqual(ref.gamecenter_landing, "https://api-web.nhle.com/v1/gamecenter/2000020001/landing")

    def test_rejects_malformed_ids(self):
        for bad in ("2000-02-0001", "12345", "2000990001", ""):
            with self.assertRaises(ValueError):
                GameRef(bad)

    def test_all_report_codes_build(self):
        ref = GameRef("2026020001")
        for code in REPORT_CODES:
            self.assertTrue(ref.report_url(code).endswith(f"/{code}020001.HTM"), code)
        with self.assertRaises(ValueError):
            ref.report_url("XX")


class LegacyGsTests(unittest.TestCase):
    """2000-01 Game Summary sheet - the layout the historical database depends on."""

    def setUp(self):
        self.rec = parse_gs_report(fixture_text("official_2000020001_gs.htm"),
                                   game_id="2000020001", url="https://example.invalid/gs.htm",
                                   retrieved_at="2026-10-07T00:00:00Z")

    def test_parsed_four_goals(self):
        self.assertTrue(self.rec.parse_ok, self.rec.parse_notes)
        self.assertEqual(self.rec.goal_count, 4)
        self.assertEqual(self.rec.extra["layout"], "legacy")

    def test_values_are_verbatim(self):
        g4 = self.rec.goals[3]
        self.assertEqual((g4.period, g4.clock, g4.team, g4.strength), (2, "18:31", "COL", "PP"))
        self.assertEqual(g4.scorer.name, "A. DEADMARSH")
        self.assertEqual([a.name for a in g4.assists], ["C. DRURY"])

    def test_missing_assist_slot_is_not_invented(self):
        self.assertEqual(len(self.rec.goals[1].assists), 1)
        self.assertEqual(len(self.rec.goals[3].assists), 1)

    def test_generation_stamp_parsed(self):
        # the footer stamp is the as-of bound for the whole historical record
        self.assertEqual(self.rec.generated_at, "2000-10-04T22:14:20")

    def test_date_from_header(self):
        self.assertEqual(self.rec.game_date, "2000-10-04")

    def test_legacy_totals_bound_to_teams(self):
        self.assertEqual(self.rec.totals["COL"].goals, 2)
        self.assertEqual(self.rec.totals["DAL"].shots, 21)
        self.assertEqual(self.rec.totals["COL"].goals_by_period.get(2), 2)


class ModernGsTests(unittest.TestCase):
    def setUp(self):
        self.rec = parse_gs_report(fixture_text("official_20152016_gs020001.htm"),
                                   game_id="2015020001", url="https://example.invalid/gs.htm")

    def test_layout_and_counts(self):
        self.assertTrue(self.rec.parse_ok, self.rec.parse_notes)
        self.assertEqual(self.rec.extra["layout"], "modern")
        self.assertEqual(self.rec.goal_count, 4)

    def test_empty_net_strength_is_preserved_verbatim(self):
        self.assertEqual(self.rec.goals[3].strength_raw, "EV-EN")
        self.assertEqual(self.rec.goals[3].strength, "EV")

    def test_onice_lists_not_mistaken_for_assists(self):
        self.assertLessEqual(len(self.rec.goals[0].assists), 1)
        for goal in self.rec.goals:
            for assist in goal.assists:
                self.assertGreater(len(assist.surname), 2)

    def test_by_period_bound_by_header_abbrevs(self):
        self.assertEqual(self.rec.totals["MTL"].goals, 3)
        self.assertEqual(self.rec.totals["TOR"].shots, 37)

    def test_sweater_numbers_survive(self):
        self.assertEqual(self.rec.goals[0].scorer.sweater_number, 67)


class ApiLandingTests(unittest.TestCase):
    def setUp(self):
        self.rec = parse_api_landing(fixture_json("official_2000020001_api_landing_excerpt.json"),
                                     game_id="2000020001", url="https://example.invalid/landing")

    def test_goals(self):
        self.assertEqual(self.rec.goal_count, 4)
        self.assertEqual(self.rec.away_abbrev, "COL")
        self.assertEqual(self.rec.away_score, 2)
        g4 = self.rec.goals[3]
        self.assertEqual([a.name_key for a in g4.assists], ["drury:c", "sakic:j"])
        self.assertEqual(g4.scorer.player_id, 8459436)
        self.assertEqual(g4.event_id, 10060839)

    def test_empty_blocks_do_not_become_goals(self):
        self.assertEqual(self.rec.goals[0].period, 1)
        self.assertTrue(all(g.period in (1, 2) for g in self.rec.goals))

    def test_limited_scoring_is_a_gap_not_a_zero(self):
        rec = parse_api_landing({"id": 2026020001, "limitedScoring": True, "summary": {"scoring": []},
                                 "awayTeam": {"abbrev": "FLA"}, "homeTeam": {"abbrev": "CAR"}},
                               game_id="2026020001", url="x")
        self.assertFalse(rec.parse_ok)
        self.assertTrue(any("limitedScoring" in n for n in rec.parse_notes))

    def test_ot_period_blocks_parse(self):
        rec = parse_api_landing({"id": 2026020001,
                                 "awayTeam": {"abbrev": "FLA", "score": 1},
                                 "homeTeam": {"abbrev": "CAR", "score": 0},
                                 "summary": {"scoring": [
                                     {"periodDescriptor": {"number": 4, "periodType": "OT"},
                                      "goals": [{"timeInPeriod": "04:55", "teamAbbrev": {"default": "FLA"},
                                                 "lastName": {"default": "Forsling"},
                                                 "firstName": {"default": "Gustav"},
                                                 "strength": "ev", "awayScore": 1, "homeScore": 0,
                                                 "assists": [{"lastName": {"default": "Verhaeghe"},
                                                              "firstName": {"default": "Carter"}}]}]}]}},
                                game_id="2026020001", url="x")
        self.assertEqual(rec.goal_count, 1)
        self.assertEqual(rec.goals[0].period, 4)
        self.assertEqual(rec.goals[0].scorer.surname_tail, "forsling")


class RightRailTests(unittest.TestCase):
    def test_reports_and_linescore(self):
        payload = fixture_json("official_2026020001_right_rail_excerpt.json")
        info = parse_api_right_rail(payload, GameRef("2026020001"))
        self.assertEqual(info["reports"]["GS"],
                         "https://www.nhl.com/scores/htmlreports/20262027/GS020001.HTM")
        self.assertEqual(len(info["reports"]), 9)
        self.assertEqual(info["by_period"][-1], {"period": 4, "period_type": "OT", "away": 1, "home": 0})
        self.assertEqual(info["team_stats"][2]["category"], "powerPlay")

    def test_missing_reports_block_is_empty_not_wrong(self):
        info = parse_api_right_rail({}, GameRef("2026020001"))
        self.assertEqual(info["reports"], {})
        self.assertEqual(info["by_period"], [])


class RobustnessTests(unittest.TestCase):
    def test_garbage_is_a_parse_failure_not_an_empty_game(self):
        rec = parse_gs_report("<html><body>404 Not Found</body></html>", game_id="2000020001",
                              url="https://example.invalid/missing.htm")
        self.assertFalse(rec.parse_ok)
        self.assertEqual(rec.goal_count, 0)
        self.assertTrue(rec.parse_notes)

    def test_error_page_html_has_no_rows(self):
        self.assertEqual(extract_rows("<p>no tables here</p>"), [])

    def test_header_without_team_column_refuses(self):
        markup = ("<table><tr><td>G</td><td>Per</td><td>Time</td><td>Goal Scorer</td></tr>"
                  "<tr><td>1</td><td>1</td><td>1:00</td><td>A. PLAYER (1)</td></tr></table>")
        rec = parse_gs_report(markup, game_id="2000020001", url="x")
        self.assertFalse(rec.parse_ok)
        self.assertTrue(any("Team" in n for n in rec.parse_notes))


if __name__ == "__main__":
    unittest.main()
