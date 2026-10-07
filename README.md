# ScoringDiscrepNHL

> **Session-start instruction:** read this README at the beginning of every work session.
> It is the standing project brief. Build only what it describes, verify line by line
> against official sources, and never hallucinate.

---

## 1. Project mission (the standing prompt)

**NHL Scoring Discrepancy Research.** Build a complete, continuously updateable database
of NHL scoring discrepancies and corrections using official NHL sources whenever available.
Search the NHL Situation Room, official NHL game reports, official scoring summaries,
official team reports, and other trusted primary sources. Capture every identifiable event
where the original scoring record/ruling was later changed, including goals changed to
no-goal, no-goals changed to goals, goals changed because of video review, scorer changes,
assist changes, scoring corrections made during the game, during intermission, and after
the game. Do not limit this to recent seasons; determine the earliest reliable historical
coverage that can be obtained from public verified sources and document any coverage
limitations.

For every discrepancy, record the game date, teams, period, game clock, initial
ruling/statistic, corrected/final ruling/statistic, reason for the discrepancy, type of
correction, when the correction occurred, whether the goal/point total changed, whether
only player attribution changed, and the exact official source supporting the entry.
Preserve both the original state and corrected state so the user can clearly see what
changed. Include direct official-source links for every record and flag any record where
the evidence is incomplete, conflicting, unavailable, or cannot be independently verified
rather than filling gaps with assumptions.

The website should allow the user to review and filter the entire database by season,
date, team, period, discrepancy type, goal/no-goal change, scorer/assist correction,
video review, intermission correction, postgame correction, and whether the correction
changed the actual game total. Clearly separate discrepancies that changed the number of
goals from corrections that only changed player attribution. Also identify which
discrepancies could potentially affect a game-total market or settlement after the event
initially appeared to be final. The system should continuously monitor available official
NHL sources and detect new scoring discrepancies automatically, explain what changed, and
generate an alert/notification when a potential discrepancy is detected. Clearly document
what can and cannot be detected automatically, source/feed limitations, latency,
historical coverage limitations, and any cases that still require human verification.

It should solve the problem of having to manually check everything ourselves and provide
an up-to-date current feed for everyday use.

## 2. Core values (binding on every decision)

- **Maximize P(Win).** In every decision, weigh tradeoffs, assess risk, and choose the
  path that maximizes the probability this project succeeds. Set aside emotion; put the
  project first.
- **Own the Outcome.** Own results end to end — not just one slice. When problems arise
  and we have the means to act, act without waiting for permission. Treat failure and
  success as signals and improve. Stay accountable to the final outcome.

## 3. Verification rules (non-negotiable)

1. Work line by line, verifying from official, trusted sources. Provide links for manual review.
2. **No hallucinations.** Unknown fields are `null` with a written flag — never guessed.
3. Every record carries a `verification_status` tier (see `docs/methodology.html`).
4. Flag irregularities for review instead of smoothing them over.
5. The monitor proposes candidates; **humans confirm** against an official source before
   anything enters the database.

## 4. Repository map

| Path | Purpose |
|---|---|
| `docs/index.html` | Database browser (GitHub Pages site) |
| `docs/alerts.html` | Alert-system documentation: feasibility, limits, latency |
| `docs/methodology.html` | Sources, verification tiers, coverage, limitations |
| `docs/data/discrepancies.json` | **Canonical database (single source of truth)** |
| `docs/data/schema.json` | Machine-readable record schema |
| `scripts/monitor.py` | Detection monitor: snapshot official NHL APIs, diff, alert (stdlib only) |
| `scripts/validate.py` | Database validator (stdlib only) |
| `.github/workflows/monitor.yml` | Scheduled monitoring + GitHub Issue alerts |
| `.github/workflows/pages.yml` | Deploy `docs/` to GitHub Pages |

## 5. Quickstart

**View the site locally:**

```bash
cd docs && python -m http.server 8080
# open http://localhost:8080
```

**Validate the database:**

```bash
python scripts/validate.py
```

**Run the monitor (needs internet access to api-web.nhle.com):**

```bash
python scripts/monitor.py --check-recent 3   # re-check last 3 days of games
python scripts/monitor.py --game 2024020204  # snapshot a single game
python scripts/monitor.py --self-test        # offline diff-logic test (no internet)
```

**Enable GitHub Pages (one-time):** repo Settings → Pages → Source: **GitHub Actions**.
The `pages` workflow deploys `docs/` on every push to `main`. To get alert
notifications: Watch → Custom → Issues.

## 6. Alert detection — feasibility summary

**Possible, with honest limits.** There is no official NHL "scoring corrections feed",
so detection works by snapshotting official scoring state and diffing it over time:

- ✅ **Detectable:** assist added/removed/swapped, scorer changed, goal added/removed
  after final, score-state edits, most in-game review reversals (with frequent polling).
- ❌ **Not automatable:** the *reason* for a change, intermediate on-ice calls, @NHLPR
  post monitoring (no free API), Situation Room text at scale (no structured feed),
  historical original-states (APIs show corrected state only), sportsbook settlement calls.
- ⏱ **Latency:** ≈ poll interval (30 min in-season) + API lag; postgame corrections
  caught on rolling re-checks of recently final games.

Full analysis: `docs/alerts.html`.

## 7. Current limitations

1. Seed database has 5 records; only 1 is `official-direct`. Backfill is the main work ahead.
2. @NHLPR scoring-change posts must currently be collected manually (no monitoring API).
3. Situation Room articles have no structured feed; scraping is fragile by nature.
4. Historical original-states are unrecoverable from APIs — backfill needs RTSS reports
   and contemporary sources, case by case.
5. Scheduled checks are cron-granularity (minutes), not real-time push.

## 8. Next steps (for upcoming sessions)

1. **Backfill pass:** collect @NHLPR "OFFICIAL SCORING CHANGE" posts (manual) and
   Situation Room review articles; add records with verification tiers + flags.
2. **RTSS cross-checks:** verify seed records' dates/assists against official HTML
   game reports (`nhl.com/scores/htmlreports/...`).
3. **Capture missing direct URLs:** direct @NHLPR post links for NHL-SD-0002/0004;
   official Situation Room page for NHL-SD-0005; 10-digit game IDs for all.
4. **Extend the monitor:** boxscore player-point cross-checks, 7-day lookback for late
   corrections, intermission-window polling notes.
5. **Historical coverage probe:** determine earliest reliable season empirically and
   document it in `docs/methodology.html`.

## 9. Session log

| Date | Work |
|---|---|
| 2026-10-07 | Repo review (was README-only). Built: README mission brief, seed DB (5 flagged records), JSON schema, 3-page GitHub Pages site with filters, monitor.py + validate.py (stdlib-only), scheduled monitor + pages workflows. Verified NHL.com Situation Room page format and NHL API endpoints from primary/secondary sources. PR → merge to main. |
