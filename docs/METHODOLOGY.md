# Methodology

## What counts as a discrepancy

A **discrepancy** is any difference between (a) the earliest official record we
captured for a game/event and (b) a later official record for the same game/event.
Two families are kept distinct everywhere (database, site, alerts):

1. **Total-changing discrepancies** — the number of goals for a team changes
   (goal → no-goal, no-goal → goal, disallowed/allowed on review). These carry
   `changes_game_total: true` and `settlement_risk: true`.
2. **Attribution-only corrections** — the goal stands, but scorer/assist/strength
   attribution changes. These carry `attribution_only: true` and
   `settlement_risk: false`.

## Record lifecycle

```
observed change → record created (status: pending_review)
   → evidence links attached (feed capture, report links, Situation Room)
   → human confirms or CI corroboration succeeds → status: confirmed
   → sources disagree → status: conflicting (never silently resolved)
```

Automation creates records; **confirmation of `reason` and historical entries is
always human-verifiable** via the attached links.

## Evidence rules

* ≥1 official source link per record (live-feed capture reference + report link).
* Each evidence item records `captured_at` (UTC) and, where possible, an Internet
  Archive copy of the captured state.
* Fields that cannot be sourced are `null`, never guessed.
* Records with any `incomplete`/`conflicting`/`unavailable` evidence automatically
  carry `needs_human_review`.

## Timing classification (heuristic)

| Classification | Rule |
|---|---|
| `in_game` | Both bracketing snapshots show the game not final |
| `intermission` | Bracketing snapshots show period ended → next period started, game not final |
| `postgame` | Older snapshot at/beyond final; change appears after final |
| `unknown` | Baseline missing or monitor downtime spans the change |

Every classification stores `timing_confidence`: `direct` (feed event timestamps
show it), `heuristic` (snapshot bracketing), or `unknown`.

## Settlement-risk flag

`settlement_risk: true` iff the discrepancy changed a goal total **after** the
earliest captured state had shown that total. This is an informational flag for
"this could matter to a market settled on the earlier state" — not betting advice,
and market settlement rules always belong to the market operator.
