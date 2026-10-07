"""ScoringDiscrepNHL monitor pipeline.

Fetches official NHL data, snapshots it, diffs snapshots to detect scoring
discrepancies/corrections, and emits records + alerts. Stdlib-only by design.
"""

__version__ = "0.1.0"
