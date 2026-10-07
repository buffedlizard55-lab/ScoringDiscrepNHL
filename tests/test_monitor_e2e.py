"""End-to-end monitor simulation (offline, SYNTHETIC feeds via monkeypatching).

Simulates two monitor cycles:
  cycle 1: baselines a game with one goal
  cycle 2: the official feed shows that goal removed + a review overturn event
Expectation: one total-changing discrepancy record, one alert, one queued issue,
and a database that passes the charter validator.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import config, httpclient, monitor, store, validate
from tests.fixture_feeds import goal_play, make_feed, review_play

SCHEDULE_JSON = {
    "dates": [{
        "date": "2026-10-06",
        "games": [{
            "gamePk": 2026020001,
            "season": "20262027",
            "gameType": "R",
            "status": {"detailedState": "Final"},
            "teams": {
                "away": {"team": {"name": "Test City A-Team", "abbreviation": "TCA"}, "score": 1},
                "home": {"team": {"name": "Test Ville B-Team", "abbreviation": "TVB"}, "score": 0},
            },
        }],
    }],
}


class TestMonitorE2E(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._orig = {}
        for name in ("DISCREPANCIES_PATH", "ALERTS_PATH", "ALERTS_RSS_PATH",
                     "COVERAGE_PATH", "NOTIFY_STATE_PATH", "PENDING_ISSUES_PATH",
                     "SNAPSHOT_DIR"):
            self._orig[name] = getattr(config, name)
        config.DISCREPANCIES_PATH = root / "discrepancies.json"
        config.ALERTS_PATH = root / "alerts.json"
        config.ALERTS_RSS_PATH = root / "alerts.xml"
        config.COVERAGE_PATH = root / "coverage_report.json"
        config.NOTIFY_STATE_PATH = root / "notifications_state.json"
        config.PENDING_ISSUES_PATH = root / "pending_issues.json"
        config.SNAPSHOT_DIR = root / "snapshots"

        self.cycle = 1
        self.feed_v1 = make_feed([goal_play(101, 2, "05:10", "TCA", "Player A",
                                            ["Player B"])])
        self.feed_v2 = make_feed(
            [],
            reviews=[review_play(102, 2, "05:00",
                                 "TCA challenge: goal overturned - offside")],
        )

    def tearDown(self):
        for name, value in self._orig.items():
            setattr(config, name, value)
        self._tmp.cleanup()

    def fake_fetch_json(self, url, **kwargs):
        if "/schedule" in url:
            return SCHEDULE_JSON
        if "/feed/live" in url:
            return self.feed_v1 if self.cycle == 1 else self.feed_v2
        raise AssertionError(f"unexpected url {url}")

    def fake_fetch(self, url, **kwargs):
        # Official report PDFs: simulate 404 (not published) in this synthetic run.
        raise httpclient.NotFound(url, 404, "not found")

    def run_cycle(self):
        with mock.patch.object(httpclient, "fetch_json", self.fake_fetch_json), \
             mock.patch.object(httpclient, "fetch", self.fake_fetch), \
             mock.patch.object(config, "REQUEST_DELAY_SECONDS", 0):
            return monitor.update(days=3)

    def test_full_cycle(self):
        # Cycle 1: baseline only, no records.
        stats1 = self.run_cycle()
        self.assertEqual(stats1["baselined"], 1)
        self.assertEqual(stats1["records_created"], 0)
        db = store.load_discrepancies()
        self.assertEqual(db["records"], [])

        # Cycle 2: the goal disappears with a review overturn -> 1 record.
        self.cycle = 2
        stats2 = self.run_cycle()
        self.assertEqual(stats2["games_with_changes"], 1)
        self.assertEqual(stats2["records_created"], 1)
        self.assertEqual(stats2["alerts_emitted"], 1)
        self.assertEqual(stats2["errors"], [])

        db = store.load_discrepancies()
        self.assertEqual(len(db["records"]), 1)
        rec = db["records"][0]
        self.assertTrue(rec["classification"]["changes_game_total"])
        self.assertTrue(rec["classification"]["settlement_risk"])
        self.assertIn("goal_to_no_goal", rec["classification"]["types"])
        self.assertIn("video_review_overturn", rec["classification"]["types"])
        self.assertEqual(rec["original"]["ruling"], "goal")
        self.assertEqual(rec["corrected"]["ruling"], "no_goal")
        self.assertEqual(rec["original"]["scorer"], "Player A")

        # Alerts + RSS + queued issue all populated.
        alerts = store.load_alerts()
        self.assertEqual(len(alerts["alerts"]), 1)
        self.assertIn("goal overturned", alerts["alerts"][0]["body"])
        self.assertTrue(config.ALERTS_RSS_PATH.exists())
        issues = store.load_json(config.PENDING_ISSUES_PATH, {"issues": []})
        self.assertEqual(len(issues["issues"]), 1)
        self.assertIn("[alert]", issues["issues"][0]["title"])

        # Charter validation passes on the produced database.
        errors, stats = validate.validate_database()
        self.assertEqual(errors, [])
        self.assertEqual(stats["records"], 1)

        # Cycle 3 (unchanged feed): nothing new, no duplicate alerts.
        stats3 = self.run_cycle()
        self.assertEqual(stats3["records_created"], 0)
        self.assertEqual(stats3["alerts_emitted"], 0)
        alerts = store.load_alerts()
        self.assertEqual(len(alerts["alerts"]), 1)

    def test_schedule_failure_degrades_gracefully(self):
        def boom(url, **kwargs):
            raise httpclient.SourceError(url, None, "unreachable")
        with mock.patch.object(httpclient, "fetch_json", boom), \
             mock.patch.object(config, "REQUEST_DELAY_SECONDS", 0):
            stats = monitor.update(days=1)
        self.assertTrue(stats["errors"])
        alerts = store.load_alerts()
        self.assertEqual(alerts["alerts"][0]["type"], "monitor_degraded")


if __name__ == "__main__":
    unittest.main()
