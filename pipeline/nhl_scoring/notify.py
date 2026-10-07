"""Notification delivery — the half of alerting that actually reaches a person.

Detection (``alerts.py``) decides *what* is worth saying and writes it to the
committed feed. This module is the only thing that *delivers* it, and it exists
because the two were conflated for most of this project's life: the Situation Room
ingest — the primary detection path, running on a schedule — raised alerts into
``data/alerts.json`` and then stopped. A subscriber had to open the website to
find out anything had happened, which is exactly the manual checking this project
is supposed to remove.

Design rules, each of which answers a failure mode that already happened here:

1. **The feed is the contract.** Delivery reads ``data/alerts.json`` — the same
   artifact the site and the RSS feed publish — never a private re-derivation, so
   what a subscriber is told always matches what the site shows.
2. **Deliver once, and say so.** ``data/notifications_state.json`` records a
   fingerprint per alert id. An unchanged alert is never re-sent (a schedule that
   fires twice an hour would otherwise re-notify the same 17 alerts 48 times a
   day); a *changed* alert is re-sent and labelled an update, because a revised
   record is news.
3. **Never claim a delivery that did not happen.** Every channel returns
   ``sent``/``failed``/``skipped`` with the HTTP status or the exception text. The
   report is committed next to the data, so a silent notification outage is
   visible in git.
4. **No credentials in the repository.** Tokens and URLs come from the
   environment (GitHub Actions secrets); a channel with no configuration is
   reported as ``not_configured``, not silently dropped.
5. **Bound the noise.** Immediate-severity alerts (a goal total changed) get their
   own issue, capped per run; everything else is folded into one digest.

Channels:

===============  =========================================================
``feed``         ``data/alerts.json`` + ``data/alerts.xml`` on GitHub Pages.
                 Always on, no configuration, and the reason the other
                 channels can be trusted to be complete.
``issue``        One GitHub issue per run (or per immediate alert). Free
                 inbox delivery to anyone watching the repository; needs
                 ``GITHUB_TOKEN`` with ``issues: write``.
``webhook``      POST to any Slack/Discord/generic endpoint. Needs
                 ``SDN_WEBHOOK_URL``.
``email``        SMTP digest. Needs ``SDN_SMTP_*``. Implemented because an
                 operator should not have to run a bridge service to get an
                 e-mail, but off until the secrets exist.
===============  =========================================================
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

#: Channels this module can deliver over. ``feed`` is the committed artifact and
#: is always "delivered" by the alerts writer; it is listed so a reader sees the
#: whole picture and so the site can render it.
CHANNELS: Tuple[str, ...] = ("feed", "issue", "webhook", "email")

GITHUB_API = "https://api.github.com"
SITE_URL = "https://buffedlizard55-lab.github.io/ScoringDiscrepNHL/"
DEFAULT_REPO = "buffedlizard55-lab/ScoringDiscrepNHL"
ISSUE_LABELS: Tuple[str, ...] = ("scoring-discrepancy", "auto-detected")
LABEL_COLOURS = {"scoring-discrepancy": "FBCA04", "auto-detected": "BFD4F2",
                 "goal-total-changed": "D93F0B"}

#: How many per-alert issues one run may open before the rest are folded into the
#: digest. A backfill or a first run must not open a hundred issues.
MAX_ISSUES_PER_RUN = 10

STATE_SCHEMA_VERSION = 1

#: ``(url, body, headers, timeout) -> (status, text)``
HttpPost = Callable[[str, bytes, Dict[str, str], int], Tuple[int, str]]
#: ``(url, headers, timeout) -> (status, text)`` — injectable so tests can exercise
#: the label lookup without touching the network.
HttpGet = Callable[[str, Dict[str, str], int], Tuple[int, str]]
SmtpFactory = Callable[[str, int], Any]


# ---------------------------------------------------------------------------
# Channel description (also what the website renders, so the site cannot claim a
# channel that the code does not have)
# ---------------------------------------------------------------------------

def describe_channels(env: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """Describe each channel, whether it is configured, and what it needs.

    The site renders this list verbatim. A channel that is present in code but
    unconfigured is shown as unconfigured with the exact variable that turns it
    on — never hidden, never implied to be working.
    """
    env = dict(os.environ if env is None else env)
    token = env.get("GITHUB_TOKEN") or env.get("GH_TOKEN")
    webhook = env.get("SDN_WEBHOOK_URL") or env.get("SDN_WEBHOOK")
    smtp_host = env.get("SDN_SMTP_HOST")
    return [
        {
            "id": "feed",
            "name": "Website feed + RSS",
            "configured": True,
            "requires": "nothing",
            "how_to_subscribe": "Open the Alerts tab, or point a feed reader at data/alerts.xml.",
            "latency": "Written by every detector run and served by GitHub Pages (a rebuild takes about a minute).",
            "notes": "Always on. This is the record of what was raised; the push channels below reference it.",
        },
        {
            "id": "issue",
            "name": "GitHub issue",
            "configured": bool(token),
            "requires": "GITHUB_TOKEN with issues: write (set automatically inside GitHub Actions)",
            "how_to_subscribe": "Watch the repository (Custom -> Issues). Every new alert opens an issue.",
            "latency": "As soon as the detector run that found it finishes.",
            "notes": "One issue per goal-total change, plus a single digest for attribution-only alerts.",
        },
        {
            "id": "webhook",
            "name": "Webhook (Slack / Discord / anything)",
            "configured": bool(webhook),
            "requires": "SDN_WEBHOOK_URL secret",
            "how_to_subscribe": "Set the secret to your incoming-webhook URL; the payload carries both "
                               "`text` (Slack) and `content` (Discord).",
            "latency": "As soon as the detector run that found it finishes.",
            "notes": "One POST per run with the new alerts, so a busy day is one message, not fifty.",
        },
        {
            "id": "email",
            "name": "E-mail digest",
            "configured": bool(smtp_host and env.get("SDN_SMTP_TO")),
            "requires": "SDN_SMTP_HOST, SDN_SMTP_PORT, SDN_SMTP_USER, SDN_SMTP_PASSWORD, "
                        "SDN_SMTP_FROM, SDN_SMTP_TO secrets",
            "how_to_subscribe": "Set the SMTP secrets; the digest goes to SDN_SMTP_TO.",
            "latency": "As soon as the detector run that found it finishes.",
            "notes": "Off until the secrets exist. GitHub Actions has no mail relay of its own.",
        },
    ]


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def load_state(path: str) -> Dict[str, Any]:
    """Read the deliver-once state, tolerating the older flat shape."""
    state: Dict[str, Any] = {"schema_version": STATE_SCHEMA_VERSION, "notified": {}}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh) or {}
    except (OSError, ValueError):
        raw = {}
    # The pre-delivery-layer shape stored two flat lists. Carry them across so an
    # older checkout reading the file still sees what it wrote.
    state["notified_record_ids"] = raw.get("notified_record_ids") or []
    state["notified_alert_hashes"] = raw.get("notified_alert_hashes") or []
    notified = raw.get("notified") or {}
    for alert_id, entry in notified.items():
        if isinstance(entry, dict):
            state["notified"][alert_id] = entry
    state["last_run"] = raw.get("last_run")
    return state


def save_state(path: str, state: Dict[str, Any]) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {
        "schema_version": STATE_SCHEMA_VERSION,
        "updated_at": state.get("updated_at"),
        "last_run": state.get("last_run"),
        "notified": state.get("notified") or {},
        # legacy keys, kept in sync so nothing that reads the old shape breaks
        "notified_record_ids": sorted({v.get("record_id") for v in (state.get("notified") or {}).values()
                                       if v.get("record_id")}),
        "notified_alert_hashes": sorted((state.get("notified") or {}).keys()),
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    return path


def fingerprint(alert: Dict[str, Any]) -> str:
    """Stable hash of the *content* of an alert.

    A record that is later re-verified, re-flagged or corrected produces a
    different fingerprint, so the subscriber hears about the revision. Cosmetic
    regeneration of the feed does not: the fingerprint covers what a human reads.
    """
    basis = json.dumps({
        "title": alert.get("title"),
        "body": alert.get("body"),
        "severity": alert.get("severity"),
        "links": sorted(alert.get("links") or []),
        "affects_goal_total": alert.get("affects_goal_total"),
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def partition(alerts: Iterable[Dict[str, Any]], state: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Split a feed into new, updated and already-delivered alerts."""
    notified = state.get("notified") or {}
    out: Dict[str, List[Dict[str, Any]]] = {"new": [], "updated": [], "unchanged": []}
    for alert in alerts:
        alert_id = alert.get("id")
        if not alert_id:
            continue
        previous = notified.get(alert_id)
        if not previous:
            out["new"].append(alert)
        elif previous.get("fingerprint") != fingerprint(alert):
            out["updated"].append(alert)
        else:
            out["unchanged"].append(alert)
    return out


