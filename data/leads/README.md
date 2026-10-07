# Leads, not records

Files here describe *suspected* problems that are not yet records in
`../discrepancies.json`. A lead is a pointer to something worth checking; a record
is a claim with both states preserved and an official link that supports it. Nothing
in this directory is loaded by the site.

## Why there is no mirrored correction log

`github.com/aknodell/nhlPbpScrapeR` maintains a public audit log of 560 games where
the NHL's own play-by-play put a goal at the wrong second or dropped the following
faceoff. That data would be the cheapest bulk seed for this database.

It is not copied here: **that repository has no license file** (checked via the
GitHub API on 2026-10-07), so mirroring its data tables into a public repo is not
something to do on someone else's behalf. What is done instead:

- five rows are quoted individually, with attribution and a link to the source file,
  as `pending_review` records in `../discrepancies.json` - representative of the
  class, small enough to be attribution rather than appropriation;
- the class itself is described in `docs/METHODOLOGY.md` and `docs/FEASIBILITY.md`;
- anyone who wants the full 560-game list runs:

```bash
# fetch the log, then feed selected rows to the record builder as leads
curl -sL https://raw.githubusercontent.com/aknodell/nhlPbpScrapeR/main/after_goal_corrections.md
curl -sL https://raw.githubusercontent.com/aknodell/nhlPbpScrapeR/main/data/manually_changed_api_events.csv
```

The claim in every one of those rows is "the official feed disagrees with the video",
which cross-source checking cannot see: when both official artifacts are wrong the
same way, C10-C17 stay silent by construction. That is why the leads are kept, and
why they are not promoted automatically.

## Other open leads

| Lead | Status | How to resolve |
| --- | --- | --- |
| Playoff `PL` reports reported missing by community threads for `20112012/PL020259`, `20102011/PL020124`, `20102011/PL020429`, `20092010/PL020081` | unverified (single forum claim) | `curl -I` each URL; a 404 is a coverage hole to record in `docs/SOURCES.md`, not a discrepancy |
| 2026 Stanley Cup Final G2: Barbashev challenge outcome and a Slavin own-goal reclassification | unverified | pull that game's landing JSON + GS sheet and compare `goalModifier` and assist sets |
| Shootout goals (e.g. `2025021181`) - do they belong in this database at all? | decision pending | they do not count toward the game total; see STATUS.md open item 5 |
