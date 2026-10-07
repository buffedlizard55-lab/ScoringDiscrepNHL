# PROJECT PROMPT - standing brief

This file and `README.md` are the project's non-negotiable brief. **Read at the start
of every session.** The site, the database and the alerting layer all exist to serve
what is written here; nothing in the repo may drift from it silently.

Reconstructed 2026-10-07 in the owner's requirements, numbered, so that a later
session can be graded against it. Where the original session's wording is not
recoverable, the requirement is written in imperative form rather than invented as a
quote - this file is a contract, not a transcript.

## Objective

Build, in this repository, a system for NHL scoring discrepancy research that:

1. maintains a **continuously updateable database** of scoring discrepancies and
   corrections sourced from **official NHL sources**:
   - goal changed to no-goal, and no-goal changed to goal
   - goals added/removed via video review
   - scorer changes
   - assist changes
   - in-game, intermission and post-game corrections
2. stores per record: **game date, teams, period, game clock, initial ruling,
   corrected/final ruling, reason, correction type, when the correction occurred,
   whether the goal/point total changed, whether only attribution changed, and the
   exact official source link**
3. **preserves both the original and the corrected state** of every affected play
4. **flags** incomplete / conflicting / unavailable / unverifiable evidence instead
   of guessing, and determines + documents the earliest reliable historical coverage
5. publishes a **GitHub Pages website**: clean, simple, easy to use, organized,
   filterable by season, date, team, period, discrepancy type, goal/no-goal change,
   scorer or assist correction, video review, intermission correction, postgame
   correction, and whether the total changed; total-changing separated from
   attribution-only; game-total/settlement exposure flagged; an official verified
   source link on every row
6. provides an **alert/notification detection system** for scoring discrepancies,
   with **explicit analysis of limitations and whether it is even possible**
7. is delivered by **opening a PR and then merging to main**, with remaining work
   and limitations listed

## Constraints

- Work **line by line**, verifying against official trusted sources; supply links for
  manual review.
- **No manual input** from the owner: complete autonomously.
- **No hallucinations.** Verify; flag irregularities for review rather than asserting.
- Do not stop after pass 1. Pass 2 hunts bugs and edge cases; pass 3 rechecks the
  result against this brief. Each pass builds on the last.
- The purpose is to **eliminate manual checking** and provide an **up-to-date feed**.

## Arena Core Values

**Maximize P(Win)** - choose what raises the probability the outcome is correct,
complete and usable. A plausible-looking row is worse than a flagged empty field.

**Own the Outcome** - no excuses, no TODO handoffs, no blaming upstream: the
deliverable is a working pipeline, real verified records, a live site, alerting, and
a true list of limitations.
