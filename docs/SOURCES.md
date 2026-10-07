# Official sources

Read this together with `python -m nhl_monitor sources` (the machine-readable registry, regenerated into
`data/reference/sources.json` at site build time) and
[`data/reference/verified_facts.json`](../data/reference/verified_facts.json) (the evidence ledger).

## Source hierarchy

1. **Official NHL artifacts** — the only things that may appear in a record's `sources[]`:
   * `api-web.nhle.com/v1/gamecenter/{id}/play-by-play` and `/boxscore`;
   * `nhl.com/scores/htmlreports/<season>/GS…HTM` (Game Summary), `ES` (Event Summary), `PL`
     (Play-by-Play), `RO` (Club Playing Roster);
   * archived copies of those exact documents (Wayback `…id_/<original url>`), which are official bytes with
     a third-party timestamp — the timestamp is what makes them evidence of an *earlier* state.
2. **Official announcements** (newsroom items, league press releases) — allowed only to fill `reason.text`,
   and only verbatim with the link.
3. **Never evidence** — media, blogs, social posts, wikis, third-party stat sites. They may appear in
   `secondary_leads_not_evidence` as a candidate to verify, and nowhere else.

## The report family

| Kind | Document | Authoritative for | Notes |
|---|---|---|---|
| `GS` | Game Summary | the scoring record: goal, period, clock, strength, scorer, assists, by-period totals, officials | the key document; carries the generation timestamp in the footer |
| `ES` | Event Summary | per-player G/A/P, TOI, shots and faceoff summaries | layout changed over the years (the 2005-06 version has no per-player G/A columns) |
| `PL` | Play-by-Play | chronological events with on-ice skaters | used to reconstruct context around a corrected event |
| `RO` | Club Playing Roster | lineups, scratches, coaches, game officials | supplies officials for the record |
| `SC` | — | — | **does not exist** (verified HTTP 404 on 2026-10-07) |

URL shape: `https://www.nhl.com/scores/htmlreports/<season>/<KIND><game_type:02d><game_no:04d>.HTM`
where `season` is `20232024`-style, `game_type` is 1 pre-season / 2 regular season / 3 playoffs, and
`game_no` is the last four digits of the ten-digit game id. `sources.report_url()`,
`sources.season_folder()` and `sources.split_game_id()` implement exactly this and are unit-tested.

## Why there is no "scoring change" feed

The brief asked to search the Situation Room and official scoring summaries. What exists:

* **Situation Room**: no public machine-readable feed was located. Review *outcomes* surface as goal state
  changes in the official record (that is detectable); the *reason* rarely appears in a machine-readable
  place (that is not).
* **Official game reports**: exactly the GS/ES/PL/RO family above, which is what this system reads.
* **Official team reports**: club-published documents are not part of the NHL's own report family and are not
  used as evidence, because they are not stable or uniformly addressable.

## Verification status used in the registry

| Status | Meaning |
|---|---|
| `verified` | fetched and cross-checked against another official artifact; the observation is recorded in the ledger |
| `reachable_at_runtime` | the document family is verified, but each individual game document must still be fetched and validated before use |
| `unverified` | implemented defensively; must not be cited until the pipeline confirms it |
