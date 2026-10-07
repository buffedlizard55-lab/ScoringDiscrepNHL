"""Tests for alerting, the static site builder, and the record store on disk."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "pipeline")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nhl_scoring import alerts, db as db_mod, site  # noqa: E402

RECORD = {
    "record_id": "SDN-abc123",
    "schema_version": "1.0",
    "status": "flagged",
    "confidence": "medium",
    "detected_by": "cross_source",
    "detection": {"check_id": "C10", "rule": "goal_missing_from_one_source",
                  "rule_label": "A goal exists in one official artifact and not the other",
                  "severity": "high", "detected_at": "2026-10-07T04:00:00Z", "run_id": "unit",
                  "tool_version": "test"},
    "game": {"game_id": "2026020003", "season": "20262027", "game_type": "REG", "date": "2026-10-03",
             "away_team": "CGY", "home_team": "VAN", "final_score": {"away": 1, "home": 4},
             "gamecenter_url": "https://www.nhl.com/gamecenter/2026020003",
             "report_urls": {"GS": "https://www.nhl.com/scores/htmlreports/20262027/GS020003.HTM"}},
    "discrepancy": {"period": 3, "clock": "01:30", "team": "VAN", "field": "goal_presence",
                    "change_type": "goal_missing_from_one_source",
                    "summary": "VAN third-period goal present in the JSON, absent from the sheet",
                    "detail": "goal present in nhl_api_landing but not in nhl_gs_report",
                    "total_changed": None, "attribution_only": False,
                    "goal_no_goal_change": True, "video_review": True,
                    "when_corrected": "in_game", "timing_uncertain": True,
                    "reason": {"stated_by_league": True, "text": "Goal awarded after review.",
                               "rule_citation": "78.4", "needs_human_read": True},
                    "market_impact": {"total_changed": None, "affects_game_total": "possible",
                                      "affects_period_total": "possible", "affects_player_props": "yes",
                                      "affects_result_markets": "possible", "risk": "high",
                                      "reason": "Two official records disagree on the existence of a goal.",
                                      "rule_class": "total"}},
    "initial_state": {"artifact": "nhl_api_landing", "goal_present": True, "ruling": "goal",
                      "scorer": {"name": "L. Ohgren"}, "assists": [{"name": "E. Pettersson"}],
                      "period": 3, "clock": "01:30", "team": "VAN", "strength": "EV",
                      "score_after": {"away": 1, "home": 4}},
    "corrected_state": {"artifact": "nhl_gs_report", "goal_present": False,
                        "ruling": "not_recorded_by_this_artifact", "scorer": None, "assists": [],
                        "period": 3, "clock": "01:30", "team": "VAN"},
    "totals": {"initial_game_goals": 5, "corrected_game_goals": 4, "goal_delta": -1},
    "sources": [
        {"label": "NHL Game Center JSON", "url": "https://api-web.nhle.com/v1/gamecenter/2026020003/landing",
         "kind": "official_api", "evidence": "primary", "retrieved_at": "2026-10-07T04:00:00Z",
         "sha256": "a" * 64},
        {"label": "NHL Game Summary report", "url": "https://www.nhl.com/scores/htmlreports/20262027/GS020003.HTM",
         "kind": "official_report", "evidence": "primary", "retrieved_at": "2026-10-07T04:00:01Z"},
    ],
    "verification": {"status": "flagged", "evidence_grade": "primary", "independently_checkable": True,
                     "check_instructions": "open both links", "verified_by": "", "verified_at": ""},
    "flags": ["requires_human_verification", "total_change_not_established"],
    "notes": "",
}


class AlertTests(unittest.TestCase):
    def test_should_alert_by_rule(self):
        self.assertEqual(alerts.should_alert(RECORD), "review")
        goal_change = json.loads(json.dumps(RECORD))
        goal_change["detection"]["rule"] = "post_snapshot_goal_count_change"
        self.assertEqual(alerts.should_alert(goal_change), "immediate")
        retired = json.loads(json.dumps(RECORD))
        retired["status"] = "retired"
        self.assertIsNone(alerts.should_alert(retired))

    def test_triage_sorts_and_dedupes(self):
        urgent = json.loads(json.dumps(RECORD))
        urgent["record_id"] = "SDN-0000000002"
        urgent["detection"]["rule"] = "final_score_conflict"
        items = alerts.triage([RECORD, urgent, RECORD])
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["level"], "immediate")

    def test_render_mentions_both_states_and_links(self):
        text = alerts.render_record(RECORD, level="review")
        self.assertIn("L. Ohgren", text)
        self.assertIn("https://www.nhl.com/scores/htmlreports/20262027/GS020003.HTM", text)
        self.assertTrue("goal total" in text or "Goal total" in text)
        self.assertIn("requires_human_verification", text)
        self.assertIn("**Goal total affected:** possible", text)

    def test_write_alerts_creates_both_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            items = alerts.triage([RECORD])
            out = alerts.write_alerts(items, tmp, date_str="2026-10-07", run_id="unit",
                                      coverage={"games_scanned": 5, "games_parsed": 4, "games_unreadable": 1})
            md = open(out["markdown"], encoding="utf-8").read()
            payload = json.load(open(out["json"], encoding="utf-8"))
            self.assertEqual(payload["count"], 1)
            self.assertIn("SDN-abc123", md)
            self.assertIn("unreadable", md)
            self.assertIn("4 parsed", md)

    def test_webhook_payload_shape(self):
        payload = alerts.webhook_payload(alerts.triage([RECORD]))
        self.assertIn("text", payload)
        self.assertIn("content", payload)
        self.assertEqual(payload["_sdn"]["count"], 1)
        self.assertIn("[review]", payload["text"])

    def test_issue_title(self):
        self.assertIn("1 NHL scoring discrepancy", alerts.issue_title(alerts.triage([RECORD])))
        self.assertIn("no new", alerts.issue_title([]))

    def test_situation_room_quotes_only_take_sentence_like_text(self):
        quotes = alerts.parse_situation_room_text(
            'The Situation Room "video review confirmed the call on the ice that the puck deflected off '
            'the shoulder and entered the net in a legal fashion" per Rule 78.4. "Short" ignored.')
        self.assertEqual(len(quotes), 1)
        self.assertIn("deflected off the shoulder", quotes[0]["quote"])


class SiteTests(unittest.TestCase):
    def test_markdown_renderer(self):
        html = site.md_to_html(
            "# Title\n\nSome *emphasis* and `code` and [a link](https://nhl.com/x).\n\n"
            "- one\n- two\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n> quoted\n\n1. first\n2. second\n")
        self.assertIn("<h1>Title</h1>", html)
        self.assertIn('<a href="https://nhl.com/x" target="_blank"', html)
        self.assertIn("<li>one</li>", html)
        self.assertIn("<td>1</td>", html)
        self.assertIn("<blockquote>quoted</blockquote>", html)
        self.assertIn("<ol>", html)

    def test_markdown_escapes_html(self):
        self.assertNotIn("<script>", site.md_to_html("<script>alert(1)</script>"))

    def test_markdown_strikethrough_and_multiline_list(self):
        # Regression: `~~struck~~` must render as <del>, and an indented
        # continuation line must stay inside its list item (it used to escape as
        # a separate <p> and split one list into several, leaving literal `~~`).
        html = site.md_to_html(
            "1. ~~old claim~~ **Corrected:** new fact\n"
            "   continues on the next line.\n"
            "2. Second item.\n")
        self.assertIn("<del>old claim</del>", html)
        self.assertNotIn("~~", html)
        # One <ol>, two <li>, and the continuation folded into the first item.
        self.assertEqual(html.count("<ol>"), 1)
        self.assertEqual(html.count("<li>"), 2)
        self.assertIn("<li><del>old claim</del> <strong>Corrected:</strong> new fact continues on the next line.</li>", html)
        # A `~~` inside a fenced code block must NOT be struck.
        code = site.md_to_html("```\nkeep ~~this~~ literal\n```")
        self.assertIn("~~this~~", code)
        self.assertNotIn("<del>", code)

    def test_summarize_counts(self):
        summary = site.summarize([RECORD])
        self.assertEqual(summary["record_count"], 1)
        self.assertEqual(summary["teams"], ["CGY", "VAN"])
        self.assertEqual(summary["total_change_unknown"], 1)
        self.assertEqual(summary["seasons"], {"20262027": 1})

    def test_build_writes_all_files_and_data_is_valid_js(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            os.makedirs(data_dir)
            db_path = os.path.join(data_dir, "discrepancies.json")
            db_mod.save_db({"records": [RECORD]}, db_path)
            out = os.path.join(tmp, "docs")
            written = site.build(out, db_path=db_path, repo_root=ROOT)
            names = sorted(os.path.basename(p) for p in written)
            self.assertEqual(names, [".nojekyll", "app.js", "data.js", "index.html", "styles.css"])
            js = open(os.path.join(out, "data.js"), encoding="utf-8").read()
            self.assertTrue(js.startswith("window.SDN = "))
            payload = json.loads(js[len("window.SDN = "):].rstrip().rstrip(";"))
            self.assertEqual(payload["records"][0]["record_id"], "SDN-abc123")
            self.assertIn("record_count", payload["summary"])
            # docs must be embedded, not just linked
            self.assertIn("Detection feasibility", json.dumps(payload["docs"]) if "docs" in payload else "")
            html = open(os.path.join(out, "index.html"), encoding="utf-8").read()
            self.assertIn('rel="stylesheet"', html)
            self.assertIn("Skip to content", html)

    def test_no_unescaped_closing_script_tag_in_data(self):
        hostile = json.loads(json.dumps(RECORD))
        hostile["notes"] = "</script><script>alert(1)</script>"
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "discrepancies.json")
            db_mod.save_db({"records": [hostile]}, db_path)
            site.build(tmp, db_path=db_path, repo_root=ROOT)
            js = open(os.path.join(tmp, "data.js"), encoding="utf-8").read()
            self.assertNotIn("</script>", js)

    @unittest.skipUnless(shutil.which("node"), "node not available")
    def test_assets_parse_as_javascript_and_balanced_css(self):
        for name in ("app.js",):
            path = os.path.join(ROOT, "pipeline", "nhl_scoring", "site_assets", name)
            subprocess.run(["node", "--check", path], check=True)
        css = site.read_asset("styles.css")
        self.assertEqual(css.count("{"), css.count("}"))
        html = site.read_asset("index.html")
        self.assertEqual(html.count("<section"), html.count("</section>"))


class RepoDataTests(unittest.TestCase):
    """The committed database must itself pass the rules we ship."""

    def test_committed_database_validates(self):
        path = os.path.join(ROOT, "data", "discrepancies.json")
        if not os.path.exists(path):
            self.skipTest("no database committed yet")
        payload = db_mod.load_db(path)
        for record in payload["records"]:
            self.assertEqual(db_mod.validate(record), [], f"{record.get('record_id')} invalid")
        self.assertEqual(payload["record_count"], len(payload["records"]))

    def test_csv_mirrors_json_row_count(self):
        json_path = os.path.join(ROOT, "data", "discrepancies.json")
        csv_path = os.path.join(ROOT, "data", "discrepancies.csv")
        if not (os.path.exists(json_path) and os.path.exists(csv_path)):
            self.skipTest("database or csv missing")
        import csv as _csv
        with open(csv_path, newline="", encoding="utf-8") as fh:
            rows = list(_csv.reader(fh))
        payload = db_mod.load_db(json_path)
        self.assertEqual(len(rows) - 1, len(payload["records"]),
                         "csv must be regenerated with `python -m nhl_scoring.cli merge --apply`")
        self.assertEqual(rows[0], db_mod.CSV_COLUMNS)

    def test_schema_file_documents_every_top_level_field(self):
        path = os.path.join(ROOT, "data", "schema", "discrepancy.schema.json")
        if not os.path.exists(path):
            self.skipTest("schema file not present")
        schema = json.load(open(path, encoding="utf-8"))
        for field in db_mod.REQUIRED_TOP:
            self.assertIn(field, schema["properties"], field)


if __name__ == "__main__":
    unittest.main()
