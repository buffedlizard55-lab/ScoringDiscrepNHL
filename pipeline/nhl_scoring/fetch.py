"""HTTP layer: one place that touches the network.

Design constraints that matter for this project:

* We must be able to prove *what the league served us and when*, because the
  core detection signal for post-game corrections is a diff between two pulls
  of the same URL. Every successful body is therefore content-addressed on disk
  (``cache/raw/<sha256>.<ext>``) and referenced from the digest.
* The endpoints are undocumented public league endpoints: assume throttling,
  transient 5xx, and gzip. Retry with backoff, but never silently invent data:
  a failed fetch is returned as ``FetchResult(ok=False)`` and shows up in the
  coverage report, not as a missing goal.
"""

from __future__ import annotations

import dataclasses
import gzip
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timezone
from typing import Any, Dict, Optional

USER_AGENT = (
    "ScoringDiscrepNHL/0.4 (+https://github.com/buffedlizard55-lab/ScoringDiscrepNHL; "
    "read-only research; contact via repository issues)"
)
DEFAULT_TIMEOUT = 25.0
MAX_ATTEMPTS = 4
BACKOFF_BASE = 1.7


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclasses.dataclass
class FetchResult:
    url: str
    ok: bool
    status: Optional[int] = None
    retrieved_at: str = dataclasses.field(default_factory=utcnow)
    sha256: Optional[str] = None
    path: Optional[str] = None          # content-addressed cache path
    error: Optional[str] = None
    attempts: int = 1
    elapsed_ms: int = 0
    from_cache: bool = False

    @property
    def is_404(self) -> bool:
        return self.status == 404

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


class Fetcher:
    """Small, boring, auditable HTTP client with an on-disk raw cache."""

    def __init__(
        self,
        cache_dir: str = "cache/raw",
        *,
        offline: bool = False,
        timeout: float = DEFAULT_TIMEOUT,
        throttle_s: float = 0.2,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> None:
        self.cache_dir = cache_dir
        self.offline = offline
        self.timeout = timeout
        self.throttle_s = throttle_s
        self.max_attempts = max_attempts
        self._last_request = 0.0
        self.cache_index_path = os.path.join(cache_dir, "index.jsonl")
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)

    # ------------------------------------------------------------------
    def get_bytes(self, url: str, *, accept: str = "*/*") -> FetchResult:
        started = time.time()
        body: Optional[bytes] = None
        status: Optional[int] = None
        err: Optional[str] = None
        attempts = 0
        for attempt in range(1, self.max_attempts + 1):
            attempts = attempt
            self._throttle()
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": USER_AGENT,
                        "Accept-Encoding": "gzip, deflate",
                        "Accept": accept,
                    },
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    status = resp.getcode()
                    body = self._decode_body(resp.read(), resp.headers.get("Content-Encoding"))
                err = None
                break
            except urllib.error.HTTPError as exc:  # 404/5xx land here
                status = exc.code
                body = None
                err = f"HTTP {exc.code} {exc.reason}"
                if exc.code in (404, 410):        # absence is an answer, stop
                    break
                if exc.code in (403, 429, 500, 502, 503, 504) and attempt < self.max_attempts:
                    time.sleep(BACKOFF_BASE ** attempt)
                    continue
                break
            except Exception as exc:  # URLError, timeout, TLS, ...
                status = None
                body = None
                err = f"{type(exc).__name__}: {exc}"
                if attempt < self.max_attempts:
                    time.sleep(BACKOFF_BASE ** attempt)
                    continue
                break
        elapsed = int((time.time() - started) * 1000)
        if body is None:
            return FetchResult(
                url=url, ok=False, status=status, error=err, attempts=attempts, elapsed_ms=elapsed
            )
        digest = hashlib.sha256(body).hexdigest()
        out_path = self._write_cache(url, body, digest)
        return FetchResult(
            url=url, ok=True, status=status or 200, sha256=digest, path=out_path,
            attempts=attempts, elapsed_ms=elapsed,
        )

    def get_json(self, url: str) -> tuple[Optional[Any], FetchResult]:
        res = self.get_bytes(url, accept="application/json")
        if not res.ok:
            return None, res
        try:
            return json.loads(self.read_cached(res)), res
        except Exception as exc:
            res.ok = False
            res.error = f"invalid JSON: {type(exc).__name__}: {exc}"
            return None, res

    def get_text(self, url: str) -> tuple[Optional[str], FetchResult]:
        res = self.get_bytes(url, accept="text/html,*/*")
        if not res.ok:
            return None, res
        raw = self.read_cached(res)
        # The htmlreports tree predates utf-8 by force of habit; latin-1 keeps
        # every byte round-trippable instead of raising mid-document.
        return raw.decode("utf-8", errors="replace"), res

    # ------------------------------------------------------------------
    def read_cached(self, res: FetchResult) -> bytes:
        if res.path and os.path.exists(res.path):
            with open(res.path, "rb") as fh:
                return fh.read()
        raise FileNotFoundError(f"payload missing from cache: {res.path}")

    def _write_cache(self, url: str, body: bytes, digest: str) -> Optional[str]:
        if not self.cache_dir:
            return None
        ext = ".json" if url.endswith((".json", "landing", "boxscore", "play-by-play", "right-rail", "score")) else ".htm"
        path = os.path.join(self.cache_dir, f"{digest}{ext}")
        if not os.path.exists(path):
            tmp = path + ".tmp"
            with open(tmp, "wb") as fh:
                fh.write(body)
            os.replace(tmp, path)
        try:
            with open(self.cache_index_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(
                    {"url": url, "sha256": digest, "bytes": len(body), "at": utcnow()},
                    separators=(",", ":"),
                ) + "\n")
        except OSError:
            pass
        return path

    def _throttle(self) -> None:
        if self.throttle_s <= 0:
            return
        delta = time.time() - self._last_request
        if delta < self.throttle_s:
            time.sleep(self.throttle_s - delta)
        self._last_request = time.time()

    @staticmethod
    def _decode_body(data: bytes, encoding: Optional[str]) -> bytes:
        enc = (encoding or "").lower()
        if enc == "gzip":
            return gzip.decompress(data)
        if enc == "deflate":
            try:
                return zlib.decompress(data)
            except zlib.error:
                return zlib.decompress(data, -zlib.MAX_WBITS)
        # Some CDNs lie about Content-Encoding; sniff the magic bytes.
        if data[:2] == b"\x1f\x8b":
            try:
                return gzip.decompress(data)
            except OSError:
                return data
        return data
