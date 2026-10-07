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

## Pass 3 — re-check against the original request (same date, 2026-10-07)

Pass 3 asked a different question: not "does it work" but "does it answer the brief". Two deliverables were
missing in substance, not in code: **the database had no verified content**, and **the earliest reliable
coverage was still a range instead of an answer**. Both were closed with retrieval, not reasoning.

| # | Check | Result | Effect on the code / data |
|---|---|---|---|
| 21 | `19992000/GS020001.HTM` | **404** | earliest-coverage bracket narrowed to 2000-01 |
| 22 | `20002001/GS020001.HTM` | 200; COL 2 - DAL 2, 2000-10-04; footer `2000-10-04-22.14.20` (game night) | **earliest season answered: 2000-01, and it is frozen** |
| 23 | `20012002/GS020001.HTM` | 200; OTT 5 - TOR 4; footer `2001-10-03-22.27.18` (game night) | second frozen 2000s sample; new era fixture written from its real rows |
| 24 | Compare the 2000-2004 layout with the modern one | on-ice columns inside the scoring summary, strength last, no shield logo, bench row reads `Team` | `tests/fixtures/gs_20002001_020001.html` + 6 era tests |
| 25 | Search for an official statement of a scoring change | the league's own public-relations posts carry a fixed format; reproductions syndicate them verbatim | `nhl_monitor.ingest.parse_scoring_change_statement` + 4 parser tests |
| 26 | Retrieve the three announcement posts directly | 200; timestamps `2025-03-27T04:51:19Z`, `2025-04-09T04:50:32Z`, `2025-04-02T05:07:35Z`; text identical to the reproductions | three case files; the announcement text is now primary, not quoted-second-hand |
| 27 | Resolve each announcement to an official report row | `GS021140` goal 2, `GS021238` goal 1, `GS021185` goal 12 — scorer, assists and season totals all match | three records, each with the report URL, the quoted row and the report's rebuild timestamp |
| 28 | Cross-check the corrected state a second way | `api-web` play-by-play event 146 for game 2024021140: scorer id 8482110, assists 8482684/8480002, `awayScore 2 homeScore 0` — the same ids the report ties to Mercer(16)/Hughes(31)/Hischier(28) | record 1 has two official sources for the corrected state |
| 29 | Independent corroboration from season totals | report says Wotherspoon 6 assists and Geekie 23; the reproduction says the change dropped Wotherspoon to six and left Geekie on 23. Same for Cole Smith 8 / McCarron 9 | recorded as an internal-consistency check on each record |
| 30 | Inspect the payload for residue of the superseded credit | event 146's English clip title reads `meier-scores-ppg`, the French one reads `mercer-…`; scoring fields read Mercer | F17; the record flags an official payload that is not internally consistent |
| 31 | Look for review / video-review events in the play-by-play | none; observed stoppage reasons are `icing, puck-in-netting, goalie-stopped-after-sog, offside, tv-timeout, puck-frozen, hand-pass` | the "no review feed" limitation is now backed by the observed vocabulary |
| 32 | Measure announcement latency | 10,159 s / 12,212 s / 12,275 s after the reported end of the game (2h49m, 3h23m, 3h25m) | `timing.latency_after_final_buzzer_seconds`, computed only when both timestamps are documented |
| 33 | CDX exact-URL query for `20242025/GS021238.HTM` | exactly one snapshot, `20250520104135`, digest `W54KGGJCRJNDN3R2PIL4JTIKFLDUOXSX` — **after** the correction, so it cannot serve as the pre-change state | the record says the pre-change state is secondary; the archive method needs a snapshot *before* the change |
| 34 | Render the shipped database through the site client in a headless DOM | 3 records render; the goal-count view stays empty; the drawer shows every flag, the announcement timestamp, the tri-state check and every source URL | `tools/check_site.mjs` now runs two passes, and `tests.yml` runs it on every push |

### Bugs pass 3 caught

1. **Goal ordering compared clocks as text.** `18:31` sorted before `2:00`, so a period with both clocks came
   out in the wrong order — in `state.sorted_goals()` and in the record sequence numbers assigned by
   `detect.build_records()`. Both now sort on seconds (`_clock_seconds`) with the raw string as a tiebreak.
2. **The announcement parser stopped at the first period**, so `now reads J. Doe unassisted` parsed the
   scorer as `J`. The clause is now captured to the end of the announcement and trimmed.
3. **The store deleted hand-maintained metadata on the first write.** `save_records` rewrote the file from
   scratch, which would have dropped the `coverage` and `status_note` blocks — and with them the coverage
   panel on the site — the moment the first record was written. Non-owned top-level keys are now preserved,
   with a regression test.
4. **A false-positive risk in the ingest design**: an announcement implies the previous reading without
   stating it. The ingest treats "the sources do not say" as *indeterminate* (a third state), never as
   "nothing changed", and flags the record.

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

* **Coverage.** Three records from one season is a method, not a census. Nothing here should be read as
  "these are the NHL's scoring changes for 2024-25".
* **The pre-change state of two of the three records** rests on a syndicated reproduction of the league's
  announcement, not on a retained official artifact. Each record says which. The archival snapshot for game
  1238 was taken *after* the correction and is therefore useless for this purpose.
* **The full scope of record 3** (game 1185). What the assists read before the change is documented nowhere
  that was reviewed; the record flags it rather than guessing.
* **A goal-count change has never been observed.** All three records move player credit only. Whether a
  post-final goal is ever added or removed — the class that would move a game total — remains an open
  question, and the pipeline is built to detect it but has no example.
* **The pre-2000-01 era is not covered at all**, and no other official historical source for it was located.
* **Feed latency is not measured prospectively.** The numbers here are announcement-vs-final-buzzer, measured
  after the fact from documented timestamps. The moment the official *feed* flipped is only measurable by
  running the monitor while it happens.
* The transition season between frozen and regenerated reports is not bracketed tighter than 2000-01 ..
  2023-24 (frozen: 2000-01, 2001-02, 2005-06, 2016-17; regenerated: 2023-24, 2024-25).
* The footer timestamps in official reports have **no documented timezone**, so they are stored verbatim and
  never converted — which means the exact minute a report was rebuilt cannot be asserted.
* The four secondary leads (L01–L04) are not verified and are not records.
* `parse_gs_report`'s **HTML layer** is exercised against reconstruction fixtures, not against the raw byte
  stream of the official document (the retrieval tool returned rendered text). This is exactly what
  `python -m nhl_monitor probe` validates at runtime, and it is listed as roadmap item P0-1.
