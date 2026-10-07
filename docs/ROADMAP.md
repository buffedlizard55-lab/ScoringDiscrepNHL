# Roadmap — what still needs to be done

> **Revision 2026-10-07 (later session, after the Situation Room backfill).** The
> roadmap below was written when the database was nearly empty and framed several
> P0 items as "the database is empty until these run." That is superseded: the
> official **Situation Room statement feed** was found and ingested
> ([`SITUATION_ROOM.md`](SITUATION_ROOM.md)), and the database now holds **1,470
> records** — 1,465 goal-count-changing video-review overturns (2016-02 onward),
> 4 attribution-only, 1 total-change-unknown. The blocker is no longer *populating*
> the database; it is the historical-coverage and post-final-change-detection work
> below. P0 items 1–2 are therefore largely closed (the pipeline ran on the GitHub
> Actions runner and committed real records); what genuinely remains open is marked
> **[still open]** inline. The list is kept in full because the remaining items are
> still the right next steps.

**Done since the first draft (2026-10-07, pass 3):** the earliest serving season is answered (**2000-01**;
1999-2000 is a 404) and its reports are frozen; the frozen/regenerated behaviour is established for seven
seasons; ~~the database is no longer empty — three records were built through the announcement-ingest path and
verified against official reports~~ **the database holds 1,470 records** (Situation Room backfill + the
announcement-ingest records); announcement latency is measured; the site and CI gained a headless
rendering test of the real database. Items 1, 6 and 13 below are therefore partially or wholly closed —
what remains is that the *pipeline* must run on a networked machine, not that it is unknown how to run it.

