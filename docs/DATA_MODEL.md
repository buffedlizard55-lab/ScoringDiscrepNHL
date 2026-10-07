# Data model

One file is the database: `data/discrepancies.json`. `data/discrepancies.csv` is a
generated flat projection of it (same row count, enforced by a test) for spreadsheets
and quick greps. `data/schema/discrepancy.schema.json` states the contract
declaratively; `nhl_scoring.db.validate()` is the executable version and CI runs it
on every push.

## The rule the whole schema exists for

> Preserve both the original and the corrected state; never average, never pick a
> winner silently, and never fill a gap with an assumption.

So every record has `initial_state` and `corrected_state` as **peer objects with the
same shape**, and a `status` that says how far the claim has been checked. Absence is
a state too: a goal that one artifact does not contain is stored as
`{"goal_present": false, "ruling": "not_recorded_by_this_artifact"}` - not as
`ruling: "no_goal"`, because "the sheet omits it" and "the referee waved it off" are
different facts and only the second is a ruling.

## Top level

| Field | Meaning |
| --- | --- |
| `record_id` | `SDN-<10 hex>` = `sha1("game_id|check_id|field|goal_key")[:10]`. **Derived**, so re-running detection updates the same record instead of minting a near-duplicate. Proven on the seed: a fresh `scan` of the fixture produced `SDN-87fb3e543f`, identical to the hand-seeded record, and `upsert` merged it (`seen_count` 1 -> 2). |
| `schema_version` | `"1.0"` |
| `status` | `verified` / `flagged` / `pending_review` / `disputed` / `retired` |
| `confidence` | `high` / `medium` / `low` |
| `detected_by` | `cross_source` / `snapshot_diff` / `integrity_check` / `manual_research` / `prior_art_log` |
| `sources[]` | mandatory, `minItems: 1`; each with `url` (https), `kind`, `evidence`, `retrieved_at`, `sha256`, `quote`, `note` |
| `flags[]` | machine vocabulary for "what is still wrong with this record" |
| `notes` | free text for the reader |

### Status ladder

- `verified` - a reader opened the official artifact and confirmed both states.
  `validate()` refuses this status without `verification.verified_at`, a
  `game.date`, and at least one `evidence: primary` source.
- `flagged` - a detector fired; nobody has read the artifact yet.
- `pending_review` - entered from research with gaps (a null `game_id`, secondary
  evidence only). Gaps are allowed here and nowhere else, and each gap must be
  named in `flags`.
- `disputed` - sources cannot be reconciled; kept because the disagreement is itself
  the finding.
- `retired` - was believed, no longer is. Never deleted: a retired record is how you
  can audit our own mistakes.

## `game`

`game_id` (official 10-digit), `season`, `game_type`, `date`, `away_team`,
`home_team`, `venue`, `final_score{away,home}`, `gamecenter_url`, `report_urls{}`.
`report_urls` is filled from the right rail's `gameReports` when available - the
league's own list of which artifacts exist - and only from constructed URLs as a
fallback, which is recorded in `notes` rather than presented as fact.

## `discrepancy`

`change_type`, `field`, `goal_key`, `period`, `clock`, `team`, `summary`, `detail`,
`total_changed`, `attribution_only`, `goal_no_goal_change`, `video_review`,
`when_corrected`, `timing_uncertain`, `reason{stated_by_league,text,rule_citation,needs_human_read}`,
`market_impact{...}`.

- `total_changed` is `true`/`false` **only when the two states prove it**; `null`
  means not established, and the site buckets such records separately instead of
  letting them look like "no impact".
- `when_corrected` is the six-value honest enum (`in_game`, `intermission`,
  `postgame`, `next_day`, `unknown`, `not_applicable`) and `timing_uncertain`
  says whether the value is inferred. See FEASIBILITY section 3 for why this field
  can never be fully trustworthy.

## `initial_state` / `corrected_state`

Identical shape on purpose so they can be diffed by eye and by code:
`artifact`, `goal_present`, `ruling`, `scorer{key,name,player_id,sweater_number,goals_to_date}`,
`assists[]`, `period`, `clock`, `team`, `strength`, `strength_raw`, `own_goal`,
`empty_net`, `shot_type`, `score_after{away,home}`, `goalkeeper`.

`scorer.key` is `surname_tail:initial` - the only identity that survives both
`S. FEDOROV (2)` in a sheet and `{"firstName":{"default":"Sergei"}}` in JSON.

## `totals`

`{initial_game_goals, corrected_game_goals, goal_delta, basis}`. `basis` is required
in practice: `goal rows counted per artifact` for cross-source findings, `running
score in the source rows` when a sheet had no totals, `not yet read from an official
artifact` for pending records. A number without its basis is how a spreadsheet lies.

## `sources[]` evidence grades

| Grade | Meaning |
| --- | --- |
| `primary` | the official artifact itself (sheet, JSON, official page) |
| `secondary` | reporting about the event, including quotes of league officials |
| `reference` | a document that defines a rule or format, e.g. the rulebook - proves what *should* be true, never what a box score says |
| `none` | explicitly no evidence; must be paired with a flag |

`sha256` + `retrieved_at` are what make a claim re-checkable after the league edits
its own page; `quote` holds the verbatim fragment the finding rests on, so a reviewer
can Ctrl-F the source instead of trusting the parser.

## Merge semantics

`upsert()` keeps `verified` / `disputed` / `retired` sticky (only a reader sets
those) but still records every re-sighting: `seen_count`, `last_seen_at`, and an
append-only `detection_history[]` of `{run_id, detected_at, machine_status}`.
A machine run cannot close a `pending_review` record - it adds
`machine_detected_too` instead, because "the conflict is still live three weeks
later" is information, not a resolution.

## Snapshots

`data/snapshots/{game_id}.jsonl` - one line per **state change** from
`record_snapshot()`: `{captured_at, url, http_status, sha256, game_state, digest,
goals[], totals{}}`. Unchanged polls go to `polls.json` counters so the git history
stays a correction log rather than a poll log.

## What the site does with it

`site.build()` embeds the whole database plus `summarize()` aggregates into
`docs/data.js` (GitHub Pages cannot call nhl.com: CORS, and the sandbox has no
route). Three buckets on the Database view: changed the goal total / attribution only
/ total change not established. Plus Settlement exposure, Detection coverage, Live
monitor, and the docs tabs. Filters live in the URL hash so a filtered view is
shareable.
