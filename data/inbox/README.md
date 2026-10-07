# Inbox — quarantined research leads

Files here hold **claims, not verified facts**. They were produced by earlier
work sessions and could not be re-verified line-by-line against official NHL
sources from the environment that quarantined them (NHL endpoints unreachable
there). They are shown on the website under **Verification Queue** with clickable
source links.

| File | Origin | Count |
|---|---|---|
| `pr3_database_review.json` | `data/discrepancies.json` after PR #3 (main commit 43594a2) | 26 leads |
| `prior_session_leads.json` | seed database from PR #1 (main commit ff5be40) | 5 leads |

## Verification procedure (per lead)

1. Open every cited source link. If a link is dead, search for the archived copy
   (`web.archive.org`) — never reconstruct content from memory.
2. Confirm: game date, teams, period, clock, the **initial** ruling, the
   **corrected** ruling, and the reason.
3. Look up the official game id (`gamePk`) from the NHL schedule API and the
   official GS/ES report for the game; cross-check the final scoring line.
4. Promote with `python3 -m pipeline.promote ...` (see `--help`). The tool
   validates against the charter schema and refuses to invent any field.
5. Delete the lead from the inbox file only after promotion is audited.

## Integrity flags already applied

* `pr3_database_review.json` → record `2023-04-30-COL-SEA-mackinnon-g7` carries
  `citation_mismatch`: its Guardian URL slug references a BOS-FLA article while
  the record concerns COL-SEA. Treat as `conflicting` until an official
  Situation Room post is verified.
* Several leads cite `x.com/NHLPR` posts (official, but fragile links) or
  secondary outlets quoting NHL PR verbatim — locate the direct official post or
  an archived copy before promotion.
* Any lead whose evidence cannot be verified must be **deleted**, not softened.
