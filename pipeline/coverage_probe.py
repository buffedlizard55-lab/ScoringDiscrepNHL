"""Coverage probe: verify, with recorded URLs, which official sources/seasons are
actually reachable — instead of assuming. Results go to data/coverage_report.json
and are rendered by the website.

Run from an environment with access to NHL endpoints (GitHub Actions qualifies).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import config, httpclient, store

# Representative samples per era. These are *probes*, selected to be cheap and
# non-invasive; every result records the exact URL that was tested.
FEED_PROBES = [
    {"label": "statsapi v1 schedule (yesterday)", "kind": "schedule"},
    {"label": "statsapi v1 live feed, gamePk 2010020001 (2010-11 era)", "url":
        config.LIVE_FEED_URL.format(game_pk=2010020001)},
    {"label": "statsapi v1 live feed, gamePk 2007020001 (2007-08 era)", "url":
        config.LIVE_FEED_URL.format(game_pk=2007020001)},
    {"label": "statsapi v1 live feed, gamePk 2005020001 (2005-06 era)", "url":
        config.LIVE_FEED_URL.format(game_pk=2005020001)},
    {"label": "statsapi v1 live feed, gamePk 2002020001 (2002-03 era)", "url":
        config.LIVE_FEED_URL.format(game_pk=2002020001)},
    {"label": "statsapi v1 live feed, gamePk 2000020001 (2000-01 era)", "url":
        config.LIVE_FEED_URL.format(game_pk=2000020001)},
    {"label": "statsapi v1 live feed, gamePk 1997020001 (1997-98 era)", "url":
        config.LIVE_FEED_URL.format(game_pk=1997020001)},
]

REPORT_SEASONS = ["20252026", "20212022", "20192020", "20152016", "20102011",
                  "20052006", "20022003", "20002001", "19981999", "19971998",
                  "19961997", "19951996"]

OTHER_PROBES = [
    {"label": "NHL Records site (records.nhl.com)", "url": config.RECORDS_SITE_URL},
    {"label": "Situation Room topic page", "url": config.SITUATION_ROOM_URL},
    # Second official API family (used by the current NHL.com web client).
    # Probed for corroboration and as a future second snapshot source.
    {"label": "nhle web API — today's scoreboard",
     "url": config.NHLE_SCOREBOARD_NOW_URL},
]


def _probe_url(url: str | None, label: str, kind: str) -> dict:
    result = {"label": label, "kind": kind, "url": url, "status": "not_run",
              "http_code": None, "bytes": None, "note": None}
    if not url:
        result["status"] = "error"
        result["note"] = "no url derivable"
        return result
    try:
        body = httpclient.fetch(url, retries=1)
        result["status"] = "ok"
        result["http_code"] = 200
        result["bytes"] = len(body)
    except httpclient.NotFound:
        result["status"] = "missing"
        result["http_code"] = 404
        result["note"] = "endpoint responded 404: source not published here"
    except httpclient.SourceError as exc:
        result["status"] = "unreachable"
        result["http_code"] = exc.status
        result["note"] = str(exc.reason)[:300]
    return result


def run_probe() -> dict:
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    results = []

    # 1. Schedule + a real recent live feed ------------------------------------
    yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    sched_url = config.SCHEDULE_URL.format(start=yesterday, end=yesterday)
    sched_result = _probe_url(sched_url, "statsapi v1 schedule (yesterday)", "schedule")
    results.append(sched_result)

    recent_feed_label = "statsapi v1 live feed, most recent final game"
    try:
        schedule = httpclient.fetch_json(sched_url, retries=1)
        pk = None
        for day in schedule.get("dates") or []:
            for g in day.get("games") or []:
                if ((g.get("status") or {}).get("detailedState")) in config.FINAL_STATES:
                    pk = g.get("gamePk")
        if pk:
            results.append(_probe_url(config.LIVE_FEED_URL.format(game_pk=pk),
                                      f"{recent_feed_label} (gamePk {pk})", "live_feed"))
        else:
            results.append({"label": recent_feed_label, "kind": "live_feed", "url": None,
                            "status": "skipped", "http_code": None, "bytes": None,
                            "note": "no final game found for yesterday (offseason?)"})
    except httpclient.SourceError as exc:
        results.append({"label": recent_feed_label, "kind": "live_feed", "url": sched_url,
                        "status": "unreachable", "http_code": exc.status, "bytes": None,
                        "note": str(exc.reason)[:300]})

    # 2. Historical live feeds ---------------------------------------------------
    for probe in FEED_PROBES[1:]:
        results.append(_probe_url(probe["url"], probe["label"], "live_feed_historical"))

    # 3. Official PDF reports per season (GS of regular-season game 1) ----------
    for season in REPORT_SEASONS:
        url = config.REPORT_URL.format(season=season, rtype="GS", report="020001")
        results.append(_probe_url(url, f"Official Game Summary PDF, season {season}",
                                  "official_report"))

    # 4. Other official surfaces --------------------------------------------------
    for probe in OTHER_PROBES:
        results.append(_probe_url(probe["url"], probe["label"], "other"))

    earliest_feed = _earliest_ok(results, "live_feed_historical",
                                 order=[r["label"] for r in FEED_PROBES[1:]])
    earliest_report_season = None
    for season in reversed(REPORT_SEASONS):
        match = [r for r in results if r["kind"] == "official_report" and season in r["label"]]
        if match and match[0]["status"] == "ok":
            earliest_report_season = season
            break

    report = {
        "probed_at": now_iso,
        "note": "Automated probe results. Every row records the exact URL tested.",
        "summary": {
            "earliest_ok_historical_feed_probe": earliest_feed,
            "earliest_ok_report_season": earliest_report_season,
        },
        "results": results,
    }
    store.save_json(config.COVERAGE_PATH, report)
    return report


def _earliest_ok(results: list[dict], kind: str, order: list[str]) -> str | None:
    ok_labels = [r["label"] for r in results if r["kind"] == kind and r["status"] == "ok"]
    for label in reversed(order):
        if label in ok_labels:
            return label
    return None
