# Can an alert/notification system for scoring discrepancies be built?

**Short answer: yes for a specific, well-defined class of it — and no for the class
people usually mean when they ask.** This document is the honest version of that
sentence, with the evidence behind each line. It is the answer to the standing
requirement in [PROJECT_PROMPT.md](../PROJECT_PROMPT.md) item 6: *"an
alert/notification detection system for scoring discrepancies, with explicit
analysis of limitations and whether it is even possible."*

Everything asserted here was checked on **2026-10-07** in this repository. Where a
claim rests on a retrieval, the artifact is committed. Where it could not be
checked in this environment, it says so instead of asserting.

> **Revision 2026-10-07 (later session, after the Situation Room backfill).**
> Sections 3.1, 3.2 and 5 below were written *before* the league's official
> Situation Room statement feed was found and ingested, and they no longer match
> the delivered system. The false claims are struck inline and corrected where
> they appear. Headline correction: the feed **does** exist
> (content API, tag `situation-room`, every coach's challenge and video review
> since 2016-02, ~4,400 statements), the site **does** carry a "video review"
> filter backed by those statements, and the database now holds **1,470 records**
> (1,465 goal-count-changing, 4 attribution-only, 1 total-change-unknown),
> not 3. See [`SITUATION_ROOM.md`](SITUATION_ROOM.md) and
> [`LIMITATIONS.md`](LIMITATIONS.md) §2, which were corrected the same way. The
> verdict in the opening paragraph — *possible as change detection, not as cause
> detection* — is unchanged and is still the honest bottom line.

---

## 1. What "detect a scoring discrepancy" can and cannot mean

The NHL publishes **state**, not **history**. There is no correction flag, no
revision number, no change log, and no `SC` (scoring-change) document — a request
for one returns 404 (fact F-series in
[`data/reference/verified_facts.json`](../data/reference/verified_facts.json)).

So there are exactly three things a detector can do, and they have very different
value:

| Formulation | Possible? | Why |
| --- | --- | --- |
| **Change detection**: we captured the official state, we captured it again, it differs | **Yes — and it is the only fully defensible one** | Both states are official artifacts, so the alert carries its own proof. This is what the pipeline does. |
| **Cross-artifact conflict**: two official renderings of one game disagree | **Yes** | e.g. the Game Summary sheet and the GameCenter JSON. Caveat in §4. |
| **Cause detection**: "this changed *because of* video review / a coach's challenge" | **No** | Measured: the official play-by-play has **no review or challenge event type**. See §3. |

A fourth thing people want — *"tell me a goal was waved off and then awarded, from
history"* — is **not possible from official sources**. An overturned call leaves no
trace in the final record: a goal that was disallowed and reinstated appears exactly
once, indistinguishable from a goal nobody questioned; a goal that was disallowed
and stayed disallowed appears zero times, so there is nothing to diff.

---

## 2. What is actually built and wired today

Three detection routes, one feed, one page.

| Route | Code | Schedule | Writes |
| --- | --- | --- | --- |
| Live monitor — poll recently finished games, diff captured states | `src/nhl_monitor/monitor.py` via `python -m nhl_monitor monitor` | `.github/workflows/monitor.yml`, cron `*/5 * * * *` | `data/records/discrepancies.json`, `data/alerts/`, `data/alerts.json`, `data/alerts.xml` |
| Announcement ingest — parse the league's own `OFFICIAL SCORING CHANGE` posts | `src/nhl_monitor/ingest.py` | on demand / backfill | same |
| Engine checks — cross-artifact and snapshot-diff checks C10–C22 | `pipeline/nhl_scoring/checks.py` via `python -m nhl_scoring.cli` | `scoring-monitor.yml` (dispatch-only) | `data/discrepancies.json`, `data/alerts/<date>/`, `data/alerts.json`, `data/alerts.xml` |

Notification channels that exist in code:

1. **Committed JSON + RSS** — `data/alerts.json` and `data/alerts.xml`, served by
   GitHub Pages. Zero external dependency; the alert is a versioned artifact.
2. **GitHub Issue** — `alerts.open_github_issue()` via `gh`, labels
   `scoring-discrepancy` / `auto-detected`, wired into `monitor.yml` with
   `--github-issue`.
3. **Generic webhook** — `alerts.webhook_payload()` produces a Slack/Discord-shaped
   body; the URL comes from `SDN_WEBHOOK`. No credentials are stored in the repo.

**Every route projects into the same site feed.** That was a real defect, not a
design choice: the published page reads `data/alerts.json`, both detection routes
wrote elsewhere, and the live Alerts tab said *"No alerts yet"* while three alerts
were committed in the repository. `alerts.write_site_feed()` now exists on both
sides, de-duplicated by record id, preserving `created_at` on re-emit so a re-run
cannot make an old alert look new. Regression tests:
[`tests/test_alert_feed.py`](../tests/test_alert_feed.py).

