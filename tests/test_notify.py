"""Tests for the notification delivery layer (``pipeline/nhl_scoring/notify.py``).

The defect these tests exist to prevent: detection worked, the feed was written,
and nobody was told. The Situation Room ingest — the primary detection path — raised
alerts into ``data/alerts.json`` and stopped there, so a subscriber had to open the
website to learn anything. Everything below asserts on *delivery*, not on detection.

Nothing here touches the network. The GitHub, webhook and SMTP transports are
injected, so a test proves what the code sends (URL, headers, payload) rather than
trusting that a live service would have accepted it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "pipeline")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nhl_scoring import notify  # noqa: E402


def alert(alert_id: str, *, severity: str = "high", total: bool = True,
          record_id: str = "", body: str = "a goal was overturned",
          links=None, created_at: str = "2026-10-07T01:41:00Z") -> dict:
    return {
        "id": alert_id,
        "record_id": record_id or alert_id,
        "severity": severity,
        "title": f"[IMMEDIATE] 2026-10-06 NSH @ TOR - {alert_id}",
        "body": body,
        "links": links if links is not None else ["https://www.nhl.com/news/example"],
        "created_at": created_at,
        "affects_goal_total": total,
        "settlement_risk": "high" if total else "",
        "settlement_window": "in_game" if total else "",
        "settlement_reason": "record's own settlement wording" if total else "",
        "detected_by": "nhl_scoring",
    }


class FakeGitHub:
    """Records every request; answers label lookups and issue creation."""

    def __init__(self, *, existing_labels=("scoring-discrepancy", "auto-detected"),
                 issue_status: int = 201, issue_body: str = ""):
        self.existing = set(existing_labels)
        self.issue_status = issue_status
        self.issue_body = issue_body or json.dumps({"html_url": "https://github.example/issues/1"})
        self.posts = []
        self.gets = []

    def get(self, url, headers, timeout=20):
        self.gets.append({"url": url, "headers": headers})
        label = url.rsplit("/labels/", 1)[-1]
        return (200, "{}") if label in self.existing else (404, '{"message":"Not Found"}')

    def post(self, url, body, headers, timeout=20):
        payload = json.loads(body.decode("utf-8") or "{}")
        self.posts.append({"url": url, "payload": payload, "headers": headers})
        if url.endswith("/labels"):
            self.existing.add(payload.get("name"))
            return 201, "{}"
        if url.endswith("/issues"):
            return self.issue_status, self.issue_body
        return 200, "{}"

    @property
    def issues(self):
        return [p for p in self.posts if p["url"].endswith("/issues")]


class FakeWebhook:
    def __init__(self, status=200, text="ok"):
        self.status = status
        self.text = text
        self.posts = []

    def post(self, url, body, headers, timeout=20):
        self.posts.append({"url": url, "payload": json.loads(body.decode("utf-8")), "headers": headers})
        return self.status, self.text


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=30):
        self.host = host
        self.port = port
        self.sent = []
        self.started_tls = False
        # NB: named `credentials`, not `login` - an instance attribute called
        # `login` shadows the method and the send fails with a confusing
        # "NoneType is not callable".
        self.credentials = None
        FakeSMTP.instances.append(self)

    def starttls(self):
        self.started_tls = True

    def login(self, user, password):
        self.credentials = (user, password)

    def send_message(self, message):
        self.sent.append(message)

    def quit(self):
        pass


class ResponseParsingTests(unittest.TestCase):
    """The issue URL in the report comes from the real GitHub response body."""

    def test_url_is_read_from_a_complete_response(self):
        self.assertEqual(notify.extract_url('{"html_url": "https://github.example/o/r/issues/18"}'),
                         "https://github.example/o/r/issues/18")

    def test_url_survives_a_truncated_response(self):
        # A capped read can hand back half a JSON document; the subscriber still
        # gets a link instead of an empty field in the committed report.
        truncated = '{"html_url": "https://github.example/o/r/issues/18", "number": 18, ' + '"pad": "x", ' * 400
        with self.assertRaises(ValueError):
            json.loads(truncated)
        self.assertEqual(notify.extract_url(truncated), "https://github.example/o/r/issues/18")

    def test_missing_url_is_empty_not_invented(self):
        self.assertEqual(notify.extract_url('{"number": 18}'), "")
        self.assertEqual(notify.extract_url("not json"), "")


class PartitionTests(unittest.TestCase):
    def test_new_updated_and_unchanged_are_separated(self):
        state = notify.load_state("/nonexistent/state.json")
        first = alert("A-1")
        notify.deliver([first], state=state, channels=("feed",), now="2026-10-07T10:00:00Z")
        same = alert("A-1")
        changed = alert("A-1", body="the record was re-verified and the wording changed")
        brand_new = alert("A-2")
        parts = notify.partition([same, changed, brand_new], state)
        self.assertEqual([a["id"] for a in parts["new"]], ["A-2"])
        self.assertEqual([a["id"] for a in parts["updated"]], ["A-1"])
        self.assertEqual([a["id"] for a in parts["unchanged"]], ["A-1"])

    def test_fingerprint_ignores_cosmetic_regeneration(self):
        a = alert("A-1")
        b = dict(a, detected_at="2026-10-08T00:00:00Z", first_seen_at="2026-10-07T00:00:00Z")
        self.assertEqual(notify.fingerprint(a), notify.fingerprint(b),
                         "a re-run of the same detection must not re-notify a subscriber")

    def test_fingerprint_moves_when_a_subscriber_would_read_something_different(self):
        a = alert("A-1")
        for change in ({"severity": "low"}, {"links": ["https://www.nhl.com/news/other"]},
                       {"affects_goal_total": False}, {"title": "a different ruling"}):
            with self.subTest(change=change):
                self.assertNotEqual(notify.fingerprint(a), notify.fingerprint(dict(a, **change)))


class DeliverOnceTests(unittest.TestCase):
    def test_second_run_delivers_nothing(self):
        state = notify.load_state("/nonexistent/state.json")
        gh = FakeGitHub()
        first = notify.deliver([alert("A-1"), alert("A-2", total=False, severity="medium")],
                              state=state, channels=("issue",), now="2026-10-07T10:00:00Z",
                              post=gh.post, get=gh.get, token="t")
        self.assertEqual(len(gh.issues), 2, "one issue for the goal-total change plus one digest")
        self.assertEqual(first["failed_channels"], [])
        parts = notify.partition([alert("A-1"), alert("A-2", total=False, severity="medium")], state)
        self.assertEqual(parts["new"], [])
        self.assertEqual(parts["updated"], [])
        self.assertEqual(len(parts["unchanged"]), 2)
        second = notify.deliver([], state=state, channels=("issue",), now="2026-10-07T10:30:00Z",
                                post=gh.post, get=gh.get, token="t",
                                unchanged=len(parts["unchanged"]))
        self.assertEqual(second["deliveries"], [])
        self.assertEqual(second["note"], "nothing new to deliver")
        self.assertEqual(len(gh.issues), 2, "an unchanged alert must never be sent twice")

    def test_state_survives_a_round_trip_through_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "notifications_state.json")
            state = notify.load_state(path)
            notify.deliver([alert("A-1")], state=state, channels=("feed",),
                           now="2026-10-07T10:00:00Z")
            notify.save_state(path, state)
            reloaded = notify.load_state(path)
            self.assertIn("A-1", reloaded["notified"])
            self.assertEqual(reloaded["notified"]["A-1"]["fingerprint"], notify.fingerprint(alert("A-1")))
            # the legacy flat keys stay in sync so an older checkout still reads it
            self.assertIn("A-1", reloaded["notified_alert_hashes"])
            self.assertEqual(notify.partition([alert("A-1")], reloaded)["unchanged"][0]["id"], "A-1")

    def test_prime_switches_delivery_on_without_announcing_the_backlog(self):
        state = notify.load_state("/nonexistent/state.json")
        backlog = [alert("A-1"), alert("A-2"), alert("A-3", total=False, severity="low")]
        self.assertEqual(notify.prime(backlog, state, now="2026-10-07T10:00:00Z"), 3)
        gh = FakeGitHub()
        parts = notify.partition(backlog, state)
        pending = parts["new"] + parts["updated"]
        self.assertEqual(pending, [], "everything in the feed is already accounted for")
        report = notify.deliver(pending, state=state, channels=("issue",),
                                now="2026-10-07T10:05:00Z", post=gh.post, get=gh.get, token="t",
                                unchanged=len(parts["unchanged"]))
        self.assertEqual(report["note"], "nothing new to deliver")
        self.assertEqual(gh.issues, [], "a primed backlog is not breaking news")
        # and deliver() itself refuses to re-send a fingerprint it already has,
        # even when a caller hands it the whole feed by mistake
        notify.deliver(backlog, state=state, channels=("issue",), now="2026-10-07T10:06:00Z",
                       post=gh.post, get=gh.get, token="t")
        self.assertEqual(gh.issues, [])
        self.assertEqual(state["notified"]["A-1"]["channels"], {"feed": "primed_from_committed_feed"})
        self.assertEqual(state["notified"]["A-1"]["notices"], 0)


class GitHubChannelTests(unittest.TestCase):
    def test_issue_payload_carries_the_record_the_links_and_the_settlement_words(self):
        gh = FakeGitHub()
        state = notify.load_state("/nonexistent/state.json")
        report = notify.deliver([alert("A-1", links=["https://www.nhl.com/news/a",
                                                     "https://api-web.nhle.com/v1/gamecenter/1/play-by-play"])],
                                state=state, channels=("issue",), now="2026-10-07T10:00:00Z",
                                post=gh.post, get=gh.get, token="secret-token",
                                repo="owner/repo")
        self.assertEqual(report["failed_channels"], [])
        issue = gh.issues[0]
        self.assertEqual(issue["url"], "https://api.github.com/repos/owner/repo/issues")
        self.assertEqual(issue["headers"]["Authorization"], "Bearer secret-token")
        self.assertEqual(issue["headers"]["Accept"], "application/vnd.github+json")
        body = issue["payload"]["body"]
        self.assertIn("https://www.nhl.com/news/a", body)
        self.assertIn("record's own settlement wording", body,
                      "settlement wording is quoted from the record, never paraphrased")
        self.assertIn("A-1", issue["payload"]["title"])
        self.assertIn("goal-total-changed", issue["payload"]["labels"])
        self.assertNotIn("[IMMEDIATE] [HIGH]", issue["payload"]["title"],
                         "the feed's own severity tag must not be doubled up")
        self.assertIn("view=database&q=A-1", body, "the issue must deep-link the record on the site")

    def test_missing_label_is_created_and_the_issue_still_opens(self):
        gh = FakeGitHub(existing_labels=())
        state = notify.load_state("/nonexistent/state.json")
        report = notify.deliver([alert("A-1")], state=state, channels=("issue",),
                                now="2026-10-07T10:00:00Z", post=gh.post, get=gh.get, token="t")
        created = [p["payload"]["name"] for p in gh.posts if p["url"].endswith("/labels")]
        self.assertIn("scoring-discrepancy", created)
        self.assertEqual(len(gh.issues), 1)
        self.assertEqual(report["failed_channels"], [])

    def test_auth_failure_is_reported_and_never_recorded_as_a_delivery(self):
        gh = FakeGitHub(issue_status=401, issue_body='{"message":"Bad credentials"}')
        state = notify.load_state("/nonexistent/state.json")
        report = notify.deliver([alert("A-1")], state=state, channels=("issue",),
                                now="2026-10-07T10:00:00Z", post=gh.post, get=gh.get, token="bad")
        self.assertEqual(report["failed_channels"], ["issue"])
        self.assertEqual(report["deliveries"][0]["status"], "failed")
        self.assertEqual(report["deliveries"][0]["http_status"], 401)
        self.assertNotIn("A-1", state.get("notified") or {},
                         "a failed send must not be recorded as delivered")
        self.assertEqual(report["retry_next_run"], ["A-1"])
        self.assertEqual([a["id"] for a in notify.partition([alert("A-1")], state)["new"]], ["A-1"],
                         "so the next run retries it")

    def test_no_token_means_skipped_with_a_reason_not_a_silent_nothing(self):
        state = notify.load_state("/nonexistent/state.json")
        report = notify.deliver([alert("A-1")], state=state, channels=("issue",),
                                now="2026-10-07T10:00:00Z", token="")
        self.assertEqual(report["deliveries"][0]["status"], "skipped")
        self.assertIn("GITHUB_TOKEN", report["deliveries"][0]["error"])
        self.assertEqual(report["failed_channels"], [], "an unconfigured channel is not a failure")

    def test_labels_are_resolved_once_per_run_not_once_per_issue(self):
        gh = FakeGitHub()
        state = notify.load_state("/nonexistent/state.json")
        notify.deliver([alert(f"A-{i}") for i in range(5)], state=state, channels=("issue",),
                       now="2026-10-07T10:00:00Z", post=gh.post, get=gh.get, token="t",
                       max_issues=4)
        self.assertEqual(len(gh.issues), 5, "4 per-alert issues plus one digest")
        label_lookups = [g for g in gh.gets if "/labels/" in g["url"]]
        self.assertLessEqual(len(label_lookups), 3,
                             f"{len(label_lookups)} label lookups for 5 issues; GitHub rate-limits bursts")

    def test_max_issues_cap_folds_the_rest_into_one_digest(self):
        gh = FakeGitHub()
        state = notify.load_state("/nonexistent/state.json")
        many = [alert(f"A-{i}") for i in range(12)]
        notify.deliver(many, state=state, channels=("issue",), now="2026-10-07T10:00:00Z",
                       post=gh.post, get=gh.get, token="t", max_issues=3)
        self.assertEqual(len(gh.issues), 4, "3 per-alert issues plus one digest")
        self.assertEqual(len(gh.issues[-1]["payload"]["body"].split("### ")) - 1, 9)


class WebhookAndEmailTests(unittest.TestCase):
    def test_webhook_payload_speaks_slack_and_discord_at_once(self):
        hook = FakeWebhook()
        state = notify.load_state("/nonexistent/state.json")
        notify.deliver([alert("A-1"), alert("A-2", total=False, severity="medium")],
                       state=state, channels=("webhook",), now="2026-10-07T10:00:00Z",
                       post=hook.post, webhook_url="https://hooks.example/xyz")
        self.assertEqual(hook.posts[0]["url"], "https://hooks.example/xyz")
        payload = hook.posts[0]["payload"]
        self.assertIn("A-1", payload["text"])
        self.assertIn("GOAL TOTAL CHANGED", payload["text"])
        self.assertTrue(payload["content"])
        self.assertEqual(payload["_sdn"]["goal_total_changes"], 1)

    def test_webhook_failure_is_recorded_and_does_not_stop_the_run(self):
        hook = FakeWebhook(status=500, text="boom")
        gh = FakeGitHub()

        def dispatch(url, body, headers, timeout=20):
            # one transport, routed by host: the failing webhook must not take the
            # GitHub issue down with it
            return hook.post(url, body, headers) if "hooks.example" in url else gh.post(url, body, headers)

        state = notify.load_state("/nonexistent/state.json")
        report = notify.deliver([alert("A-1")], state=state, channels=("webhook", "issue"),
                                now="2026-10-07T10:00:00Z", post=dispatch, get=gh.get,
                                webhook_url="https://hooks.example/xyz", token="t")
        self.assertEqual(report["failed_channels"], ["webhook"])
        self.assertEqual(len(gh.issues), 1, "a dead webhook must not stop the issue being opened")
        by_channel = {d["channel"]: d for d in report["deliveries"]}
        self.assertEqual(by_channel["webhook"]["status"], "failed")
        self.assertEqual(by_channel["webhook"]["http_status"], 500)
        self.assertEqual(by_channel["issue"]["status"], "sent")

    def test_email_digest_is_built_and_sent_through_the_injected_server(self):
        FakeSMTP.instances.clear()
        state = notify.load_state("/nonexistent/state.json")
        report = notify.deliver([alert("A-1")], state=state, channels=("email",),
                                now="2026-10-07T10:00:00Z",
                                smtp_config={"host": "smtp.example", "port": "587",
                                             "user": "u", "password": "p",
                                             "from": "monitor@example", "to": "a@example, b@example"},
                                smtp_factory=FakeSMTP)
        self.assertEqual(report["failed_channels"], [])
        server = FakeSMTP.instances[0]
        self.assertTrue(server.started_tls)
        self.assertEqual(server.credentials, ("u", "p"))
        message = server.sent[0]
        self.assertIn("A-1", message.get_body(("plain",)).get_content())
        self.assertEqual(message["To"], "a@example, b@example")
        self.assertIn("goal-total change", message["Subject"])

    def test_email_without_secrets_is_skipped_not_faked(self):
        state = notify.load_state("/nonexistent/state.json")
        report = notify.deliver([alert("A-1")], state=state, channels=("email",),
                                now="2026-10-07T10:00:00Z", smtp_config={})
        self.assertEqual(report["deliveries"][0]["status"], "skipped")
        self.assertIn("SDN_SMTP_HOST", report["deliveries"][0]["error"])


class DryRunAndSeverityTests(unittest.TestCase):
    def test_dry_run_sends_nothing_and_writes_no_state(self):
        gh = FakeGitHub()
        state = notify.load_state("/nonexistent/state.json")
        report = notify.deliver([alert("A-1")], state=state, channels=("issue", "webhook", "email"),
                                now="2026-10-07T10:00:00Z", post=gh.post, get=gh.get,
                                token="t", webhook_url="https://hooks.example/x", dry_run=True)
        self.assertEqual(gh.issues, [])
        self.assertEqual(state.get("notified"), {})
        self.assertTrue(all(d["dry_run"] for d in report["deliveries"]))
        self.assertEqual(report["mode"], "dry-run")

    def test_min_severity_drops_the_quieter_alerts(self):
        gh = FakeGitHub()
        state = notify.load_state("/nonexistent/state.json")
        report = notify.deliver([alert("A-1", severity="high"),
                                 alert("A-2", severity="medium", total=False),
                                 alert("A-3", severity="low", total=False)],
                                state=state, channels=("issue",), now="2026-10-07T10:00:00Z",
                                post=gh.post, get=gh.get, token="t", min_severity="high")
        self.assertEqual(report["candidates"], 1)
        self.assertEqual(len(gh.issues), 1)

    def test_updated_alert_is_labelled_an_update(self):
        state = notify.load_state("/nonexistent/state.json")
        notify.deliver([alert("A-1")], state=state, channels=("feed",), now="2026-10-07T10:00:00Z")
        gh = FakeGitHub()
        revised = alert("A-1", body="re-verified: the statement names a different rule")
        notify.deliver([revised], state=state, channels=("issue",), updated_ids=["A-1"],
                       now="2026-10-07T11:00:00Z", post=gh.post, get=gh.get, token="t")
        self.assertTrue(gh.issues[0]["payload"]["title"].startswith("[UPDATED]"))
        self.assertIn("re-sent because the record changed", gh.issues[0]["payload"]["body"])
        self.assertEqual(state["notified"]["A-1"]["notices"], 2)


class ChannelDescriptionTests(unittest.TestCase):
    def test_channel_list_reflects_the_environment(self):
        off = {c["id"]: c["configured"] for c in notify.describe_channels({})}
        self.assertEqual(off, {"feed": True, "issue": False, "webhook": False, "email": False})
        on = {c["id"]: c["configured"] for c in notify.describe_channels(
            {"GITHUB_TOKEN": "t", "SDN_WEBHOOK_URL": "https://hooks.example/x",
             "SDN_SMTP_HOST": "smtp.example", "SDN_SMTP_TO": "a@example"})}
        self.assertEqual(on, {"feed": True, "issue": True, "webhook": True, "email": True})

    def test_every_channel_documents_how_to_subscribe(self):
        for channel in notify.describe_channels({}):
            with self.subTest(channel=channel["id"]):
                self.assertTrue(channel["how_to_subscribe"])
                self.assertTrue(channel["requires"] is not None)
                self.assertTrue(channel["latency"])


class CommandLineTests(unittest.TestCase):
    """Drive the real CLI, because the workflow calls the CLI, not the functions."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.feed = os.path.join(self.tmp, "alerts.json")
        self.state = os.path.join(self.tmp, "state.json")
        self.report = os.path.join(self.tmp, "notifications", "last_run.json")
        with open(self.feed, "w", encoding="utf-8") as fh:
            json.dump({"schema_version": 1, "generated_at": "2026-10-07T10:00:00Z",
                       "alerts": [alert("A-1"), alert("A-2", total=False, severity="medium")]}, fh)

    def run_cli(self, *extra):
        env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "pipeline"))
        for key in ("GITHUB_TOKEN", "GH_TOKEN", "SDN_WEBHOOK_URL", "SDN_WEBHOOK"):
            env.pop(key, None)
        cmd = [sys.executable, "-m", "nhl_scoring.cli", "notify",
               "--feed", self.feed, "--state", self.state, "--report", self.report, *extra]
        return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, env=env, timeout=120)

    def test_dry_run_reports_what_would_be_sent_and_changes_nothing(self):
        proc = self.run_cli("--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("2 new", proc.stdout)
        self.assertIn("planned", proc.stdout)
        self.assertFalse(os.path.exists(self.state))
        self.assertFalse(os.path.exists(self.report))

    def test_no_token_and_no_secrets_exits_zero_with_everything_skipped(self):
        proc = self.run_cli()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("skipped", proc.stdout)
        self.assertTrue(os.path.exists(self.report), "a real run always writes its report")
        report = json.load(open(self.report, encoding="utf-8"))
        self.assertEqual(report["failed_channels"], [])
        # the feed channel is unconditional, so the subscriber is never left with nothing
        self.assertIn("feed", [d["channel"] for d in report["deliveries"]])

    def test_second_run_finds_nothing_new(self):
        self.assertEqual(self.run_cli().returncode, 0)
        proc = self.run_cli()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("0 new", proc.stdout)
        self.assertIn("2 already delivered", proc.stdout)

    def test_prime_then_run_does_not_re_announce_the_feed(self):
        self.assertEqual(self.run_cli("--prime").returncode, 0)
        state = json.load(open(self.state, encoding="utf-8"))
        self.assertEqual(len(state["notified"]), 2)
        proc = self.run_cli()
        self.assertIn("0 new", proc.stdout)

    def test_unknown_channel_is_rejected(self):
        proc = self.run_cli("--channels", "carrier-pigeon")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("unknown channel", proc.stderr)

    def test_empty_feed_is_not_an_error(self):
        with open(self.feed, "w", encoding="utf-8") as fh:
            json.dump({"alerts": []}, fh)
        proc = self.run_cli()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("nothing to deliver", proc.stdout)

    def test_describe_lists_the_channels(self):
        proc = self.run_cli("--describe")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        channels = {c["id"] for c in json.loads(proc.stdout)}
        self.assertEqual(channels, set(notify.CHANNELS))


class WorkflowWiringTests(unittest.TestCase):
    """Detection without delivery is the defect this whole module exists to fix.

    Parsed as text on purpose: a runner has no YAML library installed by default,
    and a wiring test that needs one is a wiring test that does not run.
    """

    @staticmethod
    def workflows():
        directory = os.path.join(ROOT, ".github", "workflows")
        return {name: open(os.path.join(directory, name), encoding="utf-8").read()
                for name in sorted(os.listdir(directory)) if name.endswith(".yml")}

    @staticmethod
    def commands(text):
        """The workflow with its comments removed.

        Several steps carry a comment naming the mistake they replaced, and a text
        scan that cannot tell a comment from a command would flag the fix itself.
        """
        return "\n".join(line for line in text.splitlines()
                          if not line.lstrip().startswith("#"))

    def test_every_workflow_that_renders_alerts_also_delivers_them(self):
        for name, text in self.workflows().items():
            if "cli alerts --write" in text:
                with self.subTest(workflow=name):
                    self.assertIn("cli notify", text,
                                  f"{name} renders alerts but never delivers them")

    def test_no_workflow_creates_issues_outside_the_delivery_layer(self):
        for name, text in self.workflows().items():
            commands = self.commands(text)
            with self.subTest(workflow=name):
                self.assertNotIn("--github-issue", commands,
                                 f"{name} opens issues with no memory of what it already sent")
                self.assertNotIn("issue create", commands,
                                 f"{name} hand-rolls issue creation; use nhl_scoring.cli notify")

    def test_the_scheduled_ingest_may_write_issues(self):
        text = self.workflows()["situation-room.yml"]
        self.assertIn("issues: write", text)
        self.assertIn("GITHUB_TOKEN", text)

    def test_delivery_happens_before_the_commit_so_the_state_is_persisted(self):
        for name, text in self.workflows().items():
            if "cli notify" in text and "git commit" in text:
                with self.subTest(workflow=name):
                    self.assertLess(text.index("cli notify"), text.index("git commit"),
                                    f"{name} commits before it delivers, so the deliver-once "
                                    "state and the report would be lost")

    def test_the_delivery_state_is_committed_by_the_workflows_that_write_it(self):
        for name in ("situation-room.yml", "monitor.yml", "scoring-monitor.yml"):
            text = self.workflows()[name]
            with self.subTest(workflow=name):
                self.assertRegex(text, r"git add data(/| )",
                                 f"{name} must commit data/ so the deliver-once state persists")

    def test_the_label_the_old_step_asked_for_does_not_exist(self):
        """Documents why the previous engine-monitor issue step could not work."""
        for name, text in self.workflows().items():
            with self.subTest(workflow=name):
                self.assertNotIn('--label "detection"', self.commands(text))


class CommittedArtefactTests(unittest.TestCase):
    """The published site and the committed state must agree with the code."""

    def test_site_payload_describes_the_channels(self):
        data_js = os.path.join(ROOT, "data.js")
        with open(data_js, encoding="utf-8") as fh:
            payload = json.loads(fh.read()[len("window.SDN = "):].rstrip().rstrip(";"))
        channels = ((payload.get("meta") or {}).get("notifications") or {}).get("channels") or []
        self.assertEqual({c["id"] for c in channels}, set(notify.CHANNELS),
                         "the Alerts tab must describe every channel the code has")

    def test_site_client_renders_the_subscription_panel(self):
        with open(os.path.join(ROOT, "app.js"), encoding="utf-8") as fh:
            app = fh.read()
        self.assertIn("notificationsPanel", app)
        self.assertIn("Get notified instead of checking", app)

    def test_committed_state_file_is_well_formed(self):
        path = os.path.join(ROOT, "data", "notifications_state.json")
        if not os.path.exists(path):
            self.skipTest("delivery has never run in this checkout")
        state = json.load(open(path, encoding="utf-8"))
        self.assertEqual(state.get("schema_version"), notify.STATE_SCHEMA_VERSION)
        for alert_id, entry in (state.get("notified") or {}).items():
            with self.subTest(alert=alert_id):
                self.assertTrue(entry.get("fingerprint"))
                self.assertTrue(entry.get("last_delivered_at"))
                self.assertTrue(entry.get("channels"))

    def test_every_alert_in_the_committed_feed_has_a_source_link(self):
        feed = json.load(open(os.path.join(ROOT, "data", "alerts.json"), encoding="utf-8"))
        for item in feed.get("alerts") or []:
            with self.subTest(alert=item.get("id")):
                self.assertTrue(item.get("links"),
                                "a notification without an official link is not actionable")


if __name__ == "__main__":
    unittest.main()
