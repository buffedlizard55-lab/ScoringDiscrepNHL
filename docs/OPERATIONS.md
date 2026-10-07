# Operations

## The five-minute runbook

```bash
export PYTHONPATH=src
python -m nhl_monitor probe            # 1. are the sources readable, and does the parser still understand
                                       #    the live report layout? (exit 1 = do not trust unparsed documents)
python -m nhl_monitor monitor          # 2. capture the slate, diff, alert, commit evidence
python -m nhl_monitor export-csv --out data/exports/discrepancies.csv
python tools/build_site.py             # 3. refresh the site data
```

`probe` failing on a *source* is a different problem from `probe` failing the *layout validation*:

* **source unreachable** → records that depend on it get `evidence_status = incomplete` / flags; do not
  downgrade to "no change".
* **layout validation failing** (`PARSER NEEDS ATTENTION`) → the official document changed shape. Stop the
  scheduled monitor (GitHub → Actions → scoring monitor → Disable workflow) before it writes records from a
  parser that no longer understands the document, then fix `parse.parse_gs_report`.

## Scheduled operation on GitHub

| Workflow | Cadence | Notes |
|---|---|---|
| `monitor.yml` | `*/5 * * * *` (UTC) | commits `data/` only when the official record actually changed; opens a GitHub issue per alert |
| `backfill.yml` | manual | run in slices; review before running the next slice |
| `tests.yml` | every push | unit tests, JS check, site build, record-schema validation, probe (non-blocking) |
| `pages.yml` | push to `main` touching `site/`, `data/` or the builder | deploys `_site/` |

Required repository settings:

1. **Settings → Actions → General → Workflow permissions**: *Read and write permissions* (the monitor commits
   evidence and opens issues).
2. **Settings → Pages → Build and deployment → Source**: *GitHub Actions*.
3. **Issues** must be enabled (that is the alert channel). Labels `scoring-discrepancy` and `auto-detected`
   are requested by the workflow; if a label does not exist, `gh issue create` fails — create the two labels
   once, or edit `alerts.open_github_issue` to drop `--label`.

## Alert channels

* `data/alerts/*.json` — always written; the site reads `data/alerts/index.json`.
* GitHub issues — the durable, reviewable notification. Body carries both states, every URL, timestamps,
  settlement reasoning and the record id.
* Anything else (Slack/webhook) would be a small addition in `alerts.py`; it is deliberately not wired up so
  that no external service becomes a hidden dependency of the project.

## Promoting a record from `auto_detected` to `verified`

The detector writes `status: "auto_detected"`. A record becomes `verified` only when a human has:

1. opened every `sources[].url` and confirmed the corrected state is what the official artifact shows now;
2. confirmed that the initial state really did exist (an archived snapshot, or a frozen-era document, or an
   official announcement) — if not, `evidence_status` must be `verified_corrected_state`, not
   `verified_two_official_states`;
3. filled `reason.text` **only** with a verbatim quote from an official source, plus that source in
   `sources` with `role: "reason"`;
4. removed the corresponding flags that no longer apply.

Then run `python -m unittest discover -s tests` (schema validation) and commit. There is intentionally no
CLI command that lets a human type a discrepancy into the database: records come from captured official
state, or they do not exist.

## Re-verification

`python -m nhl_monitor verify --record-id <id>` re-reads the official sources for a record and prints the
current official state for the changed event next to the stored `corrected_state`. Run it:

* for every record older than a season, once, to check nothing was re-corrected later;
* automatically (a future workflow) for all records with `evidence_status != verified_two_official_states`.

## Rate limiting and politeness

* The pipeline is a batch job: it fetches one document at a time with retries and exponential backoff
  (`fetch.http_get`).
* For the archive census, one CDX query per game document — the CDX endpoint is slow and rate limits
  aggressively (a 429 was observed on 2026-10-07 from a different Wayback endpoint). Back off and resume
  rather than hammering.
* Do not point the collector at a load-balanced mirror or a scraped copy: only the official hosts listed in
  `sources.SOURCES` may be cited as evidence.

## Troubleshooting

| Symptom | Meaning | Action |
|---|---|---|
| `probe` → `sources_ok: 0`, TLS/SSL errors | the machine running it has no route to NHL hosts (this is what the build sandbox reported, see `docs/evidence/`) | run from a normal network / GitHub Actions |
| records appearing with `flags: [parser_warnings_present]` | a document was only partially understood | inspect the document, extend the parser, re-run |
| `metadata_change` records | team score moved with no matching goal-set change | treat as an inconsistent feed, verify manually, never auto-resolve |
| CDX returns HTTP 429 | archive rate limit | wait, reduce `limit`, run fewer games per slice |
| Site shows stale data | `_site/data/*` is generated | re-run `python tools/build_site.py` (the Pages workflow does this) |
