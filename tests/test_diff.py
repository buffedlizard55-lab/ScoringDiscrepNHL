"""Tests for snapshot diffing (SYNTHETIC fixtures only)."""

from __future__ import annotations

import unittest

from pipeline import livefeed
from pipeline.diff import diff_goals, diff_report_hashes, field_changes, total_mismatches
from tests.fixture_feeds import goal_play, make_feed


def snap_goals(feed):
    return livefeed.normalize_live_feed(feed, "t", "u")["goals"]


class TestDiffGoals(unittest.TestCase):
    def test_no_change(self):
        goals = [goal_play(1, 1, "10:00", "TCA", "A")]
        self.assertEqual(diff_goals(snap_goals(make_feed(goals)),
                                    snap_goals(make_feed(goals))), [])

    def test_removed_goal_detected(self):
        old = snap_goals(make_feed([goal_play(1, 1, "10:00", "TCA", "A"),
                                    goal_play(2, 2, "09:00", "TCA", "B")]))
        new = snap_goals(make_feed([goal_play(1, 1, "10:00", "TCA", "A")]))
        changes = diff_goals(old, new)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["op"], "removed")
        self.assertEqual(changes[0]["period"], 2)
        self.assertEqual(changes[0]["old"]["scorer"], "B")

    def test_added_goal_detected(self):
        old = snap_goals(make_feed([goal_play(1, 1, "10:00", "TCA", "A")]))
        new = snap_goals(make_feed([goal_play(1, 1, "10:00", "TCA", "A"),
                                    goal_play(3, 3, "15:00", "TVB", "Z")]))
        changes = diff_goals(old, new)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["op"], "added")
        self.assertEqual(changes[0]["new"]["scorer"], "Z")

    def test_scorer_change_is_attribution_only(self):
        old = snap_goals(make_feed([goal_play(1, 1, "10:00", "TCA", "A", ["B"])]))
        new = snap_goals(make_feed([goal_play(1, 1, "10:00", "TCA", "C", ["B"])]))
        changes = diff_goals(old, new)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["op"], "changed")
        self.assertIn("scorer", changes[0]["fields_changed"])

    def test_assist_change_detected(self):
        old = snap_goals(make_feed([goal_play(1, 1, "10:00", "TCA", "A", ["B"])]))
        new = snap_goals(make_feed([goal_play(1, 1, "10:00", "TCA", "A", ["B", "C"])]))
        changes = diff_goals(old, new)
        self.assertEqual(changes[0]["op"], "changed")
        self.assertIn("assists", changes[0]["fields_changed"])

    def test_small_clock_correction_is_not_goal_flip(self):
        # A 20-second clock fix on the same goal must not appear as
        # removed+added (tolerance), but the clock itself is not an attribution
        # field, so there should be no change at all.
        old = snap_goals(make_feed([goal_play(1, 1, "10:00", "TCA", "A")]))
        new = snap_goals(make_feed([goal_play(1, 1, "09:40", "TCA", "A")]))
        self.assertEqual(diff_goals(old, new), [])

    def test_clock_beyond_tolerance_is_goal_flip(self):
        old = snap_goals(make_feed([goal_play(1, 1, "10:00", "TCA", "A")]))
        new = snap_goals(make_feed([goal_play(1, 1, "03:00", "TCA", "A")]))
        ops = [c["op"] for c in diff_goals(old, new)]
        self.assertEqual(sorted(ops), ["added", "removed"])


class TestReportHashes(unittest.TestCase):
    def test_hash_change_detected(self):
        old = {"report_hashes": {"GS": {"ok": True, "sha256": "a", "url": "u1"}}}
        new = {"report_hashes": {"GS": {"ok": True, "sha256": "b", "url": "u1"}}}
        self.assertEqual(diff_report_hashes(old, new),
                         [{"report": "GS", "url": "u1"}])

    def test_missing_report_not_flagged(self):
        old = {"report_hashes": {"GS": {"ok": False, "missing": True}}}
        new = {"report_hashes": {"GS": {"ok": False, "missing": True}}}
        self.assertEqual(diff_report_hashes(old, new), [])


class TestTotalMismatches(unittest.TestCase):
    def test_consistent_snapshot_has_no_mismatch(self):
        feed = make_feed([goal_play(1, 1, "10:00", "TCA", "A")])
        feed["liveData"]["linescore"]["teams"]["away"]["goals"] = 1
        snap = livefeed.normalize_live_feed(feed, "t", "u")
        self.assertEqual(total_mismatches(snap), [])

    def test_mismatch_detected(self):
        feed = make_feed([goal_play(1, 1, "10:00", "TCA", "A")])
        feed["liveData"]["linescore"]["teams"]["away"]["goals"] = 2  # says 2, only 1 event
        snap = livefeed.normalize_live_feed(feed, "t", "u")
        problems = total_mismatches(snap)
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0]["linescore_total"], 2)
        self.assertEqual(problems[0]["goal_events"], 1)


class TestFieldChanges(unittest.TestCase):
    def test_field_changes(self):
        old = {"scorer": "A", "assists": ["B"], "strength": "EV", "empty_net": None}
        new = {"scorer": "A", "assists": [], "strength": "PPG", "empty_net": None}
        changed = field_changes(old, new)
        self.assertIn("assists", changed)
        self.assertIn("strength", changed)
        self.assertNotIn("scorer", changed)


if __name__ == "__main__":
    unittest.main()
