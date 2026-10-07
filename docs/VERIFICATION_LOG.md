# Verification log

Line-by-line record of what was checked while building this project, on **2026-10-07**. The machine-readable
version is [`data/reference/verified_facts.json`](../data/reference/verified_facts.json) (rendered on the
site); this file adds the narrative of how each check was performed and what it changed in the code.

## Environment

* Direct HTTP from the build sandbox to `nhl.com`, `www.nhl.com`, `api-web.nhle.com`,
  `statsapi.web.nhle.com` is **blocked** (`curl` → HTTP 000; the toolkit's own probe reproduced it and the
  artifact is committed at [`evidence/sandbox_network_probe.json`](evidence/sandbox_network_probe.json)).
* Retrieval for every fact below was therefore performed through the platform's page-fetch tool, which
  *could* reach `www.nhl.com`, `api-web.nhle.com` and `web.archive.org`.
* Consequence, stated up front: **the pipeline could not be executed end-to-end here.** It is unit-tested and
  every endpoint it uses has been verified to exist and to contain the expected data, but the first real run
  must happen on a networked machine.

## Checks, in order

| # | Check | Result | Effect on the code |
|---|---|---|---|
| 1 | Retrieve `20232024/GS020001.HTM` | 200; 8-goal scoring summary; footer `2024-02-06 11.19.44` | defined the Game Summary parser target; revealed the regeneration behaviour |
| 2 | Retrieve `20232024/PL020001.HTM` | 200; event list with on-ice skaters | source of the independent player-id cross-check |
| 3 | Retrieve `api-web.nhle.com/v1/gamecenter/2023020001/play-by-play` | 200; full event stream | gave the exact event schema; `goal` events are `typeCode 505` with `scoringPlayerId`/`assist1PlayerId`/`assist2PlayerId`/`awayScore`/`homeScore` |
| 4 | Retrieve `…/2023020001/boxscore` | 200; per-player goals/assists/points | boxscore parser + the cross-check function |
| 5 | Cross-check the goal event against the documents | goal #1: `scoringPlayerId=8476453` = the `86 N.KUCHEROV(1)` line in the GS; the PL text `NSH #2 SCHENN HIT TBL #86 KUCHEROV` independently ties sweater 86 to 8476453 | proved API and documents are the same data: recorded as a *limitation* (they are not two witnesses) |
| 6 | Retrieve `20232024/ES020001.HTM` and `RO020001.HTM` | 200; event summary and roster with officials | `doc.ES` / `doc.RO` in the registry; officials added to the record's possible fields |
| 7 | Probe `20232024/SC020001.HTM` | **404** | removed any notion of a "scoring change" report; documented in SOURCES.md |
| 8 | Probe `scores/htmlreports/` index | **403** | seasons cannot be enumerated; the coverage job probes folders directly |
| 9 | Retrieve `20052006/GS020001.HTM` (2005-10-05, MTL 2 @ BOS 1) | 200; 3-goal summary; **strength column last**; footer `2005-10-05-21.40.47` | forced the header-driven, order-independent parser; added the legacy-assist/`unassisted` handling; established the "frozen" era |
| 10 | Retrieve `20052006/ES010025.HTM` | 200; old layout **without** per-player G/A columns | documented that old ES documents cannot supply attribution; parser warns instead of guessing |
| 11 | Retrieve `20162017/GS020001.HTM` (2016-10-12, TOR 4 @ OTT 5 OT) | 200; footer `2016-10-12-22.08.17` | second frozen-era data point (also exercises OT parsing) |
| 12 | Retrieve `20132014/GS020001.HTM` | 200; bilingual MTL/TOR format | header normalisation handles `But/Goal Scorer`, `Temps/Time`, `Sit/Str` |
| 13 | Probe `19992000/GS020001.HTM` | **404** | earliest-coverage question is now a measured open item rather than an assumption |
| 14 | Retrieve `api-web.nhle.com/v1/gamecenter/2005020001/boxscore` | 200; MTL 2 - BOS 1, shots 21/30 | proved the API serves 2005-06; enabled census method 1 |
| 15 | Compare fact 9 against fact 14 | consistent for every player visible in the retrieved chunk (Bulis 1G, Ryder 1G, Koivu/Kovalev/Bonk/Sundstrom 1A) | recorded as **n = 1 method validation, not a validated method** (F11); explicitly noted that Bergeron's line was not visible and is therefore unverified |
| 16 | CDX exact-URL query for `20232024/GS020001.HTM` | one snapshot, statuscode 200, digest `TE24NPUUMSEV3LQEBNQE2TN3NO5GNATJ` | `archive.snapshots_for` / `content_versions` design; latest-state-only caveat documented |
| 17 | CDX **raw** fetch of that snapshot and diff against the live document | identical scoring summary and identical footer | negative control passed; recorded that a regenerated footer alone is NOT evidence of a change (F08) |
| 18 | CDX prefix query for `20242025/` | per-document digests returned | confirms the mechanism generalises; site/README claim limited to what was observed |
| 19 | CDX prefix query for `20052006/` | 2006-era captures are **302 redirects** with digest `3I42H3S6NNFQ2MSVX7XZKYAYSCX5QBYJ`; one real 200 capture from 2015 | both the redirect digest and a known error-page digest are now filtered out by `Snapshot.usable` |
| 20 | Inspect the retrieved play-by-play chunks for review events | none present: only `period-start, faceoff, stoppage, hit, giveaway, takeaway, shot-on-goal, missed-shot, blocked-shot, goal` | `data/schema/observed_vocabulary.json` committed; the project does **not** claim to detect "video review"; no such filter on the site |

## Bugs the verification loop actually caught

All of these were found by the tests written against the retrieved data, not by inspection:

1. **`_norm()` stripped digits before period parsing**, so every row of a scoring summary was skipped and the
   parser returned zero goals. Now digits are read from the raw cell; the legacy fixture (which has numeric
   periods) covers it.
2. **`TOTAL_AFFECTING` used the record-level names** (`goal_to_no_goal`) instead of the change-level names
   (`goal_removed`), which silently disabled `affects_goal_total` — i.e. the settlement logic would have
   reported *no* market impact for a removed goal. Tests now assert both the classification and the flag.
3. **`store.upsert_record` could never detect an unchanged record** (it compared a normalised stored record
   with a raw incoming one), so every monitor run would have written a spurious revision. Comparison now
   ignores volatile bookkeeping fields.
4. **`strength_from_situation` was written team-blind** (a 5v4 goal would have been labelled PP regardless of
   who scored) and contained dead code; it now takes the scoring team's side and detects `-EN` from the
   opponent's goalie digit.
5. **`tools/build_site.py` copied data one directory too high**, so the site would have 404'd on every JSON
   file in production. Caught by building `_site/` and listing it.

## What is explicitly **not** verified

* No discrepancy record exists yet. Nothing in this repository asserts that any specific goal was ever
  changed by the NHL. The two candidates mentioned in `verified_facts.json` are labelled
  `secondary_leads_not_evidence` and may not be promoted without an official artifact.
* Feed latency is not measured.
* The transition season between frozen and regenerated reports is not bracketed tighter than 2016-17 .. 2023-24.
* The earliest serving season is between 1999-2000 (absent) and 2005-06 (present).
* `parse_gs_report`'s **HTML layer** is exercised against reconstruction fixtures, not against the raw byte
  stream of the official document (the retrieval tool returned rendered text). This is exactly what
  `python -m nhl_monitor probe` validates at runtime, and it is listed as roadmap item P0-1.