def prime(alerts: Iterable[Dict[str, Any]], state: Dict[str, Any], *, now: str,
          channel: str = "feed") -> int:
    """Mark everything currently in the feed as already delivered by ``channel``.

    Used once, when delivery is switched on, so the first scheduled run does not
    announce the whole backlog as if it were breaking news. The state entry says
    it was primed, so nobody mistakes it for a real push.
    """
    count = 0
    for alert in alerts:
        alert_id = alert.get("id")
        if not alert_id:
            continue
        state.setdefault("notified", {})[alert_id] = {
            "fingerprint": fingerprint(alert),
            "record_id": alert.get("record_id"),
            "first_delivered_at": alert.get("created_at") or now,
            "last_delivered_at": now,
            "notices": 0,
            "channels": {channel: "primed_from_committed_feed"},
        }
        count += 1
    state["updated_at"] = now
    return count


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _deep_link(alert: Dict[str, Any]) -> str:
    record_id = alert.get("record_id") or ""
    return f"{SITE_URL}#view=database&q={urllib.request.quote(record_id)}"


def _links_block(alert: Dict[str, Any]) -> str:
    links = [l for l in (alert.get("links") or []) if l]
    if not links:
        return "_No source link recorded — this alert is flagged as unverified in the database._"
    return "\n".join(f"- <{l}>" for l in links)


