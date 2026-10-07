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

> **Companion document.** This file is the *analysis*. The *operation* — which
> channels exist, which are on, how to subscribe, what latency was measured, what a
> failure looks like — is [NOTIFICATIONS.md](NOTIFICATIONS.md). A notification that
> has actually been delivered is linked there (issue #18, HTTP 201,
> 2026-10-07T21:25:51Z).

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
| **Situation Room ingest** — the league's own statement for every challenge and video review | `pipeline/nhl_scoring/situation_room.py` | `situation-room.yml`, cron `11,41 * * * *` | the ledger, `data/discrepancies.json`, `data/alerts.json`, `data/alerts.xml` |
| Live monitor — poll recently finished games, diff captured states | `src/nhl_monitor/monitor.py` via `python -m nhl_monitor monitor` | `.github/workflows/monitor.yml`, cron `*/5 * * * *` | `data/records/discrepancies.json`, `data/alerts/`, `data/alerts.json`, `data/alerts.xml` |
| Announcement ingest — parse the league's own `OFFICIAL SCORING CHANGE` posts | `src/nhl_monitor/ingest.py` | on demand / backfill | same |
| Engine checks — cross-artifact and snapshot-diff checks C10–C22 | `pipeline/nhl_scoring/checks.py` via `python -m nhl_scoring.cli` | `scoring-monitor.yml` (dispatch-only) | `data/discrepancies.json`, `data/alerts/<date>/`, `data/alerts.json`, `data/alerts.xml` |

Notification channels, all delivered by one module
([`pipeline/nhl_scoring/notify.py`](../pipeline/nhl_scoring/notify.py), CLI
`nhl_scoring.cli notify`), which every detection workflow calls after it renders the
feed:

1. **Committed JSON + RSS** — `data/alerts.json` and `data/alerts.xml`, served by
   GitHub Pages. Zero external dependency; the alert is a versioned artifact.