---

## 3. What cannot be detected automatically — measured, not assumed

1. **Video review as a cause — corrected 2026-10-07.** ~~The observed event
   vocabulary lists 10 `typeDescKey` values … and `review_event_types_found: []`.
   There is no review event to read. An overturned goal is still detectable *as a
   state change*; the reason stays empty and the record is flagged. **The site
   deliberately offers no "video review" filter**, because a filter that can never
   match honestly is a lie about capability.~~ All of that is now **false** and is
   struck. The play-by-play marks reviews as `chlg-*` / `video-review` stoppages,
   and — decisively — the league publishes an **official statement for every
   coach's challenge and video review** through its content API (tag
   `situation-room`, continuous since 2016-02). The site's **"Video review /
   challenge"** toggle and the **"Review kind"** / **"Challenge / review type"**
   selectors are backed by those statements, not by inference; a filter that
   matches 1,465 records is not a lie about capability. What remains genuinely
   unautomated is the *reason for a scorer/assist change*, which has no feed and
   stays `reason.text = null` plus a flag unless an official artifact states it in
   words (see [SITUATION_ROOM.md](SITUATION_ROOM.md), verified facts F30–F32).
2. **Why the league changed anything — corrected 2026-10-07.** ~~No
   machine-readable Situation Room feed was located. `reason.text` is filled only
   when an official artifact states it in words — which, for the three verified
   records, it did (the `OFFICIAL SCORING CHANGE` posts).~~ The first sentence was
   measured on one game that had no review and is **false**; it is struck. The feed
   exists and is ingested: for every challenge/video review since 2016-02 the
   statement's result, rule and explanation are stored **verbatim** on the record,
   so for review decisions the reason *is* automated. What stays true: for
   **scorer/assist** corrections there is no such feed, so `reason.text` is filled
   only when an official artifact states it in words — which, for the
   announcement-based records, the league's own `OFFICIAL SCORING CHANGE` posts
   did.
3. **Changes between two polls with no earlier capture.** If every capture
   post-dates the correction, the original state is unrecoverable from any source
   this project can read. This is the structural false negative, and it is the
   reason the archive census exists.
4. **Which of two disagreeing official artifacts is correct.** The HTML sheet and
   the GameCenter JSON are the same data rendered twice — proved by matching player
   ids on the same goal — so citing both is **not** independent verification.
   Conflicts are flagged, never auto-resolved.
5. **Authoritative "when was it corrected".** The only timestamps are the report
   footer generation stamp and the feed's own game clock. Neither is a correction
   timestamp. `when_corrected` is a six-value enum plus `timing_uncertain: true`
   whenever it was inferred.
6. **Anything before 2000-01.** Measured: `19992000/GS020001.HTM` → 404,
   `20002001/GS020001.HTM` → 200. Per-season availability for 28 seasons is
   committed at [`data/reference/coverage_report.json`](../data/reference/coverage_report.json).
7. **Whether a bookmaker regraded a settled market.** Private house rules. The
   system flags "a settled market may have been graded on a superseded number" and
   stops there.

---

## 4. Latency — what is measured and what is not

- **Measured:** on the three verified records, the league's own scoring-change
  announcements were posted **2h49m–3h25m after the reported end of the game**. That
  is a real number for one alert class: corrections the league announces.
- **Not measured:** the lag between the official record changing and our next poll
  seeing it. Every capture stores `retrieved_at_utc`, so it becomes measurable over
  time, but **no figure may be quoted yet** and none is.
- **Scheduler floor:** GitHub Actions cron is coarse and delayed at busy times.
  `monitor.yml` requests `*/5`; treat the practical cadence as *"within roughly ten
  minutes"*, not real-time. Genuinely in-game latency needs a self-hosted always-on
  runner (`docs/STATUS.md`).

**Consequence for anyone thinking about settlement:** the highest-value alert class
— a change *after* the record was already final — is detectable, but on the
evidence so far it arrives **hours** after the buzzer, not seconds. Any market that
settles in that window is exposed regardless of how good the detector is.

---

## 5. What has actually been detected, and what that proves

After the Situation Room backfill the database holds **1,470 records**: **1,465
goal-count-changing** (1,342 goal→no-goal and 123 no-goal→goal), **4 attribution-only**,
and **1 total-change-unknown**; by status, 1,400 `verified`, 53 `flagged`,
17 `retired` (a superseded parser's rows, kept and marked).
Each goal-count-changing record is backed by an official Situation Room statement
and cross-checked against the play-by-play where the game id resolves — 1,396
agree, 55 inconclusive, 12 conflict, 12 not checked; the conflicts and inconclusives
are flagged, not hidden.
The three **announcement-based** records below — the only ones built through the
league's `OFFICIAL SCORING CHANGE` announcement path (1 scorer change, 2 assist
changes) — remain verified and are a small subset of that total; in the canonical
database they carry `SDN-…` ids with the originals preserved under
`parallel_record`. Re-verified line by line on 2026-10-07 (transcripts in
[`data/evidence/reverify-2026-10-07/`](../data/evidence/reverify-2026-10-07/)):

