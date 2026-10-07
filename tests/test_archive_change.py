"""Tests for the archive-based census path.

The live path can only see changes that happen while the monitor is running; everything
older has to come out of the archive. These tests pin down the two properties that
decide whether an archive-derived record is trustworthy:

* a change window brackets the rewrite between two captures, and never claims more;
* an unanswered question (no capture, or a failed index query) is never reported as
  "unchanged".

The end-to-end test drives two captures of the same official Game Summary, differing by
one scoring credit, through the *same* record builder the live monitor uses.
"""

import json
import os
import tempfile
import unittest
from unittest import mock

from nhl_monitor import archive, backfill
from nhl_monitor.fetch import Response

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
HEADER = ["timestamp", "original", "statuscode", "mimetype", "digest", "length"]
URL = "http://www.nhl.com/scores/htmlreports/20052006/GS020001.HTM"


def _rows(*specs):
    rows = [HEADER]
    for timestamp, digest, status, mime in specs:
        rows.append([timestamp, URL, status, mime, digest, "1937"])
    return rows


def _snaps(*specs):
    return archive.parse_cdx(_rows(*specs), url_filter="GS020001")


class ChangeWindowTests(unittest.TestCase):
    def test_a_change_window_brackets_the_rewrite_between_two_captures(self):
        snaps = _snaps(("20100101000000", "AAAA", "200", "text/html"),
                       ("20120101000000", "AAAA", "200", "text/html"),
                       ("20140101000000", "BBBB", "200", "text/html"),
                       ("20160101000000", "BBBB", "200", "text/html"))
        windows = archive.change_windows(snaps)
        self.assertEqual(len(windows), 1)
        # the older content is proven to exist at the last AAAA capture, the newer at the
        # first BBBB capture; the rewrite happened between them and nowhere else
        self.assertEqual(windows[0]["changed_after_capture"], "20120101000000")
        self.assertEqual(windows[0]["changed_by_capture"], "20140101000000")
        self.assertFalse(windows[0]["digest_returned_to_an_earlier_version"])

    def test_redirects_and_error_pages_are_not_evidence(self):
        snaps = _snaps(("20100101000000", "AAAA", "200", "text/html"),
                       ("20110101000000", archive.REDIRECT_DIGEST, "200", "text/html"),
                       ("20120101000000", archive.ERROR_DIGEST, "200", "text/html"),
                       ("20130101000000", "AAAA", "200", "text/html"))
        self.assertEqual(archive.change_windows(snaps), [],
                         "an HTTP redirect and an error page have no content to compare")
        self.assertEqual(len(archive.content_versions(snaps)), 1)

    def test_a_digest_that_returns_to_an_earlier_value_is_flagged_not_folded_in(self):
        snaps = _snaps(("20100101000000", "AAAA", "200", "text/html"),
                       ("20110101000000", "BBBB", "200", "text/html"),
                       ("20120101000000", "AAAA", "200", "text/html"))
        windows = archive.change_windows(snaps)
        self.assertEqual(len(windows), 2)
        self.assertFalse(windows[0]["digest_returned_to_an_earlier_version"])
        self.assertTrue(windows[1]["digest_returned_to_an_earlier_version"],
                        "a reversion and a capture artefact look identical - flag, never guess")

    def test_a_single_capture_cannot_prove_a_change(self):
        snaps = _snaps(("20100101000000", "AAAA", "200", "text/html"))
        self.assertEqual(archive.change_windows(snaps), [])
        summary = archive.summarise_scan([{"label": "1", "url": URL, "captures": 1,
                                           "usable_captures": 1, "change_windows": [],
                                           "verdict": "archived_but_never_changed"}])
        self.assertEqual(summary["documents_provably_changed"], 0)
        self.assertEqual(summary["documents_with_a_usable_capture"], 1)


