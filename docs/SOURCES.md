# Official Source Catalog

Every record in the database links back to one or more of these exact sources.
URL templates below use placeholders: `{season}` = `20262027` style,
`{gamePk}` = NHL API game id (e.g. `2026020001`), `{report}` = 6-digit report
game number (e.g. `020001`).

## Primary (official NHL) sources

| # | Source | URL template | Contains | Notes |
|---|---|---|---|---|
| 1 | Schedule API (statsapi v1) | `https://statsapi.web.nhl.com/api/v1/schedule?startDate={YYYY-MM-DD}&endDate={YYYY-MM-DD}&expand=schedule.teams,schedule.score` | Game list, ids, final scores, status | Source of truth for "which games are final" |
| 2 | Live feed (statsapi v1) | `https://statsapi.web.nhl.com/api/v1/game/{gamePk}/feed/live` | Complete play-by-play incl. goals, strengths, scorers, assists, review/challenge events, linescore | Authoritative snapshot input |
| 3 | Team roster for tri-codes | `https://statsapi.web.nhl.com/api/v1/teams` | Team names/abbreviations | Cached per run |
| 4 | Official Game Summary (PDF) | `https://www.nhl.com/scores/htmlreports/{season}/GS{report}.PDF` | Official scoring summary, plus/minus, shots | Hash-monitored for silent edits |
| 5 | Official Event Summary (PDF) | `https://www.nhl.com/scores/htmlreports/{season}/ES{report}.PDF` | Event-by-event official record incl. goal scorers/assists | Hash-monitored for silent edits |
| 6 | Official Play-by-Play (PDF) | `https://www.nhl.com/scores/htmlreports/{season}/PL{report}.PDF` | Official chronological event list | Reserved for content-diff phase |
| 7 | Situation Room topic page | `https://www.nhl.com/news/topic/situation-room` | Official posts explaining review outcomes | Link captured per relevant game |
| 8 | NHL Records | `https://records.nhl.com/` | Historical official records | Manual/historical verification only |

> Report number mapping (expected, verified at runtime by the probe): for gamePk
> `YYYYTTNNNN` the report file number is `TTNNNN` (e.g. gamePk `2026020001` →
> `GS020001.PDF` in season `20262027`). The monitor confirms existence by HTTP
> status before storing the link; missing reports are flagged, never assumed.

## Archival corroboration

| Source | URL template | Use |
|---|---|---|
| Internet Archive copy | `https://web.archive.org/web/{timestamp}/{original-url}` | Preserves the exact copy the pipeline captured; every evidence link gets an archive attempt so the record survives source edits |

## Source status labels used in records

* `official` — NHL-operated endpoint/document.
* `archive` — archived copy of an official source (label keeps original URL).
* `secondary` — reputable non-official source, corroboration only, never sole evidence.
* Evidence status: `verified`, `incomplete`, `conflicting`, `unavailable`.
