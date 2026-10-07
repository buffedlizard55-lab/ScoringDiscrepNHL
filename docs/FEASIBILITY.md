# Feasibility: can this actually be detected?

The project brief asks for "explicit analysis of limitations and whether this is
even possible". This file is that analysis. It is written as a set of claims with
the evidence behind each, because a feasibility study you cannot check is
decoration.

Everything below was established by probing the live endpoints (2026-10-07, from
a network-restricted sandbox, so status codes were read through a text proxy
rather than raw sockets) and by reading the artifacts themselves. HTTP results are
listed per-URL in [SOURCES.md](SOURCES.md).

## 1. Verdict

| Capability | Verdict | Why |
| --- | --- | --- |
| Find disagreements between the NHL's own published artifacts for one game | **Achievable, working** | Two independent renderings of the same goal exist (HTML sheet, JSON game center) and they are produced by different code paths. C10-C17 compare them. One real record in the seed database came out of this. |
| Detect a correction *after* it happens | **Achievable, working, but only going forward** | The league edits the JSON in place with no version header. The only way to see an edit is to have kept a copy. `snapshot.py` stores state-change-only digests in git, so the git history *is* the audit trail. |
| Detect a goal / no-goal change from history alone | **Not achievable** | An overturned call leaves no trace in the final record. The box score of a game where a goal went goal → no-goal → goal shows exactly one goal. |
| Recover a *retracted* goal from public data | **Only from our own snapshots or live TV** | Requires having polled the game while it was in progress. See section 3. |
| Know *when* a correction was made (authoritative timestamp) | **Not achievable** | The only timestamps in the artifacts are the report generation stamp and the feed's own game clock. Neither is a correction timestamp. |
| Get a league-published corrections feed | **Does not exist** | No public endpoint exposes correction or version history. Searched and probed: see section 4. |
| Flag records whose evidence is thin | **Achievable, working** | Every record carries `status`, `confidence`, `flags`, and a per-source `evidence` grade. Validation refuses `verified` without a primary source and a timestamp. |
| Feed a real-time alerting pipeline | **Partially** | GitHub Actions scheduling is delayed and coarse (15 min floor); true in-game alerting needs the self-hosted runner path in STATUS.md. |

## 2. Why goal / no-goal changes are invisible in the record

This is the central obstacle, so the chain of reasoning is explicit:

1. The official scoring artifacts (GS sheet, `summary.scoring` in the game center
   JSON) record **final credited goals**. Neither has a field for a prior ruling.
2. The RTSS play-by-play feed has no event type for a video review or a coach's
   challenge. A third-party history of the feed describes 26 RTSS event types
   against 16 in the modern API (`puckovertheglass.substack.com/p/a-brief-history-of-nhl-play-by-play`,
   secondary, read 2026-10-07). Nothing in either is "call overturned".
3. Therefore a play that was waved off and then awarded appears **once**, as a goal,
   with the goal's period and clock - indistinguishable from a goal that was never
   questioned.
4. Conversely a goal that was disallowed appears **zero** times. There is nothing to
   diff against.

Consequences for this project:

- The only reliable in-band signals for a ruling change are (a) the two official
  artifacts disagreeing about whether a goal exists at all (C10 - that is a real
  signal: the sheet is a frozen post-game artifact, the JSON is live-edited, so a
  post-game correction shows up as a missing goal in one and not the other), and
  (b) our own before/after snapshots (C21).
- Everything else about rulings has to come from *text*: the Situation Room's
  explanations, the on-ice official's post-game remarks, or a rules analyst's
  write-up. Those are published for some plays and not others, on no schedule,
  with no API. `alerts.parse_situation_room_text()` will extract quoted rulings from
  such a page when one exists; it cannot conjure one when it does not.
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

## 4. Searches that came back empty

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
