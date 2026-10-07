# Historical backfill: how corrections that happened before monitoring are found

The live monitor can only see a correction while it is happening. Everything older has
to be recovered from artifacts that already exist, and the league publishes no revision
history: the official report for a game is **overwritten in place**, so the document at
its URL today is not necessarily what it said at any earlier time.

Two mechanisms exist because there are two ways the original record can still be
recovered. Neither is a complete census, and this document says exactly where each one
stops.

## Method 1 — frozen document vs the current database (`backfill-era`)

For seasons where the official Game Summary was generated on game night, the live
document **is** the original record, and the league's current GameCenter data is the
current record. Any difference between them is a correction.

* `python -m nhl_monitor backfill-era --season 20052006 --start 1 --end 200`
* per game: the Game Summary is parsed, its footer decides frozen vs regenerated
  (`report_era`), and only frozen documents are compared with the API state.
* a regenerated document is **skipped with a reason**, never silently treated as an
  original. This matters because the frozen/regenerated split is not chronological: the
  measured table in `data/reference/coverage_report.json` (fact F18) shows the two
  behaviours interleaved across 28 seasons, so a cut-off year would be wrong.
* comparison is by player **name**: the 2000s HTML reports carry no player ids. A name
  change is therefore not distinguishable from a different player with the same name.

## Method 2 — two archived captures of the same document (`backfill-archive`, `archive-scan`)

The Internet Archive records a content digest per capture, so "did this document ever
change?" is answerable for one CDX query per document, without downloading anything.

* `python -m nhl_monitor backfill-archive --game-id 2023020001` — one document.
* `python -m nhl_monitor archive-scan --season 20242025 --start 1 --end 60 --out ...` —
  a game range; every document whose content provably changed is downloaded and
  compared, the rest are reported by verdict.

The comparison downloads the capture *before* the change and the capture *after* it,
parses both with the same Game Summary parser and hands the pair to the same record
builder the live monitor uses (`src/nhl_monitor/backfill.py`). One parser, one
classifier, one record builder for both paths, so they cannot drift apart.

What a proven change means, and what it does not:

| Question | Answer |
| --- | --- |
| Which state is the original? | Decided by the **content comparison**, never by capture order. A document can be rewritten twice. |
| When did the correction happen? | Unknown. It is bracketed: the older content demonstrably existed at T1 and the newer at T2. The record carries the bracket, flags `correction_time_bounded_not_known`, and labels timing `postgame` with `heuristic` confidence (a Game Summary cannot be edited before it exists). |
| Does a changed digest mean a scoring change? | No. Regeneration for unrelated reasons changes the document too. A pair whose only difference is the footer produces a **finding**, never a record. |
| What is invisible? | Any correction made **before the first usable capture** — a capture taken after a correction shows the corrected state and is indistinguishable from one taken before any correction. |

## Measuring the ceiling (`archive-yield`)

* `python -m nhl_monitor archive-yield --from-season 2005 --to-season 2026 --game-numbers 1,500,1100`
* writes `data/reference/archive_yield.json`: per season, how many sampled documents are
  archived at all, and how many provably changed.

This is a **measurement of the Internet Archive**, not a claim about the NHL, and it is
what bounds any archive-based census. Three outcomes are counted separately and must
never be collapsed:

| Outcome | Meaning |
| --- | --- |
| `provably_changed` | the archive proves the document's content changed — a lead, still to survive a content comparison |
| `archived_but_never_changed` | archived at least once with usable content; no change visible to the archive |
| `no_usable_capture` | the archive cannot answer for this document — **unknowable, not unchanged** |
| `index_error` | the query itself failed — also unknowable, counted separately from a missing capture |

## Evidence rules enforced by the code

