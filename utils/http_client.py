"""HTTP client scaffolding for sync and async usage.

- Sync client uses httpx if available, otherwise requests.
- Async client uses httpx.AsyncClient when installed; otherwise raises ImportError when used.

This is a scaffold; current code paths may still use `requests` directly.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from typing import Any

DEFAULT_TIMEOUT = 10.0

try:
    import httpx  # type: ignore
except Exception:  # pragma: no cover
    httpx = None  # type: ignore

try:
    import requests  # type: ignore
except Exception:  # pragma: no cover
    requests = None  # type: ignore


class HTTPClient:
    def __init__(
        self,
        headers: dict[str, str] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = 2,
        backoff: float = 0.2,
        retry_statuses: Iterable[int] | None = None,
    ) -> None:
        self.timeout = float(timeout)
        # Apply a friendly default UA and allow override/extension via headers
        base_headers = {
            "User-Agent": ("ws-app/1.0 (+https://github.com/Revetex/ws-api-python)"),
            "Accept": "*/*",
        }
        self.headers = {**base_headers, **(headers or {})}
        self.retries = max(0, int(retries))
        self.backoff = max(0.0, float(backoff))
        self.retry_statuses = set(retry_statuses or (429, 500, 502, 503, 504))
        if httpx is not None:
            self._client = httpx.Client(timeout=self.timeout, headers=self.headers)
        elif requests is not None:
            self._client = requests.Session()
            if self.headers:
                self._client.headers.update(self.headers)
        else:
            raise ImportError("No HTTP library available (httpx/requests)")

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ):
        attempt = 0
        while True:
            try:
                if httpx is not None:
                    resp = self._client.request(
                        method.upper(), url, params=params, json=json, data=data
                    )
                else:
                    # requests.Session
                    resp = self._client.request(
                        method.upper(),
                        url,
                        params=params,
                        json=json,
                        data=data,
                        timeout=self.timeout,
                    )
            except Exception as e:
                if attempt < self.retries:
                    sleep_s = self.backoff * (2**attempt)
                    try:
                        time.sleep(sleep_s)
                    except Exception:
                        pass
                    attempt += 1
                    continue
                raise e
            # Retry on selected status codes
            try:
                code = getattr(resp, 'status_code', None)
            except Exception:
                code = None
            if code in self.retry_statuses and attempt < self.retries:
                sleep_s = self.backoff * (2**attempt)
                try:
                    time.sleep(sleep_s)
                except Exception:
                    pass
                attempt += 1
                continue
            return resp

    def get(self, url: str, params: dict[str, Any] | None = None):
        return self._request('GET', url, params=params)

    def post(
        self, url: str, json: dict[str, Any] | None = None, data: dict[str, Any] | None = None
    ):
        return self._request('POST', url, json=json, data=data)

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass


class AsyncHTTPClient:
    def __init__(
        self, headers: dict[str, str] | None = None, timeout: float = DEFAULT_TIMEOUT
    ) -> None:
        if httpx is None:
            raise ImportError("httpx is required for AsyncHTTPClient")
        self._client = httpx.AsyncClient(timeout=float(timeout), headers=headers or {})

    async def get(self, url: str, params: dict[str, Any] | None = None):
        return await self._client.get(url, params=params)

    async def post(
        self, url: str, json: dict[str, Any] | None = None, data: dict[str, Any] | None = None
    ):
        return await self._client.post(url, json=json, data=data)

    async def aclose(self) -> None:
        try:
            await self._client.aclose()
        except Exception:
            pass


__all__ = ["HTTPClient", "AsyncHTTPClient"]