def _settlement_block(alert: Dict[str, Any]) -> str:
    """The record's own settlement wording — quoted, never paraphrased."""
    risk = alert.get("settlement_risk") or ""
    window = alert.get("settlement_window") or ""
    reason = alert.get("settlement_reason") or ""
    if not (risk or window or reason):
        return ""
    head = "**Settlement exposure (from the record)**"
    line = " · ".join(x for x in [f"risk: {risk}" if risk else "",
                                  f"window: {window}" if window else ""] if x)
    return "\n".join(x for x in [head, line, reason, ""] if x)


def issue_for(alert: Dict[str, Any], *, update: bool = False) -> Dict[str, str]:
    """One issue per goal-total-changing alert."""
    severity = (alert.get("severity") or "low").upper()
    prefix = "[UPDATED] " if update else ""
    # Feed titles from the monitor line already carry their own severity tag; a
    # second one reads like a bug, so the leading tag is normalised away first.
    raw_title = re.sub(r"^\[(?:IMMEDIATE|REVIEW|INFO|HIGH|MEDIUM|LOW|UPDATED)\]\s*",
                       "", str(alert.get("title") or alert.get("id") or "scoring discrepancy"))
    title = f"{prefix}[{severity}] {raw_title}"
    # GitHub issue titles are single-line and capped; keep the record id in it so
    # a search in the issue list finds the record.
    title = f"{title} ({alert.get('record_id')})" if alert.get("record_id") else title
    total_line = (
        " — **the goal count changed** relative to the call on the ice. The record states its own "
        "settlement exposure below; a final box score already reflects the corrected state."
        if alert.get("affects_goal_total")
        else " — player attribution only; the goal total did not change.")
    body = "\n".join([
        f"Automated notification from the scoring-discrepancy monitor. Severity **{severity.lower()}**"
        + (" — this alert was re-sent because the record changed after it was first raised." if update else "")
        + total_line,
        "",
        alert.get("body") or "",
        "",
        _settlement_block(alert),
        "**Official sources**",
        _links_block(alert),
        "",
        f"- Record: `{alert.get('record_id')}` — [open on the site]({_deep_link(alert)})",
        f"- Raised: {alert.get('created_at') or 'unknown'}"
        + (f" (first seen {alert.get('first_seen_at')})" if alert.get("first_seen_at") else ""),
        f"- Detector: `{alert.get('detected_by') or 'unknown'}`",
        "",
        "_Nothing here is an official NHL ruling. Verify against the linked source before acting._",
    ])
    labels = list(ISSUE_LABELS) + (["goal-total-changed"] if alert.get("affects_goal_total") else [])
    return {"title": title[:250], "body": body, "labels": labels}