class ScanAccountingTests(unittest.TestCase):
    """Regression: the first version counted failed queries as 'answerable'."""

    def test_index_errors_and_missing_captures_are_counted_as_unknowable(self):
        summary = archive.summarise_scan([
            {"label": "1", "url": URL, "verdict": "index_error", "captures": None,
             "usable_captures": None, "change_windows": []},
            {"label": "2", "url": URL, "verdict": "no_usable_capture", "captures": 0,
             "usable_captures": 0, "change_windows": []},
            {"label": "3", "url": URL, "verdict": "archived_but_never_changed", "captures": 2,
             "usable_captures": 2, "change_windows": []},
        ])
        self.assertEqual(summary["documents_probed"], 3)
        self.assertEqual(summary["documents_with_a_usable_capture"], 1)
        self.assertEqual(summary["documents_without_a_usable_capture"], 2)
        self.assertEqual(summary["verdicts"]["index_error"], 1)

    def test_scan_urls_reports_a_failure_per_document_instead_of_raising(self):
        with mock.patch.object(archive, "snapshots_for", side_effect=OSError("index down")):
            results = archive.scan_urls({"20052006": URL})
        self.assertEqual(results[0]["verdict"], "index_error")
        self.assertIn("index down", results[0]["error"])
        self.assertIsNone(results[0]["proven_change"])


class ComparisonTests(unittest.TestCase):
    """End-to-end: two archived captures of one official Game Summary -> one record."""

    def setUp(self):
        with open(os.path.join(FIXTURES, "gs_20052006_020001.html"), encoding="utf-8") as fh:
            self.official = fh.read()
        self.assertTrue("J. BULIS (1)" in self.official and "R. BONK (1)" in self.official)

    def _fetch(self, body):
        def fake(timestamp, url, **kw):
            return Response(url=f"https://web.archive.org/web/{timestamp}id_/{url}", status=200,
                            body=body.encode("utf-8"), retrieved_at="2026-10-07T00:00:00Z",
                            content_type="text/html")
        return fake

    def _compare(self, older_body, newer_body):
        older = archive.Snapshot(timestamp="20051006000000", original=URL, statuscode="200",
                                 digest="AAAA", mimetype="text/html", length="1937")
        newer = archive.Snapshot(timestamp="20150301000000", original=URL, statuscode="200",
                                 digest="BBBB", mimetype="text/html", length="1937")
        bodies = [older_body, newer_body]
        with mock.patch.object(archive, "fetch_snapshot",
                               side_effect=lambda *a, **kw: self._fetch(bodies.pop(0))(*a, **kw)):
            return backfill.compare_captures(2005020001, "GS", older, newer)

    def test_a_corrected_credit_becomes_a_record_with_both_states(self):
        corrected = self.official.replace("R. BONK (1)", "M. RYDER (1)")
        result = self._compare(self.official, corrected)
        self.assertEqual(len(result["records"]), 1, result.get("finding") or result.get("errors"))
        record = result["records"][0]
        self.assertEqual(record["record_id"], "NHL-20052006-020001-01")
        names = lambda blobs: [b["name"] for b in blobs or []]
        self.assertEqual(names(record["initial_state"]["assists"]), ["R. BONK", "N. SUNDSTROM"])
        self.assertEqual(names(record["corrected_state"]["assists"]), ["M. RYDER", "N. SUNDSTROM"])
        self.assertEqual(record["initial_state"]["scorer"]["name"], "J. BULIS")
        self.assertEqual(record["corrected_state"]["scorer"]["name"], "J. BULIS")
        self.assertFalse(record["change"]["affects_goal_total"])
        self.assertTrue(record["change"]["attribution_only"])
        self.assertEqual(record["detection"]["detected_by"], "backfill_archive_diff")
        self.assertEqual(record["evidence_status"], "verified_two_official_states")
        self.assertEqual(record["timing"]["when"], "postgame")
        self.assertEqual(record["timing"]["confidence"], "heuristic")
        self.assertEqual(record["timing"]["change_bracket_utc"],
                         ["2005-10-06T00:00:00Z", "2015-03-01T00:00:00Z"])
        for flag in ("original_state_from_archived_capture", "corrected_state_from_archived_capture",
                     "correction_time_bounded_not_known"):
            self.assertIn(flag, record["flags"])
        self.assertTrue(record["sources"])
        for source in record["sources"]:
            if source["url"].startswith("https://web.archive.org/"):
                self.assertIn("snapshot_captured_at_utc", source)

    def test_a_rewrite_that_did_not_touch_the_scoring_record_is_a_finding_not_a_record(self):
        # same goals, regenerated document (footer differs) - this is what a re-render
        # looks like, and it must never be published as a scoring correction
        regenerated = self.official.replace("2005-10-05-21.40.47", "2015-02-01-09.11.02")
        result = self._compare(self.official, regenerated)
        self.assertEqual(result["records"], [])
        self.assertEqual(result["finding"]["kind"], "regeneration_without_scoring_change")
        self.assertIn("not a scoring correction", result["finding"]["detail"])

    def test_identical_captures_produce_nothing(self):
        result = self._compare(self.official, self.official)
        self.assertEqual(result["records"], [])
        self.assertEqual(result["states_differ"], False)

    def test_a_document_that_cannot_be_compared_is_reported_as_such(self):
        older = archive.Snapshot(timestamp="20051006000000", original=URL, statuscode="200",
                                 digest="AAAA", mimetype="text/html", length="1")
        newer = archive.Snapshot(timestamp="20150301000000", original=URL, statuscode="200",
                                 digest="BBBB", mimetype="text/html", length="1")
        result = backfill.compare_captures(2005020001, "PL", older, newer)
        self.assertEqual(result["records"], [])
        self.assertIn("not comparable", result["finding"])


