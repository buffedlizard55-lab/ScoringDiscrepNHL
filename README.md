# ScoringDiscrepNHL

A continuously updated, source-verified database and alert system for **NHL scoring
discrepancies and corrections** — every place where the official scoring record was
changed: goals overturned to no-goals (and vice versa), scorer/assist corrections,
video-review overturns, and corrections made during the game, at intermission, or
after the game.

> **Read the [Project Charter](#project-charter-verbatim) below before every work
> session.** It is the fixed statement of what this project is building.

**Live site:** served via GitHub Pages from this repository (see the repo's
Settings → Pages, or the deployed site link in the sidebar).

---

## Integrity rules (apply to all work on this project)

1. **No hallucinations.** Every record in the database must be backed by an exact,
   clickable official source link captured by the automated pipeline (or by a human
   entry that includes the same). If a field cannot be verified, it stays empty or is
   flagged — it is **never** guessed or filled with assumptions.
2. **Verify line by line from official, trusted primary sources** (NHL API feeds,
   official NHL game reports, Situation Room posts). Secondary sources are used only
   as corroboration and are labeled as such.
3. **Flag irregularities for review** (`pending_review`, `conflicting`,
   `needs_human_review`) rather than silently resolving them.
4. **Preserve both states**: every record keeps the *original* ruling/statistic and
   the *corrected* ruling/statistic so the change is unambiguous.
5. **Document limits honestly** — see [docs/COVERAGE_AND_LIMITATIONS.md](docs/COVERAGE_AND_LIMITATIONS.md).

---

## What this repository contains

| Path | Purpose |
|---|---|
| `site/` | The GitHub Pages website (clean UI, filters, alert feed, docs pages) |
| `data/` | The database itself: `discrepancies.json`, `alerts.json`, `coverage_report.json`, plus the JSON Schema |
| `data/snapshots/` | Local snapshot cache of captured official feeds (git-ignored; CI keeps them in the Actions cache) |
| `pipeline/` | Python (stdlib-only) monitor: fetch → snapshot → diff → detect → alert |
| `tests/` | Unit tests with **clearly synthetic** fixtures (runnable offline) |
| `docs/` | Coverage & limitations, source catalog, detection design, methodology, schema |
| `.github/workflows/` | Scheduled monitor (cron), CI tests, Pages deployment |

---

## How it works (architecture)

```
   Official NHL sources                       ScoringDiscrepNHL
 ┌──────────────────────────┐     fetch     ┌──────────────────────────────┐
 │ statsapi.web.nhl.com     │──────────────▶│ 1. Snapshot completed games  │
 │  (live feeds, schedule)  │               │    (normalized JSON, cached) │
 │ nhl.com official PDF     │──────────────▶│ 2. Diff vs previous snapshot │
 │  reports (GS/ES, hashed) │               │ 3. Classify change           │
 │ Situation Room posts     │──────────────▶│    - total changed?          │
 └──────────────────────────┘               │    - attribution only?       │
                                            │    - video review?           │
                                            │    - when did it change?     │
                                            │ 4. Write discrepancy record  │
                                            │    (both states + evidence)  │
                                            │ 5. Emit alert (alerts.json,  │
                                            │    RSS, GitHub Issue)        │
                                            └──────────────┬───────────────┘
                                                           │ git commit (CI)
                                                           ▼
                                            GitHub Pages site auto-redeploys
```

The monitor runs every 30 minutes in GitHub Actions (where outbound internet access
exists). It snapshots each recently completed game's official data, diffs it against
the previous snapshot, and turns any change into a discrepancy record + alert.
**Diff-first detection** means we do not need to know every possible correction
mechanism in advance — any change in official data is caught and classified.

The database shipped in this repository is **empty by design on day zero**. It is
populated only by the pipeline from captured official sources. Nothing is
hand-invented; see the honesty note below.

---

## Research leads inbox

`docs/inbox/prior_session_leads.json` contains 5 scoring-change **leads** carried
over from a prior session's seed database. They are **quarantined**: they were
hand-entered, cannot be line-by-line verified from this environment, and some rely
on secondary sources only. They are NOT part of the verified database. Each lead
must be independently re-verified against its cited official source (or deleted)
before it may enter `data/discrepancies.json` via the standard schema.

## Honesty note — current status

* The pipeline, schema, site, and documentation are complete and tested.
* The database starts **empty** because records may only enter with verified
  official-source evidence captured by the pipeline. Pre-populating it by hand from
  memory would violate the no-hallucination rule.
* From the original authoring environment for this code, NHL endpoints were
  **not reachable** (egress is restricted), so the first live data + the coverage
  probe results will be produced by the GitHub Actions monitor runs. Any statement
  about endpoint shapes or historical coverage that could not be verified live is
  explicitly marked `unverified` in the docs.

## Quick start (local)

```bash
# Run the test suite (no network needed; fixtures are synthetic)
python3 -m unittest discover -s tests -v

# Validate the data files against the schema
python3 -m pipeline.main validate

# Run one monitor cycle (needs internet access to NHL endpoints)
python3 -m pipeline.main update --days 3

# Probe which seasons/sources are reachable (writes data/coverage_report.json)
python3 -m pipeline.main probe

# Serve the site locally at http://localhost:8000 for development
python3 -m pipeline.main serve
```

## One-time GitHub setup (operational notes)

1. **GitHub Pages** must be enabled with source = **GitHub Actions**
   (Settings → Pages → Source: GitHub Actions). The `pages.yml` workflow deploys
   `site/` + `data/` on every push to `main`.
2. **Workflow permissions**: Settings → Actions → General → Workflow permissions
   must allow **Read and write** so the monitor can commit `data/` updates
   (`monitor.yml` requests `contents: write`).
3. The monitor cron runs every 30 minutes. Its snapshot baselines live in the
   **Actions cache** (not in git) by design — see
   [docs/COVERAGE_AND_LIMITATIONS.md](docs/COVERAGE_AND_LIMITATIONS.md) §3.
4. First-run expectation: cycle 1 *baselines* games (no alerts); from cycle 2
   onward, any official change becomes a record + alert.

## Development principles (focal point for all work)

**Maximize P(Win).** Every decision — architecture, sources, UI, automation — is
chosen to maximize the probability that this project succeeds at its purpose:
eliminating manual checking and providing an up-to-date, trustworthy feed of NHL
scoring discrepancies. When tradeoffs appear (coverage vs. accuracy, speed vs.
verification), accuracy and verification win, because a wrong "correction" feed is
worse than an empty one.

**Own the Outcome.** Work is owned end-to-end: fetching, verification, detection,
presentation, alerting, and documentation of failures. When something breaks or a
source goes stale, it gets fixed or explicitly flagged — not ignored. Failures are
treated as signals: every limitation in this project is written down and linked.

---

## Project Charter (verbatim)

> The following is the fixed statement of purpose for this repository. Read it at
> the start of every work session.

### NHL Scoring Discrepancy Research

Build a complete, continuously updateable database of NHL scoring discrepancies and
corrections using official NHL sources whenever available. Search the NHL Situation
Room, official NHL game reports, official scoring summaries, official team reports,
and other trusted primary sources. Capture every identifiable event where the
original scoring record/ruling was later changed, including goals changed to
no-goal, no-goals changed to goals, goals changed because of video review, scorer
changes, assist changes, scoring corrections made during the game, during
intermission, and after the game. Do not limit this to recent seasons; determine the
earliest reliable historical coverage that can be obtained from public verified
sources and document any coverage limitations.

For every discrepancy, record the game date, teams, period, game clock, initial
ruling/statistic, corrected/final ruling/statistic, reason for the discrepancy, type
of correction, when the correction occurred, whether the goal/point total changed,
whether only player attribution changed, and the exact official source supporting the
entry. Preserve both the original state and corrected state so the user can clearly
see what changed. Include direct official-source links for every record and flag any
record where the evidence is incomplete, conflicting, unavailable, or cannot be
independently verified rather than filling gaps with assumptions.

The website should allow the user to review and filter the entire database by season,
date, team, period, discrepancy type, goal/no-goal change, scorer/assist correction,
video review, intermission correction, postgame correction, and whether the
correction changed the actual game total. Clearly separate discrepancies that changed
the number of goals from corrections that only changed player attribution. Also
identify which discrepancies could potentially affect a game-total market or
settlement after the event initially appeared to be final. The system should
continuously monitor available official NHL sources and detect new scoring
discrepancies automatically, explain what changed, and generate an
alert/notification when a potential discrepancy is detected. Clearly document what
can and cannot be detected automatically, source/feed limitations, latency,
historical coverage limitations, and any cases that still require human
verification.

Put this prompt into the repo readme and read it everytime we work on the project as
a starting point to make sure we are building what we are aiming for and have a
strong base to continue building and improving on making something useful for
everyday use. It should solve the problem of having to manually check everything
ourselves and having an up to date current feed.

The following is taken from the Arena AI team and I think it makes a good point on
building a successful project, so let's keep the Core Values and Own the Outcome as a
focal point when building, developing, researching, suggesting upgrades, and
implementing the work.

**Our Core Values**

**Maximize P(Win)** — “Maximize the Probability of Winning”: our decision making
framework. In every decision, we weigh tradeoffs, assess risk, and choose the path
that maximizes the probability that Arena succeeds. We set aside our emotions and
make tough decisions in order to maximize P(Win). “Maximize P(Win)” frees us from
constraints and clarifies that we must put Arena first.

**Own the Outcome** — We own results end to end — not just our individual slice of
the work. When problems arise and we have the means to act, we do so without waiting
for permission or assignment. We treat failure and success as signals and use them to
improve. At Arena, we stay accountable to the final outcome.

Work line by line verifying from official verified trusted sources, provide links for
manual review. There should be no manual input, work on your own to complete tasks.
Flag any irregularities for review. No hallucinations.

The goal of this project is to get a full list that follow our requirements. No
hallucinations. Verify line by line.

**Site creation** — Create a github page for this repo that has clean ui, user
friendly, simple and easy to use. It should be organized and clean. It should
include all relevant information in an easy to read format with official verified
links as sources for review. Work line by line verify everything no hallucinations.
