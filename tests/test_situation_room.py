"""Situation Room feed parser, classifier, cross-check and record builder.

Fixtures under ``tests/fixtures/situation_room/`` are verbatim statements from
the league content API (``forge-dapi.d3.nhle.com``) captured 2026-10-07; the
play-by-play fixtures are reduced to the events that matter, with the event
ids, clocks, reasons and player ids copied from the live documents read the
same day (see docs/VERIFICATION_LOG.md).
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from tests._path import fixture_json  # noqa: F401  (adds pipeline/ to sys.path)

from nhl_scoring import db as db_mod  # noqa: E402
from nhl_scoring import situation_room as sr  # noqa: E402

SR = "situation_room/"


def _pbp(game_id, away, home, away_id, home_id, away_score, home_score, plays, roster=()):
    return {
        "id": int(game_id), "gameDate": "2026-10-06", "gameState": "OFF",
        "venue": {"default": "Test Arena"},
        "awayTeam": {"id": away_id, "abbrev": away, "score": away_score},
        "homeTeam": {"id": home_id, "abbrev": home, "score": home_score},
        "rosterSpots": [
            {"teamId": tid, "playerId": pid, "firstName": {"default": fn}, "lastName": {"default": ln}, "sweaterNumber": num}
            for tid, pid, fn, ln, num in roster
        ],
        "plays": plays,
    }


def _play(event_id, period, time, kind, details=None):
    return {"eventId": event_id, "periodDescriptor": {"number": period, "periodType": "REG" if period <= 3 else "OT"},
            "timeInPeriod": time, "typeDescKey": kind, "details": details or {}}


# Reduced from api-web play-by-play 2026020044 (read 2026-10-07): the Nylander
# goal is absent from the final record; the challenge stoppage sits at 11:46.
PBP_NSH_TOR = _pbp("2026020044", "NSH", "TOR", 18, 10, 2, 3, [
    _play(440, 3, "10:02", "shot-on-goal", {"eventOwnerTeamId": 10}),
    _play(454, 3, "11:46", "stoppage", {"reason": "chlg-vis-off-side", "secondaryReason": "chlg-vis-off-side"}),
    _play(471, 3, "11:46", "offside", {"eventOwnerTeamId": 10}),
    _play(962, 3, "11:46", "faceoff", {"eventOwnerTeamId": 18, "zoneCode": "N"}),
])

# Reduced from api-web play-by-play 2026020015 (read 2026-10-07): Rossi's goal
# at 04:43 with its video-review stoppage.
PBP_EDM_VAN = _pbp("2026020015", "EDM", "VAN", 22, 23, 9, 7, [
    _play(43, 3, "04:43", "stoppage", {"reason": "referee-or-linesman", "secondaryReason": "video-review"}),
    _play(899, 3, "04:43", "goal", {"eventOwnerTeamId": 23, "scoringPlayerId": 8482079, "scoringPlayerTotal": 3,
                                    "assist1PlayerId": 8483395, "assist1PlayerTotal": 1,
                                    "assist2PlayerId": 8474568, "assist2PlayerTotal": 1,
                                    "awayScore": 5, "homeScore": 8, "shotType": "deflected", "goalieInNetId": 8482221}),
], roster=[(23, 8482079, "Marco", "Rossi", 23), (23, 8483395, "Arshdeep", "Bains", 13), (23, 8474568, "Luke", "Schenn", 2)])

# Reduced from api-web play-by-play 2016020214 (read 2026-10-07).
PBP_NYI_FLA = _pbp("2016020214", "NYI", "FLA", 2, 13, 2, 3, [
    _play(292, 2, "14:53", "stoppage", {"reason": "chlg-vis-goal-interference", "secondaryReason": "chlg-vis-goal-interference"}),
    _play(415, 2, "14:53", "faceoff", {"eventOwnerTeamId": 13, "zoneCode": "N"}),
])


class TestHeadline(unittest.TestCase):
    def test_structured_headline_with_curly_apostrophe_and_trailing_space(self):
        h = sr.parse_headline("Coach\u2019s Challenge: NSH @ TOR \u2013 11:49 of the Third Period ")
        self.assertEqual((h["kind"], h["away"], h["home"], h["clock"], h["period"]), ("coach_challenge", "NSH", "TOR", "11:49", 3))

    def test_prose_era_headline_without_the(self):
        h = sr.parse_headline("Coach's Challenge: NYI @ FLA - 14:53 of Second Period")
        self.assertEqual((h["kind"], h["clock"], h["period"]), ("coach_challenge", "14:53", 2))

    def test_overtime_and_double_overtime(self):
        self.assertEqual(sr.parse_headline("Video Review: TBL @ FLA \u2013 2:13 of Overtime")["period"], 4)
        self.assertEqual(sr.parse_headline("Video Review: DAL @ COL \u2013 7:12 of the Second Overtime")["period"], 5)

    def test_all_star_headline_has_no_game(self):
        h = sr.parse_headline("Coach's Challenge: NHL All-Star Game")
        self.assertIsNone(h["clock"])
        self.assertIsNone(h["away"])

    def test_abbrev_aliases(self):
        self.assertEqual(sr.parse_headline("Coach's Challenge: NYR @ NJ - 1:00 of the First Period")["home"], "NJD")


class TestClassifier(unittest.TestCase):
    def test_structured_overturned_challenge(self):
        r = sr.ruling_from_item(fixture_json(SR + "nsh_tor_2026_coach_challenge.json"))
        self.assertEqual(r.game_id, "2026020044")
        self.assertEqual(r.game_date, "2026-10-06")
        self.assertEqual(r.season, "20262027")
        self.assertEqual(r.initiated_by, "Nashville")
        self.assertEqual(r.review_type, "Off-Side")
        self.assertFalse(r.review_type_inferred)
        self.assertEqual((r.on_ice_call, r.final_call, r.changed, r.outcome, r.confidence),
                         ("goal", "no_goal", True, "overturned", "high"))
        self.assertEqual(r.final_team, "TOR")
        self.assertEqual(r.rule_citations, ["38", "38.1", "38.9"])
        self.assertEqual(r.clock_reset, {"shows": "08:14", "elapsed": "11:46"})
        self.assertEqual(r.format, "structured")
        self.assertEqual(r.flags, [])

    def test_rule_quotation_does_not_leak_into_verdict(self):
        # The explanation quotes Rule 38.1 ("...will be overturned if, and only if...")
        # and the quotation must not be what decides the outcome.
        item = fixture_json(SR + "nsh_tor_2026_coach_challenge.json")
        item["parts"][1]["content"] = item["parts"][1]["content"].replace(
            "Call on the ice is overturned \u2013 No Goal Toronto", "Call on the ice is upheld \u2013 Goal Toronto")
        r = sr.ruling_from_item(item)
        self.assertEqual((r.changed, r.outcome), (False, "upheld"))

    def test_on_ice_call_not_stated_is_not_guessed(self):
        r = sr.ruling_from_item(fixture_json(SR + "cgy_van_2026_video_review_on_ice_not_stated.json"))
        self.assertEqual(r.final_call, "goal")
        self.assertIsNone(r.changed)
        self.assertEqual(r.outcome, "on_ice_call_not_stated")
        self.assertIn("on_ice_call_not_stated", r.flags)
        self.assertEqual(r.initiated_by, "NHL Situation Room")
        self.assertIsNone(sr.ruling_to_record(r, run_id="t"))

    def test_initial_ruling_sentence_naming_an_infraction(self):
        r = sr.ruling_from_item(fixture_json(SR + "edm_van_2026_video_review_untagged.json"))
        self.assertIsNone(r.game_id)
        self.assertIn("game_id_not_tagged", r.flags)
        self.assertEqual((r.on_ice_call, r.final_call, r.changed, r.outcome, r.confidence),
                         ("no_goal", "goal", True, "overturned", "medium"))
        self.assertIn("on_ice_call_inferred_from_wording", r.flags)
        self.assertEqual(r.review_type, "Batted Puck")
        self.assertEqual(r.final_team, "VAN")

    def test_prose_era_overturned_with_short_quotes(self):
        r = sr.ruling_from_item(fixture_json(SR + "nyi_fla_2016_coach_challenge_prose.json"))
        self.assertEqual(r.format, "prose")
        self.assertEqual(r.game_id, "2016020214")
        self.assertEqual(r.game_date, "2016-11-12")
        # last on-ice statement is "changed to good goal"; the short quotes must survive quotation stripping
        self.assertEqual((r.on_ice_call, r.final_call, r.changed, r.outcome), ("goal", "no_goal", True, "overturned"))
        self.assertEqual(r.initiated_by, "New York")
        self.assertEqual(r.review_type, "Goaltender Interference")
        self.assertTrue(r.review_type_inferred)
        self.assertEqual(r.final_team, "FLA")
        self.assertEqual(r.rule_citations, ["78.7"])

    def test_prose_upheld(self):
        item = {"headline": "Coach's Challenge: BUF @ CBJ - 14:11 of First Period",
                "fields": {"description": "Good goal Buffalo Sabres"},
                "tags": [{"slug": "gameid-2018020154", "title": "BUF@CBJ 10/27/2018 07:00PM"}],
                "parts": [{"type": "markdown", "content":
                    "At 14:11 of the first period in the Sabres/Blue Jackets game, Columbus requested a Coach's "
                    "Challenge to review whether a Buffalo player interfered with Columbus goaltender Sergei Bobrovsky "
                    "prior to the goal. After reviewing all available replays and consulting with NHL Hockey Operations "
                    "staff, the Referee confirmed no goaltender interference infractions occurred before the puck crossed "
                    "the goal line. According to Rule 78.7, \"The standard for overturning the call in the event of a "
                    "'GOAL' call on the ice is that the Referee determines that the goal should have been disallowed.\" "
                    "Therefore the original call stands - good goal Buffalo Sabres."}]}
        r = sr.ruling_from_item(item)
        self.assertEqual((r.changed, r.outcome, r.final_call, r.final_team, r.initiated_by), (False, "upheld", "goal", "BUF", "Columbus"))

    def test_verdict_team_prefers_words_after_the_verdict(self):
        self.assertEqual(sr.team_from_words("Puck did not cross Ottawa goal line - no goal Montreal", ("OTT", "MTL")), "MTL")
        self.assertIsNone(sr.team_from_words("Ottawa and Montreal", ("OTT", "MTL")))

    def test_structured_upheld_and_confirmed(self):
        item = {"headline": "Coach\u2019s Challenge: VGK @ SEA \u2013 8:16 of the First Period", "fields": {},
                "tags": [{"slug": "gameid-2026020051", "title": "VGK@SEA 10/06/2026 10:00PM"}],
                "parts": [{"type": "markdown", "content": "**Challenge Initiated By:** Seattle\n\n**Type of Challenge:** Goaltender Interference\n\n"
                                                           "**Result:** Call on the ice is upheld \u2013 Goal Vegas\n\n**Explanation:** Video review supported the Referees\u2019 call."}]}
        r = sr.ruling_from_item(item)
        self.assertEqual((r.changed, r.outcome, r.final_team, r.on_ice_call), (False, "upheld", "VGK", "goal"))
        self.assertIsNone(sr.ruling_to_record(r, run_id="t"))

    def test_structured_initially_ruled_goal_then_no_goal(self):
        item = {"headline": "Video Review: COL @ DAL \u2013 12:01 of the Second Period", "fields": {},
                "tags": [{"slug": "gameid-2025021000", "title": "COL@DAL 03/01/2026 07:00PM"}],
                "parts": [{"type": "markdown", "content": "**Type of Review:** Distinct Kicking Motion\n\n**Result:** No Goal Colorado\n\n"
                                                           "**Explanation:** The Referees initially ruled goal on the ice. Video review determined that a distinct kicking motion propelled the puck into the net. According to Rule 49.2, \u201cA goal cannot be scored by an attacking Player who uses a distinct kicking motion to propel the puck into the net with his skate/foot.\u201d"}]}
        r = sr.ruling_from_item(item)
        self.assertEqual((r.on_ice_call, r.final_call, r.changed, r.confidence), ("goal", "no_goal", True, "high"))
        self.assertEqual(r.rule_citations, ["49.2"])


class TestCrosscheck(unittest.TestCase):
    def test_disallowed_goal_absent_with_challenge_stoppage(self):
        r = sr.ruling_from_item(fixture_json(SR + "nsh_tor_2026_coach_challenge.json"))
        xc = sr.crosscheck_with_pbp(PBP_NSH_TOR, r)
        self.assertEqual(xc["status"], "agree")
        self.assertIsNone(xc["goal_event"])
        self.assertEqual(xc["review_stoppages"][0]["reason"], "chlg-vis-off-side")
        self.assertEqual(xc["review_stoppages"][0]["delta_seconds"], -3)
        self.assertEqual(xc["final_score"], {"away": 2, "home": 3})

    def test_disallowed_goal_still_present_is_a_conflict(self):
        r = sr.ruling_from_item(fixture_json(SR + "nsh_tor_2026_coach_challenge.json"))
        pbp = json.loads(json.dumps(PBP_NSH_TOR))
        pbp["plays"].append(_play(999, 3, "11:49", "goal", {"eventOwnerTeamId": 10, "scoringPlayerId": 1, "awayScore": 2, "homeScore": 4}))
        self.assertEqual(sr.crosscheck_with_pbp(pbp, r)["status"], "conflict")

    def test_awarded_goal_present_with_names(self):
        r = sr.ruling_from_item(fixture_json(SR + "edm_van_2026_video_review_untagged.json"))
        r.game_id = "2026020015"
        xc = sr.crosscheck_with_pbp(PBP_EDM_VAN, r)
        self.assertEqual(xc["status"], "agree")
        self.assertEqual(xc["goal_event"]["scorer"]["name"], "M. Rossi")
        self.assertEqual([a["name"] for a in xc["goal_event"]["assists"]], ["A. Bains", "L. Schenn"])
        self.assertEqual(xc["goal_event"]["event_id"], 899)
        self.assertEqual(xc["review_stoppages"][0]["secondary_reason"], "video-review")

    def test_awarded_goal_missing_is_a_conflict(self):
        r = sr.ruling_from_item(fixture_json(SR + "edm_van_2026_video_review_untagged.json"))
        r.game_id = "2026020015"
        pbp = json.loads(json.dumps(PBP_EDM_VAN))
        pbp["plays"] = [p for p in pbp["plays"] if p["typeDescKey"] != "goal"]
        self.assertEqual(sr.crosscheck_with_pbp(pbp, r)["status"], "conflict")

    def test_prose_era_game_cross_checks_too(self):
        r = sr.ruling_from_item(fixture_json(SR + "nyi_fla_2016_coach_challenge_prose.json"))
        xc = sr.crosscheck_with_pbp(PBP_NYI_FLA, r)
        self.assertEqual(xc["status"], "agree")
        self.assertEqual(xc["review_stoppages"][0]["reason"], "chlg-vis-goal-interference")


class TestRecord(unittest.TestCase):
    def test_overturned_record_validates_and_is_verified_only_with_agreeing_pbp(self):
        r = sr.ruling_from_item(fixture_json(SR + "nsh_tor_2026_coach_challenge.json"))
        rec = sr.ruling_to_record(r, run_id="t")
        self.assertEqual(db_mod.validate(rec), [])
        self.assertEqual(rec["status"], "flagged")
        self.assertIn("awaiting_pbp_crosscheck", rec["flags"])
        r.crosscheck = sr.crosscheck_with_pbp(PBP_NSH_TOR, r)
        rec = sr.ruling_to_record(r, run_id="t")
        self.assertEqual(db_mod.validate(rec), [])
        self.assertEqual(rec["status"], "verified")
        self.assertEqual(rec["detected_by"], "league_statement")
        self.assertEqual(rec["discrepancy"]["change_type"], "goal_overturned_to_no_goal")
        self.assertEqual(rec["discrepancy"]["field"], "goal_removed")
        self.assertTrue(rec["discrepancy"]["goal_no_goal_change"])
        self.assertTrue(rec["discrepancy"]["video_review"])
        self.assertEqual(rec["discrepancy"]["when_corrected"], "in_game")
        self.assertEqual(rec["discrepancy"]["market_impact"]["affects_game_total"], "yes")
        self.assertEqual(rec["initial_state"]["ruling"], "goal")
        self.assertEqual(rec["corrected_state"]["ruling"], "no_goal")
        self.assertEqual(rec["game"]["final_score"], {"away": 2, "home": 3})
        self.assertEqual(rec["totals"]["goal_delta"], -1)
        self.assertEqual(rec["record_id"], db_mod.compute_record_id("2026020044", "SR1", "goal_removed", "P3@11:49"))
        self.assertTrue(rec["sources"][0]["url"].startswith("https://www.nhl.com/news/"))
        self.assertEqual(sum(1 for s in rec["sources"] if s["evidence"] == "primary"), 3)
        self.assertIn("GS020044.HTM", rec["game"]["report_urls"]["GS"])

    def test_medium_confidence_record_stays_flagged_even_when_pbp_agrees(self):
        r = sr.ruling_from_item(fixture_json(SR + "edm_van_2026_video_review_untagged.json"))
        r.game_id, r.game_id_source, r.season = "2026020015", "schedule", "20262027"
        r.crosscheck = sr.crosscheck_with_pbp(PBP_EDM_VAN, r)
        rec = sr.ruling_to_record(r, run_id="t")
        self.assertEqual(db_mod.validate(rec), [])
        self.assertEqual(rec["status"], "flagged")
        self.assertIn("needs_human_read_of_on_ice_call", rec["flags"])
        self.assertIn("game_id_resolved_from_schedule", rec["flags"])
        self.assertEqual(rec["corrected_state"]["scorer"]["name"], "M. Rossi")
        self.assertEqual(rec["discrepancy"]["change_type"], "no_goal_overturned_to_goal")
        self.assertEqual(rec["totals"]["goal_delta"], 1)

    def test_conflict_record_is_flagged(self):
        r = sr.ruling_from_item(fixture_json(SR + "nsh_tor_2026_coach_challenge.json"))
        pbp = json.loads(json.dumps(PBP_NSH_TOR))
        pbp["plays"].append(_play(999, 3, "11:49", "goal", {"eventOwnerTeamId": 10, "scoringPlayerId": 1}))
        r.crosscheck = sr.crosscheck_with_pbp(pbp, r)
        rec = sr.ruling_to_record(r, run_id="t")
        self.assertEqual(rec["status"], "flagged")
        self.assertIn("pbp_conflicts_with_situation_room_statement", rec["flags"])


class TestIngestOffline(unittest.TestCase):
    def test_ingest_pages_and_ledger_roundtrip(self):
        items = [fixture_json(SR + n) for n in ("nsh_tor_2026_coach_challenge.json",
                                                 "cgy_van_2026_video_review_on_ice_not_stated.json",
                                                 "edm_van_2026_video_review_untagged.json",
                                                 "nyi_fla_2016_coach_challenge_prose.json")]
        pbps = {"2026020044": PBP_NSH_TOR, "2016020214": PBP_NYI_FLA}

        def loader(gid):
            return pbps.get(gid), None

        with tempfile.TemporaryDirectory() as tmp:
            ledger = os.path.join(tmp, "rulings.json")
            out = sr.ingest(None, ledger_path=ledger, pages=[items], pbp_loader=loader, resolve_ids=False, run_id="t1")
            self.assertEqual(out["stats"]["new"], 4)
            self.assertEqual(out["stats"]["crosschecked"], 2)
            self.assertEqual(len(out["records"]), 2)          # untagged Rossi item has no game id -> ledger only
            statuses = sorted(r["status"] for r in out["records"])
            self.assertEqual(statuses, ["verified", "verified"])
            with open(ledger, encoding="utf-8") as fh:
                saved = json.load(fh)
            self.assertEqual(saved["summary"]["rulings"], 4)
            self.assertEqual(saved["summary"]["by_outcome"], {"overturned": 3, "on_ice_call_not_stated": 1})
            self.assertEqual(saved["summary"]["missing_game_id"], 1)
            self.assertEqual(saved["summary"]["overturned_crosscheck"], {"agree": 2, "not_checked": 1})
            # second pass: nothing new on the page -> incremental stops, nothing re-fetched
            out2 = sr.ingest(None, ledger_path=ledger, pages=[items], pbp_loader=loader, resolve_ids=False, run_id="t2")
            self.assertEqual(out2["stats"]["new"], 0)
            self.assertEqual(out2["stats"]["unchanged"], 4)
            self.assertEqual(out2["stats"]["crosschecked"], 0)   # final games are not re-checked
            self.assertEqual(len(out2["records"]), 2)
            # upsert keeps ids stable across runs
            merged, stats = db_mod.upsert(out["records"], out2["records"])
            self.assertEqual(stats, {"added": 0, "updated": 0, "unchanged": 0, "skipped_human": 2})


if __name__ == "__main__":
    unittest.main()