* Every record's `sources` carry the archived URL, the **snapshot capture time**, the
  snapshot digest and the canonical URL the league serves today. `retrieved_at_utc`
  (when *we* downloaded the capture) is kept separate from
  `snapshot_captured_at_utc` (when the league's document said that) — conflating them
  would invent a correction time.
* Redirect bodies and archive error pages are rejected as evidence by digest
  (`archive.REDIRECT_DIGEST`, `archive.ERROR_DIGEST`).
* A digest that returns to an earlier value is flagged, not folded into a change: a
  genuine reversion and a capture artefact look identical in the index.
* Every detection route (live monitor, the league's own announcements, both backfill
  methods) raises alerts through one entry point, `alerts.emit_for_records`, so a
  finding cannot reach the database without reaching the feed.

## Running it in CI

`.github/workflows/backfill.yml` (manual dispatch, runs where the network exists):

| method | inputs | what it produces |
| --- | --- | --- |
| `era` | season, game range | records where a frozen document disagrees with the current database |
| `archive` | one game id | that document's change windows and their comparison |
| `change-scan` | season, game range | `data/reference/change_scan_<season>_<kind>.json` with leads and comparisons |
| `archive-yield` | season range, sampled game numbers | `data/reference/archive_yield.json` (the measured ceiling) |
| `coverage` | — | `data/reference/coverage_report.json` (per-season availability and era) |

The job commits what it measured and uploads the run output as an artifact.

## Known gaps (not solved, and not hidden)

1. **Snapshot-after-correction blindness** (method 2): a correction hidden inside the
   interval between the first capture and the correction is invisible forever.
2. **No report exists** for a season with no official document: 1999-2000 returns 404,
   so 2000-01 is the floor for the HTML report family (fact F13).
3. **1999-2004 layout**: the 2000-2004 Game Summary puts the on-ice skaters inside the
   scoring table (fact F15). The parser handles the layout, but every historical slice
   must still be reviewed row by row before its records are treated as verified.
4. **Rate limits**: one index query per document. A full season is ~1,300 documents, so
   a season scan is a long run and must be sliced.
5. **Nothing here proves a market was affected.** A corrected game total is a fact about
   the official record; whether a specific book had graded it is a separate question,
   flagged for review and never assumed.

## Measured reach (2026-10-07)

Taken through the platform's page-fetch tool against the same CDX queries the code builds
(`matchType=prefix`, fields `original,timestamp,digest,statuscode`); the full rows are in
`data/reference/verified_facts.json` (facts F19–F21).

| Season | What the index shows | Consequence |
| --- | --- | --- |
| 2000-01 | Game Summaries are archived, but the earliest capture is **2012-07-01** — twelve years after the games. | Every correction made between 2000-01 and 2012 is invisible to method 2 for that season. Method 1 (frozen document vs the database) is the method that works there. |
| 2000-01 | `GS020011.HTM` has six captures with one digest, then two with two different digests, then one back to the original digest. | A digest that returns to an earlier value is **observed on a real official document**, which is why `change_windows()` flags it instead of folding it into a change. |
| 2005-06 | `ES020024.HTM` was captured three times with one digest and once, in 2015, with a different one. | Provable changes exist outside the Game Summary too — but only the Game Summary carries the scoring record in a form that can be attributed to a goal (`backfill.COMPARABLE_KINDS`). |
| all | The same document is captured under `http://www.nhl.com:80/...`, `http://www.nhl.com/...` and `https://www.nhl.com/...`; 302 redirects, `301` image captures and `-` (no status recorded) rows are common. | Captures are matched by **document path**, not by URL string (a whole-URL match discarded every 2000-01 capture and made an archived season look unarchived — fact F21), and redirect/error digests are rejected as evidence. |

**The honest summary:** the archive can prove *that* and *when* some official documents
changed, and its comparison now produces both states from the league's own documents —
but a correction that happened before a document's first capture is unrecoverable, and
for the earliest seasons that blind spot is more than a decade. Nothing in this file
should be read as "therefore no correction happened".

## Running the full census: a permission blocker (measured, not assumed)

`gh workflow run backfill.yml …` returns **HTTP 403 `Resource not accessible by
integration`** from this session's token — dispatching a workflow requires `actions:
write`, which the integration does not have. `workflow_dispatch` additionally only
exposes default-branch workflows, so the runs must be started from the repository's
Actions tab or by an admin granting the permission. Dispatch inputs and expected
artifacts are in the table above; each run commits what it measured.
