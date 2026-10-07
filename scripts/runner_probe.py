#!/usr/bin/env python3
"""Measure the official NHL sources FROM A GITHUB RUNNER and commit the result.

Why this script exists
----------------------
The build sandbox this project is written in has no route to ``nhl.com`` or
``api-web.nhle.com`` (measured: TLS connections closed, artifact at
``docs/evidence/sandbox_network_probe.json``). Every claim about the live shape
of those feeds therefore has to be measured where the network is real. A GitHub
Actions runner is such a place, and its measurements can be committed as an
artifact a reviewer can re-run.

What it measures, and why each item matters to the alerting question:

* **reachability + HTTP status** of every endpoint the detector depends on. If a
  runner cannot read a source, no notification system built on it can work.
* **the top-level JSON keys of the daily score payload**, plus how many games are
  found under each candidate key. ``src/nhl_monitor/parse.py`` reads
  ``gamesByDate``; if the live payload uses ``games`` the monitor silently sees
  zero games and reports success. This script is how that assumption is checked
  instead of trusted.
* **request latency** (3 samples per endpoint): the floor under any polling
  cadence, and the number ``docs/LIMITATIONS.md`` says may only be quoted once it
  has been measured.
* **a structural excerpt** (keys and counts, never a full dump) so the fixture
  committed for tests is derived from the live payload rather than imagined.

Everything is written to ``data/reference/runner_probe.json``. No credentials are
used or stored; these are public, unauthenticated endpoints.

    python3 scripts/runner_probe.py                 # probe + write the artifact
    python3 scripts/runner_probe.py --out /tmp/x.json --samples 1
    python3 scripts/runner_probe.py --date 2026-10-07

Standard library only. Exits non-zero if any endpoint was unreachable, so CI
cannot turn a dead source into a green run.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(REPO_ROOT, "data", "reference", "runner_probe.json")
FIXTURE_OUT = os.path.join(REPO_ROOT, "tests", "fixtures", "score_payload_excerpt.json")

USER_AGENT = ("ScoringDiscrepNHL/1.0 runner-probe "
              "(+https://github.com/buffedlizard55-lab/ScoringDiscrepNHL)")
DELAY_SECONDS = 1.0
TIMEOUT = 20.0

#: Endpoints the detector and the alerting layer depend on. ``{date}`` /
#: ``{game_id}`` / ``{season}`` are substituted per run.
ENDPOINTS = [
    ("score.today", "https://api-web.nhle.com/v1/score/{today}", "json"),
    ("score.yesterday", "https://api-web.nhle.com/v1/score/{yesterday}", "json"),
    ("scoreboard.now", "https://api-web.nhle.com/v1/scoreboard/now", "json"),
    ("club.schedule", "https://api-web.nhle.com/v1/club-schedule-season/{season}", "json"),
    ("gamecenter.landing", "https://api-web.nhle.com/v1/gamecenter/{game_id}/landing", "json"),
    ("gamecenter.pbp", "https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play", "json"),
    ("gamecenter.boxscore", "https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore", "json"),
    ("report.GS", "https://www.nhl.com/scores/htmlreports/{season_folder}/GS{game_no}.HTM", "html"),
    ("report.PL", "https://www.nhl.com/scores/htmlreports/{season_folder}/PL{game_no}.HTM", "html"),
    ("statsapi.feed", "https://statsapi.web.nhl.com/api/v1/game/{game_pk}/feed/live", "json"),
    ("statsapi.schedule", "https://statsapi.web.nhl.com/api/v1/schedule?startDate={today}&endDate={today}", "json"),
]


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(url: str, *, timeout: float = TIMEOUT) -> dict:
    """One GET, timed, with the honest error when it fails."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept-Encoding": "gzip"})
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            elapsed = time.monotonic() - started
            return {"ok": True, "url": url, "http_status": resp.status,
                    "final_url": resp.geturl(),
                    "content_type": resp.headers.get("Content-Type", ""),
                    "bytes": len(raw), "elapsed_seconds": round(elapsed, 3),
                    "body": raw}
    except urllib.error.HTTPError as exc:
        elapsed = time.monotonic() - started
        body = b""
        try:
            body = exc.read() or b""
        except Exception:  # pragma: no cover - network dependent
            pass
        return {"ok": False, "url": url, "http_status": exc.code,
                "elapsed_seconds": round(elapsed, 3), "bytes": len(body),
                "error": f"HTTPError {exc.code}", "body": body,
                "reason": "a 404 here is data: the document does not exist"}
    except Exception as exc:  # DNS, TLS, timeout, connection reset
        return {"ok": False, "url": url, "http_status": None,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "error": f"{type(exc).__name__}: {exc}"}


