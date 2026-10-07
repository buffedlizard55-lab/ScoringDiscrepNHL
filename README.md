# ScoringDiscrepNHL

A source-verified database and continuous detector for **NHL scoring discrepancies** — goals that were
changed to no-goals, no-goals that became goals, scorer and assist corrections, in-game and intermission
corrections, and post-game corrections — with the **official NHL artifact behind every claim** and both the
original and the corrected state preserved.

> ## Standing brief - read before touching anything
>
> The full requirements live in [PROJECT_PROMPT.md](PROJECT_PROMPT.md) and are the
> contract for every session: a continuously updateable database of NHL scoring
> discrepancies and corrections from **official** sources (goal↔no-goal, video-review
> changes, scorer changes, assist changes, in-game/intermission/post-game
> corrections); per record the game date, teams, period, clock, initial ruling,
> corrected/final ruling, reason, correction type, when it was corrected, whether the
> goal/point total changed, whether attribution alone changed, and the exact official
> source link; both states preserved; incomplete or conflicting evidence **flagged,
> never guessed**; a clean filterable GitHub Pages site; an alerting layer plus an
> explicit account of whether this is even possible; a PR merged to main; and three
> passes - implement, hunt bugs, recheck against the brief.
>
> **Core Values.** *Maximize P(Win)*: a plausible-looking row is worth less than a
> flagged empty field, so nothing enters the database without a link that survives a
> click and no check ships without a fixture proving it fires **and** stays quiet on
> clean data. *Own the Outcome*: no "the API didn't provide it", no TODO handoffs -
> gaps are owned in the data (`status`, `flags`, `pending_review`) and in
> [docs/STATUS.md](docs/STATUS.md), never smoothed over.

