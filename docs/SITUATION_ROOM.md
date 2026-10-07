# The official Situation Room feed

Status: **verified live on 2026-10-07**; ingested by `pipeline/nhl_scoring/situation_room.py`;
facts recorded as F30-F32 in `data/reference/verified_facts.json`.

Earlier documents in this repository said that no machine-readable Situation Room
or video-review source existed and that the play-by-play carried no review marker.
Both statements were wrong, and they were wrong because they were measured on one
game that had no review. This page is the corrected account, with the evidence.

## 1. What the league publishes

For every coach's challenge and every Situation Room video review the NHL posts a
short official statement on nhl.com. The statements are stories tagged
`situation-room` in the league's public content API:

```
https://forge-dapi.d3.nhle.com/v2/content/en-us/stories?tags.slug=situation-room&$limit=100&$skip=N
https://forge-dapi.d3.nhle.com/v2/content/en-us/stories/<slug>        (one statement, full text)
https://www.nhl.com/news/<slug>                                         (the public page)
```

Measured size and span (2026-10-07): about **4,404** statements, newest first,
from **2016-02-01** (the first was the All-Star Game challenge; the first regular
season statements are 2016-02-02/03) to the current night's games. `$skip >= 4405`
returns an empty page. That matches the introduction of the coach's challenge in
2015-16; there is no official statement feed for reviews before that.

Each statement carries:

| Field | Example | Used for |
| --- | --- | --- |
| `headline` | `Coach's Challenge: NSH @ TOR - 11:49 of the Third Period` | kind, teams, period, clock |
| `parts[].markdown` (2019 onwards) | `**Challenge Initiated By:** Nashville` / `**Type of Challenge**: Off-Side` / `**Result:** Call on the ice is overturned - No Goal Toronto` / `**Explanation:** ...` | who, what, the verdict, the rule, the reason |
| `parts[].markdown` + `fields.description` (2016-2018) | prose paragraph + `Review overturns call of no goaltender interference, no goal Panthers` | the same, in prose |
| tag `gameid-<10 digits>` with title `NSH@TOR 10/06/2026 07:00PM` | | game id, game date, teams |
| `contentDate`, `lastUpdatedDate` | `2026-10-07T01:41:00Z` | publication latency |

A minority of statements lack the `gameid` tag (example:
`edmonton-oilers-vancouver-canucks-video-review-x7720`); those are resolved by
matching the headline teams against the official daily scoreboard
(`api-web.nhle.com/v1/score/<date>`) for the two calendar dates the UTC timestamp
can belong to, and flagged `game_id_resolved_from_schedule`.

## 2. Measured latency

| Statement | Play | Published (`contentDate`) | Latency |
| --- | --- | --- | --- |
| CGY @ VAN, 1:28 of the third, 2026-10-03 (10:00 PM ET start) | ~04:2x UTC | 2026-10-04T04:36:03Z | minutes |
| EDM @ VAN, 4:43 of the third, 2026-10-01 | ~04:1x UTC | 2026-10-02T04:34:00Z | ~20 minutes |
| NSH @ TOR, 11:49 of the third, 2026-10-06 (7:00 PM ET start) | ~01:3x UTC | 2026-10-07T01:41:00Z | minutes |

So the league's own statement is available **during the game, within minutes**.
End-to-end alert latency is therefore dominated by how often the ingest runs, not
by the source (see section 6).

## 3. What the ingest does with a statement

1. **Parse** headline (kind, teams, period, clock), structured fields or prose,
   `gameid` tag, rule citations (`Rule 38.9`), clock-reset notes.