def latency_samples(url: str, samples: int) -> dict:
    """Median/min/max of repeated GETs - the polling floor for one endpoint."""
    times, statuses = [], []
    for i in range(samples):
        res = fetch(url)
        statuses.append(res.get("http_status"))
        if res.get("ok"):
            times.append(res["elapsed_seconds"])
        if i + 1 < samples:
            time.sleep(DELAY_SECONDS)
    if not times:
        return {"url": url, "samples": samples, "ok_samples": 0,
                "http_statuses": statuses,
                "note": "no successful sample - latency NOT measured, not assumed"}
    times.sort()
    return {"url": url, "samples": samples, "ok_samples": len(times),
            "http_statuses": statuses,
            "min_seconds": times[0],
            "median_seconds": times[len(times) // 2],
            "max_seconds": times[-1]}


def structural_excerpt(payload: object, depth: int = 0) -> object:
    """Keys and counts only. A full payload is big and would bloat the repo."""
    if depth > 3:
        return "..."
    if isinstance(payload, dict):
        out = {}
        for key, value in list(payload.items())[:40]:
            if isinstance(value, (dict, list)):
                out[key] = structural_excerpt(value, depth + 1)
            else:
                out[key] = type(value).__name__
        return out
    if isinstance(payload, list):
        return [f"list[{len(payload)}]",
                structural_excerpt(payload[0], depth + 1) if payload else None]
    return type(payload).__name__


def game_counts(payload: object) -> dict:
    """How many games does the live score payload expose, and under which key?

    This is the check that decides whether ``parse_api_score`` reads the right
    key. It reports every plausible container instead of assuming one.
    """
    counts = {}
    if not isinstance(payload, dict):
        return {"note": f"payload is {type(payload).__name__}, not an object"}
    for key in ("games", "gamesByDate", "gameWeek", "dates", "data"):
        value = payload.get(key)
        if value is None:
            counts[key] = "absent"
            continue
        if isinstance(value, list):
            counts[key] = len(value)
            if value and isinstance(value[0], dict) and isinstance(value[0].get("games"), list):
                counts[f"{key}[].games"] = sum(len(d.get("games") or []) for d in value)
        elif isinstance(value, dict):
            counts[key] = f"object with keys {sorted(list(value))[:10]}"
    counts["top_level_keys"] = sorted(payload.keys())
    return counts


def score_fixture(payload: object, url: str) -> dict | None:
    """A trimmed, test-usable excerpt of the live score payload.

    Only the first game of the first day is kept, and only the fields the parser
    reads, so the fixture proves the parser against a real shape without
    committing a whole slate.
    """
    if not isinstance(payload, dict):
        return None
    container = None
    for key in ("games", "gamesByDate"):
        if isinstance(payload.get(key), list) and payload[key]:
            container = (key, payload[key])
            break
    if not container:
        return None
    key, days = container
    first = days[0]
    games = first.get("games") if isinstance(first, dict) and isinstance(first.get("games"), list) else days
    if not games:
        return None
    g = games[0]
    keep = {k: g.get(k) for k in ("id", "startTimeUTC", "gameState", "gameScheduleSequence",
                                  "season", "gameType") if k in g}
    for side in ("awayTeam", "homeTeam"):
        team = g.get(side) or {}
        keep[side] = {k: team.get(k) for k in ("abbrev", "score", "name", "placeName")
                      if k in team}
    keep["periodDescriptor"] = g.get("periodDescriptor")
    keep["clock"] = g.get("clock")
    keep["venue"] = (g.get("venue") or {}).get("default") if isinstance(g.get("venue"), dict) else None
    return {
        "_provenance": {
            "captured_from": url,
            "captured_at_utc": utcnow(),
            "captured_by": "scripts/runner_probe.py on a GitHub Actions runner",
            "note": ("Structural excerpt of a live official payload, trimmed to the first "
                     "game. Field values are verbatim from the response; nothing is "
                     "reconstructed. Used by tests/test_runner_probe_contract.py."),
            "container_key": key,
            "top_level_keys": sorted(payload.keys()) if isinstance(payload, dict) else [],
        },
        "payload_excerpt": keep,
    }


def _fixture_unchanged(new: dict, path: str) -> bool:
    """True when the committed fixture already proves the same live SHAPE.

    The fixture exists to pin the parser to the real payload structure, so the
    comparison is on keys, not on tonight's scores: rewriting it every run would
    churn a test fixture with values no test depends on.
    """
    if not os.path.exists(path):
        return False
    try:
        with open(path, encoding="utf-8") as fh:
            old = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return False
    old_shape = old.get("payload_excerpt")
    new_shape = new.get("payload_excerpt")
    if not isinstance(old_shape, dict) or not isinstance(new_shape, dict):
        return False
    return (sorted(old_shape) == sorted(new_shape)
            and old.get("_provenance", {}).get("container_key")
            == new.get("_provenance", {}).get("container_key"))


def stable_projection(report: dict) -> dict:
    """The part of a probe report that should not change between runs.

    Latencies, byte counts and timestamps move on every run; HTTP statuses, the
    payload's top-level keys and the game counts under each candidate container do
    not. Projecting onto the stable part is what lets CI commit a measurement only
    when something real changed, instead of churning a file every hour.
    """
    out = {}
    for name, res in (report.get("results") or {}).items():
        entry = {"ok": res.get("ok"), "http_status": res.get("http_status")}
        structure = res.get("structure")
        if isinstance(structure, dict):
            entry["top_level_keys"] = sorted(k for k in structure if not k.startswith("_"))
        if res.get("error"):
            entry["error_kind"] = str(res["error"]).split(":")[0]
        out[name] = entry
    out["score_payload_shape"] = report.get("score_payload_shape")
    return out


def keep_volatile_values(new: dict, old: dict) -> dict:
    """If nothing structural changed, reuse the previous run's volatile numbers.

    Then ``git diff`` is empty and no commit is produced - the file records when
    the measurement last actually changed, which is the same trick
    ``.github/workflows/tests.yml`` already uses for the coverage report.
    """
    if stable_projection(new) != stable_projection(old):
        return new
    merged = json.loads(json.dumps(new))
    for keep in ("probed_at_utc",):
        if old.get(keep):
            merged[keep] = old[keep]
    if old.get("runner"):
        merged["runner"] = old["runner"]
    if old.get("latency"):
        merged["latency"] = old["latency"]
    for name, res in (old.get("results") or {}).items():
        if name in merged["results"]:
            for field in ("elapsed_seconds", "bytes"):
                if field in res:
                    merged["results"][name][field] = res[field]
    merged["unchanged_since_utc"] = old.get("probed_at_utc")
    merged["note"] = ("Structure identical to the previous probe, so the previous run's "
                      "timestamps and latency samples are retained; see unchanged_since_utc.")
    return merged


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--fixture-out", default=FIXTURE_OUT)
    ap.add_argument("--samples", type=int, default=3, help="latency samples per endpoint")
    ap.add_argument("--stable", action="store_true",
                    help="if nothing structural changed since the existing report, keep its "
                         "timestamps and latency numbers so the file does not churn")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD to treat as 'today'")
    ap.add_argument("--game-id", default="2026020001",
                    help="a current-season game id to probe (default 2026020001)")
    ap.add_argument("--season", default="2026", help="season start year for club-schedule")
    ap.add_argument("--write-fixture", action="store_true",
                    help="also write the trimmed score-payload fixture for tests")
    args = ap.parse_args(argv)

    now = datetime.now(timezone.utc)
    today = args.date or now.strftime("%Y-%m-%d")
    yesterday = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    game_id = args.game_id
    season_folder = f"{int(game_id[:4])}{int(game_id[:4]) + 1}"
    game_no = f"{int(game_id[4:]):06d}"
    game_pk = game_id
    subs = {"today": today, "yesterday": yesterday, "game_id": game_id,
            "season": args.season, "season_folder": season_folder,
            "game_no": game_no, "game_pk": game_pk}

    report: dict = {
        "schema_version": 1,
        "what_this_file_is": ("Measurement of the official NHL sources taken from a GitHub "
                              "Actions runner (real network), by scripts/runner_probe.py. "
                              "Latency figures in this file are the only ones the project is "
                              "allowed to quote, because they are the only ones measured."),
        "probed_at_utc": utcnow(),
        "runner": {"hostname": socket.gethostname(), "python": sys.version.split()[0],
                   "utc_offset_seconds": -time.timezone,
                   "tls": ssl.OPENSSL_VERSION},
        "parameters": subs,
        "results": {},
        "latency": {},
        "score_payload_shape": {},
        "verdict": "",
    }

    reachable, unreachable = 0, 0
    for name, template, kind in ENDPOINTS:
        url = template.format(**subs)
        res = fetch(url)
        body = res.pop("body", b"")
        entry = {k: v for k, v in res.items()}
        if res.get("ok") and kind == "json" and body:
            try:
                payload = json.loads(body.decode("utf-8", errors="replace"))
                entry["structure"] = structural_excerpt(payload)
                if name.startswith("score."):
                    report["score_payload_shape"][name] = {
                        "url": url, "game_counts": game_counts(payload)}
                    if name == "score.today" and args.write_fixture:
                        fixture = score_fixture(payload, url)
                        if fixture and not _fixture_unchanged(fixture, args.fixture_out):
                            os.makedirs(os.path.dirname(args.fixture_out), exist_ok=True)
                            with open(args.fixture_out, "w", encoding="utf-8") as fh:
                                json.dump(fixture, fh, indent=2, ensure_ascii=False)
                                fh.write("\n")
                            report["fixture_written"] = os.path.relpath(args.fixture_out, REPO_ROOT)
            except json.JSONDecodeError as exc:
                entry["json_error"] = str(exc)
        if res.get("ok"):
            reachable += 1
        else:
            unreachable += 1
        report["results"][name] = entry
        time.sleep(DELAY_SECONDS)

    # Latency on the two endpoints a live poll actually hammers.
    for name in ("score.today", "gamecenter.pbp", "report.GS"):
        template = dict((n, t) for n, t, _ in ENDPOINTS)[name]
        report["latency"][name] = latency_samples(template.format(**subs), args.samples)

    report["summary"] = {"endpoints_probed": len(ENDPOINTS), "reachable": reachable,
                         "unreachable": unreachable}
    report["verdict"] = (
        "all probed endpoints reachable from the runner" if unreachable == 0 else
        f"{unreachable} of {len(ENDPOINTS)} endpoints were NOT reachable or returned an "
        "error status - see results; any detector depending on them must flag, not guess")

    if args.stable and os.path.exists(args.out):
        try:
            with open(args.out, encoding="utf-8") as fh:
                previous = json.load(fh)
            report = keep_volatile_values(report, previous)
        except (json.JSONDecodeError, OSError):
            pass  # an unreadable previous report must never stop a new measurement

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(json.dumps({"out": os.path.relpath(args.out, REPO_ROOT), **report["summary"],
                      "verdict": report["verdict"],
                      "score_payload_shape": report["score_payload_shape"]},
                     indent=2, ensure_ascii=False))
    return 0 if unreachable == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
