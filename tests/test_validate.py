"""Tests for the database validator (SYNTHETIC fixtures only)."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from pipeline import config, store, validate

VALID_RECORD = {
    "id": "2026020001#P2#TCA#1#total",
    "status": "pending_review",
    "game": {
        "game_pk": 2026020001,
        "season": "20262027",
        "game_type": "R",
        "date": "2026-10-06",
        "away": {"tri": "TCA", "name": "Test City A-Team"},
        "home": {"tri": "TVB", "name": "Test Ville B-Team"},
        "venue": "Synthetic Arena",
        "links": {"live_feed": "https://example/feed"},
    },
    "event": {"period": 2, "period_type": "REGULAR", "team": "TCA",
              "goal_ordinal": 1, "description": "synthetic"},
    "original": {"ruling": "goal", "scorer": "Player A", "assists": [],
                 "strength": "EV", "empty_net": None, "clock": "05:10",
                 "description": "synthetic"},
    "corrected": {"ruling": "no_goal", "scorer": None, "assists": [],
                  "strength": None, "empty_net": None, "clock": "05:10",
                  "description": "synthetic"},
    "classification": {
        "changes_game_total": True, "attribution_only": False,
        "types": ["goal_to_no_goal", "video_review_overturn"],
        "timing": "in_game", "timing_confidence": "heuristic",
        "reason": "offside", "settlement_risk": True,
    },
    "detection": {"method": "snapshot_diff",
                  "first_detected_at": "2026-10-07T01:00:00Z",
                  "detector_version": "0.1.0"},
    "evidence": [{
        "label": "Official live feed", "url": "https://example/feed",
        "kind": "live_feed", "status": "verified",
        "captured_at": "2026-10-07T01:00:00Z", "archive_url": None, "note": None,
    }],
    "flags": ["needs_human_review"],
    "revisions": [{"at": "2026-10-07T01:00:00Z", "note": "created"}],
}


class TestValidate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._orig_d, self._orig_a = config.DISCREPANCIES_PATH, config.ALERTS_PATH
        config.DISCREPANCIES_PATH = root / "discrepancies.json"
        config.ALERTS_PATH = root / "alerts.json"

    def tearDown(self):
        config.DISCREPANCIES_PATH, config.ALERTS_PATH = self._orig_d, self._orig_a
        self._tmp.cleanup()

    def _write_db(self, record):
        store.save_discrepancies({"schema_version": 1, "generated_at": None,
                                  "generator": "test", "records": [record]})

    def test_valid_record_passes(self):
        self.assertEqual(validate.validate_record(VALID_RECORD), [])

    def test_mutually_exclusive_flags_rejected(self):
        rec = copy.deepcopy(VALID_RECORD)
        rec["classification"]["attribution_only"] = True
        errors = validate.validate_record(rec)
        self.assertTrue(any("mutually exclusive" in e for e in errors))

    def test_total_change_requires_settlement_risk(self):
        rec = copy.deepcopy(VALID_RECORD)
        rec["classification"]["settlement_risk"] = False
        errors = validate.validate_record(rec)
        self.assertTrue(any("settlement_risk" in e for e in errors))

    def test_missing_evidence_rejected(self):
        rec = copy.deepcopy(VALID_RECORD)
        rec["evidence"] = []
        errors = validate.validate_record(rec)
        self.assertTrue(any("evidence" in e for e in errors))

    def test_non_verified_evidence_requires_flag(self):
        rec = copy.deepcopy(VALID_RECORD)
        rec["evidence"][0]["status"] = "incomplete"
        rec["flags"] = []
        errors = validate.validate_record(rec)
        self.assertTrue(any("needs_human_review" in e for e in errors))

    def test_bad_url_rejected(self):
        rec = copy.deepcopy(VALID_RECORD)
        rec["evidence"][0]["url"] = "ftp://nope"
        errors = validate.validate_record(rec)
        self.assertTrue(any("url" in e for e in errors))

    def test_seeded_database_validates_clean(self):
        store.save_discrepancies({"schema_version": 1, "generated_at": None,
                                  "generator": None, "records": []})
        store.save_alerts({"schema_version": 1, "generated_at": None, "alerts": []})
        errors, stats = validate.validate_database()
        self.assertEqual(errors, [])
        self.assertEqual(stats["records"], 0)

    def test_duplicate_ids_rejected(self):
        store.save_discrepancies({"schema_version": 1, "records":
                                  [VALID_RECORD, copy.deepcopy(VALID_RECORD)]})
        store.save_alerts({"schema_version": 1, "alerts": []})
        errors, _ = validate.validate_database()
        self.assertTrue(any("duplicate" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