| Record | Change | Confirmed today against |
| --- | --- | --- |
| `NHL-20242025-021140-01` | scorer **Timo Meier → Dawson Mercer**, 6:50 P1 | `GS021140.HTM` row 2 (character for character) + footer `2025-03-27 8.23.23` + GameCenter event 146 |
| `NHL-20242025-021185-01` | assists resolved to **Cole Smith + Michael McCarron**, 9:02 P3 | `GS021185.HTM` row 12 (character for character) + `Start 7:09 EDT; End 9:43 EDT` |
| `NHL-20242025-021238-01` | assist **Parker Wotherspoon → Morgan Geekie**, 9:38 P1 | GameCenter event 324 (Geekie, `assistsToDate` 23) + Wotherspoon at 6 in the same game |

Two honest consequences:

- **No *post-final* goal-count correction has been found via change detection.**
  The class that would move a game total *after* the record was published as final
  — the settlement-critical one — is still *unobserved* through the
  snapshot-diff / announcement path, not disproved. The 1,465 goal-count-changing
  records are a different, well-documented class: **in-game video-review
  overturns** stated by the league's own Situation Room feed (2016-02 onward).
  They move the goal total, but they are decided during the game and announced by
  the league, not corrected after publication. The detector handles both
  (`goal_added` / `goal_removed` are the change types that set `affects_goal_total`)
  and the site separates them.
- **One stored claim did not survive re-verification.** The record for game 1140
  asserted that the official payload carried two different clip titles for the same
  goal (English "meier", French "mercer"). The payload fetched on the re-check reads
  **"meier" in both**, with a different French clip id. The corroboration is
  withdrawn, fact F17 is amended rather than deleted, and the record now carries
  `initial_state_corroboration_withdrawn_on_reverification`. Root cause: the
  database stored a *paraphrase* of a payload instead of the payload, so the claim
  was never auditable. That is the strongest argument in this project for committing
  raw captures — see §7.

---

## 6. Environment limitation that shapes everything

**This build sandbox has no direct HTTP route to NHL hosts.** Re-measured this
session: `https://api-web.nhle.com/...` and `https://www.nhl.com/scores/htmlreports/...`
both fail with `URLError: <urlopen error TLS/SSL connection has been closed (EOF)>`,
while `https://api.github.com/rate_limit` returns 200. Evidence:
[`data/reference/probe_report.json`](../data/reference/probe_report.json) and
[`docs/evidence/sandbox_network_probe.json`](../evidence/sandbox_network_probe.json).

This pass therefore retrieved official artifacts through the platform's page-fetch
text proxy. That is a **weaker evidence class** than a runner-side capture: the
stored text is what the proxy returned, response headers are unavailable, and
`http_status` is inferred from content rather than read. It is recorded as such. The
mass backfill and the live monitor still need a networked machine — which is what
the GitHub Actions runners are.

---

## 7. The gap that matters most next

**Raw captures are not committed.** Records store a quoted row or a paraphrased
note, not the bytes they came from. That is exactly how the §5 claim went
unnoticed: there was nothing to re-read. The fix is small and mechanical —
`fetch.py` already records URL + status + retrieval time; add the response body (or
its SHA-256 plus the quoted excerpt) under `data/evidence/<date>/<game>/`, and make
`store.validate()` refuse `verified` for a record whose quote has no committed
capture behind it.

Until that exists, every "verified" record is verified **as of the last time a human
or a runner re-read the source**, and this document should be re-read whenever that
changes.

---

## 8. Bottom line

- **Possible and built:** continuous change detection over official NHL artifacts,
  typed classification (goal-count vs attribution-only), timing bounded by poll
  times, settlement-exposure flagging, and notification to a static feed, RSS and
  GitHub Issues — with an official URL on every alert.
- **Not possible from official sources:** the *cause* of a ruling change, an
  authoritative correction timestamp, a retracted goal with no prior capture,
  independent verification from a second witness, and anything before 2000-01.
- **Not yet demonstrated:** a single goal-count-changing correction. Three
  records is a proof of method, not coverage.

Related: [FEASIBILITY.md](FEASIBILITY.md) · [LIMITATIONS.md](LIMITATIONS.md) ·
[DETECTION.md](DETECTION.md) · [COVERAGE_AND_LIMITATIONS.md](COVERAGE_AND_LIMITATIONS.md)