def digest_for(alerts: Sequence[Dict[str, Any]], *, run_label: str = "",
               unchanged: int = 0) -> Dict[str, str]:
    """One digest issue for everything that does not warrant its own thread."""
    immediate = sum(1 for a in alerts if a.get("affects_goal_total"))
    title = (f"{len(alerts)} scoring-discrepancy alert(s)"
             + (f", {immediate} changed a goal total" if immediate else ", attribution only")
             + (f" [{run_label}]" if run_label else ""))
    rows = []
    for alert in alerts:
        rows.append("\n".join([
            f"### {alert.get('title') or alert.get('id')}",
            "",
            (alert.get("body") or "").strip(),
            "",
            "**Official sources**",
            _links_block(alert),
            "",
            f"Record `{alert.get('record_id')}` — [open on the site]({_deep_link(alert)})",
        ]))
    body = "\n\n".join([
        "Automated digest from the scoring-discrepancy monitor. These alerts did not warrant "
        "their own issue; a goal-total change always does.",
        "",
        f"- New or updated alerts in this digest: **{len(alerts)}**",
        f"- Already delivered and unchanged (not repeated): {unchanged}",
        f"- Feed: <{SITE_URL}#view=alerts> · RSS: <{SITE_URL}data/alerts.xml>",
    ] + rows + [
        "_Nothing here is an official NHL ruling. Verify against the linked source before acting._",
    ])
    labels = list(ISSUE_LABELS)
    return {"title": title[:250], "body": body, "labels": labels}


def webhook_body(alerts: Sequence[Dict[str, Any]], *, run_label: str = "") -> Dict[str, Any]:
    """Slack- and Discord-shaped payload for the run's new alerts."""
    immediate = [a for a in alerts if a.get("affects_goal_total")]
    lines = []
    for alert in alerts[:20]:
        mark = "GOAL TOTAL CHANGED" if alert.get("affects_goal_total") else "attribution"
        lines.append(f"*[{(alert.get('severity') or 'low').upper()} | {mark}]* "
                     f"{alert.get('title') or alert.get('id')}\n"
                     f"<{_deep_link(alert)}|record> · sources: "
                     + " ".join(f"<{l}>" for l in (alert.get("links") or [])[:3] if l))
    text = "\n".join(lines) or "No new scoring discrepancies this run."
    header = (f"NHL scoring discrepancies: {len(alerts)} new alert(s)"
              + (f", {len(immediate)} changed a goal total" if immediate else "")
              + (f" ({run_label})" if run_label else ""))
    return {
        # Slack reads `text`, Discord reads `content`; both are sent so one URL
        # shape works for either without the operator configuring a flavour.
        "text": f"{header}\n{text}",
        "content": header[:1900],
        "username": "NHL scoring discrepancy monitor",
        "embeds": [{"title": header[:250], "description": text[:3900], "url": f"{SITE_URL}#view=alerts"}]
        if alerts else [],
        "_sdn": {"count": len(alerts),
                 "goal_total_changes": len(immediate),
                 "record_ids": [a.get("record_id") for a in alerts],
                 "run": run_label},
    }


