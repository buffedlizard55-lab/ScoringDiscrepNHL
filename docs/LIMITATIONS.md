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
| *Why* did it change? | **Yes for review decisions (official statement, verbatim); no for scorer/assist edits** | Situation Room statement text; otherwise only if an official artifact states it in words |
| Did a bookmaker regrade anything? | **No** | private house rules |

## 2. What cannot be detected automatically

1. **Video review as a cause - corrected 2026-10-07.** This item originally said no machine-readable
   Situation Room feed existed and that the play-by-play had no review marker. Both were measured on one
   game without a review and are wrong: the league publishes an official statement for every challenge
   and video review (content API, tag `situation-room`, continuous since 2016-02) and the play-by-play
   marks reviews as `chlg-*` / `video-review` stoppages. See `docs/SITUATION_ROOM.md` and verified facts
   F30-F31. What remains true: the statement sometimes gives the result without the on-ice call
   (`on_ice_call_not_stated`), in which case no change is inferred; and nothing of the kind exists for
   **scorer / assist** corrections, whose reason stays `null` unless an official artifact says so. The
   website's "video review" filter is backed by the statements, not by inference.
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

Measured archive reach (2026-10-07, facts F19–F21 in `data/reference/verified_facts.json`):
the Internet Archive holds 2000-01 Game Summaries but its earliest capture of that season
is from 2012, so for the first seasons of the documented era a correction made before
2012 cannot be recovered from any capture. Where two or more captures straddle a change,
the comparison now yields both states from the league's own documents, and the rewrite is
bracketed between capture timestamps rather than assigned an invented moment. The
per-season ceiling is what `archive-yield` measures; the full mechanism is in
[`docs/BACKFILL.md`](BACKFILL.md).

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

## Limits specific to the announcement-ingest path (added in pass 3)

The ingest path (`python -m nhl_monitor ingest`) builds records from the league's own scoring-change
announcements. It closes the "before monitoring started" gap, but each of its limits is real and is stored on
the record rather than hidden:

| Limit | What it means | How the project handles it |
|---|---|---|
| The announcement states the **new** credit, not the old one | "now reads X from Y" proves the record changed and who is credited now; it does not prove what it read before | three-state comparison (`same` / `changed` / **indeterminate**). "Not documented" never becomes "nothing changed". `assists_before_the_change_not_captured` is a first-class flag |
| The superseded credit often survives only in secondary reporting | for two of the three shipped records the pre-change credit comes from a syndicated reproduction | the record says `initial_state_reported_by_secondary_source_only` and the drawer shows it next to the official evidence |
| The announcement channel has no supported API | the posts were retrieved here through the platform's page-fetch tool | the post URL is stored and its retrievability is recorded per source; automatic retrieval on a runner is roadmap P1-17 |
| Announcement text can be reproduced with small differences | one reproduction renders the same statement with a dash after the game number; one misspells a player's name twice | the primary post is stored as the announcement text; the reproduction is stored as a separate named source with its wording preserved |
| The offset between the *feed* flipping and the *announcement* | not measurable retrospectively | prospective measurement is the monitor's job; the record only claims what its timestamps support |
| The report footer has no documented timezone | a rebuild time cannot be converted to UTC, and cannot be compared across sources with confidence | footer timestamps are stored verbatim, and the records say so |

## What has *not* been demonstrated

* **No goal-count-changing correction has ever been found.** All three records are attribution-only, so the
  class that would move a game total is, so far, unobserved rather than disproved. The detector handles it
  (`goal_added` / `goal_removed` are the only two change types that set `affects_goal_total`), and the site
  keeps a separate view for it that is currently empty on purpose.
* **No in-game announced-then-overturned goal has been found.** The official play-by-play contains no review
  event, and the Game Summary records only the final ruling, so this class is not detectable from the
  official machine-readable sources reviewed here.
* **No pre-2000-01 material.** The official report host 404s on 1999-2000 and no alternative official
  historical source was located.
