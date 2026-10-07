# Detection & Alert Design

How the monitor turns official NHL data into discrepancy records and alerts.

## Pipeline (one cycle)

1. **Discover games** — schedule API for the rolling window (default: last 3 days),
   keep games with status `Final`/`Official`/`Game Over`.
2. **Snapshot** — fetch the live feed for each game; normalize to a compact JSON
   snapshot (final score, per-goal records, review events, feed state). Also hash
   the GS/ES official PDFs when present. Snapshots are stored under
   `data/snapshots/{gamePk}.json` (kept in the GitHub Actions cache, not git).
3. **Diff** against the previous snapshot for the same game:
   * **Goal set change** (a goal appears/disappears, matched by period + team +
     sequence alignment on game clock) → `changes_game_total: true`.
   * **Per-goal field change** (scorer, assists, strength, empty-net) on a matched
     goal → attribution correction (`attribution_only: true`).
   * **Report hash change** → `official_report_changed` flag (content diff pending).
4. **Corroborate** — if review/challenge events are present in the feed, attach
   them as evidence and refine the type (`video_review_overturn`,
   `coach_challenge_*`). A Situation Room link is attached when available.
   *(2026-10-07: the engine line now does this the other way round as its primary
   path — it ingests the official Situation Room statement feed and cross-checks
   each overturned call against the play-by-play's `chlg-*` / `video-review`
   stoppage; see `docs/SITUATION_ROOM.md`.)*
5. **Classify timing** (heuristic, documented confidence):
   * change visible while game not final → `in_game` (or `intermission` when
     snapshots bracket an intermission boundary),
   * first visible in a snapshot taken after final → `postgame`.
6. **Persist** — upsert the discrepancy record (stable id per game+goal+type),
   keeping the **earliest observed state as `original`** and the newest as
   `corrected`.
7. **Alert** — new/updated records produce entries in `data/alerts.json`,
   `data/alerts.xml` (RSS), and (in CI) a GitHub Issue labeled
   `scoring-alert`. Alerts include: what changed, from → to, evidence links, and
   flags.

## Detector guarantees & non-guarantees

* Guaranteed: **no record without evidence links**; **no invented fields**;
  every automated classification carries `detection.method`.
* Not guaranteed: sub-30-minute latency; timing classification for changes that
  span monitor downtime; explanation of *why* a correction was made.

## Alert shapes

* `discrepancy_new` — first time a change is observed.
* `discrepancy_updated` — the corrected state changed again (e.g., attribution
  refined after an overturn).
* `official_report_changed` — GS/ES hash changed; human review requested.
* `monitor_degraded` — source unreachable beyond retry budget (with error detail).
* `schema_drift` — feed shape missing expected fields; parsing degraded, review
  requested.

## Re-run & repair

`python3 -m pipeline.main update --days N --force-rebaseline` re-baselines
snapshots without emitting alerts (used after cache loss).
`python3 -m pipeline.main validate` re-checks all stored records against the
schema and evidence rules.
