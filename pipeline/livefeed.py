"""Normalize the official statsapi v1 live feed into a compact snapshot.

The snapshot is the unit of comparison: two snapshots of the same game taken at
different times are diffed to detect discrepancies. All parsing is defensive —
unknown shapes produce warnings in the snapshot, never crashes, and never
invented data.
"""

from __future__ import annotations

import re

_TIME_RE = re.compile(r"^(\d+):(\d{2})$")

# Markers (lower-cased) that indicate a video review / challenge event in the
# play-by-play. These are calibrated against observed feeds; unknown shapes are
# surfaced as schema_drift warnings rather than dropped silently.
REVIEW_NAME_MARKERS = ("video review", "coach", "challenge", "review")
REVIEW_TYPE_MARKERS = ("VIDEO", "CHALLENGE", "REVIEW")
OVERTURN_MARKERS = ("overturn", "no goal", "disallowed", "stands reversed",
                    "overturned", "goal disallowed")


def time_to_seconds(clock: str | None) -> int | None:
    """'MM:SS' (time remaining in period) -> seconds, or None if unparseable."""
    if not clock:
        return None
    m = _TIME_RE.match(clock.strip())
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


def _first(iterable, default=None):
    for item in iterable:
        return item
    return default


def _extract_goal(play: dict, warnings: list) -> dict | None:
    result = play.get("result") or {}
    about = play.get("about") or {}
    team = play.get("team") or {}
    players = play.get("players") or []

    scorer = None
    assists: list[str] = []
    for p in players:
        ptype = (p.get("playerType") or "").strip()
        name = ((p.get("player") or {}).get("fullName") or "").strip()
        if not name:
            continue
        if ptype == "Scorer" and scorer is None:
            scorer = name
        elif ptype == "Assist":
            assists.append(name)

    if scorer is None:
        warnings.append(
            f"goal play without scorer name: period={about.get('period')} "
            f"eventId={about.get('eventId')}"
        )

    strength = None
    strength_obj = result.get("strength")
    if isinstance(strength_obj, dict):
        strength = strength_obj.get("code") or strength_obj.get("name")
    elif isinstance(strength_obj, str):
        strength = strength_obj

    return {
        "period": about.get("period"),
        "period_type": about.get("periodType"),
        "clock": about.get("periodTime"),
        "team": team.get("triCode") or team.get("name"),
        "scorer": scorer,
        "assists": assists,
        "strength": strength,
        # Only assert True when the feed explicitly says so; otherwise unknown
        # (never invent False, so None/False drift cannot create fake diffs).
        "empty_net": True if result.get("emptyNet") else None,
        "shootout": (about.get("periodType") or "").upper() == "SHOOTOUT",
        "event_id": about.get("eventId"),
        "description": result.get("description"),
        "goals_after": about.get("goals") or {},
    }


def _extract_review(play: dict) -> dict | None:
    result = play.get("result") or {}
    about = play.get("about") or {}
    team = play.get("team") or {}
    description = result.get("description") or ""
    lowered = description.lower()
    return {
        "period": about.get("period"),
        "clock": about.get("periodTime"),
        "event": result.get("event"),
        "event_type": result.get("eventTypeId"),
        "team": team.get("triCode") or team.get("name"),
        "description": description,
        "mentions_overturn": any(marker in lowered for marker in OVERTURN_MARKERS),
    }


def normalize_live_feed(feed: dict, captured_at: str, source_url: str) -> dict:
    """Convert a full /feed/live JSON document into a compact snapshot dict."""
    warnings: list[str] = []
    game_data = feed.get("gameData") or {}
    live_data = feed.get("liveData") or {}
    game = game_data.get("game") or {}
    teams = game_data.get("teams") or {}
    status = game_data.get("status") or {}
    linescore = live_data.get("linescore") or {}
    all_plays = ((live_data.get("plays") or {}).get("allPlays")) or []

    if not isinstance(all_plays, list) or not all_plays:
        warnings.append("live feed has no allPlays array (possible shape drift)")

    goals: list[dict] = []
    reviews: list[dict] = []
    for play in all_plays:
        if not isinstance(play, dict):
            continue
        result = play.get("result") or {}
        event_type = str(result.get("eventTypeId") or "").upper()
        event_name = str(result.get("event") or "").lower()

        if event_type == "GOAL" or event_name == "goal":
            goal = _extract_goal(play, warnings)
            if goal is not None:
                goals.append(goal)
            continue

        name_is_review = any(m in event_name for m in REVIEW_NAME_MARKERS)
        type_is_review = any(m in event_type for m in REVIEW_TYPE_MARKERS)
        if name_is_review or type_is_review:
            review = _extract_review(play)
            if review is not None:
                reviews.append(review)

    ls_teams = linescore.get("teams") or {}
    away_ls = ls_teams.get("away") or {}
    home_ls = ls_teams.get("home") or {}

    away_gd = teams.get("away") or {}
    home_gd = teams.get("home") or {}

    detailed_state = status.get("detailedState") or ""
    final = detailed_state in {"Final", "Official", "Game Over"}

    snapshot = {
        "schema": 1,
        "captured_at": captured_at,
        "source": {"live_feed": source_url},
        "game": {
            "game_pk": feed.get("gamePk") or game.get("pk"),
            "season": game.get("season"),
            "game_type": game.get("type"),
            "date": (game_data.get("datetime") or {}).get("dateTime", "")[:10] or None,
            "venue": ((game_data.get("venue") or {}).get("name")),
        },
        "teams": {
            "away": {"tri": away_gd.get("triCode") or away_gd.get("abbreviation"),
                     "name": away_gd.get("name")},
            "home": {"tri": home_gd.get("triCode") or home_gd.get("abbreviation"),
                     "name": home_gd.get("name")},
        },
        "status": detailed_state,
        "final": final,
        "feed_state": {
            "current_period": linescore.get("currentPeriod"),
            "time_remaining": linescore.get("currentPeriodTimeRemaining"),
            "in_intermission": bool((linescore.get("intermissionInfo") or {}).get("inIntermission")),
            "goals": {"away": away_ls.get("goals"), "home": home_ls.get("goals")},
        },
        "goals": goals,
        "reviews": reviews,
        "report_hashes": {},
        "warnings": warnings,
    }
    return snapshot


def feed_url(game_pk) -> str:
    from . import config
    return config.LIVE_FEED_URL.format(game_pk=game_pk)
