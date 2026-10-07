"""Polite, resilient HTTP client (stdlib only).

Identifies itself with a descriptive User-Agent, retries transient failures with
backoff, respects HTTP 429, and surfaces 404s as a distinct error so callers can
record 'unavailable' evidence instead of guessing.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from . import config


class SourceError(Exception):
    """A source could not be fetched."""

    def __init__(self, url: str, status: int | None = None, reason: str = ""):
        self.url = url
        self.status = status
        self.reason = reason
        super().__init__(f"{url} -> status={status} {reason}")


class NotFound(SourceError):
    """The source definitively does not exist (HTTP 404)."""


_RETRYABLE = {429, 500, 502, 503, 504}


def fetch(url: str, timeout: int | None = None, retries: int | None = None,
          backoff: float = 2.0) -> bytes:
    """GET a URL, returning the body bytes. Raises SourceError/NotFound."""
    timeout = timeout or config.HTTP_TIMEOUT
    retries = config.HTTP_RETRIES if retries is None else retries
    last: Exception | None = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": config.USER_AGENT,
                "Accept": "*/*",
                "Accept-Encoding": "identity",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise NotFound(url, 404, "not found") from exc
            if exc.code in _RETRYABLE and attempt < retries:
                last = exc
                time.sleep(backoff * (attempt + 1))
                continue
            raise SourceError(url, exc.code, str(exc)) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
            if attempt < retries:
                time.sleep(backoff * (attempt + 1))
                continue
    raise SourceError(url, None, f"unreachable after retries: {last}")


def fetch_json(url: str, **kwargs):
    body = fetch(url, **kwargs)
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceError(url, None, f"invalid JSON: {exc}") from exc


def try_archive(url: str) -> str | None:
    """Best-effort Internet Archive capture of a URL. Returns the archive URL or
    None. Never raises: archival is opportunistic, never a blocker."""
    try:
        target = config.ARCHIVE_SAVE_URL.format(url=url)
        req = urllib.request.Request(
            target,
            headers={"User-Agent": config.USER_AGENT},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=config.ARCHIVE_TIMEOUT) as resp:
            final_url = resp.geturl()
        if final_url and "web.archive.org" in final_url:
            return final_url
    except Exception:  # noqa: BLE001 - archival must never break monitoring
        pass
    return None
