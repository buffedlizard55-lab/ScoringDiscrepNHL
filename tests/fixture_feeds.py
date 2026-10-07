"""SYNTHETIC test fixtures shaped like statsapi v1 live feeds.

!!! NOT REAL NHL DATA !!!
Team names, players, game ids, and events here are invented for unit tests.
They mirror the *structure* of the official feed so parsing logic is exercised
without network access. Real records may only enter the database via the
pipeline from official sources.
"""

from __future__ import annotations

FIXTURE_NOTE = "SYNTHETIC TEST FIXTURE - NOT REAL NHL DATA"


def goal_play(event_id, period, clock, tri, scorer, assists=(), strength="EV",
              description="synthetic goal", empty_net=False, period_type="REGULAR"):
    players = [{"player": {"fullName": scorer}, "playerType": "Scorer"}]
    players += [{"player": {"fullName": name}, "playerType": "Assist"} for name in assists]
    return {
        "result": {
            "event": "Goal",
            "eventTypeId": "GOAL",
            "description": description,
            "strength": {"code": strength},
            "emptyNet": empty_net,
        },
        "about": {
            "eventId": event_id,
            "period": period,
            "periodType": period_type,
            "periodTime": clock,
            "goals": {"away": 0, "home": 0},
        },
        "team": {"triCode": tri},
        "players": players,
    }


def review_play(event_id, period, clock, description, tri="TCA"):
    return {
        "result": {
            "event": "Video Review",
            "eventTypeId": "VIDEO_REVIEW",
            "description": description,
        },
        "about": {
            "eventId": event_id,
            "period": period,
            "periodType": "REGULAR",
            "periodTime": clock,
        },
        "team": {"triCode": tri},
    }


def make_feed(goals, reviews=(), final=True, in_intermission=False, current_period=3):
    """Build a synthetic live-feed document."""
    all_plays = []
    all_plays.extend(goals)
    all_plays.extend(reviews)
    return {
        "_fixture": FIXTURE_NOTE,
        "gamePk": 2026020001,
        "gameData": {
            "game": {"pk": 2026020001, "season": "20262027", "type": "R"},
            "datetime": {"dateTime": "2026-10-06T23:00:00Z"},
            "status": {"detailedState": "Final" if final else "Live"},
            "teams": {
                "away": {"name": "Test City A-Team", "triCode": "TCA"},
                "home": {"name": "Test Ville B-Team", "triCode": "TVB"},
            },
            "venue": {"name": "Synthetic Arena"},
        },
        "liveData": {
            "plays": {"allPlays": all_plays},
            "linescore": {
                "currentPeriod": current_period,
                "currentPeriodTimeRemaining": "Final" if final else "10:00",
                "intermissionInfo": {"inIntermission": in_intermission},
                "teams": {"away": {"goals": len(goals)}, "home": {"goals": 0}},
            },
        },
    }