> **Status, stated plainly (2026-10-07).** The toolkit, the website and both detection paths are built,
> unit-tested (**73 tests**) and wired to a scheduler. The database holds **three verified records** — every
> one built from the league's own scoring-change announcement *and* cross-checked against the official game
> report it names, with the superseded credit, the flags and the exact URLs preserved (see
> [the first three records](#the-first-three-records)). It is **not** a complete census of NHL scoring
> changes: three records from one season is a proof of method, not coverage, and each record states in its
> own flags which part of its evidence is missing. Two things still require a networked machine: the mass
> backfill and the live monitor (the build sandbox has no route to NHL hosts — measured, artifact committed
> at [`docs/evidence/sandbox_network_probe.json`](docs/evidence/sandbox_network_probe.json)). Nothing is
> seeded from memory, media reporting or assumptions, which is why every row below can be opened and
> re-checked.

> **Two implementations of this brief now coexist in this repository (2026-10-07).** `main` already
> carried a complete, independently built implementation from parallel sessions — `pipeline/`, a
> root-served site (`index.html`, `js/`, `css/`), its own database `data/discrepancies.json`
> (**0 records**), its own tests and docs, and a 30-minute monitor. This branch adds a second:
> `src/nhl_monitor/`, `site/` and `data/records/discrepancies.json` (**3 verified records**).
> Nothing from either line was deleted. The four colliding artifacts were each resolved once: one
> monitor is scheduled (this line's), the parallel line's monitor is parked verbatim at
> `.github/workflows/monitor_root_site.yml.disabled`, and the parallel line's README and source
> catalog are preserved verbatim under `docs/parallel_line/`. **A decision is owed** — two
> databases, two monitors and two sites are one too many of each. See
> [`docs/parallel_line/PARALLEL_LINE.md`](docs/parallel_line/PARALLEL_LINE.md) for what differs,
> what each line is good at, and the exact steps to keep either one.

---

## Contents

- [What is verified today](#what-is-verified-today)
- [How it works](#how-it-works)
- [Quickstart](#quickstart)
- [Populating the database](#populating-the-database)
- [The website](#the-website)
- [Data model](#data-model)
- [What can and cannot be detected automatically](#what-can-and-cannot-be-detected-automatically)
- [Repository layout](#repository-layout)
- [Open items for the next session](#open-items-for-the-next-session)
- [The original brief (verbatim)](#the-original-brief-verbatim)
- [Working agreement (verbatim)](#working-agreement-verbatim)

---

## What is verified today

Every row below was established by fetching the source and cross-checking it against another official
artifact on **2026-10-07**. The full ledger, including the observations and the URLs, is
[`data/reference/verified_facts.json`](data/reference/verified_facts.json) and is rendered on the site under
*Sources & verification*.

| Fact | Evidence |
|---|---|
| The official report family on `nhl.com/scores/htmlreports/<season>/` contains four documents: `GS` (Game Summary), `ES` (Event Summary), `PL` (Play-by-Play), `RO` (Club Playing Roster). | All four retrieved for `20232024`. `SC…` returns 404, so there is no separate scoring-change document. |
| The GameCenter JSON API serves both modern and historic seasons. | `/v1/gamecenter/2023020001/…` and `/v1/gamecenter/2005020001/…` both returned 200. |
| **The API and the HTML reports agree, down to player ids.** | The play-by-play goal event for 2023020001 goal #1 carries `scoringPlayerId=8476453`, which the Play-by-Play report text independently identifies as Kucherov (`NSH #2 SCHENN HIT TBL #86 KUCHEROV`), matching `86 N.KUCHEROV(1)` in the Game Summary. They are the same data rendered twice — **not** two independent witnesses. |
| **Old reports are frozen at game time; new reports are regenerated.** | `20052006/GS020001.HTM` footer `2005-10-05-21.40.47` (game night), `20162017/GS020001.HTM` footer `2016-10-12-22.08.17` (game night), but `20232024/GS020001.HTM` footer `2024-02-06 11.19.44` — 119 days after the game. |
| The frozen era preserves the **original** ruling; the regenerated era does not. | Consequence of the row above: for 2005-06 and 2016-17 the live document *is* the game-night record, so diffing it against the league's current database exposes any later scoring change with both states official. |
| **Coverage was measured for all 28 seasons, 1999-2000 → 2026-27, on a CI runner.** | `data/reference/coverage_report.json`: no report for 1999-2000 or 2004-05 (that season was not played), and a report for every season from 2000-01 on. 12 seasons are still game-night documents, 10 have been regenerated, 4 have a footer that cannot be read, and **the two sets interleave** — 2003-04 and 2012-13..2014-15 are regenerated while 2016-17, 2018-19 and 2019-20 are frozen. |
| **The earliest season served is 2000-01.** | `19992000/GS020001.HTM` → 404, `20002001/GS020001.HTM` → 200 (COL 2 - DAL 2, 2000-10-04, frozen footer `2000-10-04-22.14.20`), `20012002/GS020001.HTM` → 200 (OTT 5 - TOR 4, frozen footer `2001-10-03-22.27.18`). The 2000-2004 reports are **frozen at game time**, so the original record for a 25-year-old game is still retrievable. |
| The 2000-2004 report layout is different and is parsed. | On-ice skaters sit inside the scoring summary, the strength column is last, there is no league-shield logo, and bench penalties appear as a player cell literally reading `Team`. Fixture: `tests/fixtures/gs_20002001_020001.html`. |
| **The NHL publishes scoring changes in a fixed, machine-parseable form.** | `OFFICIAL SCORING CHANGE: Game <n> @<away> at @<home> Goal at <M:SS> of the <ordinal> period now reads <scorer> from <assist1> and <assist2>. #NHLStats` — retrieved and parsed for three games; each resolves to a specific goal in the official report (F16). |
| Corrections land **after** the game is final, by hours. | All three announcements were posted between **2h49m and 3h25m** after the reported end of the game. This is the latency a market would care about, and it is measured from the announcement timestamp and the report's own end-of-game clock. |
| An official payload can still show the **superseded** credit. | For the corrected goal of game 1140, the event's English highlight-clip title still reads `meier-scores-ppg` while the French title for the same event reads `mercer-…`, and the scoring fields read Mercer (F17). Stored as corroboration, flagged as an inconsistency. |
| The Wayback CDX index exposes a content **digest per snapshot**. | One snapshot for `20232024/GS020001.HTM` (digest `TE24NPUUMSEV3LQEBNQE2TN3NO5GNATJ`), so "did this document ever change?" is answerable without downloading every version. |
| Archive coverage is sparse and noisy. | 2006-era captures of 2005-06 reports are HTTP 302 redirects with the empty digest `3I42H3S6NNFQ2MSVX7XZKYAYSCX5QBYJ`; these are rejected as evidence. |
| A **negative control** passed. | The archived copy of `20232024/GS020001.HTM` (2025-01-25) has the same eight-goal scoring summary and the same footer as the live document, so the method produced no false positive on that game — and it proves a regenerated footer is *not* by itself a change. |
| No machine-readable Situation Room / video-review feed was located. | The observed event vocabulary (committed at `data/schema/observed_vocabulary.json`) contains no review event type, so the project does **not** claim to detect video review from the feed. |

## The first three records

Three records exist, all from the 2024-25 season, all **attribution-only** (the goal count of each game is
unchanged). Each one is in [`data/records/discrepancies.json`](data/records/discrepancies.json), is
reproducible from its case file in [`data/inbox/statements/`](data/inbox/statements/), and carries flags for
the parts of its evidence that are missing.

| Record | Game | Goal | Change | Verified against | Flags |
|---|---|---|---|---|---|
| `NHL-20242025-021140-01` | 2025-03-26 NJD 5 @ CHI 3 | 6:50 P1 (PP) | scorer **Timo Meier → Dawson Mercer** (from Hughes, Hischier) | `GS021140.HTM` (rebuilt 2025-03-27 8.23.23) + GameCenter event 146 + the league's post | superseded credit is secondary only; pre-change assists unresolved; the English clip title still says Meier |
| `NHL-20242025-021238-01` | 2025-04-08 BOS 7 @ NJD 2 | 9:38 P1 (EV) | assist **Parker Wotherspoon → Morgan Geekie** | `GS021238.HTM` (rebuilt 2025-04-11 21.36.36) + the league's post | superseded assist is secondary only; the reproduction's own citation points at a different goal |
| `NHL-20242025-021185-01` | 2025-04-01 NSH 4 @ CBJ 8 | 9:02 P3 (EV) | assists resolved to **Cole Smith + Michael McCarron** | `GS021185.HTM` + the league's post | what the assists read *before* the change is not documented anywhere reviewed — the record says so instead of guessing |

Two independent season totals in each official report corroborate the corrected state (for example Geekie 23
assists and Wotherspoon 6 in game 1238, exactly as the syndicated reproduction of the announcement states).
No record claims a game-total change, because none of the three changed the number of goals — and the site
keeps them out of the goal-count view accordingly.

## How it works

```
                    ┌─────────────────────────── official sources ───────────────────────────┐
                    │ api-web play-by-play │ api-web boxscore │ GS / ES / PL / RO documents │
                    └───────────┬──────────────────┬───────────────────┬────────────────────┘
                                │                  │                   │
                        fetch.py│ (URL + status + retrieval time recorded for every read)
                                ▼                  ▼                   ▼
                    ┌───────────────────────────────────────────────────────────────┐
                    │ parse.py  →  one normalised GameState (period, clock, team,   │
                    │              scorer, assists, strength, own-goal, score-after)│
                    └───────────────────────────┬───────────────────────────────────┘
                                                ▼
      state.py diff_states(new, stored)  →  goal_removed / goal_added / scorer_change /
                                             assist_change / strength_change / own_goal / metadata
                                                ▼
      classify.py  →  discrepancy type · affects goal total? · attribution only?
                      timing (in-game / intermission / post-game) · settlement relevance
                                                ▼
      store.py     →  append-only record with both states + every source URL    alerts.py → GitHub issue
```

Two census methods recover history:

1. **Frozen-era document vs current database** — for seasons whose official report was generated on game
   night (verified for 2005-06 and 2016-17), the live document holds the *original* ruling and the API holds
   the *current* record. `nhl_monitor backfill-era` walks a game-number range and records every difference.
2. **Archived snapshots of the same document** — the only method that works for the modern era, where the
   document is regenerated in place. `nhl_monitor backfill-archive` compares the two captures that
   bracket a proven change, so both states come from the league's own documents.

## Quickstart

Standard library only — no `pip install`, no bundler, Python 3.9+.

```bash
git clone https://github.com/buffedlizard55-lab/ScoringDiscrepNHL
cd ScoringDiscrepNHL
export PYTHONPATH=src

python -m nhl_monitor probe                       # is every official source readable, and does the parser
                                                  # understand the live report layout? (run this first)
python -m nhl_monitor monitor --date 2026-10-07   # capture the slate, detect + alert on any change
python -m nhl_monitor collect --game-id 2023020001 --dry-run
python -m nhl_monitor backfill-era    --season 20052006 --start 1 --end 1065
python -m nhl_monitor backfill-archive --game-id 2023020001 --kind GS
python -m nhl_monitor archive-scan    --season 20242025 --start 1 --end 60 --out /tmp/scan.json
python -m nhl_monitor archive-yield   --from-season 2005 --to-season 2026
python -m nhl_monitor verify --record-id NHL-20232024-020001-01
python -m nhl_monitor export-csv --out data/exports/discrepancies.csv
python -m nhl_monitor sources                     # the source registry with verification status

python -m unittest discover -s tests -v           # 121 tests
python tools/build_site.py && python -m http.server 8080 --directory _site   # local site
```

`probe` is not decoration: it fetches the live Game Summary and parses it, so a league layout change makes
the pipeline fail loudly instead of silently returning zero goals.

## Populating the database

**Locally**

```bash
# 1. the league's own announcements -> records (this is how the three shipped records were built)
PYTHONPATH=src python -m nhl_monitor ingest

# 2. history: a frozen report (the original record) vs the current official database
PYTHONPATH=src python -m nhl_monitor backfill-era --season 20052006 --start 1 --end 1065
PYTHONPATH=src python -m nhl_monitor archive-yield --from-season 2005 --to-season 2026  # measured archive ceiling

# 3. live: poll, diff, alert
PYTHONPATH=src python -m nhl_monitor monitor --date 2026-10-07 --github-issue
```

**Adding a further case by hand (no manual checking required, but this is the door for it)** — copy an
announcement's text plus the official report row that verifies it into a JSON file in
`data/inbox/statements/`, run `ingest`, and the module will parse the announcement, cross-check it against
the fields you supplied, flag any disagreement, and refuse to build a record whose corrected state has no
official URL. The shipped case files are the template.

**On GitHub (recommended — this is the "no manual checking" part)**

| Workflow | Trigger | What it does |
|---|---|---|
| [`tests.yml`](.github/workflows/tests.yml) | every push | 73 unit tests, a browser-less site smoke test, JS syntax check, site build, JSON record-schema validation, source reachability probe (which also measures per-season coverage on the runner) |
| [`monitor.yml`](.github/workflows/monitor.yml) | every 5 minutes | captures the slate, diffs against the stored state, commits the evidence timeline, opens a GitHub issue for every detected discrepancy |
| [`backfill.yml`](.github/workflows/backfill.yml) | manual | walks a season/game range with either census method, scans the archive for provable changes, measures the archive's coverage ceiling, and commits the results |
| [`pages.yml`](.github/workflows/pages.yml) | on push to `main` | builds and deploys the site |

GitHub Actions is the right home for this because a runner has unrestricted outbound network access, a
scheduler, durable storage (git history) and a notification channel (issues) — none of which the build
sandbox had.

> GitHub scheduled workflows can be delayed at busy times. Treat the cadence as "within ~10 minutes", and
> note that a correction published and superseded inside one polling interval is only recoverable from an
> archived snapshot.

## The website

GitHub Pages, static, no dependencies, deployed from the repository's own committed JSON.

* **Database** — record counts, live filters (season, team, date range, period, discrepancy type,
  goal-count vs attribution-only, timing, settlement risk, evidence status, free-text), click-through drawer
  with both states, every captured timestamp, every source link, flags and a completion score.
* **Goal-count changes** and **attribution-only corrections** are in two separate tables, because only the
  first can move a game total.
* **How detection works** — the pipeline, the two census methods, and what the classifier refuses to do.
* **Limitations** — including what cannot be detected automatically.
* **Sources & verification** — the source registry with status, the verification ledger, the observed event
  vocabulary, and measured season coverage.

## Data model

One record per changed goal (full schema in [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md)):

| Field group | Contents |
|---|---|
| `game` | game id, season, date, away/home with final score |
| `event` | period, period type, game clock, strength, team |
| `initial_state` / `corrected_state` | ruling, scorer, assists, strength, own-goal flag — **both preserved** |
| `change` | discrepancy type, whether the goal count changed, whether it was attribution-only, every raw change |
| `reason` | category + verbatim quote **only if an official artifact states it**, otherwise `null` with a flag |
| `timing` | in-game / intermission / post-game (before or after publication) + the reasoning + both capture timestamps |
| `sources` | role, type, name, URL, HTTP status, retrieval time |
| `evidence_status` | `verified_two_official_states`, `verified_corrected_state`, `conflicting`, `incomplete`, … |
| `settlement` | level, could it touch a game total, could it touch props, reasoning, "needs book-specific review" |
| `detection` | how it was found, when, the state fingerprints compared, confidence |
| `flags` + `completeness` | every gap, spelled out — never filled in |

Records are append-only: a revision keeps the superseded version under `previous_revisions`, and git history
is the final backstop.

## What can and cannot be detected automatically

**Can be detected automatically** — any semantic difference between two captured official states:
goal→no-goal, no-goal→goal (including overturned goals from video review), scorer change, assist change,
strength change, own-goal annotation change, and score movement with no matching goal-set change (flagged as
an inconsistent feed). Also: the *timing* of a change relative to the game, the *settlement relevance*, and
disagreement between two official renderings of the same game.

**Cannot be detected automatically** (and the project does not pretend otherwise):

* **The reason** — no machine-readable Situation Room / review feed was located, so "video review" is only
  recorded when an official artifact says so in words. Everything else keeps `reason.text = null` plus a flag.
* **A change that happened and was superseded between two of our polls**, when no archive snapshot exists
  from before the change. The archive method cannot see it either if every snapshot postdates the correction.
* **Whether a bookmaker regraded anything** — house rules are private.
* **Pre-2005-ish history** until the coverage job pins the earliest season that actually serves reports.

Full detail, including latency and coverage limits: [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md).

## Repository layout

```
src/nhl_monitor/     sources.py fetch.py parse.py state.py classify.py detect.py archive.py store.py
                     ingest.py alerts.py cli.py   (standard library only)
site/                index.html app.js styles.css   (static, GitHub Pages)
data/                records/discrepancies.json  inbox/statements/ (one case file per record)
                     reference/verified_facts.json  taxonomy.json
                     schema/observed_vocabulary.json  games/ evidence/ alerts/ exports/
tests/               73 unittest cases + provenance-documented fixtures from real official documents
tools/build_site.py  assembles _site/ (static files + committed JSON)
docs/                LIMITATIONS.md BACKFILL.md DATA_MODEL.md SOURCES.md OPERATIONS.md ROADMAP.md
                     VERIFICATION_LOG.md  evidence/
.github/workflows/   tests.yml monitor.yml backfill.yml pages.yml
```

## Open items for the next session

Ranked by how much they block the goal (details in [`docs/ROADMAP.md`](docs/ROADMAP.md)):

1. **Run the backfill slice on a networked machine** (`backfill-era --season 20052006 --start 1 --end 200`,
   or via `backfill.yml`). The three shipped records prove the *announcement* path end to end; the frozen-era
   census path is built and unit-tested but has never run against live sources at scale. Expect the first
   slice to be the slowest: markup drift, missing games and archive redirects all surface at once.
2. **Turn the announcement watch into a scheduled job.** The announcements are the sharpest signal that exists
   (they name the game, the period, the clock and the new credit), and they were retrieved here through the
   platform's page-fetch tool, not through a supported API. A runner needs either an X API tier or a
   documented, polite fetch of the announcement account; until then the monitoring path is the game feeds.
3. **Decide how to treat a 1–4 day rebuild.** Footers 1–4 days after the game (2003-04, 2012-13..2014-15,
   2020-21, 2026-27) are neither a game-night record nor a late batch rebuild, and may already contain corrections.
   They are currently marked regenerated; whether they deserve their own, weaker evidence class is an open design
   question.
4. **Hunt for a goal-count change.** All three records are attribution-only, so the highest-value class —
   a goal added or removed *after* the record was final — is still unobserved. It should be rare by
   construction; proving that claim, rather than asserting it, is the next research step.
5. **Recover pre-change states from the archive** where a frozen or early snapshot exists, which would
   upgrade a record from "superseded credit is secondary" to two official states.
6. **Verify the four secondary leads** (L01–L04 in `data/reference/verified_facts.json`) or drop them; none
   may become a record without an official artifact.
7. **Player-id resolution for HTML reports** — frozen documents carry sweater numbers and surnames but no
   ids, so name→id matching must go through the season's roster and must refuse to guess on ambiguity.

## The original brief (verbatim)

<details>
<summary>Click to expand — this is the contract this repository is built against; read it first every session.</summary>

### NHL Scoring Discrepancy Research

Build a complete, continuously updateable database of NHL scoring discrepancies and corrections using
official NHL sources whenever available. Search the NHL Situation Room, official NHL game reports, official
scoring summaries, official team reports, and other trusted primary sources. Capture every identifiable
event where the original scoring record/ruling was later changed, including goals changed to no-goal,
no-goals changed to goals, goals changed because of video review, scorer changes, assist changes, scoring
corrections made during the game, during intermission, and after the game. Do not limit this to recent
seasons; determine the earliest reliable historical coverage that can be obtained from public verified
sources and document any coverage limitations.

For every discrepancy, record the game date, teams, period, game clock, initial ruling/statistic,
corrected/final ruling/statistic, reason for the discrepancy, type of correction, when the correction
occurred, whether the goal/point total changed, whether only player attribution changed, and the exact
official source supporting the entry. Preserve both the original state and corrected state so the user can
clearly see what changed. Include direct official-source links for every record and flag any record where
the evidence is incomplete, conflicting, unavailable, or cannot be independently verified rather than
filling gaps with assumptions.

The website should allow the user to review and filter the entire database by season, date, team, period,
discrepancy type, goal/no-goal change, scorer/assist correction, video review, intermission correction,
postgame correction, and whether the correction changed the actual game total. Clearly separate
discrepancies that changed the number of goals from corrections that only changed player attribution. Also
identify which discrepancies could potentially affect a game-total market or settlement after the event
initially appeared to be final. The system should continuously monitor available official NHL sources and
detect new scoring discrepancies automatically, explain what changed, and generate an alert/notification
when a potential discrepancy is detected. Clearly document what can and cannot be detected automatically,
source/feed limitations, latency, historical coverage limitations, and any cases that still require human
verification.

Put this prompt into the repo readme and read it everytime we work on the project as a starting point to
make sure we are building what we are aiming for and have a strong base to continue building and improving
on making something useful for everyday use. It should solve the problem of having to manually check
everything ourselves and have an up to date current feed.

</details>

## Working agreement (verbatim)

<details>
<summary>Click to expand — how this project is built and reviewed.</summary>

The following is taken from the Arena AI team and I think it makes a good point on building a successful
project, so let's keep the Core Values and Own the Outcome as a focal point when building, developing,
researching, suggesting upgrades, and implementing the work.

**Our Core Values**

*Maximize P(Win)* — "Maximize the Probability of Winning": our decision making framework. In every
decision, we weigh tradeoffs, assess risk, and choose the path that maximizes the probability that Arena
succeeds. We set aside our emotions and make tough decisions in order to maximize P(Win). "Maximize
P(Win)" frees us from constraints and clarifies that we must put Arena first.

*Own the Outcome* — We own results end to end — not just our individual slice of the work. When problems
arise and we have the means to act, we do so without waiting for permission or assignment. We treat failure
and success as signals and use them to improve. At Arena, we stay accountable to the final outcome.

Work line by line verifying from official verified trusted sources, provide links for manual review. There
should be no manual input, work on your own to complete tasks. Flag any irregularities for review. No
hallucinations.

Verify no hallucinations.

The goal of this project is to get a full list that follow our requirements. No hallucinations. Verify
line by line.

**Site creation** — Create a github page for this repo that has clean ui, user friendly, simple and easy to
use. It should be organized and clean. It should include all relevant information in an easy to read format
with official verified links as sources for review. Work line by line verify everything no hallucinations.

Go ahead and create a pull request and then merge the pull request onto the main. Make suggestions for what
work still needs to be done and any limitations that is in the way of a successful project. It should be
worked on in this next session or the next session. Work line by line verify everything no hallucinations.

**Run this task through multiple passes.** Pass 1: Implement the task completely and verify the result.
Pass 2: Review your work for bugs, missing requirements, incorrect assumptions, and edge cases. Fix
everything you find. Pass 3: Re-check the entire implementation against the original request. Improve
accuracy, reliability, completeness, and code quality. Fix any remaining issues. Do not stop after the first
pass. Each pass must build on the previous one. Before finishing, verify that the final result fully
satisfies the original request. Work line by line verify everything no hallucinations.

</details>

---

## How this project applies those values

* **Maximize P(Win)** — the decision that matters is *what to trust*. Anything that could not be fetched and
  cross-checked against a second official artifact is a **lead**, not a record. That is why the database is
  empty rather than plausible-looking, and why `probe` exists to fail loudly.
* **Own the outcome** — the pipeline does not stop at "detected something": it stores the evidence timeline,
  writes an alert, opens an issue, re-verifies records, and publishes the site. If a source is unreachable
  the record says so in `evidence_status` instead of quietly degrading.
* **No hallucinations** — every factual claim about the sources lives in
  [`data/reference/verified_facts.json`](data/reference/verified_facts.json) with its URL and observation; a
  claim that is not in that ledger may not appear on the site or in this README. Media reporting is confined
  to a clearly-labelled *not evidence* list.

---

## Consolidation of the parallel lines (2026-10-07, this PR)

`main` already carried a complete implementation built in parallel (`pipeline/`,
`src/nhl_monitor/`, a root-served site, 3 records verified from the NHL's own
scoring-change announcements, 108 tests). Its README said a decision was owed. Here
it is, taken without deleting either line's work:

| Question | Decision |
| --- | --- |
| Which database is canonical? | **`data/discrepancies.json`** - one file, engine schema, now **11 records**: the monitor line's 3 verified announcements (mechanically ported, losslessly - each keeps its full original object under `parallel_record`) + 1 cross-source verified historical conflict + 7 pending leads. Port command: `python3 scripts/import_parallel_records.py`. |
| What happens to `data/records/discrepancies.json`? | Left exactly as the monitor line wrote it, and it stays the root site's data source. It is now provenance for the port, not a competing database. |
| Which site is the site of record? | **`docs/`** (built by `python3 -m nhl_scoring.cli site --out docs`) - it renders all 11 records with the filters and both lines' documentation as tabs. The root site keeps working and is not modified. |
| Which scheduler runs? | The monitor line's `monitor.yml` / `backfill.yml` keep the only crons. This line's equivalents ship as `scoring-monitor.yml` (dispatch-only) and `scoring-backfill.yml` (offset weekly cron), so nothing commits to `main` twice on a timer. Flip the schedule in `scoring-monitor.yml` if the engine line becomes the single monitor. |
| Which docs win where they collided? | `docs/DATA_MODEL.md`, `docs/METHODOLOGY.md`, `docs/SOURCES.md` stayed the monitor line's, verbatim. This line's are at `docs/engine/*.md` and published as "engine" tabs. Nothing was overwritten. |
| Tests | Both suites run together: `python3 -m unittest discover -s tests -t .` -> **182 tests, 0 failures**. |

Still owed, and not decided here: whether one engine is eventually retired. The two
answer the same brief through different mechanisms (statement-ingest vs cross-source
diff + snapshots) and the ported records prove they compose - the strongest argument
for keeping the detector and the announcement feed as two inputs to one database.

### This line's additions, in one list

- `pipeline/nhl_scoring/` - fetch/cache with content hashes, parsers for **both**
  official HTML-report eras + the Game Center landing/right-rail JSON, 20 implemented
  checks (`C1`-`C17`, `C20`-`C22`; `C18`/`C19` documented as unimplementable), market
  classification, record store with validation and sticky merge, state-change-only
  snapshots, alerting, site generator, CLI.
- `tests/` - 74 offline tests over verbatim official fixtures, including a **clean
  control pair** that must produce zero findings and a regression test for the
  pairing bug that once would have manufactured phantom missing-goal records.
- `docs/FEASIBILITY.md` - the "is this even possible" analysis the brief asks for.
- `docs/STATUS.md`, `docs/engine/*`, `data/schema/discrepancy.schema.json`,
  `data/leads/README.md`, `scripts/{seed_records,verify_sources,backfill,import_parallel_records}.py`.
