# Limitations

This document is deliberately blunt. It lists what the system can prove, what it can only suspect, and what
it can never know. The prompt for this project asked for exactly this list, and a system that hides its
limits is worse than no system at all. Every measured claim here traces back to
[`data/reference/verified_facts.json`](../data/reference/verified_facts.json).

---

## 1. Is a detector even possible?

**Yes — as change detection, not as mind reading.** The official NHL artifacts carry no "corrected" flag, no
revision number and no published change history. What they do have is *state*, and state can be captured.
If we capture the official state of a game and later capture it again and something differs, a discrepancy
provably happened, with the two captured states as evidence. That is what this system does, and it is the
only formulation of the problem that is fully defensible.

Everything else is reconstruction:

| Question | Can it be answered automatically? | How |
|---|---|---|
| Did the scoring record change? | **Yes** | diff of two captured official states |
| What changed (goal count vs attribution)? | **Yes** | typed diff of goals, scorers, assists, strength |
| When did it change, relative to the game? | **Yes, bounded by poll times** | the game state at each capture |
| Could it affect a settled total? | **Yes, as a flag** | change type + whether the previous capture was already final |
| *Why* did it change? | **No** | only if an official artifact states it in words |
| Did a bookmaker regrade anything? | **No** | private house rules |

## 2. What cannot be detected automatically

1. **Video review as a cause.** No machine-readable Situation Room feed was located, and the observed event
   vocabulary in the official play-by-play contains no review event type (measured 2026-10-07, committed at
   `data/schema/observed_vocabulary.json`). An overturned goal *is* detected — as a goal-removed state
   change — but the *reason* stays `null` with the flag `reason_not_stated_in_official_source` unless an
   official artifact says so. Consequence: the website has **no** "video review" filter, because offering a
   filter that can never match accurately would be a lie about capability.
2. **Changes that were superseded between two polls with no archive snapshot from before the change.** If a
   goal is credited to player A at 20:14, changed to player B at 20:16 and we polled at 20:12 and 20:20, we
   see nothing. The archive method cannot help if every snapshot postdates the correction.
3. **Pre-report-era history.** The official HTML report path serves nothing at `19992000` (verified 404) and
   serves documents from `20052006` (verified 200). Anything before the earliest serving season has no
   machine-readable official source in this family, so it cannot be part of the database without a different
   primary source.
4. **Games whose official documents are complete but whose *attribution* is only in a document layout the
   parser does not yet handle.** The parser is header-driven and version-tolerant, but old formats differ
   (the 2005-06 Event Summary has no per-player G/A columns at all). Unparsed documents produce an empty
   goal list **plus a warning** — never a silent zero.
5. **Independent verification of the same fact.** The JSON API and the HTML documents are the same official
   data rendered twice (proved by matching player ids on 2026-10-07). They are one witness, not two. A record
   that cites both is not "double-verified"; the field `evidence_status` says which states were captured, and
   the site shows it.
6. **Any change in a league, competition or feed that the NHL does not publish.** Out of scope by
   construction.

## 3. Source and feed limitations

| Source | Limitation |
|---|---|
| `api-web.nhle.com/v1/gamecenter/{id}/play-by-play` | No revision history and no "this was corrected" marker: you get the current state or nothing. Payload is large (a full game is ~17 chunks of text), so polling cost scales with the slate size. |
| `api-web.nhle.com/v1/gamecenter/{id}/boxscore` | Aggregated per player; useful as a cheap fingerprint and cross-check, but it cannot tell you *which* goal changed. |
| `nhl.com/scores/htmlreports/...GS…HTM` | The document is overwritten when the league regenerates it (verified: a 2023-10-10 game's report was regenerated on 2024-02-06). The generation timestamp is in the footer, which is how the system distinguishes "frozen original" from "regenerated current". |
| `nhl.com/scores/htmlreports/` (index) | Returns **403**; seasons cannot be enumerated from it. Season folders must be probed directly. |
| No `SC…` report | A `SC`-family document does not exist (verified 404), so there is no official "scoring change" report to read. |
| Wayback CDX and snapshots | Coverage is uneven; 2006-era captures of official reports are often HTTP 302 redirects with an empty digest (`3I42H3S6NNFQ2MSVX7XZKYAYSCX5QBYJ`) and are rejected. Most games have zero or one usable snapshot. |

## 4. Latency

* The public feed's update cadence is not published. **Measured latency: not established** — the pipeline
  records `retrieved_at_utc` for every capture, so latency becomes measurable over time, but no figure may be
  quoted yet.
* GitHub Actions cron runs every 5 minutes but can be delayed at busy times; treat the practical cadence as
  "within ~10 minutes", not real-time.
* Between the on-ice ruling and the first official publication there is an unknown gap. A correction that
  happens *inside* that gap is invisible to any poller — which is precisely why the archive-based census
  matters.

## 5. Historical coverage

| Era | Status | Consequence |
|---|---|---|
| ≥ 2023-24 | reports **regenerated in place** | the live document holds the *current* state; the original state is only recoverable from an archive snapshot taken before the correction |
| ≤ 2016-17 | reports **frozen at game time** (verified) | the live document holds the *original* state, so diffing it against the current API exposes later changes |
| 2017-18 … 2022-23 | **unknown** | the transition season is not bracketed tighter than 2016-17 .. 2023-24; must be measured before the census can be called complete |
| 1999-2000 | 404 (verified) | not available in this document family |
| earliest serving season | between 1999-2000 and 2005-06 | measured by the coverage job, never assumed |

## 6. Cases that still require human verification

1. **A reason that exists only in a press conference, a broadcast or a beat-writer's feed.** The system will
   detect the state change and leave the reason empty. A human adds it *with the official link* or it stays
   empty.
2. **Conflicting official artifacts.** When two official renderings disagree and neither is a superseded
   snapshot, the record gets `evidence_status = conflicting` and is not resolved automatically.
3. **Settlement regrades.** The system flags "a settled market was graded on a superseded number"; whether an
   operator regraded it depends on house rules that must be checked with the operator.
4. **Name collisions in the frozen era.** Frozen documents carry sweater numbers and surnames without player
   ids; mapping them to ids must refuse to guess when the roster is ambiguous.
5. **The two secondary leads** listed under `secondary_leads_not_evidence` (a 2026 playoff goal-attribution
   change, and the own-goal tracking claim). Neither may be promoted to a record until an official artifact
   is retrieved.

## 7. Cost and scale

A full census means tens of thousands of official document fetches (roughly 1,300 games per regular season ×
seasons × report kinds) plus a throttled CDX query per game. This is a batch job with polite rate limiting,
not a live request path — which is why the system is built around a scheduler and committed JSON rather than
an on-demand API.