def email_message(alerts: Sequence[Dict[str, Any]], *, run_label: str = "",
                  sender: str = "", recipients: Sequence[str] = ()) -> EmailMessage:
    immediate = sum(1 for a in alerts if a.get("affects_goal_total"))
    subject = (f"[NHL scoring] {len(alerts)} new alert(s)"
               + (f", {immediate} goal-total change(s)" if immediate else "")
               + (f" {run_label}" if run_label else ""))
    parts = []
    for alert in alerts:
        parts.append("\n".join([
            f"{alert.get('title') or alert.get('id')}",
            (alert.get("body") or "").strip(),
            "Official sources:",
            "\n".join(f"  - {l}" for l in (alert.get("links") or []) if l) or "  (none recorded)",
            f"Record: {alert.get('record_id')} — {_deep_link(alert)}",
            "-" * 72,
        ]))
    msg = EmailMessage()
    msg["Subject"] = subject[:200]
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content("\n\n".join(parts) or "No new scoring discrepancies this run.")
    return msg


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

#: Response bodies are capped so a chatty endpoint cannot bloat the committed
#: report. The cap is generous enough for a GitHub issue payload, whose
#: ``html_url`` sits near the front of the JSON.
RESPONSE_CAP = 200_000


def http_post(url: str, body: bytes, headers: Dict[str, str], timeout: int = 20) -> Tuple[int, str]:
    """Minimal POST. Returns ``(status, response_text)``; raises on transport error."""
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed hosts
            return response.getcode(), response.read().decode("utf-8", "replace")[:RESPONSE_CAP]
    except urllib.error.HTTPError as exc:  # a 4xx is a result, not a crash
        return exc.code, (exc.read() or b"").decode("utf-8", "replace")[:RESPONSE_CAP]


def extract_url(text: str) -> str:
    """Pull ``html_url`` out of a GitHub response.

    Parsing the JSON is the honest path, but a body that arrives truncated (or a
    shape change) must still leave the subscriber a link, so a regular expression
    is the fallback rather than an empty field in the report.
    """
    try:
        value = (json.loads(text) or {}).get("html_url")
        if value:
            return str(value)
    except (ValueError, AttributeError):
        pass
    match = re.search(r'"html_url"\s*:\s*"([^"]+)"', text or "")
    return match.group(1) if match else ""


def github_get(url: str, headers: Dict[str, str], timeout: int = 20) -> Tuple[int, str]:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - api.github.com only
            return response.getcode(), response.read().decode("utf-8", "replace")[:RESPONSE_CAP]
    except urllib.error.HTTPError as exc:
        return exc.code, (exc.read() or b"").decode("utf-8", "replace")[:RESPONSE_CAP]


def _github_headers(token: str) -> Dict[str, str]:
    return {"Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ScoringDiscrepNHL-notify"}


def _ensure_labels(post: HttpPost, get: HttpGet, repo: str, token: str,
                   labels: Sequence[str]) -> List[str]:
    """Create any label the repository does not have yet; return the usable set.

    ``gh issue create --label`` fails outright on an unknown label, which is how
    the engine monitor's issue step silently never opened an issue: the label it
    asked for did not exist, the command failed, and a ``|| echo`` swallowed it.
    Creating the label is idempotent and costs one request.
    """
    headers = _github_headers(token)
    usable: List[str] = []
    for label in labels:
        status, _ = get(f"{GITHUB_API}/repos/{repo}/labels/{urllib.request.quote(label)}", headers)
        if status == 200:
            usable.append(label)
            continue
        payload = json.dumps({"name": label,
                              "color": LABEL_COLOURS.get(label, "ededed"),
                              "description": "Applied automatically by the scoring-discrepancy monitor."}).encode()
        created, _ = post(f"{GITHUB_API}/repos/{repo}/labels", payload, headers)
        if created in (200, 201, 422):  # 422 = already exists (race)
            usable.append(label)
    return usable


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------

