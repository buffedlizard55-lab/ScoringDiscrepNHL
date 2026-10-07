"""Regression tests for the alert feed the published site actually reads.

The bug these tests exist to prevent: GitHub Pages serves this repository root, and
the root site reads ``data/alerts.json``. Both detection routes wrote their alerts
somewhere else (``data/alerts/index.json`` and ``data/alerts/<date>/alerts.json``),
so three alerts could be committed to the repository while the published Alerts tab
said "No alerts yet". Nothing in the test suite caught it because nothing asserted
on the artifact the page reads.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "src"), os.path.join(ROOT, "pipeline")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nhl_monitor import alerts as monitor_alerts  # noqa: E402
from nhl_scoring import alerts as engine_alerts  # noqa: E402


MONITOR_RECORD = {
    "record_id": "NHL-20242025-021140-01",
    "status": "verified_from_official_announcement",
    "game": {"game_id": 2024021140, "season": "20242025", "date": "2025-03-26",
             "away": {"abbrev": "NJD"}, "home": {"abbrev": "CHI"}, "final_score": "5-3"},
    "event": {"period": 1, "period_type": "REG", "clock": "6:50", "strength": "PP", "team": "NJD"},
    "initial_state": {"ruling": "goal", "scorer": {"name": "Timo Meier", "sweater": 28}, "assists": None},
    "corrected_state": {"ruling": "goal", "scorer": {"name": "Dawson Mercer", "sweater": 91},
                        "assists": [{"name": "Luke Hughes", "sweater": 43}]},
    "change": {"discrepancy_type": "scorer_change", "affects_goal_total": False,
               "attribution_only": True, "detail": "scorer changed"},
    "reason": {"category": "official_source_statement", "text": "OFFICIAL SCORING CHANGE: ..."},
    "timing": {"when": "postgame_after_publication", "reasoning": "announced after final"},
    "settlement": {"level": "attribution", "reasoning": "attribution only"},
    "sources": [{"role": "corrected_state", "type": "official-document",
                 "name": "GS021140.HTM",
                 "url": "https://www.nhl.com/scores/htmlreports/20242025/GS021140.HTM",
                 "http_status": 200, "retrieved_at_utc": "2026-10-07T00:00:00Z"}],
    "evidence_status": "verified",
    "flags": ["initial_state_reported_by_secondary_source_only"],
    "detection": {"detected_by": "ingest", "detected_at_utc": "2026-10-07T00:00:00Z",
                  "confidence": "high"},
}

ENGINE_RECORD = {
    "record_id": "SDN-42c8407955",
    "schema_version": "1.0",
    "status": "pending_review",
    "confidence": "medium",
    "detected_by": "manual_research",
    "detection": {"check_id": "MANUAL", "rule": "nogoal_reversed_to_goal_on_league_review",
                  "rule_label": "Ruling change reported", "severity": "high",
                  "detected_at": "2026-10-07T05:00:00Z", "run_id": "unit", "tool_version": "test"},
    "game": {"game_id": None, "season": "20262027", "game_type": "REG", "date": "2026-10-01",
             "away_team": "EDM", "home_team": "VAN", "final_score": None, "gamecenter_url": None,
             "report_urls": {}},
    "discrepancy": {"period": 3, "clock": None, "team": "VAN", "field": "ruling", "goal_key": None,
                    "change_type": "nogoal_reversed_to_goal_on_league_review",
                    "summary": "goal reinstated after league review",
                    "detail": "goal reinstated after league review",
                    "total_changed": None, "attribution_only": False,
                    "goal_no_goal_change": True, "video_review": True,
                    "when_corrected": "in_game", "timing_uncertain": True,
                    "reason": {"stated_by_league": False, "text": "", "rule_citation": None,
                               "needs_human_read": True},
                    "market_impact": {"total_changed": None, "affects_game_total": "yes",
                                      "affects_period_total": "yes", "affects_player_props": "yes",
                                      "affects_result_markets": "yes", "risk": "high",
                                      "reason": "a goal that did not exist now exists",
                                      "rule_class": "total"}},
    "initial_state": {"artifact": "on-ice ruling", "goal_present": False,
                      "ruling": "no_goal_gloved_puck", "scorer": {"name": "M. Rossi"},
                      "assists": [], "period": 3, "clock": None, "team": "VAN"},
    "corrected_state": {"artifact": "Situation Room review outcome", "goal_present": True,
                        "ruling": "goal", "scorer": {"name": "M. Rossi"}, "assists": [],
                        "period": 3, "clock": None, "team": "VAN"},
    "totals": {"initial_game_goals": None, "corrected_game_goals": None, "goal_delta": 1,
               "basis": "reported"},
    "sources": [{"label": "Official GS sheet", "url": "https://www.nhl.com/scores/htmlreports/x.HTM",
                 "kind": "official_report", "evidence": "primary", "retrieved_at": ""}],
    "verification": {"status": "pending_review", "evidence_grade": "secondary",
                     "independently_checkable": True, "check_instructions": "",
                     "verified_by": "", "verified_at": ""},
    "flags": ["requires_human_verification"],
    "notes": "",
    "first_seen_at": "2026-10-07T05:00:00Z",
    "seen_count": 1,
}


class TestMonitorAlertFeedProjection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.data = os.path.join(self.tmp, "data")
        os.makedirs(self.data)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _emit(self, records):
        return monitor_alerts.emit_for_records(
            records, root=os.path.join(self.data, "alerts"))

    def test_emitting_an_alert_writes_the_feed_the_site_reads(self):
        """The published page reads data/alerts.json - it must not stay empty."""
        out = self._emit([MONITOR_RECORD])
        self.assertEqual(len(out["alerts"]), 1)

        feed_path = os.path.join(self.data, "alerts.json")
        self.assertTrue(os.path.exists(feed_path),
                        "emit_for_records must project into data/alerts.json")
        feed = json.load(open(feed_path))
        self.assertEqual(len(feed["alerts"]), 1)
        alert = feed["alerts"][0]
        self.assertEqual(alert["id"], "ALERT-NHL-20242025-021140-01")
        self.assertEqual(alert["record_id"], "NHL-20242025-021140-01")
        self.assertEqual(alert["type"], "scorer_change")
        self.assertIn("NJD @ CHI", alert["title"])
        self.assertTrue(alert["body"])
        self.assertEqual(alert["links"],
                         ["https://www.nhl.com/scores/htmlreports/20242025/GS021140.HTM"])
        self.assertTrue(alert["created_at"])

    def test_the_rss_feed_is_regenerated_with_the_alert(self):
        self._emit([MONITOR_RECORD])
        rss = open(os.path.join(self.data, "alerts.xml"), encoding="utf-8").read()
        self.assertIn("<item>", rss)
        self.assertIn("Goal scorer changed", rss)
        self.assertIn("GS021140.HTM", rss)

    def test_re_emitting_does_not_make_an_old_alert_look_new(self):
        self._emit([MONITOR_RECORD])
        first = json.load(open(os.path.join(self.data, "alerts.json")))["alerts"][0]

        second = self._emit([MONITOR_RECORD])
        again = json.load(open(os.path.join(self.data, "alerts.json")))["alerts"][0]
        self.assertEqual(len(second["alerts"]), 1)
        self.assertEqual(len(json.load(open(os.path.join(self.data, "alerts.json")))["alerts"]), 1,
                         "the same correction must not appear twice in the feed")
        self.assertEqual(again["created_at"], first["created_at"],
                         "created_at must survive a re-emit or the feed fakes recency")
        self.assertEqual(again.get("first_seen_at"), first["created_at"])

    def test_an_existing_alert_from_the_other_writer_is_preserved(self):
        """Both detection routes write this file; neither may clobber the other."""
        feed_path = os.path.join(self.data, "alerts.json")
        with open(feed_path, "w", encoding="utf-8") as fh:
            json.dump({"schema_version": 1, "generated_at": "2026-01-01T00:00:00Z",
                       "alerts": [{"id": "SDN-keepme", "record_id": "SDN-keepme",
                                   "title": "kept", "body": "kept", "links": [],
                                   "created_at": "2026-01-01T00:00:00Z"}]}, fh)

        self._emit([MONITOR_RECORD])
        ids = {a["id"] for a in json.load(open(feed_path))["alerts"]}
        self.assertEqual(ids, {"SDN-keepme", "ALERT-NHL-20242025-021140-01"})

    def test_index_and_feed_stay_in_step(self):
        out = self._emit([MONITOR_RECORD])
        index = json.load(open(out["index"][0]))
        feed = json.load(open(os.path.join(self.data, "alerts.json")))
        self.assertEqual(index["count"], len(feed["alerts"]))


class TestEngineAlertFeedProjection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "data"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_triaged_alerts_reach_the_site_feed(self):
        triaged = engine_alerts.triage([ENGINE_RECORD])
        self.assertEqual(len(triaged), 1)
        out = engine_alerts.write_site_feed(triaged, self.tmp, now="2026-10-07T06:00:00Z")

        feed = json.load(open(out["json"]))
        self.assertEqual(len(feed["alerts"]), 1)
        alert = feed["alerts"][0]
        self.assertEqual(alert["id"], "SDN-42c8407955")
        self.assertEqual(alert["severity"], "high", "an 'immediate' alert must not render as low")
        self.assertIn("EDM @ VAN", alert["title"])
        self.assertIn("nogoal_reversed_to_goal_on_league_review", alert["body"])
        self.assertIn("nhl.com", alert["links"][0])

    def test_a_possible_total_impact_alerts_at_medium_not_high(self):
        """The mapping must stay honest in both directions."""
        softer = json.loads(json.dumps(ENGINE_RECORD))
        softer["record_id"] = "SDN-softer"
        softer["discrepancy"]["market_impact"]["affects_game_total"] = "possible"
        out = engine_alerts.write_site_feed(engine_alerts.triage([softer]), self.tmp)
        alert = json.load(open(out["json"]))["alerts"][0]
        self.assertEqual(alert["severity"], "medium")

    def test_rss_is_well_formed_and_carries_the_link(self):
        engine_alerts.write_site_feed(engine_alerts.triage([ENGINE_RECORD]), self.tmp)
        rss = open(os.path.join(self.tmp, "data", "alerts.xml"), encoding="utf-8").read()
        self.assertIn("<item>", rss)
        self.assertIn("htmlreports", rss)
        self.assertTrue(rss.strip().endswith("</rss>"))

    def test_both_writers_can_share_one_feed(self):
        """The engine writes first, then the monitor: both alerts must survive."""
        engine_alerts.write_site_feed(engine_alerts.triage([ENGINE_RECORD]), self.tmp)
        monitor_alerts.write_site_feed(
            [monitor_alerts.build_alert(MONITOR_RECORD)],
            json_path=os.path.join(self.tmp, "data", "alerts.json"),
            rss_path=os.path.join(self.tmp, "data", "alerts.xml"))
        feed = json.load(open(os.path.join(self.tmp, "data", "alerts.json")))
        self.assertEqual({a["id"] for a in feed["alerts"]},
                         {"SDN-42c8407955", "ALERT-NHL-20242025-021140-01"})


class TestNoRecordContradictsItself(unittest.TestCase):
    """A corrected record must not still carry the claim that was corrected.

    This shipped once. The withdrawal was applied to the record but not to the
    case file the record is rebuilt from, so the next ingest re-added
    `official_payload_contains_two_different_clip_titles_for_the_same_goal`
    alongside `initial_state_corroboration_withdrawn_on_reverification`, and the
    published alert body listed both.
    """

    def test_the_guard_fires_on_a_contradictory_flag_pair(self):
        from nhl_monitor import store

        errors = store._flag_contradictions(
            ["official_payload_contains_two_different_clip_titles_for_the_same_goal",
             "initial_state_corroboration_withdrawn_on_reverification"])
        self.assertEqual(len(errors), 1)
        self.assertIn("contradictory flags", errors[0])

    def test_the_guard_stays_quiet_on_a_single_sided_record(self):
        from nhl_monitor import store

        self.assertEqual(store._flag_contradictions(
            ["initial_state_corroboration_withdrawn_on_reverification"]), [])
        self.assertEqual(store._flag_contradictions(
            ["official_payload_contains_two_different_clip_titles_for_the_same_goal"]), [])

    def test_no_committed_record_in_either_store_contradicts_itself(self):
        from nhl_monitor import store

        offenders = []
        for r in store.load_records():
            offenders.extend((r.get("record_id"), e) for e in store._flag_contradictions(r.get("flags")))
        self.assertEqual(offenders, [])

        engine_path = os.path.join(ROOT, "data", "discrepancies.json")
        engine = json.load(open(engine_path))
        for r in engine.get("records", []):
            offenders.extend((r.get("record_id"), e)
                             for e in store._flag_contradictions(r.get("flags")))
        self.assertEqual(offenders, [])

    def test_the_corrected_record_carries_the_withdrawal_and_not_the_claim(self):
        from nhl_monitor import store

        rec = next(r for r in store.load_records()
                   if r["record_id"] == "NHL-20242025-021140-01")
        self.assertIn("initial_state_corroboration_withdrawn_on_reverification", rec["flags"])
        self.assertNotIn("official_payload_contains_two_different_clip_titles_for_the_same_goal",
                         rec["flags"])
        self.assertTrue(rec.get("reverification", {}).get("not_confirmed"))

    def test_no_committed_alert_body_lists_a_withdrawn_claim(self):
        """The alert body is what a subscriber actually reads."""
        feed = json.load(open(os.path.join(ROOT, "data", "alerts.json")))
        for a in feed.get("alerts", []):
            self.assertNotIn("official_payload_contains_two_different_clip_titles_for_the_same_goal",
                             a.get("body") or "",
                             f"alert {a.get('id')} still advertises a withdrawn claim")

    def test_no_derived_artifact_republishes_a_withdrawn_claim(self):
        """Every artifact the site or a subscriber reads, not just the alert feed.

        Fixing the record and the feed was not enough: the engine store embeds a
        verbatim copy of the parallel line's object under ``parallel_record``, that
        copy was frozen while the record was protected, and ``docs/data.js`` - the
        payload the published site actually renders - republished the stale flags
        from it. History is allowed to retain a withdrawn claim; a *current* flags
        list is not.
        """
        stale = "official_payload_contains_two_different_clip_titles_for_the_same_goal"

        def current_flags(obj):
            """Every flags list that asserts the present state, skipping history."""
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if key in ("previous_revisions", "withdrawn_flags", "detection_history"):
                        continue  # an audit trail is supposed to keep superseded claims
                    if key == "flags" and isinstance(value, list):
                        yield value
                    else:
                        yield from current_flags(value)
            elif isinstance(obj, list):
                for item in obj:
                    yield from current_flags(item)

        checked = 0
        for rel in ("data/discrepancies.json", "data/records/discrepancies.json",
                    "data/alerts.json", "data/alerts/index.json",
                    "data/alerts/2026-10-07/alerts.json"):
            path = os.path.join(ROOT, rel)
            if not os.path.exists(path):
                continue
            checked += 1
            for flags in current_flags(json.load(open(path, encoding="utf-8"))):
                self.assertNotIn(stale, flags, f"{rel} still asserts a withdrawn claim")

        # docs/data.js is the published site's payload: window.SDN = {...}
        site = os.path.join(ROOT, "docs", "data.js")
        if os.path.exists(site):
            checked += 1
            payload = json.loads(open(site, encoding="utf-8").read()
                                 .split("=", 1)[1].strip().rstrip(";"))
            for flags in current_flags(payload):
                self.assertNotIn(stale, flags, "docs/data.js still asserts a withdrawn claim")

        self.assertGreaterEqual(checked, 4, "expected to scan the shipped artifacts")


class TestCommittedAlertFeedIsNotEmpty(unittest.TestCase):
    """The committed repository state, asserted directly.

    This is the check that was missing: three alerts were committed under
    data/alerts/ while data/alerts.json - the file the published site fetches -
    held an empty list, so the live page said "No alerts yet".
    """

    def test_committed_site_feed_matches_the_committed_alerts(self):
        feed_path = os.path.join(ROOT, "data", "alerts.json")
        index_path = os.path.join(ROOT, "data", "alerts", "index.json")
        if not os.path.exists(feed_path) or not os.path.exists(index_path):
            self.skipTest("no committed alert feed")
        feed = json.load(open(feed_path))
        index = json.load(open(index_path))
        self.assertGreater(len(feed.get("alerts", [])), 0,
                           "the published site reads this file; it must not be empty while "
                           "alerts exist in data/alerts/index.json")
        index_ids = {a.get("record_id") for a in index["alerts"]}
        feed_ids = {a.get("record_id") for a in feed["alerts"]}
        self.assertTrue(index_ids <= feed_ids,
                        f"alerts missing from the site feed: {index_ids - feed_ids}")

    def test_committed_rss_is_not_empty(self):
        rss_path = os.path.join(ROOT, "data", "alerts.xml")
        rss = open(rss_path, encoding="utf-8").read()
        self.assertIn("<item>", rss, "the advertised RSS feed must carry the committed alerts")


class MonitorLineIssueDedupeTests(unittest.TestCase):
    """The five-minute monitor must not open the same issue twice.

    ``monitor.yml`` runs on a schedule and a detectable change stays detectable, so
    an issue path with no memory of what it already sent would open a new issue on
    every pass. The canonical delivery path is ``nhl_scoring.notify``; this guards
    the legacy ``--github-issue`` flag against flooding while it still exists.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "alerts")
        os.makedirs(self.root, exist_ok=True)
        self.calls = []
        self._real = monitor_alerts.open_github_issue
        monitor_alerts.open_github_issue = lambda title, body, labels=None, repo=None: (
            self.calls.append(title) or {"created": True, "url": f"https://github.example/issues/{len(self.calls)}",
                                         "reason": ""})

    def tearDown(self):
        monitor_alerts.open_github_issue = self._real
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_one_issue_per_alert_id_however_many_times_it_is_emitted(self):
        for _ in range(3):
            monitor_alerts.emit_for_records([MONITOR_RECORD], root=self.root, github_issue=True)
        self.assertEqual(len(self.calls), 1, "the same alert id must not open a second issue")
        state = json.load(open(os.path.join(self.root, "notified_issues.json"), encoding="utf-8"))
        self.assertEqual(len(state), 1)
        self.assertTrue(next(iter(state.values()))["url"])

    def test_a_failed_issue_creation_is_retried_next_run(self):
        monitor_alerts.open_github_issue = lambda *a, **k: {"created": False, "url": None,
                                                            "reason": "gh CLI not available"}
        monitor_alerts.emit_for_records([MONITOR_RECORD], root=self.root, github_issue=True)
        self.assertFalse(os.path.exists(os.path.join(self.root, "notified_issues.json")),
                         "an issue that was not created must not be remembered as delivered")

    def test_the_monitor_alert_route_reaches_the_published_feed(self):
        """Regression: the scheduled monitor wrote per-date files only."""
        monitor_alerts.emit_for_records([MONITOR_RECORD], root=self.root)
        data_dir = os.path.dirname(self.root)
        feed = json.load(open(os.path.join(data_dir, "alerts.json"), encoding="utf-8"))
        self.assertTrue(feed.get("alerts"), "emit_for_records must project into the site feed")


if __name__ == "__main__":
    unittest.main()
