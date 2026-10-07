# Two implementations of the same brief now coexist — read this before editing either

**Date:** 2026-10-07. **Status:** an integration decision is owed; nothing here is broken, but the
repository currently carries two of everything.

## Why this happened

Two work sessions built this project in parallel and both ended up on `main`. The branch
`arena/02629288-scoringdiscrepnhl` (this one) adds its work by merge; the earlier line
(`arena/86c4bcfe-scoringdiscrepnhl`, PRs #4–#6) was already merged. Neither line was deleted. Both
lines' own READMEs warned about exactly this hazard — the merged line's README has a
"Coordination warning (important)" section stating that architectures had been overwritten
mid-flight by earlier sessions.

## What each line contains

| | This line (`src/nhl_monitor/`, `site/`, `data/records/`) | The merged line (`pipeline/`, root `index.html`, `js/`, `css/`, `data/discrepancies.json`) |
|---|---|---|
| Database | `data/records/discrepancies.json` — **3 records**, each verified against the official Game Summary row it cites and the league's own announcement | `data/discrepancies.json` — **0 records**; candidate leads are quarantined in `data/inbox/` pending promotion |
| How a record is born | two paths: (a) poll-and-diff an official feed; (b) `ingest` — parse the league's "OFFICIAL SCORING CHANGE" announcement and verify the corrected state against an official report. Path (b) is what found the three records, and it is the only mechanism here that can recover a correction made before monitoring existed | one path: snapshot official feeds, diff, promote. `pipeline/promote.py` moves a quarantined lead into the database |
| Tests | 73 unittest cases, incl. an era fixture built from real 2000-01 rows and a headless run of the site client against the shipped database | its own suite with synthetic fixtures (`tests/test_diff.py`, `test_livefeed.py`, `test_monitor_e2e.py`, `test_store.py`, `test_validate.py`, `test_records.py`) |
| Monitor cadence | every 5 minutes, `data/` committed on change | every 30 minutes, snapshot baselines in the Actions cache |
| Site | `site/` + `tools/build_site.py` → `_site/`, deployed by `pages.yml` (needs Pages source = **GitHub Actions**) | root `index.html`/`js/`/`css/`, served by the repository's **existing legacy Pages configuration** (branch root), so it is live today with no settings change |
| Coverage data | `data/reference/coverage_report.json` — measured on a runner for all 28 seasons; the two era behaviours interleave per season | `data/coverage_report.json` — its own probe, run daily from its monitor workflow |
| Standout capability | announcement ingest + the verified records + the measured per-season era table | the quarantine-and-promote discipline for unverified leads, and a site that publishes without touching repository settings |

Both are stdlib-only and both are honest about their gaps. Neither is obviously "the right one";
they optimise for different halves of the brief.

## The collisions, and how each was resolved in this merge

| Collision | Resolution | How to reverse |
|---|---|---|
| Two scheduled monitors on `main` — both write to `data/` and open issues, which would double-poll the official sources and duplicate every alert | this line's `monitor.yml` stays scheduled; the other is parked verbatim as `.github/workflows/monitor_root_site.yml.disabled` (a `.disabled` suffix means GitHub never picks it up) | rename the parked file to `monitor_root_site.yml` **and** disable `.github/workflows/monitor.yml` |
| Two READMEs | this one is the file; the merged line's README is preserved verbatim at `docs/parallel_line/README_main_line.md` | copy it back, or merge the two by hand |
| Two source catalogs at `docs/SOURCES.md` | this line's is the file; the merged line's is preserved verbatim at `docs/parallel_line/SOURCES_main_line.md` | copy it back, or merge the two by hand |
| Two `.gitignore` files | unioned, grouped and commented by hand | `git show <merge-parent>:…` to recover either side |
| Two databases, two sites, two CI workflows | **left alone** — they use different paths, so nothing is broken. `tests.yml` (this line) and `ci.yml` (the other) both run; each verifies its own line | — |

## The decision that is owed

1. **Which database is canonical?** `data/records/discrepancies.json` holds the only verified
   records in the repository. If the other line's `data/discrepancies.json` is to be canonical, the
   three records must be re-encoded in its schema (`docs/schema.json`) and re-verified there —
   do not hand-copy them, and do not leave two databases claiming to be "the database".
2. **Which site is published?** The live GitHub Pages site is currently the repo-root site (legacy
   branch deployment) and therefore shows an empty database. Publishing this line's site needs
   `Settings → Pages → Source: GitHub Actions` (then `pages.yml` deploys `_site/`). Until that is
   decided, the same project is described differently by two UIs.
3. **Keep the announcement ingest wherever the database lands.** It is the only mechanism in the
   repository that recovers corrections the poll-and-diff path can never see (anything that happened
   before monitoring started), and it is what produced the three records.
4. **Keep the quarantine discipline wherever the database lands.** Quarantining unverified leads in
   `data/inbox/` and promoting them only with an official artifact is the right instinct; this
   line's `data/inbox/statements/` is the same idea for announcements, and its records carry
   `initial_state_reported_by_secondary_source_only` flags where the pre-change state is weaker.

**Recommendation (not a unilateral change):** make the verified-records line canonical for the
database, keep this line's site deployed via GitHub Actions, and port the other line's
`promote.py` discipline into it; then delete one monitor, one database and one site deliberately in
a normal reviewed PR. That is a product decision and belongs to the repository owner.
