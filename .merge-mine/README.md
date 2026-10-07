# NHL Scoring Discrepancy Research

**Standing brief for every session. Read this file before touching anything else.
It is not allowed to be summarized away, truncated, or replaced by hope.**

Purpose in one sentence: a continuously updateable database of NHL scoring
discrepancies and corrections, taken from official NHL sources, with a filterable
website on top and an alerting layer that finds new ones - plus an honest account of
what that cannot include.

## Core Values

**1. Maximize P(Win).** Every choice is judged by whether it makes the final result
more likely to be correct, complete and usable - not by whether it looks like
progress. If a shortcut produces a database with plausible-looking rows, the
shortcut loses, and the shortcut is what gets taken unless the process forbids it.
Here that means: a record is only as good as the official link that survives a
click, and a check is only as good as the fixture that proves it fires *and* proves
it stays quiet on clean data.

**2. Own the Outcome.** No "the API didn't provide it", no "the parser would need a
change", no handing back a half-built thing with a README saying TODO. The outcome
is a working pipeline, a database with real verified rows, a live site, alerting
that fires, and a list of limitations that is *true*. Gaps are owned explicitly:
flagged in the data, stated in STATUS.md, never smoothed over.

## The brief

### 1. Database of discrepancies and corrections

Continuously updateable, built from official NHL sources. Must cover:

- goals changed to no-goals, and no-goals changed to goals
- goals added or removed by video review
- scorer-of-record changes
- assist changes (added, removed, moved between players)
- in-game, intermission, and post-game corrections

Each record must carry: game date, teams, period, game clock, initial ruling,
corrected/final ruling, reason for the change, type of correction, when the
correction occurred, whether the goal/point total changed, whether only attribution
changed, and the exact official source link.

Both the original state and the corrected state are preserved. Where evidence is
incomplete, conflicting, unavailable or unverifiable, the record is **flagged**, not
guessed. Earliest reliable historical coverage must be determined and its limitations
documented (see docs/FEASIBILITY.md and docs/SOURCES.md).

### 2. Website

GitHub Pages. Clean, simple, easy to use, well organized, all relevant information
with official verified source links on every row. Filterable by season, date, team,
period, discrepancy type, goal/no-goal change, scorer correction, assist
correction, video review, intermission correction, postgame correction, and whether
the goal total changed. Total-changing and attribution-only records are kept
separate. Records that could touch a game total or a settlement outcome are flagged.

### 3. Detection and alerting

A system that identifies potential scoring discrepancies and corrections as they
appear, with explicit analysis of the limitations and of whether this is even
possible. The analysis is a deliverable, not a disclaimer (docs/FEASIBILITY.md).

### 4. Delivery

Open a PR, then merge to main. List remaining work and limitations.

### 5. Method

Work line by line, verified against official trusted sources, with links a human can
click. No manual input from the project owner - finish it autonomously. No
hallucinations: verify, and flag any irregularity for review instead of asserting
it. Do not stop after the first pass: pass 1 implements and verifies, pass 2 hunts
bugs and edge cases, pass 3 re-reads the result against this brief. Each pass builds
on the last, and the final result is checked against the original request before it
is called done. The goal is the full list meeting the requirements, not a demo.

## Repository map

| Path | What it is |
| --- | --- |
| `pipeline/nhl_scoring/` | the engine: `fetch`, `parsers`, `models`, `checks`, `market`, `db`, `snapshot`, `alerts`, `site`, `cli`, `sources` |
| `data/discrepancies.json` | **the database** (single source of truth, schema-validated) |
| `data/discrepancies.csv` | generated flat projection of the same rows |
| `data/schema/discrepancy.schema.json` | the record contract, declarative |
| `data/snapshots/` | git-tracked state-change digests - the audit trail |
| `data/alerts/` | rendered alert digests per day |
| `docs/` | the published site (`index.html`, `data.js`, `app.js`) + the four analysis docs |
| `tests/` | 74 offline tests over verbatim official fixtures |
| `scripts/` | `seed_records.py`, `verify_sources.py`, backfill helpers |
| `.github/workflows/` | `monitor.yml` (poll + alert), `backfill.yml` (grow the DB), `pages.yml` (publish) |

## Run it

```bash
python3 -m unittest discover -s tests -t .                              # 74 tests, no network
PYTHONPATH=pipeline python3 -m nhl_scoring.cli scan \
    --games "2000020001,2000030162" --fixtures tests/fixtures --out out/findings.json
PYTHONPATH=pipeline python3 -m nhl_scoring.cli validate
PYTHONPATH=pipeline python3 -m nhl_scoring.cli site --out docs
python3 scripts/verify_sources.py                                       # re-check source claims
```

Python 3.9+, standard library only - no install step, no dependencies to drift.

## Where the truth lives

- [docs/FEASIBILITY.md](docs/FEASIBILITY.md) - what is and is not detectable, and why
- [docs/SOURCES.md](docs/SOURCES.md) - every source, its status code, its limits
- [docs/DATA_MODEL.md](docs/DATA_MODEL.md) - record contract, statuses, flags
- [docs/METHODOLOGY.md](docs/METHODOLOGY.md) - pipeline, pairing, era handling
- [docs/STATUS.md](docs/STATUS.md) - working / open / never-going-to-work
