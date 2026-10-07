# ScoringDiscrepNHL

A continuously updateable, source-verified database of **NHL scoring discrepancies and
corrections** — goals waved off or reinstated on video review, scorer/assist changes made
during or after games, and league-acknowledged review errors — plus an **automatic
snapshot-diff monitor** that detects new discrepancies from the official NHL API.

> **Read this file at the start of every work session.** It contains the project brief and
> the current state so each session builds on a strong base instead of drifting.

---

## 📌 Project brief (verbatim — this is what we are building)

### NHL Scoring Discrepancy Research

Build a complete, continuously updateable database of NHL scoring discrepancies and corrections using official NHL sources whenever available. Search the NHL Situation Room, official NHL game reports, official scoring summaries, official team reports, and other trusted primary sources. Capture every identifiable event where the original scoring record/ruling was later changed, including goals changed to no-goal, no-goals changed to goals, goals changed because of video review, scorer changes, assist changes, scoring corrections made during the game, during intermission, and after the game. Do not limit this to recent seasons; determine the earliest reliable historical coverage that can be obtained from public verified sources and document any coverage limitations.

For every discrepancy, record the game date, teams, period, game clock, initial ruling/statistic, corrected/final ruling/statistic, reason for the discrepancy, type of correction, when the correction occurred, whether the goal/point total changed, whether only player attribution changed, and the exact official source supporting the entry. Preserve both the original state and corrected state so the user can clearly see what changed. Include direct official-source links for every record and flag any record where the evidence is incomplete, conflicting, unavailable, or cannot be independently verified rather than filling gaps with assumptions.

The website should allow the user to review and filter the entire database by season, date, team, period, discrepancy type, goal/no-goal change, scorer/assist correction, video review, intermission correction, postgame correction, and whether the correction changed the actual game total. Clearly separate discrepancies that changed the number of goals from corrections that only changed player attribution. Also identify which discrepancies could potentially affect a game-total market or settlement after the event initially appeared to be final. The system should continuously monitor available official NHL sources and detect new scoring discrepancies automatically, explain what changed, and generate an alert/notification when a potential discrepancy is detected. Clearly document what can and cannot be detected automatically, source/feed limitations, latency, historical coverage limitations, and any cases that still require human verification.

It should solve the problem of having to manually check everything ourselves and having an up to date current feed.

**Working principles (keep as focal points when building, researching, suggesting upgrades, and implementing):**

- *Maximize P(Win)* — weigh tradeoffs, assess risk, choose the path that maximizes the probability the project succeeds.
- *Own the Outcome* — own results end to end; act without waiting for permission when problems arise and the means to act exist; treat failure and success as signals and improve.
- Work line by line verifying from official verified trusted sources; provide links for manual review.
- No manual input required for routine operation; work autonomously to complete tasks.
- Flag any irregularities for review. **No hallucinations.** Every fact transcribed from a linked source; unknown values stay `null` and are flagged.

---

## Current status (updated 2026-10-07)

| Item | Status |
|---|---|
| Verified discrepancy database | ✅ **26 records**, seasons 1976-77 → 2026-27, every record source-linked |
| Goal-total vs attribution split | ✅ `category` field + dedicated filters |
| Market/settlement impact flags | ✅ `market_impact` field (none / potential / high) |
| Evidence flags | ✅ `evidence_status`: `verified_official` / `verified_secondary` |
| Website (GitHub Pages) | ✅ Live at **https://buffedlizard55-lab.github.io/ScoringDiscrepNHL/** |
| Automatic monitor | ✅ `monitor/nhl_monitor.py` + GitHub Actions every 15 min |
| Alerts feed | ✅ `data/alerts/feed.json`, rendered on the site |
| Alert notifications | ✅ each new detection also opens a **GitHub Issue** automatically |
| Historical coverage documentation | ✅ see "Known limitations" below and on the site |

## Repository layout

```
data/discrepancies.json     ← verified database (single source of truth)
data/discrepancies.csv      ← derived spreadsheet export (scripts/build_csv.py)
data/snapshots/             ← monitor: latest official-state snapshot per game
data/alerts/feed.json       ← monitor: automatic discrepancy detections
monitor/nhl_monitor.py      ← snapshot-diff detector (stdlib only, has --self-test)
scripts/build_csv.py        ← regenerates the CSV from the JSON
docs/SOURCES.md             ← line-by-line source dossier for manual review
assets/ + index.html        ← the GitHub Pages website
.github/workflows/nhl-monitor.yml ← scheduled monitor runs + issue notifications
```