Ordered by how much each item blocks the stated goal ("a full, continuously-updated list that nobody has to
check by hand"). Effort is a rough estimate for one focused session.

## P0 — the database is empty until these run

> **[mostly closed 2026-10-07]** The Situation Room backfill populated the
> database (1,470 records) on the runner. Items 1–2 below are retained for the
> *historical census* (cross-source diff over old frozen reports), which is a
> coverage enhancement, not a prerequisite for a non-empty database.

| # | Task | Why | How | Effort |
|---|---|---|---|---|
| 1 | Run `python -m nhl_monitor probe` on a networked machine | proves the sources AND that the parser understands the live report layout; everything downstream depends on it | `PYTHONPATH=src python -m nhl_monitor probe` (also runs, non-blocking, in `tests.yml`) | minutes |
| 2 | First backfill slice | the announcement path is proven (3 records); the frozen-era census path has never run against live sources | `backfill-era --season 20052006 --start 1 --end 200` via `backfill.yml`, then review each produced record against its two links | 1 session |
| 3 | Label creation + workflow permissions | `gh issue create` fails without the labels/permissions, so alerts would be written to disk but nobody would be told | Settings → Actions → Read/write; create labels `scoring-discrepancy`, `auto-detected` | minutes |
| 4 | Confirm Pages deployment | the site must actually publish | Settings → Pages → Source: GitHub Actions, then run `pages.yml` | minutes |

## P1 — completeness and trust

| # | Task | Why | Notes |
|---|---|---|---|
| 5 | ~~Bracket the frozen→regenerated transition season~~ **DONE, and the premise was wrong** | the measured table (F18) shows the two behaviours INTERLEAVE across 28 seasons, so there is no transition season to bracket | the per-season table in `data/reference/coverage_report.json` is what the backfill must read |
| 6 | ~~Determine the earliest serving season~~ **DONE** | answered by retrieval: **2000-01** (`19992000` → 404, `20002001` → 200, frozen footer) | recorded as F13; the `coverage` job re-measures it per season on a runner |
| 7 | Player id resolution for frozen-era documents | frozen documents have sweater numbers + surnames but no ids, so a name→id map is needed to compare them with the API reliably | use the API roster for that season; **must refuse to guess on ambiguity** and flag instead |
| 8 | Full-season backfill with resumability | tens of thousands of fetches; needs a checkpoint so a rate-limited run resumes instead of restarting | store per-game progress; back off on 429 |
| 9 | Latency instrumentation | "when did the official record say X" should be a measurement, not an assertion | the evidence timeline already stores `retrieved_at_utc`; add a report of observed lag between the game clock and the first capture showing each goal |

## P2 — coverage of the modern era

| # | Task | Why | Notes |
|---|---|---|---|
| 10 | Archive census over a season's worth of reports | the method is now complete end to end (`archive-scan` compares the captures it proves; `archive-yield` measures the ceiling) and the remaining work is scale: one CDX query per document, ~1,300 documents per season | run `backfill.yml` with `method=change-scan` season by season; `method=archive-yield` says how much of each season is reachable at all |
| 11 | Snapshot-bracket heuristics | a snapshot taken after a correction is useless; prefer snapshots close to the game | use CDX `from`/`to` windows around the game date and prefer the earliest usable snapshot |
| 12 | Post-final change watch | the highest-value alert class is a change *after* the record was final (settlement exposure) | the monitor already classifies this; add a dedicated, higher-severity notification path and a "changed after final" filter on the site |

## P3 — reason and verification quality

| # | Task | Why | Notes |
|---|---|---|---|
| 13 | ~~Look for an official written source of corrections~~ **DONE** | `reason.text` is now filled from the league's own announcements for every ingested record | the posts were retrieved and parsed; the open part is *automatic* retrieval on a runner (see P1-17) |
| 14 | Verify the four secondary leads | they are the only concrete candidate discrepancies mentioned in the repo | L01 the 2026 playoff goal credit change (Samuelsson → Greenway), L02 the own-goal tracking claim, L03 two Flyers-Sabres assist corrections, L04 a Bruins-Hurricanes assist correction; each must be confirmed from official artifacts or dropped |
| 15 | Scheduled `verify` sweep | records must not rot | run `verify` over old records; if the official record moved again, append a new revision rather than editing |
| 16 | Human review queue UI | the brief allows for "still requires human verification" | a page listing records with `needs_manual_review` / `conflicting`, with the exact links to open |

## P4 — nice to have

* CSV/JSON export buttons on the site (the CSV export exists in the CLI; the site can link to
  `data/exports/discrepancies.csv`).
* Per-team and per-season summary views (which clubs' records get corrected most).
* An "own goal" annotation view once the own-goal semantics are verified from an official source.
* A settlement-timeline view: for each change, the wall-clock time of each capture relative to typical
  publication times, to make the "was this already graded?" question easier to answer.

## Known blockers, plainly

1. ~~**No networked machine has run the collector yet.** The build sandbox is network-isolated from NHL hosts
   (evidence committed). Until items 1-2 run, the database has no rows — by design, not by oversight.~~
   **Superseded 2026-10-07:** the GitHub Actions runner ran the Situation Room ingest and committed 1,470
   records. The sandbox is still network-isolated from NHL hosts (evidence committed), so the *historical*
   cross-source census still needs a networked machine to reach full coverage.
2. ~~**No machine-readable Situation Room feed exists**, so "reason" can never be fully automated.~~
   **Corrected 2026-10-07:** it exists (content API, tag `situation-room`, every challenge and video review
   since 2016-02) and is ingested; see `docs/SITUATION_ROOM.md`. What stays permanent: no official feed
   states the reason for a **scorer / assist** change.
3. **The modern era's original bytes are gone** once a document is regenerated, so the archive census will
   always under-count changes that were made before the first snapshot.

## P1 (new in pass 3) — the announcement channel

| # | Task | Why | Notes |
|---|---|---|---|
| 17 | Automate retrieval of the league's scoring-change announcements | it is the sharpest signal that exists: it names game, period, clock, scorer and assists, and it arrives 2h49m–3h25m after the final buzzer | the posts were read here through the platform's page-fetch tool. A runner needs either a paid X API tier or a documented, rate-limited fetch; neither has been exercised from this repository yet |
| 18 | Prefer, but never require, a pre-change official artifact | two of three shipped records can only say "reported by a secondary source" for the superseded credit | a CDX search for a snapshot *before* the announcement date is the mechanism; the one snapshot found for game 1238 post-dates the correction |
| 19 | Prove or disprove the *post-final* goal-count class | ~~all three records are attribution-only, so the highest-value class (a goal added or removed after the record was final) has no example~~ — still true for the **post-final** class specifically: the 1,465 goal-count-changing records are all in-game video-review overturns, none is a goal added/removed *after* publication | a season-wide snapshot census is the only honest way; treat "not found" as a result to report, not a failure |
| 20 | Add a latency column to the site and the export | the measured 2h49m–3h25m is a concrete answer to "what latency can a user expect", but it is currently only inside the record JSON | `timing.latency_after_final_buzzer_seconds` is already stored per record |
| 11 | Start the CI census runs | `gh workflow run` returns HTTP 403 from the agent token (cannot write to Actions), so the measured sweeps must be started from the Actions tab | repository admin dispatches `backfill.yml` with `method=archive-yield` and `method=change-scan`, then `method=era`
