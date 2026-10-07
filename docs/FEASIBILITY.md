# Feasibility: can this actually be detected?

The project brief asks for "explicit analysis of limitations and whether this is
even possible". This file is that analysis. It is written as a set of claims with
the evidence behind each, because a feasibility study you cannot check is
decoration.

Everything below was established by probing the live endpoints (2026-10-07, from
a network-restricted sandbox, so status codes were read through a text proxy
rather than raw sockets) and by reading the artifacts themselves. HTTP results are
listed per-URL in [SOURCES.md](SOURCES.md).

**Revision 2026-10-07 (later session).** Sections 1, 2 and 4 originally said that
no review marker exists in the play-by-play and that no machine-readable Situation
Room source exists. Both were measured on a single game that had no review and
both are wrong: the play-by-play marks reviews as `stoppage` events with
`chlg-*` / `video-review` reasons, and the league publishes an official statement
for every challenge and video review through its content API, continuously since
February 2016. The corrected evidence is in [SITUATION_ROOM.md](SITUATION_ROOM.md)
and `data/reference/verified_facts.json` (F30-F32). The text below has been
amended in place; struck claims are kept so the correction is visible.

## 1. Verdict

| Capability | Verdict | Why |
| --- | --- | --- |
| Find disagreements between the NHL's own published artifacts for one game | **Achievable, working** | Two independent renderings of the same goal exist (HTML sheet, JSON game center) and they are produced by different code paths. C10-C17 compare them. One real record in the seed database came out of this. |
| Detect a correction *after* it happens | **Achievable, working, but only going forward** | The league edits the JSON in place with no version header. The only way to see an edit is to have kept a copy. `snapshot.py` stores state-change-only digests in git, so the git history *is* the audit trail. |
| Detect a goal / no-goal change caused by a review, from history | **Achievable, working (2016-02 onward)** | ~~An overturned call leaves no trace in the final record.~~ The final box score does show one goal or none, but (a) the official Situation Room statement for every challenge/review states the on-ice call, the result and the rule, and (b) the play-by-play keeps a `chlg-*` / `video-review` stoppage at the clock. `situation_room.py` ingests (a) and cross-checks against (b). Before 2016-02 there is no statement feed, so there the original verdict stands. |
| Recover a *retracted* goal from public data | **From the Situation Room statement (2016+); otherwise only from our own snapshots or live TV** | The disallowed goal is removed from the play-by-play, not annotated; the statement is the official record that it was signalled. See section 3. |
| Know *when* a correction was made (authoritative timestamp) | **Not achievable** | The only timestamps in the artifacts are the report generation stamp and the feed's own game clock. Neither is a correction timestamp. |
| Get a league-published corrections feed | **Exists for review decisions; does not exist for scorer/assist corrections** | Review decisions: the `situation-room` statement feed (section 4, SITUATION_ROOM.md). Scorer/assist corrections: no public endpoint exposes a changelog or version history; only @PR_NHL / team notes, which are secondary. |
| Flag records whose evidence is thin | **Achievable, working** | Every record carries `status`, `confidence`, `flags`, and a per-source `evidence` grade. Validation refuses `verified` without a primary source and a timestamp. |
| Feed a real-time alerting pipeline | **Partially** | The source is fast (statements publish within minutes of the play) but GitHub Actions cron is best-effort: this repository measured one scheduled run in eleven hours against a `*/5` request. Minutes-level alerting needs an external trigger of the workflow or a self-hosted runner. |

## 2. Why goal / no-goal changes are invisible in the record

This is the central obstacle, so the chain of reasoning is explicit:

1. The official scoring artifacts (GS sheet, `summary.scoring` in the game center
   JSON) record **final credited goals**. Neither has a field for a prior ruling.
2. ~~The RTSS play-by-play feed has no event type for a video review or a coach's
   challenge.~~ **Corrected:** reviews are not an event *type* but a stoppage
   *reason*: `details.reason` / `secondaryReason` = `video-review`,
   `chlg-vis-off-side`, `chlg-vis-goal-interference` (observed in 2016020214,
   2026020015, 2026020033, 2026020044). The stoppage says a review happened; it
   does not say what the on-ice call was or how it ended.
3. A play that was waved off and then awarded appears **once** in the final record,
   as a goal - distinguishable from an unquestioned goal only by the adjacent
   `video-review` stoppage and by the Situation Room statement.
4. A goal that was disallowed appears **zero** times in the final record; the
   `chlg-*` stoppage and the statement are the only official evidence it was
   signalled. The statement feed is therefore the primary source for these
   records, and the play-by-play is the cross-check.

Consequences for this project:

- The only reliable in-band signals for a ruling change are (a) the two official
  artifacts disagreeing about whether a goal exists at all (C10 - that is a real
  signal: the sheet is a frozen post-game artifact, the JSON is live-edited, so a
  post-game correction shows up as a missing goal in one and not the other), and
  (b) our own before/after snapshots (C21).
- The *reason* for a ruling comes from text, and for reviews that text is
  official and systematic: ~~published for some plays and not others, on no
  schedule, with no API~~ **the league publishes a statement for every challenge
  and video review, within minutes, through a paginated content API**
  (SITUATION_ROOM.md). What remains text-only and unsystematic is the reason for
  a scorer/assist change (post-game @PR_NHL notes, team notes).
