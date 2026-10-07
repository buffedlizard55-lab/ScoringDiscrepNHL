# Coverage & Limitations

This document is the honest accounting of **what this system can and cannot detect,
how fast, and how far back in history**. It is required reading for interpreting the
database and the alert feed.

**Status legend:** `verified` = observed live from this project's tooling with a
recorded URL; `unverified` = expected from prior knowledge of the NHL's public data
surface but **not yet confirmed from a running environment with network access to NHL
endpoints**. The GitHub Actions monitor and the `probe` command convert
`unverified` entries into `verified` results (see `data/coverage_report.json`).

---

## 1. Can an automated alert/detection system be built? — Summary answer

**Yes — partially automated, with well-defined boundaries.** Concretely:

| Capability | Automatable? | How | Confidence |
|---|---|---|---|
| Detect a goal flipped to no-goal (or vice versa) | **Yes** | Diff consecutive snapshots of the official live feed for a completed game; any added/removed goal is a game-total discrepancy | High |
| Detect video-review overturns as they happen | **Yes** | The league's own Situation Room statement for every challenge / review (published within minutes) is ingested and cross-checked against the `chlg-*` / `video-review` stoppage in the official play-by-play; see `docs/SITUATION_ROOM.md` | High (2016-02 onward) |
| Detect scorer/assist attribution changes | **Yes** | Diff per-goal scorer/assist fields between snapshots of live feeds and official Event Summaries | High |
| Detect corrections to official PDF reports (silent edits) | **Yes (as a flag)** | SHA-256 hashes of Game Summary / Event Summary PDFs are stored per game; a hash change ⇒ "official report changed — human review needed". The system tells you *that* a report changed, not *what* changed — PDF text diffing is a planned enhancement | High for detection, human needed for explanation |
| Classify *when* the correction happened (in-game / intermission / postgame) | **Partially** | From snapshot timestamps + feed state (period/intermission/final). Heuristic; low-confidence cases carry `timing_confidence: heuristic` and may need review | Medium |
| Explain *why* a correction happened | **Partially** | Situation Room posts and review-event descriptions are captured as evidence; free-text reasons require human verification | Medium |
| Detect corrections that occurred **before monitoring started** for a game | **No** | No baseline snapshot exists. Historical backfill must come from archived official documents and is flagged `pending_review` | n/a |
| Detect corrections never reflected in any public official document | **No** | By definition invisible to automated monitoring; requires tips/human research, always flagged | n/a |
| Historical discrepancies (pre-live-feed era) | **No (not automatically)** | See Section 4 — requires archival research with per-entry verification | n/a |

**Bottom line:** the everyday use case — "did anything change in recent NHL games,
and what exactly changed, with official links" — **can** be automated reliably.
Deep history and explanation of causes cannot be fully automated and are handled by
flagging for human verification instead of guessing.

## 2. Official sources used (exact endpoints)

All are public, no API key. Catalog with URL templates: [SOURCES.md](SOURCES.md).

| Source | Used for | Status here |
|---|---|---|
| `statsapi.web.nhl.com` schedule API | Discover completed games, final scores | `unverified` (blocked from authoring environment; verified in CI by first run) |
| `statsapi.web.nhl.com` live feed (`/api/v1/game/{gamePk}/feed/live`) | Authoritative play-by-play, goals, review events | `unverified` (same) |
| `nhl.com/scores/htmlreports/...` official PDF reports (GS/ES) | Hash-based change detection of official reports | `unverified` (same) |
| Situation Room statements (`forge-dapi.d3.nhle.com/v2/content/en-us/stories?tags.slug=situation-room`, public pages `nhl.com/news/<slug>`) | Official on-ice call, result, rule and explanation for every coach's challenge / video review since 2016-02 | **verified and ingested 2026-10-07** by `pipeline/nhl_scoring/situation_room.py`; see `docs/SITUATION_ROOM.md` |
| `api-web.nhle.com` (scoreboard, gamecenter play-by-play/boxscore) | Second official endpoint family: corroboration and planned second snapshot source | `unverified` (same); probed by the coverage probe |

## 3. Latency & timeliness

* The monitor runs **every 30 minutes** in GitHub Actions (`monitor.yml`). This is
  the detection latency floor: a correction is detected within ~30 minutes of the
  snapshot that reveals it, plus the time between the correction and that snapshot.