2. **Classify** the outcome:
   * `overturned` - the on-ice call was changed. Explicit `Result: ... overturned`,
     or an explicit on-ice call in the text (`the call on the ice was "good goal"`,
     `The Referees initially ruled goal`) that differs from the result.
   * `upheld` - `upheld`, `confirmed`, `stands`, `supported the Referee's call`.
   * `on_ice_call_not_stated` - the statement gives a result (`Goal Vancouver`)
     but never says what the on-ice call was. **No change is inferred by the
     parser.** The CGY @ VAN Ohgren review is this case: the text says the
     Situation Room reviewed whether the puck crossed the line and that it did;
     it does not say the referee had waved it off. Such cases can be settled by
     a *documented human read* (step 2b) when an official page states the on-ice
     call - for Ohgren the league's own NHL.com game recap does ("initially waved
     off on the ice").
   * `unclassified` - no result phrase recognised (expected to be rare; counted
     and shown, never hidden).
   Verdict words are never read from quoted rule text: every modern statement
   quotes Rule 38.1 (*"the original call on the ice will be overturned if, and
   only if ..."*), and the 2016 statements quote Rule 78.7 (*"The standard for
   overturning the call ..."*).
   When the on-ice call is only implied by an infraction (*"initially ruled that
   Rossi batted the puck into the net with his glove"*) the classification is
   `overturned` with `medium` confidence and the record stays `flagged` for a
   human read.
2b. **Documented human reads** (`data/curation/situation_room_human_reads.json`).
   A read supplies **only the on-ice call** for one statement (by slug), with the
   source that states it, a verbatim quote, who read it and when. The ingest
   applies the file on every run: the ruling becomes `overturned`/`upheld`
   accordingly with `high` confidence, flag `on_ice_call_from_documented_human_read`,
   the read and its sources are copied onto the record (`verification.human_read`,
   `sources[]`), and the play-by-play cross-check still has to agree before the
   record is `verified`. A read can never override an on-ice call the statement
   states explicitly (ignored, flag `human_read_contradicts_statement_ignored`),
   and deleting a read returns the row to the parser's own reading on the next
   run. This is the "cases needing human verification" path from the brief,
   made reproducible instead of hand-typed.
3. **Cross-check** every `overturned` statement against the official play-by-play
   for the game. The play-by-play marks reviews as stoppages:
   `details.reason` / `secondaryReason` = `video-review`, `chlg-vis-off-side`,
   `chlg-vis-goal-interference`, and by the league's naming the `chlg-hm-*` /
   `chlg-league-*` forms (matched on the `chlg-` prefix). A goal awarded on review
   must exist at the stated period/clock; a goal disallowed on review must be
   **absent** from the final record (it is removed, not annotated) with a review
   stoppage within 150 s. `agree` / `conflict` / `inconclusive` is stored on the
   record with the play-by-play URL and hash.
4. **Record.** Only `overturned` statements become rows in
   `data/discrepancies.json` (`detected_by: league_statement`, check `SR1`,
   `change_type` `goal_overturned_to_no_goal` or `no_goal_overturned_to_goal`,
   `goal_no_goal_change: true`, `video_review: true`, `when_corrected: in_game`).
   Status is `verified` only when the classification is high-confidence **and**
   the play-by-play agrees - two independent official artifacts - otherwise
   `flagged` with the reason (`awaiting_pbp_crosscheck`,
   `pbp_crosscheck_inconclusive`, `pbp_conflicts_with_situation_room_statement`,
   `needs_human_read_of_on_ice_call`).
   Both states are preserved: `initial_state` is the on-ice call, `corrected_state`
   the official ruling with the scorer/assists/score from the play-by-play when the
   goal stands.
5. **Ledger.** Every statement, whatever its outcome, is kept in
   `data/situation_room/rulings.json` with its classification, flags, cross-check
   result and official link, and is browsable on the site ("Situation Room log").

## 4. What this covers and what it does not

Covered, from the league's own words, 2016-02 onward:

* goal on the ice overturned to no goal (off-side, goaltender interference,
  kicked/batted puck, high stick, net off, missed stoppage, time expired);
* no goal on the ice overturned to goal (puck over the line, legal deflection);
* the reason and the rule the league cited, verbatim;
* the kind of review (coach's challenge vs league/referee video review), who
  initiated it, and the clock reset when an off-side wipes out time.

Not covered by this source (and not pretended):

* **scorer and assist changes** - the Situation Room does not rule on credit;
  there is no official feed for those (the engine's snapshot diff and
  cross-source checks are the only automated path);
* reviews whose statement never states the on-ice call (`on_ice_call_not_stated`)
  - counted and listed, not turned into records unless a documented human read
  with an official source for the on-ice call is added (section 3, step 2b);
* anything before February 2016, and any review the league did not write up
  (the feed is complete for challenges and Situation Room reviews by design, but
  that completeness is the league's claim, not something this project can prove);
* the exact on-ice *scorer* of a disallowed goal (the goal is removed from the
  official record; the explanation sometimes names the player, the record stores
  the explanation verbatim rather than parsing a name out of it).

## 5. Market relevance

Every overturned call changes the number of goals **inside the game**: a goal was
announced and then taken away, or waved off and then awarded. Records therefore
carry `market_impact.affects_game_total: yes` with `settlement_window: in_game`:
live totals, period totals and anytime-scorer markets that moved on the on-ice
call were exposed; the post-game box score already reflects the ruling, so a
settlement made from the final official record is not affected. The project does
not claim any market was mis-settled.

## 6. Cadence and alerting

`.github/workflows/situation-room.yml` runs the ingest in incremental mode (first
pages until nothing new), validates, renders alerts (`data/alerts/`), rebuilds the
site and commits. It is scheduled twice an hour, but GitHub's cron is best-effort
and this repository measured **one scheduled run in eleven hours** against a
`*/5` request (F32). Anyone who needs minutes-level alerts should trigger the
workflow from an external scheduler:

```
gh workflow run "Situation Room ingest" --ref main
# or POST /repos/buffedlizard55-lab/ScoringDiscrepNHL/actions/workflows/situation-room.yml/dispatches
```

On a branch where the dispatch API cannot see the workflow, committing
`data/situation_room/run_request.json` (`{"mode": "incremental"}`) starts a run.
