"""Tests for persistence + upsert semantics (SYNTHETIC fixtures only)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pipeline import config, store
from tests.test_records import build_records_for_changes  # reuse builders
from pipeline import livefeed
from pipeline.diff import diff_goals
from tests.fixture_feeds import goal_play, make_feed

NOW = "2026-10-07T01:00:00Z"


def _make_records():
    old_feed = make_feed([goal_play(1, 1, "10:00", "TCA", "Player A")])
    new_feed = make_feed([goal_play(1, 1, "10:00", "TCA", "Player B")])
    old = livefeed.normalize_live_feed(old_feed, NOW, "https://example/old")
    new = livefeed.normalize_live_feed(new_feed, NOW, "https://example/new")
    old["final"] = new["final"] = True
    return build_records_for_changes(diff_goals(old["goals"], new["goals"]),
                                     old, new, NOW)


class TestStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._orig = (config.DISCREPANCIES_PATH, config.ALERTS_PATH,
                      config.ALERTS_RSS_PATH, config.NOTIFY_STATE_PATH,
                      config.PENDING_ISSUES_PATH, config.SNAPSHOT_DIR)
        config.DISCREPANCIES_PATH = root / "discrepancies.json"
        config.ALERTS_PATH = root / "alerts.json"
        config.ALERTS_RSS_PATH = root / "alerts.xml"
        config.NOTIFY_STATE_PATH = root / "notifications_state.json"
        config.PENDING_ISSUES_PATH = root / "pending_issues.json"
        config.SNAPSHOT_DIR = root / "snapshots"

    def tearDown(self):
        (config.DISCREPANCIES_PATH, config.ALERTS_PATH, config.ALERTS_RSS_PATH,
         config.NOTIFY_STATE_PATH, config.PENDING_ISSUES_PATH,
         config.SNAPSHOT_DIR) = self._orig
        self._tmp.cleanup()

    def test_upsert_create_then_update_keeps_original(self):
        db = {"schema_version": 1, "records": []}
        records = _make_records()
        self.assertEqual(store.upsert_record(db, records[0], NOW), "created")

        # Same change detected again later -> corrected state identical -> unchanged
        self.assertEqual(store.upsert_record(db, records[0], "2026-10-07T02:00:00Z"),
                         "unchanged")

        # Further refinement (assist added) -> original preserved, revision appended
        newer = dict(records[0])
        newer["corrected"] = dict(records[0]["corrected"])
        newer["corrected"]["assists"] = ["Player Z"]
        self.assertEqual(store.upsert_record(db, newer, "2026-10-07T03:00:00Z"),
                         "updated")
        rec = db["records"][0]
        self.assertEqual(rec["original"]["scorer"], "Player A")
        self.assertEqual(rec["corrected"]["assists"], ["Player Z"])
        self.assertEqual(len(rec["revisions"]), 2)

    def test_snapshots_roundtrip(self):
        snap = {"schema": 1, "goals": []}
        store.save_snapshot(2026020001, snap)
        self.assertEqual(store.load_snapshot(2026020001), snap)
        self.assertEqual(store.list_snapshot_pks(), [2026020001])

    def test_atomic_write_leaves_no_tmp(self):
        store.save_json(config.DISCREPANCIES_PATH, {"schema_version": 1})
        leftovers = [p for p in config.DISCREPANCIES_PATH.parent.glob(".tmp-*")]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
