"""HTTP layer. Standard library only, so the collector runs anywhere (no pip needed).

Design notes
------------
* Every response is recorded with its URL, HTTP status and retrieval timestamp so
  that "unavailable / conflicting / incomplete" evidence can be flagged instead of
  silently guessed.
* Retries use exponential backoff and only retry on transient errors (5xx, 429,
  timeouts). A 404 is *data*: it tells us a document does not exist.
* Nothing is cached across runs except under ``--cache-dir`` (git-ignored) so that
  a monitor run can never mistake stale bytes for a fresh official record.
"""

from __future__ import annotations

import gzip
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional, Tuple

DEFAULT_UA = (
    "ScoringDiscrepNHL/1.0 (+https://github.com/buffedlizard55-lab/ScoringDiscrepNHL) "
    "python-urllib"
)


class FetchError(RuntimeError):
    def __init__(self, url: str, message: str, status: Optional[int] = None):
        super().__init__(f"{url}: {message}")
        self.url = url
        self.status = status


@dataclass
class Response:
    url: str
    status: int
    body: bytes
    retrieved_at: str
    from_cache: bool = False
    final_url: Optional[str] = None
    content_type: str = ""

    @property
    def text(self) -> str:
        charset = "utf-8"
        if "charset=" in self.content_type:
            charset = self.content_type.split("charset=")[-1].split(";")[0].strip() or "utf-8"
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.text)

    def as_evidence(self) -> dict:
        return {
            "url": self.url,
            "http_status": self.status,
            "retrieved_at_utc": self.retrieved_at,
            "bytes": len(self.body),
            "from_cache": self.from_cache,
        }


def _utcnow() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def http_get(
    url: str,
    *,
    timeout: float = 30.0,
    retries: int = 3,
    backoff: float = 2.0,
    headers: Optional[dict] = None,
    cache_dir: Optional[str] = None,
    expect_status: Tuple[int, ...] = (200,),
) -> Response:
    """GET a URL, returning a :class:`Response`.

    Raises :class:`FetchError` for non-expected statuses after retries. A 404 is
    returned as a Response when the caller passes ``expect_status=(200, 404)``.
    """
    hdrs = {"User-Agent": DEFAULT_UA, "Accept-Encoding": "gzip"}
    if headers:
        hdrs.update(headers)

    cache_path = None
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        import hashlib

        name = hashlib.sha256(url.encode()).hexdigest()[:24] + ".cache"
        cache_path = os.path.join(cache_dir, name)
        if os.path.exists(cache_path):
            with open(cache_path, "rb") as fh:
                blob = json.loads(fh.read())
            return Response(
                url=url,
                status=blob["status"],
                body=blob["body"].encode("utf-8", errors="surrogateescape"),
                retrieved_at=blob["retrieved_at"],
                from_cache=True,
                final_url=blob.get("final_url"),
                content_type=blob.get("content_type", ""),
            )

    last_error: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed allow-list of official hosts)
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                out = Response(
                    url=url,
                    status=resp.status,
                    body=raw,
                    retrieved_at=_utcnow(),
                    final_url=resp.geturl(),
                    content_type=resp.headers.get("Content-Type", ""),
                )
            if out.status not in expect_status:
                raise FetchError(url, f"unexpected HTTP {out.status}", out.status)
            if cache_path:
                with open(cache_path, "w") as fh:
                    fh.write(json.dumps({
                        "status": out.status,
                        "body": out.body.decode("utf-8", errors="surrogateescape"),
                        "retrieved_at": out.retrieved_at,
                        "final_url": out.final_url,
                        "content_type": out.content_type,
                    }))
            return out
        except urllib.error.HTTPError as exc:  # noqa: PERF203
            if exc.code in expect_status:
                raw = exc.read() or b""
                return Response(url=url, status=exc.code, body=raw, retrieved_at=_utcnow(),
                                content_type=exc.headers.get("Content-Type", "") if exc.headers else "")
            last_error = FetchError(url, f"HTTP {exc.code}", exc.code)
            if exc.code < 500 and exc.code != 429:
                raise last_error
        except Exception as exc:  # timeouts, DNS, TLS
            last_error = FetchError(url, f"{type(exc).__name__}: {exc}")
        if attempt < retries:
            time.sleep(backoff ** attempt)
    raise last_error if last_error else FetchError(url, "unknown failure")


def get_json(url: str, **kw) -> Tuple[dict, Response]:
    resp = http_get(url, **kw)
    return resp.json(), resp


def get_text(url: str, **kw) -> Tuple[str, Response]:
    resp = http_get(url, **kw)
    return resp.text, resp