> **Consolidation note (2026-10-07):** a v0.1.0 seed system (site under `docs/`,
> `scripts/monitor.py`) had previously been merged to main. It was merged into this
> system: its four verifiable records were independently re-verified and re-recorded in
> `data/discrepancies.json` (gaps fixed, direct NHL PR links added), and the duplicated
> site/workflows/scripts were removed so there is exactly one monitor, one workflow, and
> one website. The old files remain in git history.

## Using the site

The website is served by GitHub Pages from the repository root:
**https://buffedlizard55-lab.github.io/ScoringDiscrepNHL/**

- **Database** — filter by season, team, category, type, correction timing, period,
  market impact, and evidence flags; expand any card for before/after states, reason,
  evidence notes, and source links (official sources are tagged).
- **Alerts feed** — automatic detections from the monitor; each requires human review.
- **Monitor & detection** — exactly what can/cannot be caught automatically and why.
- **Sources & limits** — primary sources and honest coverage limitations.

## The monitor (how alerts are generated)

The NHL has **no official corrections feed**: when a ruling changes, the official
play-by-play is simply rewritten in place. The monitor therefore keeps its own snapshots:

1. Every 15 minutes (GitHub Actions) it reads `api-web.nhle.com/v1/score/{date}` and each
   game's `/v1/gamecenter/{id}/play-by-play` for today + the last 3 days.
2. It normalizes goal events (event id, period, clock, team, scorer, assists).
3. It diffs against the stored snapshot and raises typed alerts:
   `score_decreased`, `goal_event_removed`, `goal_event_added`,
   `scorer_changed`, `assist_changed`, `total_mismatch_flag`.
4. Alerts land in `data/alerts/feed.json`, are committed back to the repo,
   appear on the site, and each run with new alerts opens a GitHub Issue so
   you get a notification without having to check anything manually.

Run it locally:

```bash
python3 monitor/nhl_monitor.py --self-test   # offline verification of the diff engine
python3 monitor/nhl_monitor.py --days 4      # real run (writes data/snapshots + data/alerts)
```

## Known limitations (honest list — keep this current)

1. **No official corrections feed exists.** The monitor detects *that* the record changed,
   not *why*; classification still needs a human reading NHL.com / NHL PR.
2. **Postgame “OFFICIAL SCORING CHANGE” notices** are published only via NHL PR on X with no
   searchable archive; we archive them one-by-one as found.
3. **Historical depth is uneven.** Play-by-play (RTSS) exists from 2007-08, machine-readable
   feeds are strongest from ~2010-11; coach's challenges began 2015-16; the Situation Room
   launched 2011-12. Older discrepancies (this DB goes back to 1977) only exist when
   documentation survived (newspapers, team media, NHL.com features).
4. **The database is a growing verified sample, not a census.** We never guess; gaps are flagged.
5. **Four entries are secondary-source-only** (`verified_secondary`: 1987 Froese,
   2017 Subban, 2023 MacKinnon G7, 2026 Rossi) — they are explicitly flagged in the UI
   and in `evidence_notes` until an official document is located.
6. **Notification delivery** currently means: a GitHub Issue per detection + the website
   feed + commits. Email/Discord/webhook push would additionally need user-supplied
   credentials.

## Next steps (work queue for the next session)

1. **Grow the historical corpus**: mine NHL.com Situation Room archive posts season-by-season
   (2011-12 onward) and NHL PR “OFFICIAL SCORING CHANGE” history to turn the sample into a
   census of the video-review era.
2. **Find official posts for the 4 flagged records** (2017 Subban, 2023 MacKinnon G7,
   2026 Rossi, and the 1987 Froese case) or keep them flagged.
3. **Add a verified intermission-correction record** (none documented yet — the DB records
   `correction_timing`, so the slot exists).
4. **Wire real notifications** (GitHub issue creation per alert, then optional email/webhook
   once credentials are provided).
5. **Monitor hardening**: handle NHL API schema drift with contract tests; add per-season
   backfill mode (`--date YYYY-MM-DD`) to replay past seasons where feeds exist.
6. **Cross-check pass**: for every record, re-open each source link and re-verify the quoted
   facts line by line before each release.

---

*Independent research project. Not affiliated with or endorsed by the National Hockey
League. NHL and NHL team marks are trademarks of the NHL.*
