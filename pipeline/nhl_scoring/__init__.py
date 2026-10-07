"""NHL scoring-discrepancy detection pipeline.

Zero third-party dependencies on purpose: this has to run inside a GitHub
Actions runner (and any stock Python >= 3.9 install) with nothing but the
standard library, because the only reliable way to detect silent corrections to
the official scoring record is to keep a long-lived, unattended poller running.

Modules
-------
sources    URL construction for every official artifact we read.
fetch      HTTP with gzip, retry, caching and an honest failure record.
models     The normalized goal/game model every source is mapped onto.
parsers    api-web JSON + legacy/modern HTML game-summary parsers.
checks     Cross-source and intra-source discrepancy checks (C1..C16).
snapshot   Point-in-time digests + diff (the only way to see a silent edit).
market     Whether a change could move a market (game totals, props).
db         Canonical record store: validate, upsert, merge, flatten to CSV.
alerts     Human-readable alert rendering + dedupe.
site       Static GitHub Pages builder.
"""

__version__ = "0.4.0"
SCHEMA_VERSION = "1.0"
