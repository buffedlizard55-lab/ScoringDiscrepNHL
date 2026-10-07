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

    @classmethod
    def from_dict(cls, d: dict) -> "Snapshot":
        """Rebuild a snapshot from :meth:`as_dict` (unknown keys are ignored)."""
        return cls(timestamp=str(d.get("timestamp", "")), original=str(d.get("url") or d.get("original") or ""),
                   statuscode=str(d.get("statuscode", "")), digest=str(d.get("digest", "")),
                   mimetype=str(d.get("mimetype", "")), length=str(d.get("length", "")))

    def as_dict(self) -> dict:
        return {
            "timestamp": self.timestamp, "url": self.original, "statuscode": self.statuscode,
            "digest": self.digest, "mimetype": self.mimetype, "length": self.length,
            "usable_as_evidence": self.usable,
        }


def _document_path(url: str) -> str:
    """The document path, ignoring scheme, host and port.

    The archive stores a capture of ``http://www.nhl.com:80/scores/htmlreports/...``
    under the same document as ``https://www.nhl.com/scores/htmlreports/...``. Matching
    on the whole URL string silently discards those captures, which *undercounts* how
    often a document was archived - measured 2026-10-07 on the 2000-01 season, where the
    league's own http:// captures are the only ones that exist.
    """
    from urllib.parse import urlparse

    path = urlparse(url).path or url
    return path.rstrip("/").lower()


def parse_cdx(payload, *, url_filter: Optional[str] = None) -> List[Snapshot]:
    """Parse a CDX JSON payload (list of lists, first row is the header).

    ``url_filter`` compares document *paths* (see :func:`_document_path`), so scheme and
    host variants of the same document are kept instead of being mistaken for other
    documents - and other documents in the same prefix are still excluded.
    """
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
        if url_filter and _document_path(url_filter) != _document_path(snap.original):
            continue
        out.append(snap)
    return sorted(out, key=lambda s: s.timestamp)


def snapshots_for(url: str, *, limit: int = 100, timeout: float = 45.0,
                  cache_dir: Optional[str] = None) -> List[Snapshot]:
    """All archived captures of one document (throttle politely: one call per URL).

    Captures taken from a different scheme/host/port for the same document path count as
    captures of the document; each one keeps its own ``original`` URL as evidence.
    """
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


def change_windows(snaps: List[Snapshot]) -> List[dict]:
    """Bracket every change the archive can prove, oldest first.

    A change is *provable* when two adjacent usable captures carry different content
    digests. The last capture of the older version and the first capture of the newer
    version bracket the moment the document was rewritten: the older content
    demonstrably existed at T1 and the newer content demonstrably existed at T2, while
    everything between T1 and T2 is unknowable from the archive alone. Nothing outside
    that bracket is claimed.

    A digest that returns to a value seen earlier is kept but flagged: it is either a
    genuine reversion of the ruling or a capture artefact, and the two are not
    distinguishable from the index, so it must not be folded silently into a change.
    """
    usable = [s for s in snaps if s.usable]
    first_seen: Dict[str, int] = {}
    for i, s in enumerate(usable):
        first_seen.setdefault(s.digest, i)
    windows: List[dict] = []
    for i, (older, newer) in enumerate(zip(usable, usable[1:])):
        if older.digest == newer.digest:
            continue
        returned = first_seen.get(newer.digest, i + 1) <= i
        windows.append({
            "older_capture": older.as_dict(),
            "newer_capture": newer.as_dict(),
            "changed_after_capture": older.timestamp,
            "changed_by_capture": newer.timestamp,
            "digest_returned_to_an_earlier_version": returned,
            "note": ("The document's content changed between these two captures. Which of "
                     "the two states is the original ruling is decided by the content "
                     "comparison, not by the capture order."),
        })
    return windows


def scan_urls(urls: Dict[str, str], *, limit: int = 200, cache_dir: Optional[str] = None,
              timeout: float = 45.0, delay: float = 0.0,
              on_result=None) -> List[dict]:
    """Ask the index, for a set of official documents, whether each one ever changed.

    ``urls`` maps a label (e.g. the game id) to the canonical official URL. One CDX
    query per URL - the index answers "how many captures, how many distinct contents,
    and when did the content change" without downloading the documents themselves,
    which is what makes a multi-season census affordable at all.

    Returns one result dict per label with the capture counts and the proven change
    windows, so a caller can separate "archived and never changed", "archived and
    provably changed" (a lead) and "not archived" (unknowable) - three very different
    answers that must never be collapsed into one.
    """
    import time as _time

    results: List[dict] = []
    for label, url in urls.items():
        row: dict = {"label": label, "url": url}
        try:
            snaps = snapshots_for(url, limit=limit, timeout=timeout, cache_dir=cache_dir)
            usable = [s for s in snaps if s.usable]
            windows = change_windows(snaps)
            row.update({
                "captures": len(snaps),
                "usable_captures": len(usable),
                "distinct_content_versions": len(content_versions(snaps)),
                "oldest_capture": usable[0].timestamp if usable else None,
                "newest_capture": usable[-1].timestamp if usable else None,
                "proven_change": bool(windows),
                "change_windows": windows,
                "verdict": ("provably_changed" if windows else
                            "archived_but_never_changed" if usable else
                            "no_usable_capture"),
            })
        except Exception as exc:  # network / index error
            row.update({"captures": None, "usable_captures": None, "proven_change": None,
                        "verdict": "index_error", "error": f"{type(exc).__name__}: {exc}"})
        results.append(row)
        if on_result is not None:
            try:
                on_result(row)
            except Exception:
                pass
        if delay:
            _time.sleep(delay)
    return results


def summarise_scan(results: List[dict]) -> dict:
    """Aggregate a scan: how much of the sample is even answerable, and what changed.

    The three outcomes are counted separately and never collapsed: an index error is a
    failed question, a document with no usable capture is an unanswered question, and
    only a document with a usable capture is an answered one. Reporting either of the
    first two as "unchanged" would overstate what the archive can see.
    """
    verdicts: Dict[str, int] = {}
    leads: List[dict] = []
    archived = 0
    for row in results:
        verdict = row.get("verdict", "unknown")
        verdicts[verdict] = verdicts.get(verdict, 0) + 1
        if isinstance(row.get("usable_captures"), int) and row["usable_captures"] > 0:
            archived += 1
        for window in row.get("change_windows") or []:
            leads.append({
                "label": row["label"],
                "url": row["url"],
                "changed_after_capture": window["changed_after_capture"],
                "changed_by_capture": window["changed_by_capture"],
                "older_raw_url": sources.snapshot_url(window["older_capture"]["timestamp"],
                                                      window["older_capture"]["url"]),
                "newer_raw_url": sources.snapshot_url(window["newer_capture"]["timestamp"],
                                                      window["newer_capture"]["url"]),
                "digest_returned_to_an_earlier_version":
                    window["digest_returned_to_an_earlier_version"],
            })
    return {
        "documents_probed": len(results),
        "verdicts": verdicts,
        "documents_with_a_usable_capture": archived,
        "documents_without_a_usable_capture": len(results) - archived,
        "documents_provably_changed": len(leads),
        "proven_change_rate_among_archived": round(len(leads) / archived, 4) if archived else None,
        "proven_change_rate_among_probed": round(len(leads) / len(results), 4) if results else None,
        "leads": leads,
        "reading": ("documents_provably_changed counts documents whose archived content is "
                    "known to have changed - each lead is a candidate scoring correction "
                    "that still has to survive a content comparison. A document with no "
                    "usable capture, and a document whose index query failed, are both "
                    "UNKNOWABLE, not unchanged."),
    }


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
