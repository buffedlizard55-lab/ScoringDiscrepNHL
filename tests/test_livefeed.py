"""Tests for live-feed normalization (SYNTHETIC fixtures only)."""

from __future__ import annotations

import unittest

from pipeline import livefeed
from tests.fixture_feeds import FIXTURE_NOTE, goal_play, make_feed, review_play


class TestNormalize(unittest.TestCase):
    def test_goals_extracted_with_scorer_and_assists(self):
        feed = make_feed([
            goal_play(101, 1, "12:34", "TCA", "Player A", ["Player B", "Player C"]),
            goal_play(150, 2, "01:00", "TVB", "Player D", strength="PPG"),
        ])
        snap = livefeed.normalize_live_feed(feed, "2026-10-07T00:00:00Z", "http://x/feed")
        self.assertEqual(snap["game"]["game_pk"], 2026020001)
        self.assertEqual(snap["game"]["season"], "20262027")
        self.assertTrue(snap["final"])
        self.assertEqual(len(snap["goals"]), 2)
        first = snap["goals"][0]
        self.assertEqual(first["scorer"], "Player A")
        self.assertEqual(first["assists"], ["Player B", "Player C"])
        self.assertEqual(first["period"], 1)
        self.assertEqual(first["clock"], "12:34")
        self.assertEqual(first["strength"], "EV")
        self.assertEqual(first["team"], "TCA")
        self.assertEqual(snap["goals"][1]["strength"], "PPG")
        self.assertEqual(snap["teams"]["away"]["tri"], "TCA")

    def test_review_events_captured(self):
        feed = make_feed(
            [goal_play(101, 2, "05:10", "TCA", "Player A")],
            reviews=[review_play(102, 2, "05:00",
                                 "TCA challenge: goal overturned - offside")],
        )
        snap = livefeed.normalize_live_feed(feed, "2026-10-07T00:00:00Z", "http://x/feed")
        self.assertEqual(len(snap["reviews"]), 1)
        self.assertTrue(snap["reviews"][0]["mentions_overturn"])

    def test_empty_feed_warns_instead_of_crashing(self):
        feed = {"gameData": {}, "liveData": {}}
        snap = livefeed.normalize_live_feed(feed, "2026-10-07T00:00:00Z", "http://x/feed")
        self.assertEqual(snap["goals"], [])
        self.assertTrue(snap["warnings"])  # shape drift surfaced, not swallowed

    def test_fixture_is_synthetic(self):
        feed = make_feed([])
        self.assertEqual(feed["_fixture"], FIXTURE_NOTE)

    def test_time_to_seconds(self):
        self.assertEqual(livefeed.time_to_seconds("12:34"), 754)
        self.assertEqual(livefeed.time_to_seconds("00:05"), 5)
        self.assertIsNone(livefeed.time_to_seconds(None))
        self.assertIsNone(livefeed.time_to_seconds("garbage"))


if __name__ == "__main__":
    unittest.main()