* Corrections made **during the game or at intermission** are visible in the live
  feed itself and are classified `in_game` / `intermission` when the snapshot
  evidence supports it.
* Corrections made **after the game** (postgame scoring changes) appear when the
  official feed/report changes after final; monitor continues to re-check each game
  for **21 days** after it ends, then archives it. Corrections later than 21 days
  are rare but possible — this window is configurable (`STABLE_DAYS`).
* **GitHub Actions cache eviction** (7+ days of inactivity or cache pressure) can
  drop snapshot baselines; affected games are re-baselined and flagged
  `baseline_lost` — detection resumes from the new baseline.

## 4. Historical coverage — what can be reached, honestly

Exact historical reach must be **verified, not assumed**. The `probe` command
(`python3 -m pipeline.main probe`, also run in CI) tests representative games per
era and writes results with exact URLs into `data/coverage_report.json`, which the
website renders. The expected picture, all flagged `unverified` until probed:

| Era | Expected best official source | Expected automated detectability |
|---|---|---|
| ~2010s → present | Live feeds via statsapi v1 (gamePk era) | Full: snapshot diffs + review events |
| ~1997/98 → ~2010s | Official PDF reports on nhl.com (`htmlreports`) | Partial: report text can be archived and diffed retrospectively; no live snapshots exist, so entries are `pending_review` unless two dated copies of a document differ |
| Pre-RTSS era (before ~1997/98) | No machine-readable official play-by-play online | **Not automatable.** Requires archival research (official records site, archived pages) with per-entry human verification. Not attempted by the automated monitor. |

Video review history (background context, **unverified — requires official citation
before being quoted elsewhere**): video review for goals was introduced in the NHL
in the early 1990s, the centralized Situation Room became the review hub in the
2010s, and coach's challenge / expanded review categories arrived in later seasons.
The exact seasons must be confirmed from NHL official publications before any
database record relies on them; until then they are context only.

## 5. Source & feed limitations

1. **No official corrections feed exists.** The NHL does not publish a changelog of
   scoring corrections. Detection therefore relies on snapshot diffing, which only
   sees changes that happen *while we are watching*.
2. **Silent edits.** Official documents can be updated without announcement. Hash
   monitoring catches the fact of the edit; the content diff requires PDF text
   extraction (planned) and human review.
3. **Endpoint shape risk.** The statsapi v1 feed is public but unofficial; field
   names can change. The pipeline is defensive (all parsing via `.get` with
   explicit unknown-shape warnings) and a schema-drift alert is emitted when the
   expected fields are missing.
4. **Rate limiting / availability.** The client is polite (1s delay between
   requests, retries with backoff, respects HTTP 429/503). Extended NHL outages
   produce `monitor_degraded` entries in `data/alerts.json` instead of failures.
5. **Game totals vs. shootouts.** Shootout decisions add one goal to the final
   score without a standard even-strength goal event; the pipeline treats the
   shootout game-winner specially and never counts it as a discrepancy. Overtime /
   shootout totals are tracked from the linescore, not inferred.
6. **Attribution timing.** Scorer/assist corrections are frequently made hours after
   final by the official scorers; they are real discrepancies and are captured, but
   they **do not change game totals** — the site separates these clearly.
7. **Settlement impact is informational.** `settlement_risk` means "the change
   altered the goal total after it had appeared final" — a betting-market
   relevance flag, **not** betting advice. Markets settle under their own rules;
   nothing in this project guarantees any settlement outcome.

## 6. Cases that still require human verification

Every record that meets any of these conditions carries a
`needs_human_review` flag and is visually flagged on the site:

* Evidence status is `incomplete`, `conflicting`, or `unavailable`.
* The change was detected only by a report-hash change (PDF changed, content diff
  not yet extracted).
* Timing classification is ambiguous (e.g., monitor was down across the change).
* Historical/backfilled records (pre-monitor era).
* Any discrepancy between two official sources (e.g., live feed vs. Event Summary).

## 7. What we deliberately do NOT do

* We do **not** fill gaps with assumptions or estimates. Empty fields mean
  "not verifiable from captured official evidence".
* We do **not** use secondary/aggregator sites as the evidence of record. They may
  be linked as corroboration only, labeled `secondary`.
* We do **not** scrape behind paywalls, bypass robots directives, or hammer
  endpoints. The pipeline identifies itself with a descriptive User-Agent.