2. **GitHub issue** — REST API with `GITHUB_TOKEN`; one issue per goal-total change,
   one digest for attribution-only alerts, capped per run. Labels are created if the
   repository does not have them. **Proven live**: [issue
   #18](https://github.com/buffedlizard55-lab/ScoringDiscrepNHL/issues/18), HTTP 201,
   2026-10-07T21:25:51Z.
3. **Generic webhook** — Slack/Discord-shaped payload (`text` *and* `content`); the URL
   comes from `SDN_WEBHOOK_URL`. Off until the secret exists, and reported as skipped
   rather than silently dropped.
4. **E-mail digest** — SMTP over the six `SDN_SMTP_*` secrets. Off until they exist.

Delivery is **once per alert**, enforced by a committed fingerprint per alert id
([`data/notifications_state.json`](../data/notifications_state.json)), and every run
writes a committed report under `data/notifications/`. A failed send is recorded as
failed and retried on the next run — it is never recorded as delivered.

**Every route projects into the same site feed.** That was a real defect, not a
design choice: the published page reads `data/alerts.json`, both detection routes
wrote elsewhere, and the live Alerts tab said *"No alerts yet"* while three alerts
were committed in the repository. `alerts.write_site_feed()` now exists on both
sides, de-duplicated by record id, preserving `created_at` on re-emit so a re-run
cannot make an old alert look new. Regression tests:
[`tests/test_alert_feed.py`](../tests/test_alert_feed.py).

---

## 3. What cannot be detected automatically — measured, not assumed

1. **Video review as a cause.** The observed event vocabulary
   ([`data/schema/observed_vocabulary.json`](../data/schema/observed_vocabulary.json))
   lists 10 `typeDescKey` values — `period-start, faceoff, stoppage, hit, giveaway,
   takeaway, shot-on-goal, missed-shot, blocked-shot, goal` — and
   `review_event_types_found: []`. There is no review event to read. An overturned
   goal is still detectable *as a state change*; the reason stays empty and the
   record is flagged. **The site deliberately offers no "video review" filter**,
   because a filter that can never match honestly is a lie about capability.
2. **Why the league changed a *scoring credit*.** The Situation Room feed explains
   every review ruling (4,406 statements ingested, raw text committed), so a
   goal↔no-goal reversal carries the league's own words and rule citations. Scorer
   and assist corrections have **no** equivalent feed: `reason.text` is filled only
   when an official artifact states it in words, which so far means the three records
   built from `OFFICIAL SCORING CHANGE` posts. Everything else keeps `null` plus a
   flag.
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

The database holds **1,470 records** (2026-10-07): 1,342 goal→no-goal and 123
no-goal→goal reversals from the official Situation Room feed, 3 attribution-only
corrections from the league's own scoring-change announcements, 1 assist conflict and
1 goal-line review. **1,400 are `verified`, 53 are `flagged` for a human, 17 are
`retired`** (kept, marked, never silently deleted).

The three attribution-only records below were the first the project had, and they
remain the only class whose *reason* is an official announcement rather than a review
statement. All are 2024-25, re-verified line by line on 2026-10-07 (transcripts in
[`data/evidence/reverify-2026-10-07/`](../data/evidence/reverify-2026-10-07/)):

| Record | Change | Confirmed today against |
| --- | --- | --- |
| `NHL-20242025-021140-01` | scorer **Timo Meier → Dawson Mercer**, 6:50 P1 | `GS021140.HTM` row 2 (character for character) + footer `2025-03-27 8.23.23` + GameCenter event 146 |
| `NHL-20242025-021185-01` | assists resolved to **Cole Smith + Michael McCarron**, 9:02 P3 | `GS021185.HTM` row 12 (character for character) + `Start 7:09 EDT; End 9:43 EDT` |
| `NHL-20242025-021238-01` | assist **Parker Wotherspoon → Morgan Geekie**, 9:38 P1 | GameCenter event 324 (Geekie, `assistsToDate` 23) + Wotherspoon at 6 in the same game |

Two honest consequences:

- **A goal-count change *relative to the call on the ice* is now common** — 1,465 of
  the 1,470 records change the goal count in that sense, because an overturned call
  changes what the scoreboard said. **A goal added or removed *after the game was
  final* has still never been observed.** That is the class that would move a settled
  market, and it remains unobserved rather than disproved. The record's own
  `settlement_window` field keeps the two apart (`in_game` versus post-final), and the
  notification quotes that field instead of paraphrasing it.
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

## 7. The gap that mattered most, and what is left of it

**Raw captures are now committed for the Situation Room line.** The 0.5.0 parser
stores the league's own text for every statement — **4,406 of 4,406** entries in
[`data/situation_room/rulings.json`](../data/situation_room/rulings.json) carry `raw`
— so a claim about a ruling can be re-read from the repository instead of being
trusted. That is the direct answer to the §5 withdrawal: the record that failed
re-verification failed because a paraphrase had been stored instead of the payload.

What remains of the gap: the **HTML report line** still stores quoted rows rather than
the bytes, so a claim about a game-night scoring summary is verifiable only by
re-fetching the document. `store.validate()` does not yet refuse `verified` for a
record whose quote has no committed capture behind it.

---

## 8. Bottom line

- **Possible and built:** continuous detection over the league's own review-statement
  feed (4,406 statements, February 2016 → today) plus the game-record census that
  reaches back to 2000-01; typed classification (goal-count vs attribution-only);
  the league's own reason and rule citation for every review ruling; settlement
  exposure quoted from the record; and delivery to a feed, RSS, GitHub issues,
  webhook and e-mail — deduplicated, reported, with an official URL on every alert.
- **Not possible from official sources:** the *cause* of a **scoring-credit** change
  (no corrections feed exists; probed 404), an authoritative correction timestamp, a
  retracted goal with no prior capture, independent verification from a second
  witness (the HTML sheet and the GameCenter JSON are one dataset rendered twice),
  and anything before 2000-01.
- **Demonstrated:** 1,470 records and one delivered notification
  ([issue #18](https://github.com/buffedlizard55-lab/ScoringDiscrepNHL/issues/18)).
- **Not yet demonstrated:** a goal added or removed *after the game was final* — the
  only class that can move a settled market. 1,470 records is coverage of the review
  class, not proof about the post-final class.

Related: [NOTIFICATIONS.md](NOTIFICATIONS.md) · [FEASIBILITY.md](FEASIBILITY.md) ·
[LIMITATIONS.md](LIMITATIONS.md) · [SITUATION_ROOM.md](SITUATION_ROOM.md) ·
[DETECTION.md](DETECTION.md) · [COVERAGE_AND_LIMITATIONS.md](COVERAGE_AND_LIMITATIONS.md)
