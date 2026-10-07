"""Tests for record building + classification (SYNTHETIC fixtures only)."""

from __future__ import annotations

import unittest

from pipeline import livefeed
from pipeline.diff import diff_goals
from pipeline.records import build_records_for_changes
from tests.fixture_feeds import goal_play, make_feed, review_play

NOW = "2026-10-07T01:00:00Z"


def normalize(feed, final=None):
    if final is not None:
        feed["gameData"]["status"]["detailedState"] = "Final" if final else "Live"
        feed["liveData"]["linescore"]["currentPeriodTimeRemaining"] = (
            "Final" if final else "10:00")
    return livefeed.normalize_live_feed(feed, NOW, "https://example/feed")


class TestBuildRecords(unittest.TestCase):
    def test_removed_goal_becomes_total_change_record(self):
        old_feed = make_feed([goal_play(1, 2, "05:10", "TCA", "Player A")])
        new_feed = make_feed([])
        old = normalize(old_feed, final=True)
        new = normalize(new_feed, final=True)
        changes = diff_goals(old["goals"], new["goals"])
        records = build_records_for_changes(changes, old, new, NOW)
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertTrue(rec["classification"]["changes_game_total"])
        self.assertTrue(rec["classification"]["settlement_risk"])
        self.assertIn("goal_to_no_goal", rec["classification"]["types"])
        self.assertEqual(rec["original"]["ruling"], "goal")
        self.assertEqual(rec["corrected"]["ruling"], "no_goal")
        self.assertEqual(rec["status"], "pending_review")
        self.assertIn("needs_human_review", rec["flags"])
        self.assertGreaterEqual(len(rec["evidence"]), 2)
        for ev in rec["evidence"]:
            self.assertTrue(ev["url"].startswith("http"))

    def test_added_goal_review_corroborated(self):
        old_feed = make_feed([])
        new_feed = make_feed(
            [goal_play(1, 2, "05:10", "TCA", "Player A")],
            reviews=[review_play(2, 2, "05:00", "Review: goal overturned, good goal")],
        )
        old = normalize(old_feed, final=True)
        new = normalize(new_feed, final=True)
        changes = diff_goals(old["goals"], new["goals"])
        records = build_records_for_changes(changes, old, new, NOW)
        self.assertEqual(len(records), 1)
        self.assertIn("video_review_overturn", records[0]["classification"]["types"])
        self.assertEqual(records[0]["detection"]["method"], "review_marker")
        self.assertIn("no_goal_to_goal", records[0]["classification"]["types"])

    def test_scorer_change_is_attribution_only(self):
        old_feed = make_feed([goal_play(1, 1, "10:00", "TCA", "Player A")])
        new_feed = make_feed([goal_play(1, 1, "10:00", "TCA", "Player B")])
        old = normalize(old_feed, final=True)
        new = normalize(new_feed, final=True)
        changes = diff_goals(old["goals"], new["goals"])
        records = build_records_for_changes(changes, old, new, NOW)
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertFalse(rec["classification"]["changes_game_total"])
        self.assertTrue(rec["classification"]["attribution_only"])
        self.assertFalse(rec["classification"]["settlement_risk"])
        self.assertIn("scorer_change", rec["classification"]["types"])

    def test_timing_postgame_when_baseline_already_final(self):
        old_feed = make_feed([goal_play(1, 1, "10:00", "TCA", "Player A")])
        new_feed = make_feed([goal_play(1, 1, "10:00", "TCA", "Player B")])
        old = normalize(old_feed, final=True)
        new = normalize(new_feed, final=True)
        changes = diff_goals(old["goals"], new["goals"])
        records = build_records_for_changes(changes, old, new, NOW)
        self.assertEqual(records[0]["classification"]["timing"], "postgame")

    def test_report_hash_change_creates_flag_record(self):
        old = normalize(make_feed([]), final=True)
        new = normalize(make_feed([]), final=True)
        report_changes = [{"report": "GS", "url": "https://example/GS.pdf"}]
        records = build_records_for_changes([], old, new, NOW, report_changes)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["classification"]["types"], ["official_report_changed"])
        self.assertIn("report_content_diff_pending", records[0]["flags"])


if __name__ == "__main__":
    unittest.main()
