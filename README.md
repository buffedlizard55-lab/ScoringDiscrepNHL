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

> **Status, stated plainly (2026-10-07, after the first full Situation Room backfill).** The league publishes
> an official **Situation Room statement for every Coach's Challenge and video review** (NHL content API,
> tag `situation-room`, February 2016 → today, minutes after the play). This repository now ingests that
> feed end to end: **4,406 statements** are in the ledger
> ([`data/situation_room/rulings.json`](data/situation_room/rulings.json)); **1,471 are rulings that changed
> the on-ice call** (goal→no goal or no goal→goal), 1,915 upheld the call, 902 give the result but not the
> on-ice call (kept, no change inferred), 98 are not goal reviews at all (officiating-crew updates,
> penalty-only challenges, non-reviewable plays) and 20 could not be classified by machine (flagged). Every changed call with a resolvable game id was
> cross-checked against the official play-by-play: **1,396 agree, 55 inconclusive, 12 conflict, 12 not
> checked** - the conflicts and inconclusives are *flagged*, not hidden.
>
> The database ([`data/discrepancies.json`](data/discrepancies.json)) holds **1,470 records**: 1,449 live
> Situation Room records (**1,396 verified** by statement + play-by-play agreement, 53 flagged for a human;
> two of them carry their on-ice call from a documented human read of the official NHL.com recap), 3 verified
> scorer/assist corrections from official scoring-change announcements, 1 single-artifact assist conflict,
> and **17 retired** rows (records a parser correction no longer supports - kept, marked, never
> silently deleted). Five third-party goal-clock leads were moved out of the database to
> [`data/leads/third_party_clock_claims.json`](data/leads/third_party_clock_claims.json) because no official
> source states a correction. `PYTHONPATH=pipeline python3 -m nhl_scoring.cli validate` → **1,470 records,
> 0 invalid**; `python3 -m unittest discover -s tests -t .` → **304 tests OK**; `node tools/check_engine_site.mjs`
> runs the published client against the committed payload and passes.
>
> **What is live.** One site at the repository root (GitHub Pages: `main`, `/`): Database (filters for season,
> date, team, period, type, goal-count vs attribution-only, video review, when corrected, market impact),
> Situation Room log (all 4,406 statements, grouped review types, PBP cross-check column), Alerts
> ([`data/alerts.json`](data/alerts.json) + [`data/alerts.xml`](data/alerts.xml), bounded to the last 14 days
> of games so a backfill cannot flood subscribers), Market view, Coverage, Monitor, and every document in
> `docs/`. [`situation-room.yml`](.github/workflows/situation-room.yml) polls the feed twice an hour on `main`
> (cron on GitHub Actions is best-effort - measured, see fact F32) and commits ledger, database, alerts and site.
>
> **What is notified.** Detection alone was not enough: the feed updated and nobody was told. Every detection
> workflow now ends with `nhl_scoring.cli notify`, which delivers over four channels - the committed feed + RSS,
> a GitHub issue (one per goal-total change, one digest for attribution-only, capped per run), a webhook
> (Slack/Discord-shaped), and an e-mail digest - deduplicated by a committed fingerprint per alert
> ([`data/notifications_state.json`](data/notifications_state.json)) so a run that finds nothing new sends
> nothing, and reporting every delivery to
> [`data/notifications/`](data/notifications/) so an outage is visible in git. It has been proven against the
> real GitHub API: [issue #18](https://github.com/buffedlizard55-lab/ScoringDiscrepNHL/issues/18), HTTP 201,
> 2026-10-07T21:25:51Z. Webhook and e-mail are implemented and unit-tested but off until their secrets exist.
> The full account - channels, latency, failure modes, what can never be notified - is
> [`docs/NOTIFICATIONS.md`](docs/NOTIFICATIONS.md).
>
> **What this is not, yet.** Scorer/assist-only corrections still come only from the league's scoring-change
> announcements (3 records); pre-2016 reviews have no statement feed (documented limit); 902 statements state
> the result without the on-ice call and become records only through a *documented* human read
> ([`data/curation/situation_room_human_reads.json`](data/curation/situation_room_human_reads.json)); the
> ledger has been re-read in full by parser 0.5.0 (raw statement text captured for every row, so later parser
> fixes replay offline without re-fetching); 12 play-by-play conflicts, 55 inconclusives and 12 statements not
> yet cross-checked (3 without a resolvable game id) are waiting for a human. Open items are listed at the end of this file and in
> [`docs/STATUS.md`](docs/STATUS.md).

---

## Contents

- [What is verified today](#what-is-verified-today)
- [How it works](#how-it-works)
- [Quickstart](#quickstart)
- [Populating the database](#populating-the-database)
- [The website](#the-website)
- [Data model](#data-model)
- [What can and cannot be detected automatically](#what-can-and-cannot-be-detected-automatically)
- [Notifications: getting told instead of checking](#notifications-getting-told-instead-of-checking)
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
| ~~An official payload can still show the **superseded** credit.~~ **WITHDRAWN on re-verification.** | The claim was that event 146 of game 1140 carried an English clip title reading `meier-…` and a French one reading `mercer-…`. Re-fetched 2026-10-07, the payload reads `njd-chi-meier-scores-ppg-…-6370610304112` and `njd-chi-meier-marque-un-but-en-a-n-contre-spencer-knight-6370610205112` — **both "meier"**, and a different French clip id than was recorded. The corroboration is withdrawn (F17 amended, F22 records the pass, transcript at [`data/evidence/reverify-2026-10-07/gamecenter-2024021140-event146.txt`](data/evidence/reverify-2026-10-07/gamecenter-2024021140-event146.txt)). Root cause: a paraphrase was stored instead of the payload, so the claim was never auditable. |
| The Wayback CDX index exposes a content **digest per snapshot**. | One snapshot for `20232024/GS020001.HTM` (digest `TE24NPUUMSEV3LQEBNQE2TN3NO5GNATJ`), so "did this document ever change?" is answerable without downloading every version. |
| Archive coverage is sparse and noisy. | 2006-era captures of 2005-06 reports are HTTP 302 redirects with the empty digest `3I42H3S6NNFQ2MSVX7XZKYAYSCX5QBYJ`; these are rejected as evidence. |
| A **negative control** passed. | The archived copy of `20232024/GS020001.HTM` (2025-01-25) has the same eight-goal scoring summary and the same footer as the live document, so the method produced no false positive on that game — and it proves a regenerated footer is *not* by itself a change. |
| ~~No machine-readable Situation Room / video-review feed was located.~~ **Corrected 2026-10-07:** the league publishes an official statement for every challenge and video review. | `forge-dapi.d3.nhle.com/v2/content/en-us/stories?tags.slug=situation-room` - ~4,400 statements, 2016-02 to today, with `gameid-` tags; the play-by-play marks reviews as `chlg-*` / `video-review` stoppages. Ingested by `pipeline/nhl_scoring/situation_room.py`; evidence in `docs/SITUATION_ROOM.md` and facts F30-F32. The earlier claim was measured on a single game that had no review. |

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

PYTHONPATH=pipeline python -m nhl_scoring.cli notify --describe    # which notification channels are on
PYTHONPATH=pipeline python -m nhl_scoring.cli notify --dry-run     # what would be sent, sending nothing

python3 -m unittest discover -s tests -t .       # 304 tests (engine + monitor lines)
python3 -m nhl_scoring.cli site && python3 -m http.server 8080   # rebuild + serve the live site at the repo root
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
| [`ci.yml`](.github/workflows/ci.yml) | every push / PR | the full combined suite, validates the database under **both** contracts, rebuilds the site and asserts it is byte-identical to the committed one, smoke-tests the published client against the real payload (`tools/check_engine_site.mjs`), and checks the alert feed |
| [`situation-room.yml`](.github/workflows/situation-room.yml) | twice hourly (`:11`,`:41`) + dispatch + a committed request file | **the primary alert path**: ingests the official Situation Room statement feed, cross-checks overturned calls against the play-by-play, **delivers notifications**, and commits ledger + database + alerts + rebuilt site |
| [`monitor.yml`](.github/workflows/monitor.yml) | every 5 minutes | the monitor line's live slate capture: diffs captured states, ports new records into the canonical database, then delivers anything new through the same deduplicated notification path |
| [`backfill.yml`](.github/workflows/backfill.yml) | manual | walks a season/game range with either census method, scans the archive for provable changes, ports records, rebuilds the published site, delivers alerts, and commits the results |
| [`scoring-monitor.yml`](.github/workflows/scoring-monitor.yml) · [`scoring-backfill.yml`](.github/workflows/scoring-backfill.yml) · [`scoring-ci.yml`](.github/workflows/scoring-ci.yml) | dispatch / weekly offset / push | the engine line's monitor, backfill and CI, kept off the monitor line's timers so nothing commits to `main` twice |
| [`tests.yml`](.github/workflows/tests.yml) | every push | the suite (304 tests, including the 41 delivery tests), a browser-less site smoke test, JS syntax check, site build, record-schema validation, source reachability probe (which also measures per-season coverage on the runner) |
| ~~`pages.yml`~~ | — | **disabled**: Pages is a legacy build of `main` at `/`, so the commit *is* the deploy |

GitHub Actions is the right home for this because a runner has unrestricted outbound network access, a
scheduler, durable storage (git history) and a notification channel (issues) — none of which the build
sandbox had. Every one of those workflows ends with the same `notify` step, so there is exactly one delivery
path and one deduplication state.

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

* **The reason for a scorer / assist change** — there is no official feed for those, so it is only recorded
  when an official artifact says so in words; everything else keeps `reason.text = null` plus a flag. (The
  reason for a *review* decision **is** available: the Situation Room statement feed, see
  `docs/SITUATION_ROOM.md`.)
* **A change that happened and was superseded between two of our polls**, when no archive snapshot exists
  from before the change. The archive method cannot see it either if every snapshot postdates the correction.
* **Whether a bookmaker regraded anything** — house rules are private.
* **Reviews before February 2016** — the statement feed starts there. Scoring *differences* still reach back
  to 2000-01 through the frozen-era census; review *rulings* do not.
* **Anything before 2000-01** — measured: `19992000/GS020001.HTM` → 404, `20002001/GS020001.HTM` → 200.

Full detail, including latency and coverage limits: [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md).

## Notifications: getting told instead of checking

The brief asks for an alert *and* a notification, plus an honest account of whether that is even possible.
Both halves are written down: the analysis in [`docs/ALERTING.md`](docs/ALERTING.md) and
[`docs/FEASIBILITY.md`](docs/FEASIBILITY.md), the operation in
[`docs/NOTIFICATIONS.md`](docs/NOTIFICATIONS.md). The short version:

| | |
|---|---|
| **Detect** | the league publishes an official statement for every challenge and video review, minutes after the play; 4,406 are ingested, 1,471 of them changed the on-ice call, 1,465 became records |
| **Deliver** | `nhl_scoring.cli notify` — feed/RSS (always on), GitHub issue (on in Actions), webhook and e-mail (off until secrets exist). Deliver-once per alert, one issue per goal-total change, a digest for the rest, a committed report per run |
| **Proven** | [issue #18](https://github.com/buffedlizard55-lab/ScoringDiscrepNHL/issues/18), HTTP 201, 2026-10-07T21:25:51Z; 40 offline tests assert on the wire (URL, headers, payload, dedupe, retry-after-401, workflow wiring) |
| **Impossible** | why a *scoring credit* changed (no official corrections feed — probed 404), a correction made and overwritten between two polls, pre-2016 review rulings, and whether any bookmaker regraded a market |

```bash
PYTHONPATH=pipeline python3 -m nhl_scoring.cli notify --describe   # the channel table, as the site renders it
PYTHONPATH=pipeline python3 -m nhl_scoring.cli notify --dry-run    # what would be sent, sending nothing
```

Subscribe without touching code: watch the repository (Custom → Issues), or point a reader at
[`data/alerts.xml`](data/alerts.xml), or add the `SDN_WEBHOOK_URL` / `SDN_SMTP_*` secrets.

## Repository layout

```
src/nhl_monitor/     sources.py fetch.py parse.py state.py classify.py detect.py archive.py store.py
                     ingest.py alerts.py cli.py   (standard library only)
site/                index.html app.js styles.css   (static, GitHub Pages)
data/                discrepancies.json (canonical)  situation_room/rulings.json (4,406 statements)
                     alerts.json + alerts.xml (the feed subscribers read)  alerts/ notifications/
                     notifications_state.json (deliver-once fingerprints)
                     records/discrepancies.json  inbox/statements/  reference/verified_facts.json
                     taxonomy.json  schema/observed_vocabulary.json  games/ evidence/ exports/
tests/               304 unittest cases (engine + monitor lines) + provenance-documented fixtures
index.html app.js styles.css data.js   the published site (Pages serves the repository root)
tools/               build_site.py (legacy _site build) + check_engine_site.mjs / check_site.mjs
docs/                NOTIFICATIONS.md ALERTING.md FEASIBILITY.md SITUATION_ROOM.md LIMITATIONS.md
                     STATUS.md ROADMAP.md DATA_MODEL.md METHODOLOGY.md SOURCES.md OPERATIONS.md
                     VERIFICATION_LOG.md  engine/  evidence/
.github/workflows/   ci.yml tests.yml scoring-ci.yml situation-room.yml monitor.yml backfill.yml
                     scoring-monitor.yml scoring-backfill.yml
```

## Open items for the next session

> **Revised 2026-10-07, twice.** First after the Situation Room backfill (the database
> is no longer "three records": 1,470 records, 1,465 of them goal-count-changing in-game
> overturns), and again in the notification pass, which is what items 1-4 below are.

1. **Publish a measured end-to-end latency.** The league's statement appears minutes
   after the play (three samples measured), but "how late do *we* see it" is still
   bounded by the cron slot rather than measured. Every record stores the statement's
   `content_date` and our `detected_at`, so this is a report away once a week of
   scheduled runs exists. Until then no latency figure is quoted anywhere.
2. **Prove the webhook and e-mail channels against real endpoints.** Both are
   implemented and unit-tested with injected transports; only the GitHub issue channel
   has been proven live. Turning either on is a secret, not a change - and the first
   real run should be checked against `data/notifications/last_run.json`.
3. **Run the frozen-era cross-source census at scale, and hunt for a post-final
   goal-count change.** The Situation Room feed covers 2016-02 onward, so the census is
   now a *historical-coverage and post-final-detection* task, not initial population.
   A goal added or removed **after the game was final** is the only class that can move
   a settled market and it is still unobserved at 1,470 records - unobserved, not
   disproved. `backfill-era --season 20052006 --start 1 --end 200` via `backfill.yml`;
   expect the first slice to be the slowest (markup drift, missing games, archive
   redirects all surface at once).
4. **Route notifications by team, market or severity.** A subscriber who cares about
   one club, or only about goal totals, currently gets everything. The feed already
   carries `teams`, `settlement_window` and `affects_goal_total`; `notify` needs the
   filters.
5. **Turn the announcement watch into a scheduled job.** The league's scoring-change
   posts are the sharpest signal that exists for attribution corrections (they name the
   game, period, clock and new credit, and arrive 2h49m-3h25m after the final buzzer),
   and there is still no supported API for them.
6. **Fill or remove `evidence_status`.** The schema and `docs/DATA_MODEL.md` describe
   it; **all 1,470 records leave it null**, with the same information living in
   `status` + `flags`. Either derive it and enforce it in `validate()`, or delete it -
   a documented field that nothing populates is a lie about the model.
7. **Retire the third alerting implementation.** `pipeline/alerts.py` still carries its
   own issue queue and its own notify state beside the delivery layer. Two states is
   how a duplicate notification eventually happens.
8. **Recover pre-change states from the archive** where a frozen or early snapshot
   exists, which upgrades a record from "superseded credit is secondary" to two
   official states.
9. **Verify the four secondary leads** (L01-L04 in
   [`data/reference/verified_facts.json`](data/reference/verified_facts.json)) or drop
   them; none may become a record without an official artifact.
10. **Player-id resolution for HTML reports** - frozen documents carry sweater numbers
    and surnames but no ids, so name→id matching must go through the season's roster
    and must refuse to guess on ambiguity.
11. **Decide how to treat a 1-4 day report rebuild.** Footers 1-4 days after the game
    (2003-04, 2012-13..2014-15, 2020-21, 2026-27) are neither a game-night record nor a
    late batch rebuild and may already contain corrections; whether they deserve their
    own, weaker evidence class is an open design question.

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
  cross-checked against a second official artifact is a **lead**, not a record; that is why 5 third-party
  goal-clock claims sit in `data/leads/` instead of the database, why 53 records are `flagged` rather than
  smoothed into `verified`, and why `probe` exists to fail loudly.
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
| Which database is canonical? | **`data/discrepancies.json`** - one file, engine schema (1,470 records after the 0.5.0 re-read; it started as 11, and stood at 1,469 after the first Situation Room backfill): the monitor line's 3 verified announcements (mechanically ported, losslessly - each keeps its full original object under `parallel_record`) + 1 cross-source verified historical conflict + 7 pending leads. Port command: `python3 scripts/import_parallel_records.py`. |
| What happens to `data/records/discrepancies.json`? | Left exactly as the monitor line wrote it. It is provenance for the port, not a competing database, and no published page reads it any more. |
| Which site is the site of record? | **The repository root** (`index.html`, `app.js`, `styles.css`, `data.js`), built by `PYTHONPATH=pipeline python3 -m nhl_scoring.cli site`. GitHub Pages serves `main` at `/`. The former `docs/` build and the legacy root client were removed (2026-10-07); `docs/` holds documentation only. |
| Which scheduler runs? | `situation-room.yml` (feed poll, twice hourly) plus the monitor line's `monitor.yml` / `backfill.yml` crons. This line's equivalents ship as `scoring-monitor.yml` (dispatch-only) and `scoring-backfill.yml` (offset weekly cron), so nothing commits to `main` twice on a timer. Flip the schedule in `scoring-monitor.yml` if the engine line becomes the single monitor. |
| Which docs win where they collided? | `docs/DATA_MODEL.md`, `docs/METHODOLOGY.md`, `docs/SOURCES.md` stayed the monitor line's, verbatim. This line's are at `docs/engine/*.md` and published as "engine" tabs. Nothing was overwritten. |
| Tests | Both suites run together: `python3 -m unittest discover -s tests -t .` -> 182 tests at consolidation, 260 after the Situation Room line's suite, **304 today** (41 of them the notification-delivery suite), 0 failures. |

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
