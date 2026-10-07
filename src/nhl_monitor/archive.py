"""Wayback Machine helpers: the historical backfill mechanism.

Why this matters
----------------
The official NHL documents are overwritten in place. There is no revision history
behind them. The only way to recover the ORIGINAL ruling of a game played in, say,
2019 is to find an archived copy of the official document from before the
correction, or to compare a frozen-era document (pre-regeneration era, see
docs/LIMITATIONS.md) against the league's current database.

The CDX index returns a content ``digest`` per snapshot, so the system can detect
THAT a document changed without downloading both versions, then download only the
snapshots whose digests differ.

Verified 2026-10-07 against the live index (see data/reference/verified_facts.json).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from . import sources
from .fetch import Response, http_get

#: Digest emitted by the Wayback Machine for an HTTP redirect with no body.
#: Observed 2026-10-07 for the 2006-era nhl.com:80 redirects of 2005-06 reports.
REDIRECT_DIGEST = "3I42H3S6NNFQ2MSVX7XZKYAYSCX5QBYJ"

#: Digest of a generic error page (observed for http:// captures of images).
ERROR_DIGEST = "OQ3OBNFR7DBCFQ4ANGEQW5P2FOXZZJRA"


@dataclass
class Snapshot:
    timestamp: str
    original: str
    statuscode: str
    digest: str
    mimetype: str = ""
    length: str = ""

    @property
    def usable(self) -> bool:
        """Only real, complete, non-redirect captures count as evidence."""
        return (self.statuscode == "200"
                and self.digest not in (REDIRECT_DIGEST, ERROR_DIGEST)
                and self.mimetype in ("text/html", "application/json", "text/plain", ""))

    def as_dict(self) -> dict:
        return {
            "timestamp": self.timestamp, "url": self.original, "statuscode": self.statuscode,
            "digest": self.digest, "mimetype": self.mimetype, "length": self.length,
            "usable_as_evidence": self.usable,
        }


def parse_cdx(payload, *, url_filter: Optional[str] = None) -> List[Snapshot]:
    """Parse a CDX JSON payload (list of lists, first row is the header)."""
    if not payload:
        return []
    rows = payload
    header = rows[0] if isinstance(rows[0], list) else None
    if header:
        rows = rows[1:]
    out: List[Snapshot] = []
    for row in rows:
        rec = dict(zip(header or [], row)) if header else {}
        snap = Snapshot(
            timestamp=str(rec.get("timestamp", "")),
            original=str(rec.get("original") or rec.get("urlkey") or ""),
            statuscode=str(rec.get("statuscode", "")),
            digest=str(rec.get("digest", "")),
            mimetype=str(rec.get("mimetype", "")),
            length=str(rec.get("length", "")),
        )
        if url_filter and url_filter not in snap.original:
            continue
        out.append(snap)
    return sorted(out, key=lambda s: s.timestamp)


def snapshots_for(url: str, *, limit: int = 100, timeout: float = 45.0,
                  cache_dir: Optional[str] = None) -> List[Snapshot]:
    """All archived captures of one exact URL (throttle politely: one call per URL)."""
    api = sources.cdx_query(url, limit=limit, collapse=None)
    resp = http_get(api, timeout=timeout, cache_dir=cache_dir, expect_status=(200, 404, 429))
    if resp.status != 200 or not resp.body.strip():
        return []
    try:
        return parse_cdx(resp.json(), url_filter=url)
    except Exception:
        return []


def content_versions(snaps: List[Snapshot]) -> Dict[str, List[Snapshot]]:
    """Group usable snapshots by digest = distinct content versions, oldest first."""
    versions: Dict[str, List[Snapshot]] = {}
    for s in snaps:
        if s.usable:
            versions.setdefault(s.digest, []).append(s)
    return versions


def changed(url: str, **kw) -> bool:
    """True when the archived record shows more than one distinct content version."""
    return len(content_versions(snapshots_for(url, **kw))) > 1


def described_versions(snaps: List[Snapshot]) -> List[dict]:
    out = []
    for digest, group in content_versions(snaps).items():
        out.append({
            "digest": digest,
            "first_seen": group[0].timestamp,
            "last_seen": group[-1].timestamp,
            "snapshot_count": len(group),
            "raw_urls": [sources.snapshot_url(s.timestamp, s.original) for s in group[:3]],
        })
    return sorted(out, key=lambda d: d["first_seen"])


def fetch_snapshot(timestamp: str, url: str, *, timeout: float = 45.0,
                   cache_dir: Optional[str] = None, expect_status=(200, 404)) -> Response:
    """Download the raw archived bytes of an official document."""
    return http_get(sources.snapshot_url(timestamp, url), timeout=timeout,
                    cache_dir=cache_dir, expect_status=expect_status)


def coverage_probe_report(prefixes: Dict[str, str], *, limit: int = 5,
                          cache_dir: Optional[str] = None) -> List[dict]:
    """Measure how well an official report path is archived.

    ``prefixes`` maps a human label to a URL prefix, e.g.
    ``{"2005-2006 reports": "nhl.com/scores/htmlreports/20052006/"}``.
    Returns one dict per prefix with the number of usable captures seen in the
    first ``limit`` rows, so the README/limitations can quote measured coverage
    instead of assumed coverage.
    """
    out = []
    for label, prefix in prefixes.items():
        api = sources.cdx_prefix_query(prefix, limit=limit)
        try:
            resp = http_get(api, timeout=60.0, cache_dir=cache_dir,
                            expect_status=(200, 404, 429))
            snaps = parse_cdx(resp.json()) if resp.status == 200 and resp.body.strip() else []
        except Exception as exc:  # network / parse
            out.append({"label": label, "prefix": prefix, "error": f"{type(exc).__name__}: {exc}"})
            continue
        out.append({
            "label": label,
            "prefix": prefix,
            "sampled_rows": len(snaps),
            "usable_captures": sum(1 for s in snaps if s.usable),
            "redirects_or_errors": sum(1 for s in snaps if not s.usable),
        })
    return out
