"""HTTP client for the public takam.mof.gov.il API (no auth)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class TakamAPIError(RuntimeError):
    """The site could not be reached or returned an error after retries."""


class InvalidDocumentError(TakamAPIError):
    """The download endpoint answered, but not with a DOCX file."""


class TakamClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 60.0,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": "takam-search-poc/0.1"},
            follow_redirects=True,
        )
        self._max_retries = max_retries
        self._sleep = sleep

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> TakamClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _get(self, path: str) -> httpx.Response:
        last_error: str = ""
        for attempt in range(self._max_retries + 1):
            try:
                response = self._http.get(path)
            except httpx.TransportError as exc:  # timeouts, connection errors
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code < 400:
                    return response
                last_error = f"HTTP {response.status_code}"
                if response.status_code not in RETRYABLE_STATUS:
                    break
            if attempt < self._max_retries:
                backoff = 2**attempt
                log.warning("GET %s failed (%s); retry %d in %ss", path, last_error, attempt + 1, backoff)
                self._sleep(backoff)
        raise TakamAPIError(f"GET {path} failed: {last_error}")

    def documents(self) -> list[dict[str, Any]]:
        return self._get("api/Document").json()

    def versions(self, sfid: str) -> list[dict[str, Any]]:
        return self._get(f"api/DocumentVersion/{sfid}").json()

    def download(self, content_version_id: str, code: str) -> bytes:
        data = self._get(f"api/DocumentSF/DownloadDocument/{content_version_id}/{code}").content
        # DOCX is a ZIP container. An HTML error page served with 200 must not be indexed.
        if not data.startswith(b"PK"):
            raise InvalidDocumentError(f"{code}: download is not a DOCX file ({len(data)} bytes)")
        return data
