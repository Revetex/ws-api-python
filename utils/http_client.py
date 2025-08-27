"""HTTP client scaffolding for sync and async usage.

- Sync client uses httpx if available, otherwise requests.
- Async client uses httpx.AsyncClient when installed; otherwise raises ImportError when used.

This is a scaffold; current code paths may still use `requests` directly.
"""
from __future__ import annotations
from typing import Optional, Dict, Any

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
    def __init__(self, headers: Optional[Dict[str, str]] = None, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.timeout = float(timeout)
        self.headers = headers or {}
        if httpx is not None:
            self._client = httpx.Client(timeout=self.timeout, headers=self.headers)
        elif requests is not None:
            self._client = requests.Session()
            if self.headers:
                self._client.headers.update(self.headers)
        else:
            raise ImportError("No HTTP library available (httpx/requests)")

    def get(self, url: str, params: Optional[Dict[str, Any]] = None):
        if httpx is not None:
            return self._client.get(url, params=params)
        return self._client.get(url, params=params, timeout=self.timeout)

    def post(self, url: str, json: Optional[Dict[str, Any]] = None, data: Optional[Dict[str, Any]] = None):
        if httpx is not None:
            return self._client.post(url, json=json, data=data)
        return self._client.post(url, json=json, data=data, timeout=self.timeout)

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass


class AsyncHTTPClient:
    def __init__(self, headers: Optional[Dict[str, str]] = None, timeout: float = DEFAULT_TIMEOUT) -> None:
        if httpx is None:
            raise ImportError("httpx is required for AsyncHTTPClient")
        self._client = httpx.AsyncClient(timeout=float(timeout), headers=headers or {})

    async def get(self, url: str, params: Optional[Dict[str, Any]] = None):
        return await self._client.get(url, params=params)

    async def post(self, url: str, json: Optional[Dict[str, Any]] = None, data: Optional[Dict[str, Any]] = None):
        return await self._client.post(url, json=json, data=data)

    async def aclose(self) -> None:
        try:
            await self._client.aclose()
        except Exception:
            pass


__all__ = ["HTTPClient", "AsyncHTTPClient"]
