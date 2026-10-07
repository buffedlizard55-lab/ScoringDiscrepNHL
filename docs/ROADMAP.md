# Roadmap — what still needs to be done

Ordered by how much each item blocks the stated goal ("a full, continuously-updated list that nobody has to
check by hand"). Effort is a rough estimate for one focused session.

## P0 — the database is empty until these run

| # | Task | Why | How | Effort |
|---|---|---|---|---|
| 1 | Run `python -m nhl_monitor probe` on a networked machine | proves the sources AND that the parser understands the live report layout; everything downstream depends on it | `PYTHONPATH=src python -m nhl_monitor probe` (also runs, non-blocking, in `tests.yml`) | minutes |
| 2 | First backfill slice | this is the moment the database stops being empty | `backfill-era --season 20052006 --start 1 --end 200` via `backfill.yml`, then review each produced record against its two links | 1 session |
| 3 | Label creation + workflow permissions | `gh issue create` fails without the labels/permissions, so alerts would be written to disk but nobody would be told | Settings → Actions → Read/write; create labels `scoring-discrepancy`, `auto-detected` | minutes |
| 4 | Confirm Pages deployment | the site must actually publish | Settings → Pages → Source: GitHub Actions, then run `pages.yml` | minutes |

## P1 — completeness and trust

| # | Task | Why | Notes |
|---|---|---|---|
| 5 | Bracket the frozen→regenerated transition season | the census method for history depends on it; today only known to lie between 2016-17 and 2023-24 | scan `GS020001.HTM` footers for a handful of seasons; cheap |
| 6 | Determine the earliest serving season | the brief explicitly asks for the earliest reliable historical coverage | probe `GS020001.HTM` per season folder downward from 2005-06; record results in the ledger |
| 7 | Player id resolution for frozen-era documents | frozen documents have sweater numbers + surnames but no ids, so a name→id map is needed to compare them with the API reliably | use the API roster for that season; **must refuse to guess on ambiguity** and flag instead |
| 8 | Full-season backfill with resumability | tens of thousands of fetches; needs a checkpoint so a rate-limited run resumes instead of restarting | store per-game progress; back off on 429 |
| 9 | Latency instrumentation | "when did the official record say X" should be a measurement, not an assertion | the evidence timeline already stores `retrieved_at_utc`; add a report of observed lag between the game clock and the first capture showing each goal |

## P2 — coverage of the modern era

| # | Task | Why | Notes |
|---|---|---|---|
| 10 | Archive census over a season's worth of reports | the only method for the modern era; today it is implemented but unexercised at scale | `backfill-archive` per game, one CDX query each, politely throttled |
| 11 | Snapshot-bracket heuristics | a snapshot taken after a correction is useless; prefer snapshots close to the game | use CDX `from`/`to` windows around the game date and prefer the earliest usable snapshot |
| 12 | Post-final change watch | the highest-value alert class is a change *after* the record was final (settlement exposure) | the monitor already classifies this; add a dedicated, higher-severity notification path and a "changed after final" filter on the site |

## P3 — reason and verification quality

| # | Task | Why | Notes |
|---|---|---|---|
| 13 | Look for an official written source of corrections | `reason.text` is empty today by design | check league newsroom items, in-document notes, and whether any report family ever carries a scoring-change note; only a primary source may fill the field |
| 14 | Verify the two secondary leads | they are the only concrete candidate discrepancies mentioned in the repo | a 2026 playoff goal credit change (Samuelsson → Greenway) and the own-goal tracking claim; both must be confirmed from official artifacts or dropped |
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

1. **No networked machine has run the collector yet.** The build sandbox is network-isolated from NHL hosts
   (evidence committed). Until items 1-2 run, the database has no rows — by design, not by oversight.
2. **No machine-readable Situation Room feed exists**, so "reason" can never be fully automated. This is a
   permanent limitation of the sources, not a bug to fix.
3. **The modern era's original bytes are gone** once a document is regenerated, so the archive census will
   always under-count changes that were made before the first snapshot.
