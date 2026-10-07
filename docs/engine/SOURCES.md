# Sources: what we read, and what each one can prove

Every URL in this file was requested on 2026-10-07 and the status is recorded
below. A source that returns 200 today is not a promise for next season, which is
why `scripts/verify_sources.py` exists and CI re-runs it.

## Tier 1 - official, machine-readable, primary

| Source | URL pattern | Proves | Verified status |
| --- | --- | --- | --- |
| Game Summary sheet (`GS`) | `https://www.nhl.com/scores/htmlreports/{season}/{CODE}{game:06d}.HTM` | Final credited goals, scorers, assists with `(n)` counters, strength (`EV`/`PP`/`SH`, `EN` suffix), on-ice players, per-team BY PERIOD goals/shots/PN/PIM tables, generation stamp | `20002001/GS020001.HTM` 200; `20022003/GS020001.HTM` 200; `20152016/GS020001.HTM` 200; `20262027/GS020001.HTM` 200 |
| Play-by-Play sheet (`PL`) | same, `PL` prefix | Event timeline including `GOAL`, `GOAL_STOP`, `FACEOFF`; the only artifact where a review delay leaves a footprint | used in prior-art leads; ~1 MB per file, never bulk-fetched |
| Game Center JSON | `https://api-web.nhle.com/v1/gamecenter/{game_id}/landing` | `summary.scoring[].goals[]`: `eventId`, `strength`, `playerId`, `assists[].playerId`, `goalsToDate`, `timeInPeriod`, `awayScore`/`homeScore`, `shotType`, `goalModifier`, `pptReplayUrl`; top-level `limitedScoring` | `2023030155/landing` 200; `1999020001/landing` 200 (1999-2000); 10-digit id required |
| Right rail JSON | `https://api-web.nhle.com/v1/gamecenter/{game_id}/right-rail` | **`gameReports[]` = the canonical list of official report links** (gameSummary, eventSummary, playByPlay, faceoffSummary, shotSummary, toiAway/Home, shiftChart), plus `linescore.byPeriod`, `shotsByPeriod`, `teamGameStats` (`powerPlay: "0/7"`), `gameOutcome.lastPeriodType` | `2026020001/right-rail` 200 |
| Daily scoreboard JSON | `https://api-web.nhle.com/v1/score/{YYYY-MM-DD}` | Which games happened on a date and their game ids - the entry point for backfills | `2024-05-01` 200 |
| Landing HTML | `https://www.nhl.com/gamecenter/{game_id}` | Human view of the same final data; the link a reviewer should land on | linked from records, not parsed |

Notes on behaviour, learned the hard way:

- The landing JSON is **mutable and unversioned**. No `ETag`/`Last-Modified`
  contract, no version field. Two polls can straddle an edit and see nothing.
- `limitedScoring: true` means "the league is withholding scoring detail" - the
  parser marks the record unreadable (`parse_ok: false`) rather than reporting a
  goalless game.
- Pre-2000-01 seasons have no `GS` file: the fallback is exactly one artifact, so
  cross-source checks (C10-C17) cannot run and coverage says so.
- `gameReports` is the only trustworthy way to know which reports exist for a game.
  Constructed URLs 404 for games whose reports were never generated (see the
  missing-playoff-reports list in STATUS.md).

## Tier 1b - official, machine-readable: the Situation Room statement feed (added 2026-10-07)

- `https://forge-dapi.d3.nhle.com/v2/content/en-us/stories?tags.slug=situation-room&$limit=100&$skip=N`
  - one story per coach's challenge / video review, newest first, ~4,400 items from
  2016-02-01 to the current night, each tagged `gameid-<id>` (a few are not and are
  resolved through the daily scoreboard). Public page: `https://www.nhl.com/news/<slug>`.
  States the on-ice call, the result ("Call on the ice is overturned - No Goal
  Toronto"), the rule cited and the explanation; publishes within minutes of the
  play. Read by `situation_room.py` (check SR1); details and limits in
  `docs/SITUATION_ROOM.md`. The earlier Tier 2 wording below ("not published for
  every game, no API") was wrong and is kept struck through.

## Tier 2 - official, human-readable, primary but not machine-readable

- **Situation Room live blogs / recaps** - e.g.
  `https://www.nhl.com/news/frozen-frenzy-nhl-situation-room-live-blog-october-22-2024`.
  ~~The only official format that states *why* a call was overturned ... Not
  published for every game, not structured, no API, no SLA.~~ Superseded by the
  statement feed above; still quotable (`alerts.parse_situation_room_text`).
- **NHL Rule Book** (Rule 78 for goals/assists, 37 for video review) - the standard
  against which "correct" is defined; cited as evidence `reference`, never as proof
  that a specific entry is wrong.

## Tier 3 - third party, secondary

| Source | Why it is in the list | Treatment |
| --- | --- | --- |
| `github.com/aknodell/nhlPbpScrapeR` - `after_goal_corrections.md` + `data/manually_changed_{api,html}_events.csv` | A public audit log of 560 games where the official play-by-play had a goal at the wrong second or lost the following faceoff | **Repository has no license file**, so the data is not copied in. Five rows are quoted individually with attribution as `pending_review` leads. |
| `5v5hockey.com/hockey/games/` | Third-party scorekeeping that deliberately re-pulls ~7 days of games to absorb league stat corrections - independent evidence that corrections happen silently and how fast | Cited in METHODOLOGY for the 7-day re-poll window; never used as a data source |
| `puckovertheglass.substack.com/p/a-brief-history-of-nhl-play-by-play` | Documents RTSS's 26 event types vs the API's 16, and that own goals could only be inferred before 2022-23 | Feeds the FEASIBILITY analysis of what the feed cannot express |
| `forums.hfboards.com/threads/1429377` | Community list of specific playoff `PL` reports that 404 | Kept as a known-holes list; not load-bearing |
| Sportradar live game API (`developer.sportradar.com/.../nhl-ig-live-game-retrieval`) | Has a real `challenge{outcome: call_overturned, decision}` object - proof that the data exists, and that it is licensed | Not used: the project's premise is free official sources |

## Explicitly dead ends (do not retry)

- `https://www.nhl.com/webapi/v1/statspdf` - 404.
- `statsapi.hockey.com` - unreachable.
- `https://api-web.nhle.com/v1/club-schedule/{TEAM}/{start}/{end}` - 404; that
  pattern circulates in old notes and does not exist.
- Any "corrections" or "versions" query parameter on the game center endpoints: no
  such API is documented or discoverable.

## Rate and etiquette

Single-threaded, 0.25 s minimum spacing (configurable), `User-Agent` identifying the
project, exponential backoff on 5xx, no retry on 404/410, response cache keyed by
content hash so re-runs do not re-hit the network. A full regular-season day is
~8 games x 3 requests = 24 requests. A season backfill is batched at 25 games per
CI run.
