# Methodology

How a fact becomes a record, and what stops a parser bug from becoming a fake
discrepancy.

## 1. Pipeline

```
 date / game id
      |
      v
 [fetch]      Fetcher: urllib, throttled, retried, content-addressed cache
      |        -> FetchResult{url,status,sha256,retrieved_at,path}
      v
 [parse]      parse_api_landing / parse_gs_report / parse_api_right_rail
      |        -> SourceRecord{goals[], totals{}, parse_ok, parse_notes[]}
      v
 [compare]    compare_sources(GS, API)  -> C10..C17   (cross-source)
      |        check_record(rec)         -> C1..C9     (intra-source arithmetic)
      |        diff_snapshots(b, a)      -> C20..C22   (temporal, same URL)
      v
 [build]      db.record_from_finding()  -> both states, sources, market impact
      |
      v
 [validate]   db.validate()             -> refuses records with holes in them
      |
      v
 [merge]      db.upsert()               -> sticky statuses, seen_count, history
      |
 +---------+-------------+
 v         v             v
alerts   site (Pages)   snapshots (git-tracked digests)
```

## 2. Why three engines

- **Cross-source (C10-C17)** is the only engine that can find a *historical*
  correction: the GS sheet is a frozen post-game artifact and the landing JSON is
  edited in place, so a disagreement between them is evidence that something was
  changed on one side after generation. This produced the seed record.
- **Intra-source (C1-C9)** costs nothing and always runs: goal rows must add up to
  the team totals and the BY PERIOD tables, the running score must be monotonic and
  end on the final score, no duplicated rows, clocks inside the period. It catches
  *our* parse errors as reliably as league errors, which is exactly what we want
  before believing anything.
- **Temporal (C20-C22)** is the only engine that can catch a silent edit *with its
  before-state*, and only for games polled from now on.

## 3. Pairing goals across sources

Two goals are the same goal when, in order:

1. `period | clock_seconds | team` matches exactly (the `match_key`), or
2. period + team + scorer surname/initial match and the clocks are within 120 s
   (`goal_clock_conflict`, not two findings), or
3. period + team match and the nearest clock is within 120 s.

Anything unmatched on both sides becomes `goal_missing_from_one_source` **only if
the other side parsed cleanly and the game was not `limitedScoring`**. Bookkeeping is
by index into the right-hand goal list; an earlier version marked "used" by
per-key bucket index, which re-freed already matched goals and manufactured
phantom missing-goal findings on games that agree. Regression test:
`CrossSourceTests.test_clock_drift_matches_by_scorer_not_as_missing_goal` and the
zero-findings control pair.

Names are compared by `surname_tail:initial`, which is why `J.VAN RIEMSDYK`,
`Van Riemsdyk` and `J. van Riemsdyk` are one player and `A. DEADMARSH` vs
`C. DRURY` are not. Where both sources carry `playerId`, the id wins.

## 4. Era handling

| Era | Sheet layout | Consequences |
| --- | --- | --- |
| 2000-01 .. ~2004 | `G, Per, Time, Team, Scorer(n), Assist, Assist, on-ice, on-ice, STR`; dotted abbrevs (`L.A`); no jersey numbers; `(W)(L)(T)` goalie markers; FACE-OFFS or ZONE TIME | totals come from the legacy positional table `Per, awayGoals, homeGoals, Per, awayShots, homeShots`; strength column is last |
| ~2005 .. present | `G, Per, Time, Str, Team, Scorer, Assist, Assist, {AWY} on Ice, {HOM} on Ice`; jersey numbers; `EV-EN` style | BY PERIOD blocks are per team (`MTL on Ice` header binds the block to a club) |

The layout is *detected* per file (`header[team_col-1] == 'str'`), never assumed from
the season, because a regenerated file can differ from its neighbours. Clocks are
read as printed; `2:00` and `02:00` normalise to the same seconds - a fix that
prevented a fabricated `goal_missing`/`goal_added` pair on every early-minute
historical goal.

**Totals binding is conservative.** If a BY PERIOD table's totals disagree with the
goal rows, the parser refuses to trust the table: it records a note, skips the
totals-based checks for that team, and does not label GS rows away/home (nothing in a
GS sheet says which club is home; guessing by "who scored first" was removed as
unfalsifiable).

## 5. Market / settlement exposure

`market.classify()` maps a change to `total_changed` plus four tri-state fields
(`affects_game_total`, `affects_period_total`, `affects_player_props`,
`affects_result_markets`) and a `risk` level, from the *rule class* of the change:

- total-affecting rules (`goal_added`, `goal_removed`, `goal_no_goal_*`,
  `nogoal_reversed_*`, `final_score_conflict`, `post_snapshot_goal_count_change`)
  -> `yes`
- attribution-only rules (`assist_added/removed/moved`, scorer re-credit)
  -> `no` for game totals, `yes` for player props (an assist is a prop)
- timing-only rules (`goal_clock_conflict`) -> `no`, with a note for
  period-total-to-the-second and last-goal props
- anything else -> `possible`/`unknown`, never `no` by silence

The classification is deliberately not a claim about any sportsbook's rules: no
public NHL feed contains settlement lines. It says which *class of outcome* moved.

## 6. Snapshot discipline

`record_snapshot()` appends a digest **only when the state changed**; unchanged polls
bump a counter in `polls.json`. Why: `data/snapshots/` is committed to git, and a
poll file that rewrites identical digests every 15 minutes would bury the one line
that matters in history and make the audit trail unreadable. Digest = sorted goal
tuples (period, clock, team, scorer key, assist keys, strength, own/EN) + per-team
totals + game state.

## 7. Alerts

`alerts.triage()` ranks by rule (a goal-count change in a live game is `immediate`;
an attribution conflict is `review`; a clock drift is `info`), dedupes by record id,
renders markdown + JSON to `data/alerts/<date>/`, optionally POSTs to a webhook
(`SDN_WEBHOOK`) and can open a GitHub issue. A record whose `total_changed` is null
is still alerted - "we cannot tell yet" is the urgent case, not the dismissable one.

## 8. Deliberate non-goals

No scraping of paywarded content; no bulk mirroring of unlicensed third-party data;
no storing of raw HTML in git (cache lives outside the repo, digests are what we
keep); no auto-"correction" of anything - this project publishes *discrepancies with
links*, never a rewritten box score.

## 9. Commands

```bash
python3 -m nhl_scoring.cli scan --games "2000020001,2000030162" --fixtures tests/fixtures --out out/findings.json
python3 scripts/backfill.py --season 20252026 --max-dates 10 --out out/ids.txt   # needs network
python3 -m nhl_scoring.cli scan --games-file out/ids.txt --apply                    # needs network
python3 -m nhl_scoring.cli snap --date 2026-10-14                            # live poll + digest
python3 -m nhl_scoring.cli snapfind --out out/temporal.json
python3 -m nhl_scoring.cli merge --findings out/findings.json --db data/discrepancies.json --apply
python3 -m nhl_scoring.cli validate
python3 -m nhl_scoring.cli alerts --write --webhook "$SDN_WEBHOOK"
python3 -m nhl_scoring.cli site --out docs
python3 scripts/verify_sources.py            # re-check the documented source claims
python3 scripts/seed_records.py              # rebuild the seed database from fixtures
python3 -m unittest discover -s tests -t .   # 74 tests, offline
```