- Commercial providers (e.g. Sportradar's live game feed) do expose a
  `challenge{outcome: call_overturned, decision, ...}` object. That is a licensed
  product, not a free primary source, so it is not part of the pipeline; it is
  listed as the known paid alternative.

## 3. What "when the correction occurred" can honestly mean

Requested field: *whether the correction happened during the game, at intermission,
after the game.*

What exists:

| Signal | What it proves | What it does not prove |
| --- | --- | --- |
| GS report footer stamp, e.g. `2000-10-04-22.14.20` | When that HTML file was last generated | When any value in it was changed. Sheets for games in the same week were stamped `2026-09-30-11.59.44` while containing a game finished that night: regeneration timing is not a bound. |
| Difference between our two snapshots of the JSON | That the value changed between our poll N and poll N+1 | That nothing changed in between: polls are 15-60 min apart, and an edit invisible to both polls is invisible forever. |
| Sheet says X, JSON says Y | That the two artifacts disagree | Which is the corrected one. The JSON is normally the *later* one, but it is also the one that is edited for other reasons. |
| Feed event sequence (goal followed by `GOAL_STOP`, no faceoff) | Suggests review delay in games from ~2007-08 on | Anything in older seasons: pre-2007-08 there is no play-by-play to read. |

The data model therefore stores `when_corrected` as a six-value enum
(`in_game`, `intermission`, `postgame`, `next_day`, `unknown`, `not_applicable`)
**plus** `timing_uncertain: true` whenever the value came from an inference rather
than a statement. Roughly: in-game is assertable for a live-monitored game,
`unknown` is the honest default for history, and a report stamp alone never earns
better than `timing_uncertain`.

## 4. Searches that came back empty - and the one that did not

**Found (2026-10-07):** `https://forge-dapi.d3.nhle.com/v2/content/en-us/stories?tags.slug=situation-room`
- the official Situation Room statements, ~4,400 of them, 2016-02 to today, with
`gameid-` tags. `nhl.com/news/topic/video-review` and the Forge tag `video-review`
are dead ends; `situation-room` is the tag that works. Details in SITUATION_ROOM.md.

Recorded so nobody repeats them: `nhl.com/webapi/v1/statspdf` (404),
`statsapi.hockey.com` (unreachable), a version/history parameter on
`api-web.nhle.com/v1/gamecenter/.../landing` (none documented or discoverable),
`club-schedule/{TEAM}/{start}/{end}` (404 - that pattern does not exist, despite
appearing in older third-party notes). The corrections-history hole was confirmed
by absence, which is weaker evidence than documentation: if the league adds such an
endpoint later, sections 1-3 should be re-read.

## 5. Coverage floors (measured, not assumed)

| Source | Earliest observed | Evidence |
| --- | --- | --- |
| Official HTML reports (`/scores/htmlreports/`) | **2000-01 season** | `20002001/GS020001.HTM` → 200 with a legacy-layout sheet; `19992000/GS020001.HTM`, `19992000/GS020002.HTM`, `19992000/GS030001.HTM`, `19981999/GS030001.HTM`, `19941995/GS020001.HTM` → 404. Directory begins at season 20002001. |
| Game center JSON (`api-web.nhle.com`) | **1999-2000 season** | `gamecenter/1999020001/landing` → 200 (its `summary.scoring` is the fallback for pre-2000-01 games). Older seasons were not enumerated; treat "1999-2000" as a floor we verified, not a boundary we mapped. |
| Play-by-play JSON | ~2007-08 with gaps | Not re-verified here; carried from the third-party audit repo and marked secondary. |
| Shift data | 2009-10 with gaps | as above, secondary. |

Practical statement of limits, safe to put on the website:

> Reliability starts 2000-01 (both official artifacts exist). 1999-2000 and earlier
> can be checked against one official artifact only, so cross-source
> goal/attribution conflicts are structurally undetectable there. No official online
> source exists before 1999-2000 at all; anything older needs the printed
> *Official Guide / Record Book* or a newspaper archive, which is manual research by
> definition. Playoff report coverage has holes even inside 2000-01+ (community
> reports of missing `PL` files for `20112012/PL020259`, `20102011/PL020124`,
> `20102011/PL020429`, `20092010/PL020081`) - secondary, unverified by us, kept as
> a known-risk list in STATUS.md.

## 6. What a false negative looks like

The failure mode to respect is not a wrong alert, it is silence:

- Both artifacts regenerated after a correction → the conflict disappears and the
  original state is unrecoverable unless we had a snapshot.
- A correction that keeps every number identical but re-credits a player in *both*
  artifacts → nothing to diff.
- A game where the sheet is missing entirely (404) → zero goals parsed, which the
  pipeline reports as `parse_ok: false` and never as "no discrepancies".
- Own goals before 2022-23: the API has no `goalModifier` for them, so an own goal
  is inferable only from the sheet's `(OWN GOAL)` marker or from the scoring team
  mismatch. C16 is therefore written to fire only when *both* artifacts state a
  own-goal decision explicitly; where the JSON has nothing to say it stays quiet
  instead of inventing a conflict.

Each of those is encoded as a coverage flag in the site's Detection view rather than
pretended away.
