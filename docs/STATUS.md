# Status

Updated 2026-10-07. This file is the honest ledger: what runs, what is seeded, what
is still open, and what will never work.

## Working now

- **Parsers** for both official HTML-report eras (legacy 2000-01..~2004 and modern
  ~2005+) and for the Game Center landing + right-rail JSON. Layout is detected per
  file, not assumed from season.
- **Three detection engines**: cross-source C10-C17, intra-source C1-C9, temporal
  C20-C22 (`C18`/`C19` are documented as reserved-but-unimplementable).
- **Record store** with validation, derived ids, sticky merge, CSV projection.
- **Snapshot digests** written only on state change; `snapfind` turns history into
  records.
- **Alerting**: triage, markdown + JSON output, webhook payload, issue title,
  Situation Room quote extraction.
- **GitHub Pages site** built from the database: filterable by season, date, team,
  period, discrepancy type, goal/no-goal, scorer/assist, video review, intermission,
  postgame, and total-changed; separate buckets for total-changing vs
  attribution-only; settlement exposure view; detection coverage view; every row with
  official links.
- **Tests**: `python3 -m unittest discover -s tests -t .` -> 182 tests with the monitor
  line's suite (74 of them here), all offline,
  including a real conflicting fixture pair and a control pair that must stay clean.
- **Verified against live data before the sandbox boundary was known**: the seed
  record was produced by reading the actual `20002001/GS020001.HTM` and
  `gamecenter/2000020001/landing`, then encoded as fixtures so CI re-verifies it.

## Consolidation with the parallel line (this PR)

`main` carried an independently built line (`src/nhl_monitor/`, root site, its own
tests and docs) that had finished **3 records verified from the NHL's own
scoring-change announcements** and left `data/discrepancies.json` empty. Its README
said a decision was owed. It is taken in the README's "Consolidation" section: one
canonical database at `data/discrepancies.json`, their file untouched as provenance,
`docs/` as the site of record, their crons as the only schedulers, their three
colliding docs preserved with mine at `docs/engine/`. The port is a script, not a
retyping: `scripts/import_parallel_records.py` maps their fields onto this schema and
keeps each original object verbatim under `parallel_record`, so a reviewer can diff
the translation. `validate()` rejects a lossy or invented port: all three came out
`verified`, with their own flags carried across
(`assists_before_the_change_not_captured`, `initial_state_reported_by_secondary_source_only`).

Combined suite: `python3 -m unittest discover -s tests -t .` -> **182 tests**
(this line 74, the monitor line 108), 0 failures.

## The database (11 records)

| Record | Status | What it is |
| --- | --- | ---|
| `SDN-87fb3e543f` | `verified` | Game 2000020001 (COL 2 @ DAL 2, OT, 2000-10-04): goal 4, P2 18:31 PP A. Deadmarsh - sheet credits 1 assist (`C. DRURY (1)`), JSON credits 2 (`Drury`, `Sakic`). Attribution-only; game total unaffected. Reproduced by running the detector on the fixtures. |
| Ohgren, CGY @ VAN 2026-10-03 | `pending_review` | Goal waived off, awarded on goal-line review, 1-0 became part of a 4-1 win. Changes period and game total. Secondary reporting quoting the league; official artifact pull is the next step. |
| Rossi, EDM @ VAN 2026-10-01 | `pending_review` | goal -> no-goal (gloved) -> goal (shoulder deflection) in one play. Three-state ruling sequence invisible in the final box score. |
| 5 x clock-drift rows | `pending_review` | Five quoted lines from a public audit log of 560 games where the official feed's goal clock was wrong. Entered as leads, one per game, with the log's own text and the official sheet links to check against. |

`data/discrepancies.csv` mirrors it. The two `pending_review` current-season records
have `game_id: null` on purpose: we did not find the id in an official source during
this session, and inventing a plausible 10-digit id would be exactly the failure this
project exists to prevent. `verification.check_instructions` states the one API call
that resolves each.

## Open work, in priority order

1. **Backfill the detector across seasons.** `backfill.yml` runs the scan in batches
   (25 games/run). 2000-01 -> present is ~18k games; at CI-friendly pacing that is
   weeks of scheduled runs, and it self-limits: coverage notes record what was not
   reached. First target is the last 5 seasons plus 2000-01..2002-03 (era coverage).
2. **Live monitor for the current season.** `monitor.yml` polls the day's scoreboard,
   snapshots each game while `LIVE`, and emits alerts. Needs a schedule; Actions'
   15-minute floor and scheduling lag means "within ~15-30 min", not real time. For
   real-time: `scripts/daemon.sh`-style loop on any always-on host
   (`snap --date <today>` + `snapfind` + `alerts --webhook`) - documented, not built
   here.
3. **Resolve the two pending ruling-change records** (game id + official artifacts),
   then promote or retire them.
3b. **Decide the site/line question for real**: the root site still renders the
   monitor line's 3-record file. Either teach `tools/build_site.py` to read the
   consolidated `data/discrepancies.json` (needs a schema adapter for their
   `site/app.js`) or retire the root UI and point Pages at `docs/`. Left undone on
   purpose rather than half-done: the port direction that matters (records) is done,
   and no renderer was broken to make a number look tidier.
4. **Own-goal `goalModifier` era check** for 2022-23+ (assert C16 can actually fire
   on a modern fixture; today it is only proven not to fire spuriously).
5. **Shootout goals** (game 2025021181-style cases): decide whether SO "goals" belong
   in the database at all - they are not counted in the game total. Currently
   unparsed by design in the sheet path; needs an explicit decision + test.
6. **Goaltender-assist edge cases** and empty-net-into-an-empty-net anomalies
   (`C3` today compares goalie GA to team goals only when the sheet lists them).
7. **Human review UI polish**: the Database view can already filter and share URLs; a
   "mark reviewed" flow would live in issues, not in the static site (Pages cannot
   write).
8. **Cross-check with a second official view**: the `es`/`pp`/`pk` sheets restate
   goals by special teams; adding C18-style "goal counted in ES sheet but not in
   scoring summary" costs one fetch per game and would catch a class we currently
   miss.

## Limitations that will not be fixed

- **No official corrections feed exists**, so nothing can be detected for games we
  never polled and where both artifacts now agree.
- **Overturned/no-goal rulings leave no trace in final data.** Pre-2007-08 there is
  also no play-by-play to infer a review delay from.
- **Correction timestamps are unobtainable.** Best available: the sheet's generation
  stamp (proven unreliable as a bound) and our own poll times.
- **No official online artifact before 1999-2000.** Pre-2000-01 = single-source,
  so cross-source checks are structurally impossible; earlier still = printed
  sources only.
- **Missing reports exist** (e.g. community-reported playoff `PL` holes for
  `20112012/PL020259`, `20102011/PL020124`, `20102011/PL020429`,
  `20092010/PL020081`) and are unverified by us: a 404 is recorded as "artifact
  unavailable", never as "no discrepancy".
- **Settlement lines are not public.** Market impact is a *class* judgement, not a
  statement about any specific bet.
- **The league can change its formats without notice.** Parser version is stamped
  into every record; `verify_sources.py` fails loudly when a documented URL stops
  returning what this file says it returns.
- **This repository's tests run offline against fixtures.** Fixture `<table>`
  scaffolding was reconstructed by hand (cell values verbatim), so a fixture can
  never prove the live page's markup shape - per-game `parse_ok` assertions in CI do
  that.
