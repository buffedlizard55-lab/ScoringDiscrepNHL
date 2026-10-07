"""Central configuration for the monitor pipeline.

All URLs point at official NHL endpoints. They are public but *unofficial* in the
sense that the NHL offers no API contract; the pipeline is defensive about shape
changes and flags drift instead of failing silently.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
SNAPSHOT_DIR = DATA_DIR / "snapshots"

DISCREPANCIES_PATH = DATA_DIR / "discrepancies.json"
ALERTS_PATH = DATA_DIR / "alerts.json"
ALERTS_RSS_PATH = DATA_DIR / "alerts.xml"
COVERAGE_PATH = DATA_DIR / "coverage_report.json"
NOTIFY_STATE_PATH = DATA_DIR / "notifications_state.json"
PENDING_ISSUES_PATH = DATA_DIR / "pending_issues.json"
SCHEMA_PATH = REPO_ROOT / "docs" / "schema.json"

# HTTP behaviour -----------------------------------------------------------------
USER_AGENT = (
    "ScoringDiscrepNHL/0.1 (non-commercial research project; "
    "https://github.com/buffedlizard55-lab/ScoringDiscrepNHL)"
)
HTTP_TIMEOUT = int(os.environ.get("SDNHL_HTTP_TIMEOUT", "30"))
HTTP_RETRIES = int(os.environ.get("SDNHL_HTTP_RETRIES", "3"))
REQUEST_DELAY_SECONDS = float(os.environ.get("SDNHL_REQUEST_DELAY", "1.0"))

# Monitoring behaviour ------------------------------------------------------------
# How many days back the schedule scan reaches each cycle.
DEFAULT_LOOKBACK_DAYS = int(os.environ.get("SDNHL_LOOKBACK_DAYS", "3"))
# Keep re-checking each game for this many days after its date (postgame
# corrections window). Rare corrections later than this can be missed.
STABLE_DAYS = int(os.environ.get("SDNHL_STABLE_DAYS", "21"))
# Which official game types to monitor. R = regular season, P = playoffs.
MONITORED_GAME_TYPES = ("R", "P")
# Game statuses treated as finished.
FINAL_STATES = {"Final", "Official", "Game Over"}
# Official PDF reports to hash-monitor for silent edits.
MONITORED_REPORT_TYPES = ("GS", "ES")
# Max alerts retained in alerts.json (RSS keeps the newest 50).
ALERTS_MAX = 500
# Best-effort attempt to archive captured evidence via web.archive.org.
ARCHIVE_SAVE_URL = "https://web.archive.org/save/{url}"
ARCHIVE_TIMEOUT = 15

# Endpoints -----------------------------------------------------------------------
STATSAPI_BASE = "https://statsapi.web.nhl.com"
SCHEDULE_URL = (
    STATSAPI_BASE
    + "/api/v1/schedule?startDate={start}&endDate={end}"
    + "&expand=schedule.teams,schedule.score"
)
LIVE_FEED_URL = STATSAPI_BASE + "/api/v1/game/{game_pk}/feed/live"
TEAMS_URL = STATSAPI_BASE + "/api/v1/teams"
REPORT_URL = "https://www.nhl.com/scores/htmlreports/{season}/{rtype}{report}.PDF"
SITUATION_ROOM_URL = "https://www.nhl.com/news/topic/situation-room"
RECORDS_SITE_URL = "https://records.nhl.com/"
# Second official endpoint family (api-web.nhle.com — powers the current NHL.com).
# Probed for coverage and usable as a corroboration/second-snapshot source.
NHLE_BASE = "https://api-web.nhle.com"
NHLE_SCOREBOARD_NOW_URL = NHLE_BASE + "/scoreboard/now"
NHLE_GAME_PBP_URL = NHLE_BASE + "/gamecenter/{game_id}/play-by-play"
NHLE_GAME_BOXSCORE_URL = NHLE_BASE + "/gamecenter/{game_id}/boxscore"
