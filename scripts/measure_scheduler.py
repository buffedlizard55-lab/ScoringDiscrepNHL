#!/usr/bin/env python3
"""Measure what the scheduler ACTUALLY does, from the GitHub API.

A cron string is a request, not a guarantee. GitHub documents that scheduled
workflows "may be delayed during periods of high loads" and that "if the load is
sufficient high enough, some queued jobs may be dropped", and that schedules only
run on the default branch. For an alert/notification system the difference between
the promised cadence and the delivered cadence IS the product, so this script
measures it instead of quoting the YAML:

1. read every workflow file in ``.github/workflows/`` and extract its ``cron``
   entries (the promise);
2. ask the GitHub REST API for that workflow's runs (the delivery);
3. count how many runs the cron should have produced inside the observed window,
   using a small cron evaluator, and compare with how many ``schedule``-event runs
   actually exist;
4. read the job steps of the most recent scheduled run, because a run that
   "succeeded" in 9 seconds may have done no work at all;
5. write ``data/reference/scheduler_measurement.json`` with the exact API URLs, so
   every number in it can be re-checked by clicking a link.

Unauthenticated public-repo API access only; no token is read, used or stored.
Rate-limited to 60 requests/hour per IP, which is plenty for one repository.

    python3 scripts/measure_scheduler.py
    python3 scripts/measure_scheduler.py --repo owner/name --days 1 --out /tmp/x.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW_DIR = os.path.join(REPO_ROOT, ".github", "workflows")
DEFAULT_OUT = os.path.join(REPO_ROOT, "data", "reference", "scheduler_measurement.json")
API = "https://api.github.com"
USER_AGENT = "ScoringDiscrepNHL scheduler-measurement (research; no credentials)"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def api_get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


# --------------------------------------------------------------------------- #
# cron: the promise
# --------------------------------------------------------------------------- #

CRON_RE = re.compile(r"""cron:\s*["']?([^"'\n]+)["']?""")


def workflow_crons(path: str) -> list[str]:
    """Extract cron expressions from a workflow file.

    Deliberately a text scan, not a YAML parse: this script must run with the
    standard library only, and a comment line containing "cron:" is still worth
    surfacing to a human reviewer.
    """
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for match in CRON_RE.finditer(line):
            out.append(match.group(1).strip())
    return out


def _field_values(field: str, lo: int, hi: int) -> set[int]:
    """Evaluate one POSIX cron field (``*``, ``a``, ``a-b``, ``*/n``, ``a,b``)."""
    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        step = 1
        if "/" in part:
            part, step_s = part.split("/", 1)
            step = int(step_s)
        if part in ("*", ""):
            start, end = lo, hi
        elif "-" in part:
            start_s, end_s = part.split("-", 1)
            start, end = int(start_s), int(end_s)
        else:
            start = end = int(part)
        values.update(range(start, end + 1, step))
    return values


def cron_matches(cron: str, minute: datetime) -> bool:
    """Does a 5-field cron expression fire at this UTC minute?

    Supports the subset GitHub Actions documents: ``* , - /`` over
    minute hour day-of-month month day-of-week. Day-of-week accepts 0-6 (0=Sunday)
    and three-letter names. Raises ValueError for anything else rather than
    guessing, because a silently mis-read cron would corrupt the measurement.
    """
    fields = cron.split()
    if len(fields) != 5:
        raise ValueError(f"not a 5-field cron expression: {cron!r}")
    names = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}
    dow_field = fields[4].lower()
    for name, num in names.items():
        dow_field = dow_field.replace(name, str(num))
    try:
        minutes = _field_values(fields[0], 0, 59)
        hours = _field_values(fields[1], 0, 23)
        doms = _field_values(fields[2], 1, 31)
        months = _field_values(fields[3], 1, 12)
        dows = _field_values(dow_field, 0, 6)
    except ValueError as exc:
        raise ValueError(f"unsupported cron field in {cron!r}: {exc}") from exc
    # POSIX: when both day-of-month and day-of-week are restricted, either may match.
    dom_restricted, dow_restricted = fields[2] != "*", dow_field != "*"
    if dom_restricted and dow_restricted:
        day_ok = (minute.day in doms) or (dow_of(minute) in dows)
    else:
        day_ok = (minute.day in doms) and (dow_of(minute) in dows)
    return (minute.minute in minutes and minute.hour in hours
            and minute.month in months and day_ok)


def dow_of(dt: datetime) -> int:
    """cron day-of-week: 0=Sunday..6=Saturday (Python weekday(): 0=Monday)."""
    return (dt.weekday() + 1) % 7


def expected_firings(crons: list[str], start: datetime, end: datetime) -> dict:
    """Count the minutes in [start, end) at which any cron should have fired."""
    per_cron = {c: 0 for c in crons}
    total_minutes = 0
    minute = start.replace(second=0, microsecond=0)
    while minute < end:
        fired = False
        for cron in crons:
            try:
                if cron_matches(cron, minute):
                    per_cron[cron] += 1
                    fired = True
            except ValueError:
                per_cron[cron] = -1  # unreadable: reported, never assumed
        if fired:
            total_minutes += 1
        minute += timedelta(minutes=1)
    return {"window_start_utc": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "window_end_utc": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expected_firings_per_cron": per_cron,
            "expected_firings_total": total_minutes}


# --------------------------------------------------------------------------- #
# runs: the delivery
# --------------------------------------------------------------------------- #

def measure_workflow(repo: str, workflow: dict, days: float) -> dict:
    wid = workflow["id"]
    runs_url = f"{API}/repos/{repo}/actions/workflows/{wid}/runs?per_page=100"
    payload = api_get(runs_url)
    runs = payload.get("workflow_runs", [])
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    scheduled = []
    for run in runs:
        started = run.get("run_started_at") or run.get("created_at") or ""
        try:
            when = datetime.strptime(started, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if when < cutoff:
            continue
        scheduled.append({"run_id": run.get("id"), "event": run.get("event"),
                          "conclusion": run.get("conclusion"),
                          "branch": run.get("head_branch"),
                          "started_at_utc": started,
                          "url": run.get("html_url"),
                          "run_attempt": run.get("run_attempt")})
    schedule_runs = [r for r in scheduled if r["event"] == "schedule"]
    schedule_runs.sort(key=lambda r: r["started_at_utc"])

    gaps_minutes = []
    for a, b in zip(schedule_runs, schedule_runs[1:]):
        t0 = datetime.strptime(a["started_at_utc"], "%Y-%m-%dT%H:%M:%SZ")
        t1 = datetime.strptime(b["started_at_utc"], "%Y-%m-%dT%H:%M:%SZ")
        gaps_minutes.append(round((t1 - t0).total_seconds() / 60.0, 1))

    steps = []
    if schedule_runs:
        jobs_url = f"{API}/repos/{repo}/actions/runs/{schedule_runs[-1]['run_id']}/jobs"
        try:
            jobs = api_get(jobs_url).get("jobs", [])
            for job in jobs:
                for step in job.get("steps", []):
                    steps.append({"name": step.get("name"),
                                  "conclusion": step.get("conclusion"),
                                  "started_at": step.get("started_at"),
                                  "completed_at": step.get("completed_at")})
        except urllib.error.URLError:
            steps = [{"error": "jobs could not be retrieved"}]

    return {"workflow_id": wid, "name": workflow.get("name"),
            "path": workflow.get("path"), "state": workflow.get("state"),
            "runs_url": runs_url,
            "runs_in_window": len(scheduled),
            "scheduled_runs_in_window": len(schedule_runs),
            "scheduled_runs": schedule_runs[-25:],
            "gaps_minutes_between_scheduled_runs": gaps_minutes,
            "latest_scheduled_run_steps": steps}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default="buffedlizard55-lab/ScoringDiscrepNHL")
    ap.add_argument("--days", type=float, default=1.0,
                    help="window to measure, in days (default 1)")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--default-branch", default=None,
                    help="override; default is read from the repository API")
    args = ap.parse_args(argv)

    repo_payload = api_get(f"{API}/repos/{args.repo}")
    default_branch = args.default_branch or repo_payload.get("default_branch")
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=args.days)

    workflows = api_get(f"{API}/repos/{args.repo}/actions/workflows").get("workflows", [])
    measured = []
    for wf in workflows:
        path = os.path.join(REPO_ROOT, wf.get("path", ""))
        crons = workflow_crons(path) if os.path.exists(path) else []
        entry = {"crons_declared": crons,
                 "cron_source_file": wf.get("path"),
                 "cron_source_present_locally": os.path.exists(path)}
        if crons:
            entry["expected"] = expected_firings(crons, start, now)
            try:
                entry["observed"] = measure_workflow(args.repo, wf, args.days)
            except urllib.error.URLError as exc:
                entry["observed"] = {"error": f"{type(exc).__name__}: {exc}"}
            expected = entry.get("expected", {}).get("expected_firings_total", 0)
            observed = entry.get("observed", {}).get("scheduled_runs_in_window", 0)
            entry["delivery_ratio"] = (round(observed / expected, 4) if expected else None)
            entry["verdict"] = (
                "cron not evaluated (unreadable expression)" if expected and any(
                    v == -1 for v in entry["expected"]["expected_firings_per_cron"].values())
                else f"{observed} of {expected} expected firings delivered"
                if expected else "no expected firings in window")
        measured.append(entry)

    report = {
        "schema_version": 1,
        "what_this_file_is": ("Measured scheduler delivery for this repository, produced by "
                              "scripts/measure_scheduler.py against the public GitHub REST API. "
                              "It compares the cron expressions declared in .github/workflows/ "
                              "with the runs that actually happened. This is the latency figure "
                              "the alert documentation is allowed to quote."),
        "measured_at_utc": utcnow(),
        "repository": args.repo,
        "default_branch": default_branch,
        "window_days": args.days,
        "api_urls": {
            "repository": f"{API}/repos/{args.repo}",
            "workflows": f"{API}/repos/{args.repo}/actions/workflows",
            "note": "Public, unauthenticated. Re-run the script to reproduce.",
        },
        "github_documented_behaviour": [
            "Scheduled workflows run on the latest commit on the default branch only.",
            "The shortest interval you can run scheduled workflows is once every 5 minutes.",
            "The schedule event can be delayed during periods of high loads; if the load is "
            "sufficiently high, some queued jobs may be dropped.",
            "In a public repository, scheduled workflows are automatically disabled when no "
            "repository activity has occurred in 60 days.",
        ],
        "github_docs_url": ("https://docs.github.com/en/actions/using-workflows/"
                            "events-that-trigger-workflows#schedule"),
        "workflows": measured,
    }

    with_cron = [m for m in measured if m.get("crons_declared")]
    if with_cron:
        worst = min((m.get("delivery_ratio") or 0) for m in with_cron)
        report["summary"] = {
            "workflows_with_a_schedule": len(with_cron),
            "worst_delivery_ratio": worst,
            "headline": ("A cron expression in this repository is NOT being honoured at its "
                         "declared rate" if worst < 0.5 else
                         "Scheduled runs are being delivered close to the declared rate"),
        }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(json.dumps({"out": os.path.relpath(args.out, REPO_ROOT),
                      "summary": report.get("summary"),
                      "workflows": [{k: v for k, v in m.items()
                                     if k in ("cron_source_file", "crons_declared",
                                              "delivery_ratio", "verdict")}
                                    for m in with_cron]}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