def _record_delivery(report: Dict[str, Any], *, channel: str, target: str, alert_ids: Sequence[str],
                     status: str, http_status: Optional[int] = None, url: str = "",
                     error: str = "", dry_run: bool = False) -> Dict[str, Any]:
    entry = {"channel": channel, "target": target, "alert_ids": list(alert_ids), "status": status,
             "http_status": http_status, "url": url, "error": error,
             # a dry run never touches the network, whatever the channel decided
             "dry_run": bool(dry_run or report.get("mode") == "dry-run")}
    report["deliveries"].append(entry)
    if status == "failed" and not dry_run:
        report["failed_channels"].append(channel)
    return entry


def deliver(alerts: Sequence[Dict[str, Any]], *, state: Dict[str, Any],
            channels: Sequence[str] = ("issue", "webhook", "email"),
            updated_ids: Iterable[str] = (),
            now: str = "", run_label: str = "", repo: str = DEFAULT_REPO,
            token: str = "", webhook_url: str = "", smtp_config: Optional[Dict[str, str]] = None,
            post: Optional[HttpPost] = None, get: Optional[HttpGet] = None,
            smtp_factory: Optional[SmtpFactory] = None,
            dry_run: bool = False, max_issues: int = MAX_ISSUES_PER_RUN,
            unchanged: int = 0, min_severity: str = "low",
            force: bool = False) -> Dict[str, Any]:
    """Deliver ``alerts`` over ``channels`` and return the run report.

    ``alerts`` must already be the new/updated set (see :func:`partition`);
    ``updated_ids`` marks the ones that are a revision of an alert already sent,
    and ``unchanged`` is only used for the digest's "not repeated" count. The
    state object is mutated in place and is the caller's to save, so a dry run
    cannot leave a half-written file behind.
    """
    post = post or http_post
    get = get or github_get
    smtp_config = smtp_config or {}
    updated_ids = set(updated_ids)
    rank = {"high": 0, "medium": 1, "low": 2}
    threshold = rank.get(min_severity, 2)
    alerts = [a for a in alerts if rank.get(a.get("severity") or "low", 2) <= threshold]
    if not force:
        # Defence in depth: even if a caller forgets to partition, an alert that
        # is already in the state with the same fingerprint is not sent again.
        notified = state.get("notified") or {}
        alerts = [a for a in alerts
                  if (notified.get(a.get("id")) or {}).get("fingerprint") != fingerprint(a)]
    report: Dict[str, Any] = {
        "generated_at": now, "run": run_label, "mode": "dry-run" if dry_run else "deliver",
        "repo": repo, "candidates": len(alerts), "unchanged_skipped": unchanged,
        "deliveries": [], "failed_channels": [],
    }
    if not alerts:
        report["note"] = "nothing new to deliver"
        return report

    by_id = {a.get("id"): a for a in alerts}
    immediate = [a for a in alerts if a.get("affects_goal_total")]
    per_alert = immediate[:max_issues]
    per_alert_ids = {a.get("id") for a in per_alert}
    digest_items = [a for a in alerts if a.get("id") not in per_alert_ids]

    delivered: Dict[str, Dict[str, str]] = {}

    def mark(channel: str, alert_ids: Iterable[str], result: str) -> None:
        for alert_id in alert_ids:
            delivered.setdefault(alert_id, {})[channel] = result

    # ---- GitHub issues ----------------------------------------------------
    if "issue" in channels:
        if not token:
            _record_delivery(report, channel="issue", target=repo, alert_ids=[a.get("id") for a in alerts],
                             status="skipped", error="GITHUB_TOKEN not set")
        else:
            issues: List[Tuple[Dict[str, str], List[str]]] = []
            for alert in per_alert:
                issues.append((issue_for(alert, update=alert.get("id") in updated_ids),
                               [alert.get("id")]))
            if digest_items:
                issues.append((digest_for(digest_items, run_label=run_label, unchanged=unchanged),
                               [a.get("id") for a in digest_items]))
            # Resolve the label set once for the whole run. Doing it per issue
            # costs three requests a time and GitHub rate-limits bursts.
            wanted = sorted({label for issue, _ in issues for label in issue["labels"]})
            usable_labels = _ensure_labels(post, get, repo, token, wanted) if not dry_run else wanted
            for issue, alert_ids in issues:
                if dry_run:
                    _record_delivery(report, channel="issue", target=repo, alert_ids=alert_ids,
                                     status="planned", dry_run=True,
                                     error=f"would open: {issue['title']}")
                    mark("issue", alert_ids, "planned")
                    continue
                labels = [label for label in issue["labels"] if label in usable_labels]
                body = json.dumps({"title": issue["title"], "body": issue["body"],
                                   "labels": labels}).encode("utf-8")
                status, text = post(f"{GITHUB_API}/repos/{repo}/issues", body, _github_headers(token))
                url = extract_url(text)
                if status in (200, 201):
                    _record_delivery(report, channel="issue", target=repo, alert_ids=alert_ids,
                                     status="sent", http_status=status, url=url)
                    mark("issue", alert_ids, url or "sent")
                else:
                    _record_delivery(report, channel="issue", target=repo, alert_ids=alert_ids,
                                     status="failed", http_status=status, error=text[:400])
                    mark("issue", alert_ids, f"failed:{status}")

    # ---- webhook ----------------------------------------------------------
    if "webhook" in channels:
        ids = [a.get("id") for a in alerts]
        if not webhook_url:
            _record_delivery(report, channel="webhook", target="(unset)", alert_ids=ids,
                             status="skipped", error="SDN_WEBHOOK_URL not set")
        elif dry_run:
            _record_delivery(report, channel="webhook", target="SDN_WEBHOOK_URL", alert_ids=ids,
                             status="planned", dry_run=True,
                             error=f"would POST {len(alerts)} alert(s)")
            mark("webhook", ids, "planned")
        else:
            body = json.dumps(webhook_body(alerts, run_label=run_label)).encode("utf-8")
            try:
                status, text = post(webhook_url, body, {"Content-Type": "application/json",
                                                        "User-Agent": "ScoringDiscrepNHL-notify"})
                ok = 200 <= status < 300
                _record_delivery(report, channel="webhook", target="SDN_WEBHOOK_URL", alert_ids=ids,
                                 status="sent" if ok else "failed", http_status=status,
                                 error="" if ok else text[:400])
                mark("webhook", ids, "sent" if ok else f"failed:{status}")
            except Exception as exc:  # noqa: BLE001 - a dead webhook must not kill the run
                _record_delivery(report, channel="webhook", target="SDN_WEBHOOK_URL", alert_ids=ids,
                                 status="failed", error=f"{type(exc).__name__}: {exc}")
                mark("webhook", ids, "failed")

    # ---- email ------------------------------------------------------------
    if "email" in channels:
        ids = [a.get("id") for a in alerts]
        recipients = [r.strip() for r in (smtp_config.get("to") or "").split(",") if r.strip()]
        if not (smtp_config.get("host") and recipients):
            _record_delivery(report, channel="email", target="(unset)", alert_ids=ids,
                             status="skipped", error="SDN_SMTP_HOST / SDN_SMTP_TO not set")
        else:
            message = email_message(alerts, run_label=run_label,
                                    sender=smtp_config.get("from") or smtp_config.get("user") or "nhl-monitor@localhost",
                                    recipients=recipients)
            if dry_run:
                _record_delivery(report, channel="email", target=", ".join(recipients), alert_ids=ids,
                                 status="planned", dry_run=True, error=f"would send: {message['Subject']}")
                mark("email", ids, "planned")
            else:
                try:
                    factory = smtp_factory or (lambda host, port: smtplib.SMTP(host, port, timeout=30))
                    server = factory(smtp_config["host"], int(smtp_config.get("port") or 587))
                    try:
                        if str(smtp_config.get("starttls", "1")) not in ("0", "false", "no"):
                            server.starttls()
                        if smtp_config.get("user"):
                            server.login(smtp_config["user"], smtp_config.get("password") or "")
                        server.send_message(message)
                    finally:
                        try:
                            server.quit()
                        except Exception:  # noqa: BLE001
                            pass
                    _record_delivery(report, channel="email", target=", ".join(recipients),
                                     alert_ids=ids, status="sent")
                    mark("email", ids, "sent")
                except Exception as exc:  # noqa: BLE001
                    _record_delivery(report, channel="email", target=", ".join(recipients),
                                     alert_ids=ids, status="failed", error=f"{type(exc).__name__}: {exc}")
                    mark("email", ids, "failed")

    # ---- feed -------------------------------------------------------------
    if "feed" in channels:
        _record_delivery(report, channel="feed", target="data/alerts.json + data/alerts.xml",
                         alert_ids=[a.get("id") for a in alerts],
                         status="planned" if dry_run else "published", dry_run=dry_run,
                         url=f"{SITE_URL}#view=alerts")
        mark("feed", [a.get("id") for a in alerts], "planned" if dry_run else "published")

    # ---- state ------------------------------------------------------------
    # An alert is only marked delivered when nothing that was attempted for it
    # failed. A 401 or a dead webhook therefore stays in the "new" set and the
    # next run retries it, instead of the failure being swallowed once and the
    # alert never being sent at all.
    if not dry_run:
        notified = state.setdefault("notified", {})
        for alert_id, channels_result in delivered.items():
            alert = by_id.get(alert_id) or {}
            previous = notified.get(alert_id) or {}
            failed_here = [k for k, v in channels_result.items() if str(v).startswith("failed")]
            if failed_here and not previous:
                report.setdefault("retry_next_run", []).append(alert_id)
                continue
            notices = int(previous.get("notices") or 0) + (0 if failed_here else 1)
            notified[alert_id] = {
                "fingerprint": fingerprint(alert) if not failed_here else previous.get("fingerprint"),
                "record_id": alert.get("record_id"),
                "severity": alert.get("severity"),
                "first_delivered_at": previous.get("first_delivered_at") or alert.get("created_at") or now,
                "last_delivered_at": now,
                "notices": notices,
                "channels": channels_result,
                **({"delivery_incomplete": failed_here} if failed_here else {}),
            }
        state["updated_at"] = now
        state["last_run"] = {"at": now, "run": run_label, "delivered": len(delivered),
                             "failed_channels": list(report["failed_channels"])}
    report["delivered_alert_ids"] = sorted(a for a in delivered
                                           if a in (state.get("notified") or {})
                                           and not (state["notified"][a].get("delivery_incomplete")))
    report["retry_next_run"] = sorted(report.get("retry_next_run") or [])
    report["state_entries"] = len(state.get("notified") or {})
    return report


# ---------------------------------------------------------------------------
# Feed reading
# ---------------------------------------------------------------------------

def read_feed(path: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Read the published alert feed. Returns ``(alerts, feed_meta)``."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh) or {}
    except (OSError, ValueError) as exc:
        return [], {"error": f"{type(exc).__name__}: {exc}", "path": path}
    alerts = payload.get("alerts") or []
    return alerts, {"path": path, "generated_at": payload.get("generated_at"), "count": len(alerts)}