class CompareWindowTests(unittest.TestCase):
    def test_compare_change_windows_uses_every_window_and_isolates_failures(self):
        window = {"older_capture": archive.Snapshot("20100101000000", URL, "200", "AAAA",
                                                    "text/html", "10").as_dict(),
                  "newer_capture": archive.Snapshot("20110101000000", URL, "200", "BBBB",
                                                    "text/html", "10").as_dict(),
                  "changed_after_capture": "20100101000000",
                  "changed_by_capture": "20110101000000",
                  "digest_returned_to_an_earlier_version": False}
        with mock.patch.object(archive, "fetch_snapshot", side_effect=OSError("gone")):
            out = backfill.compare_change_windows(2005020001, "GS", [window])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["records"], [])
        self.assertIn("gone", out[0]["errors"][0])


if __name__ == "__main__":
    unittest.main()


class AlertEmissionTests(unittest.TestCase):
    """Every detection route must feed the alert feed.

    Regression: records built from the league's own announcements and from the census
    were written to the database while data/alerts/index.json stayed at "0 alerts", so
    the site reported a clean feed next to three verified discrepancies.
    """

    def test_records_produce_alerts_and_refresh_the_index(self):
        from nhl_monitor import alerts, store

        records = [r for r in store.load_records() if r.get("record_id")]
        if not records:
            self.skipTest("no records in the database to alert on")
        with tempfile.TemporaryDirectory() as tmp:
            out = alerts.emit_for_records(records[:1], root=tmp)
            self.assertEqual(len(out["alerts"]), 1)
            alert_id = out["alerts"][0]["alert_id"]
            self.assertTrue(os.path.exists(os.path.join(tmp, alert_id + ".json")))
            with open(os.path.join(tmp, "index.json"), encoding="utf-8") as fh:
                index = json.load(fh)
            self.assertEqual(index["count"], 1)
            self.assertEqual(index["alerts"][0]["alert_id"], alert_id)

    def test_re_emitting_does_not_make_an_old_alert_look_new(self):
        from nhl_monitor import alerts, store

        records = [r for r in store.load_records() if r.get("record_id")]
        if not records:
            self.skipTest("no records in the database to alert on")
        with tempfile.TemporaryDirectory() as tmp:
            first = alerts.emit_for_records(records[:1], root=tmp)["alerts"][0]
            second = alerts.emit_for_records(records[:1], root=tmp)["alerts"][0]
            self.assertEqual(second["created_at_utc"], first["created_at_utc"],
                             "a re-detection must not restamp the alert as new")
            self.assertIn("last_emitted_at_utc", second)
