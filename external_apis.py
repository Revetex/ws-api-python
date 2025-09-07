"""External API clients for portfolio enhancement.

Includes:
- News API for financial news
- Alpha Vantage for additional market data
- Telegram Bot for notifications
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
from datetime import datetime

import requests


class NewsAPIClient:
    """Client for NewsAPI.org - financial news and sentiment."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv('NEWS_API_KEY')
        self.base_url = 'https://newsapi.org/v2'
        # pooled HTTP client
        try:
            from utils.http_client import HTTPClient  # type: ignore

            self._http = HTTPClient(headers={'Accept': 'application/json'})
        except Exception:
            self._http = None  # type: ignore
        # opt-in flag to force HTTPClient exclusively (keeps compatibility by default)
        try:
            self._http_only = os.getenv('WSAPP_HTTPCLIENT_ONLY', '0').strip().lower() in (
                '1',
                'true',
                'yes',
                'on',
            )
        except Exception:
            self._http_only = False
        # optional error logging (off by default to avoid console spam when offline)
        try:
            self._log_errors = os.getenv('NEWS_LOG_ERRORS', '0').strip().lower() in (
                '1',
                'true',
                'yes',
                'on',
            )
        except Exception:
            self._log_errors = False
        # tiny cache with negative TTL support
        self._cache: dict[tuple[str, int], tuple[float, list[dict], bool]] = {}
        self._ttl = 180.0
        self._neg_ttl = 30.0
        # optional persistent cache from APIManager; will be injected post-init if available
        self._persistent_cache = None  # type: ignore
        try:
            ttl_env = os.getenv('CACHE_TTL_NEWS_SEC')
            self._persist_ttl = float(ttl_env) if ttl_env else 600.0
        except Exception:
            self._persist_ttl = 600.0
        # Optional circuit breaker
        try:
            from utils.circuit_breaker import CircuitBreaker  # type: ignore

            self._cb = CircuitBreaker(
                name='newsapi',
                failure_threshold=int(os.getenv('NEWS_CB_FAILURES', '5') or '5'),
                recovery_time=float(os.getenv('NEWS_CB_RECOVERY_SEC', '30') or '30'),
                half_open_max_calls=int(os.getenv('NEWS_CB_HALF_OPEN_MAX', '2') or '2'),
            )
        except Exception:
            self._cb = None  # type: ignore

    def breaker_stats(self) -> dict:
        try:
            if getattr(self, '_cb', None):
                return self._cb.stats()  # type: ignore[attr-defined]
        except Exception:
            pass
        return {}

    def get_financial_news(self, query: str = 'stock market', page_size: int = 10) -> list[dict]:
        """Get financial news articles."""
        if not self.api_key:
            return []

        try:
            # Persistent cache read-through
            try:
                if getattr(self, '_persistent_cache', None):
                    k = f"{query}|{int(page_size)}"
                    cached = self._persistent_cache.get_if_fresh(
                        'news', k, max_age_s=self._persist_ttl
                    )
                    if isinstance(cached, list) and cached:
                        return cached
            except Exception:
                pass

            url = f"{self.base_url}/everything"
            params = {
                'q': query,
                'language': 'en',
                'sortBy': 'publishedAt',
                'pageSize': page_size,
                'apiKey': self.api_key,
            }
            now = time.time()
            key = (query, page_size)
            cached = self._cache.get(key)
            if cached:
                ts, data, neg = cached
                ttl = self._neg_ttl if neg else self._ttl
                if (now - ts) < ttl:
                    return data
            if getattr(self, '_cb', None):
                from utils.circuit_breaker import CircuitOpenError  # type: ignore

                try:
                    with self._cb:  # type: ignore[attr-defined]
                        if getattr(self, '_http', None) is not None:
                            response = self._http.get(url, params=params)  # type: ignore[assignment]
                        elif not getattr(self, '_http_only', False):
                            response = requests.get(url, params=params, timeout=10)
                        else:
                            raise RuntimeError('HTTP client unavailable')
                except CircuitOpenError:
                    raise RuntimeError('NewsAPI circuit open')
            else:
                if getattr(self, '_http', None) is not None:
                    response = self._http.get(url, params=params)  # type: ignore[assignment]
                elif not getattr(self, '_http_only', False):
                    response = requests.get(url, params=params, timeout=10)
                else:
                    raise RuntimeError('HTTP client unavailable')
            response.raise_for_status()
            data = response.json()
            articles = data.get('articles', [])
            self._cache[key] = (now, articles, False)
            # persist
            try:
                if getattr(self, '_persistent_cache', None):
                    self._persistent_cache.set('news', f"{query}|{int(page_size)}", articles)
            except Exception:
                pass
            return articles
        except Exception as e:
            if getattr(self, '_log_errors', False):
                print(f"News API error: {e}")
            # cache empty to avoid hammering API momentarily
            try:
                now = time.time()
                key = (query, page_size)
                self._cache[key] = (now, [], True)
            except Exception:
                pass
            return []

    def get_company_news(self, symbol: str, page_size: int = 5) -> list[dict]:
        """Get news for specific company/stock symbol."""
        return self.get_financial_news(f"{symbol} stock", page_size)


class AlphaVantageClient:
    """Client for Alpha Vantage - market data and indicators."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv('ALPHA_VANTAGE_KEY')
        self.base_url = 'https://www.alphavantage.co/query'
        try:
            from utils.http_client import HTTPClient  # type: ignore

            self._http = HTTPClient(headers={'Accept': 'application/json'})
        except Exception:
            self._http = None  # type: ignore
        try:
            self._http_only = os.getenv('WSAPP_HTTPCLIENT_ONLY', '0').strip().lower() in (
                '1',
                'true',
                'yes',
                'on',
            )
        except Exception:
            self._http_only = False
        # Optional circuit breaker
        try:
            from utils.circuit_breaker import CircuitBreaker  # type: ignore

            self._cb = CircuitBreaker(
                name='alpha_vantage',
                failure_threshold=int(os.getenv('ALPHA_CB_FAILURES', '5') or '5'),
                recovery_time=float(os.getenv('ALPHA_CB_RECOVERY_SEC', '20') or '20'),
                half_open_max_calls=int(os.getenv('ALPHA_CB_HALF_OPEN_MAX', '2') or '2'),
            )
        except Exception:
            self._cb = None  # type: ignore
        # optional error logging (off by default)
        try:
            self._log_errors = os.getenv('ALPHA_LOG_ERRORS', '0').strip().lower() in (
                '1',
                'true',
                'yes',
                'on',
            )
        except Exception:
            self._log_errors = False

    def breaker_stats(self) -> dict:
        try:
            if getattr(self, '_cb', None):
                return self._cb.stats()  # type: ignore[attr-defined]
        except Exception:
            pass
        return {}

    def get_quote(self, symbol: str) -> dict | None:
        """Get real-time quote for symbol."""
        if not self.api_key:
            return None

        try:
            params = {'function': 'GLOBAL_QUOTE', 'symbol': symbol, 'apikey': self.api_key}
            if getattr(self, '_cb', None):
                from utils.circuit_breaker import CircuitOpenError  # type: ignore

                try:
                    with self._cb:  # type: ignore[attr-defined]
                        if getattr(self, '_http', None) is not None:
                            response = self._http.get(self.base_url, params=params)  # type: ignore[assignment]
                        elif not getattr(self, '_http_only', False):
                            response = requests.get(self.base_url, params=params, timeout=10)
                        else:
                            raise RuntimeError('HTTP client unavailable')
                except CircuitOpenError:
                    raise RuntimeError('AlphaVantage circuit open')
            else:
                if getattr(self, '_http', None) is not None:
                    response = self._http.get(self.base_url, params=params)  # type: ignore[assignment]
                elif not getattr(self, '_http_only', False):
                    response = requests.get(self.base_url, params=params, timeout=10)
                else:
                    raise RuntimeError('HTTP client unavailable')
            response.raise_for_status()
            data = response.json()
            return data.get('Global Quote', {})
        except Exception as e:
            if getattr(self, '_log_errors', False):
                print(f"Alpha Vantage error: {e}")
            return None

    def get_intraday(self, symbol: str, interval: str = '5min') -> dict | None:
        """Get intraday data for symbol."""
        if not self.api_key:
            return None

        try:
            params = {
                'function': 'TIME_SERIES_INTRADAY',
                'symbol': symbol,
                'interval': interval,
                'apikey': self.api_key,
            }
            if getattr(self, '_cb', None):
                from utils.circuit_breaker import CircuitOpenError  # type: ignore

                try:
                    with self._cb:  # type: ignore[attr-defined]
                        if getattr(self, '_http', None) is not None:
                            response = self._http.get(self.base_url, params=params)  # type: ignore[assignment]
                        elif not getattr(self, '_http_only', False):
                            response = requests.get(self.base_url, params=params, timeout=10)
                        else:
                            raise RuntimeError('HTTP client unavailable')
                except CircuitOpenError:
                    raise RuntimeError('AlphaVantage circuit open')
            else:
                if getattr(self, '_http', None) is not None:
                    response = self._http.get(self.base_url, params=params)  # type: ignore[assignment]
                elif not getattr(self, '_http_only', False):
                    response = requests.get(self.base_url, params=params, timeout=10)
                else:
                    raise RuntimeError('HTTP client unavailable')
            response.raise_for_status()
            return response.json()
        except Exception as e:
            if getattr(self, '_log_errors', False):
                print(f"Alpha Vantage intraday error: {e}")
            return None

    def get_time_series(
        self, symbol: str, interval: str = '1day', outputsize: str = 'compact'
    ) -> dict | None:
        """Get time series for symbol for various intervals.

        interval values supported:
        - '1min','5min','15min','30min','60min','1hour' -> TIME_SERIES_INTRADAY
        - '1day' -> TIME_SERIES_DAILY (adjusted not required here)
        - '1week' -> TIME_SERIES_WEEKLY
        - '1month' -> TIME_SERIES_MONTHLY
        """
        if not self.api_key:
            return None

        try:
            func = None
            params: dict[str, str] = {
                'symbol': symbol,
                'apikey': self.api_key,
                'datatype': 'json',
            }

            intraday_map = {
                '1min': '1min',
                '5min': '5min',
                '15min': '15min',
                '30min': '30min',
                '60min': '60min',
                '1hour': '60min',
            }
            if interval in intraday_map:
                func = 'TIME_SERIES_INTRADAY'
                params.update(
                    {'function': func, 'interval': intraday_map[interval], 'outputsize': outputsize}
                )
            elif interval == '1day':
                func = 'TIME_SERIES_DAILY'
                params.update({'function': func, 'outputsize': outputsize})
            elif interval == '1week':
                func = 'TIME_SERIES_WEEKLY'
                params.update({'function': func})
            elif interval == '1month':
                func = 'TIME_SERIES_MONTHLY'
                params.update({'function': func})
            else:
                # Fallback to daily
                func = 'TIME_SERIES_DAILY'
                params.update({'function': func, 'outputsize': outputsize})

            if getattr(self, '_cb', None):
                from utils.circuit_breaker import CircuitOpenError  # type: ignore

                try:
                    with self._cb:  # type: ignore[attr-defined]
                        if getattr(self, '_http', None) is not None:
                            response = self._http.get(self.base_url, params=params)  # type: ignore[assignment]
                        elif not getattr(self, '_http_only', False):
                            response = requests.get(self.base_url, params=params, timeout=10)
                        else:
                            raise RuntimeError('HTTP client unavailable')
                except CircuitOpenError:
                    raise RuntimeError('AlphaVantage circuit open')
            else:
                if getattr(self, '_http', None) is not None:
                    response = self._http.get(self.base_url, params=params)  # type: ignore[assignment]
                elif not getattr(self, '_http_only', False):
                    response = requests.get(self.base_url, params=params, timeout=10)
                else:
                    raise RuntimeError('HTTP client unavailable')
            response.raise_for_status()
            return response.json()
        except Exception as e:
            if getattr(self, '_log_errors', False):
                print(f"Alpha Vantage time series error: {e}")
            return None

    def get_technical_indicators(
        self, symbol: str, indicator: str = 'RSI', interval: str = 'daily'
    ) -> dict | None:
        """Get technical indicators (RSI, MACD, etc.)."""
        if not self.api_key:
            return None

        try:
            params = {
                'function': indicator,
                'symbol': symbol,
                'interval': interval,
                'time_period': 14,
                'series_type': 'close',
                'apikey': self.api_key,
            }
            if getattr(self, '_http', None) is not None:
                response = self._http.get(self.base_url, params=params)  # type: ignore[assignment]
            elif not getattr(self, '_http_only', False):
                response = requests.get(self.base_url, params=params, timeout=10)
            else:
                raise RuntimeError('HTTP client unavailable')
            response.raise_for_status()
            return response.json()
        except Exception as e:
            if getattr(self, '_log_errors', False):
                print(f"Alpha Vantage indicators error: {e}")
            return None


class YahooFinanceClient:
    """Free alternative data source using Yahoo Finance public endpoints (no API key)."""

    BASE_QUOTE = 'https://query1.finance.yahoo.com/v7/finance/quote'
    BASE_CHART = 'https://query1.finance.yahoo.com/v8/finance/chart'

    def __init__(self):
        # Shared HTTP session with friendly headers (kept for compatibility with tests)
        self._session = requests.Session()
        self._session.headers.update(
            {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
                'Accept': 'application/json, text/plain, */*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Connection': 'keep-alive',
            }
        )
        # Optional pooled HTTP client for future migration
        try:
            from utils.http_client import HTTPClient  # type: ignore

            self._http = HTTPClient(headers=dict(self._session.headers))
        except Exception:
            self._http = None  # type: ignore
        # opt-in flag to force HTTPClient exclusively; default False to keep tests patching _session working
        try:
            self._http_only = os.getenv('WSAPP_HTTPCLIENT_ONLY', '0').strip().lower() in (
                '1',
                'true',
                'yes',
                'on',
            )
        except Exception:
            self._http_only = False

        # Simple in-memory caches to avoid hammering endpoints
        # quote cache: key=(symbol)
        # series cache: key=(symbol, interval, outputsize)
        self._quote_cache: dict[str, tuple[float, dict, bool]] = {}
        self._series_cache: dict[tuple[str, str, str], tuple[float, dict, bool]] = {}
        # TTLs (configurable via environment)
        try:
            self._quote_ttl = float(os.getenv('YAHOO_QUOTE_TTL_SEC', '60'))
        except Exception:
            self._quote_ttl = 60.0
        try:
            self._series_ttl = float(os.getenv('YAHOO_SERIES_TTL_SEC', '300'))
        except Exception:
            self._series_ttl = 300.0
        try:
            self._neg_quote_ttl = float(os.getenv('YAHOO_NEG_QUOTE_TTL_SEC', '15'))
        except Exception:
            self._neg_quote_ttl = 15.0
        try:
            self._neg_series_ttl = float(os.getenv('YAHOO_NEG_SERIES_TTL_SEC', '45'))
        except Exception:
            self._neg_series_ttl = 45.0

        # optional persistent cache; APIManager can set this attribute after construction
        self._persistent_cache = None  # type: ignore
        try:
            self._screener_ttl = float(os.getenv('CACHE_TTL_SCREENER_SEC', '180'))
        except Exception:
            self._screener_ttl = 180.0

        # Simple metrics counters
        self._metrics = {
            'quote_hit': 0,
            'quote_miss': 0,
            'quote_stale': 0,
            'series_hit': 0,
            'series_miss': 0,
            'series_stale': 0,
            'screener_hit': 0,
            'screener_miss': 0,
        }

        # Basic rate limiting with exponential backoff on 429s (shared across all requests)
        self._lock = threading.Lock()
        self._next_allowed_ts: float = 0.0
        self._backoff_sec: float = 0.0
        # Logging control: set YAHOO_LOG_ERRORS=1 to enable console error logs
        self._log_errors = os.getenv('YAHOO_LOG_ERRORS', '0').strip() in ('1', 'true', 'yes', 'on')
        # Optional circuit breaker
        try:
            from utils.circuit_breaker import CircuitBreaker  # type: ignore

            self._cb = CircuitBreaker(
                name='yahoo',
                failure_threshold=int(os.getenv('YAHOO_CB_FAILURES', '8') or '8'),
                recovery_time=float(os.getenv('YAHOO_CB_RECOVERY_SEC', '20') or '20'),
                half_open_max_calls=int(os.getenv('YAHOO_CB_HALF_OPEN_MAX', '3') or '3'),
            )
        except Exception:
            self._cb = None  # type: ignore

    def breaker_stats(self) -> dict:
        try:
            if getattr(self, '_cb', None):
                return self._cb.stats()  # type: ignore[attr-defined]
        except Exception:
            pass
        return {}

    def _rate_limited(self) -> bool:
        # Non-blocking check to avoid spamming when we already know we're limited
        with self._lock:
            return time.time() < self._next_allowed_ts

    def _note_429(self):
        # Increase backoff with jitter and set next allowed time
        with self._lock:
            self._backoff_sec = max(
                2.0, min(60.0, self._backoff_sec * 2.0 if self._backoff_sec else 2.0)
            )
            jitter = random.uniform(0.2, 0.8)
            self._next_allowed_ts = time.time() + self._backoff_sec + jitter

    def _note_success(self):
        # On success gradually reduce backoff
        with self._lock:
            if self._backoff_sec:
                self._backoff_sec = max(0.0, self._backoff_sec * 0.5)
                if self._backoff_sec == 0:
                    self._next_allowed_ts = 0.0

    def get_quote(self, symbol: str) -> dict | None:
        # Serve from cache when fresh
        now = time.time()
        cached_entry = self._quote_cache.get(symbol)
        cached_ts: float | None = None
        cached_data: dict | None = None
        cached_neg = False
        if isinstance(cached_entry, tuple):
            if len(cached_entry) == 3:
                cached_ts, cached_data, cached_neg = cached_entry  # type: ignore[assignment]
            elif len(cached_entry) == 2:
                cached_ts, cached_data = cached_entry  # type: ignore[assignment]
        if cached_ts is not None and cached_data is not None:
            ttl = self._neg_quote_ttl if cached_neg else self._quote_ttl
            if (now - cached_ts) < ttl:
                try:
                    self._metrics['quote_hit'] += 1
                except Exception:
                    pass
                return cached_data

        # Respect backoff window
        if self._rate_limited():
            # Serve stale-if-error if available
            if cached_data is not None:
                try:
                    self._metrics['quote_stale'] += 1
                except Exception:
                    pass
                return cached_data
            return {}

        try:
            if getattr(self, '_cb', None):
                from utils.circuit_breaker import CircuitOpenError  # type: ignore

                try:
                    with self._cb:  # type: ignore[attr-defined]
                        if not getattr(self, '_http_only', False) and getattr(
                            self, '_session', None
                        ):
                            resp = self._session.get(
                                self.BASE_QUOTE, params={'symbols': symbol}, timeout=10
                            )
                        elif getattr(self, '_http', None):
                            resp = self._http.get(self.BASE_QUOTE, params={'symbols': symbol})  # type: ignore[assignment]
                        else:
                            resp = requests.get(
                                self.BASE_QUOTE, params={'symbols': symbol}, timeout=10
                            )
                except CircuitOpenError:
                    raise requests.HTTPError('Circuit open for Yahoo quote')
            else:
                if not getattr(self, '_http_only', False) and getattr(self, '_session', None):
                    resp = self._session.get(
                        self.BASE_QUOTE, params={'symbols': symbol}, timeout=10
                    )
                elif getattr(self, '_http', None):
                    resp = self._http.get(self.BASE_QUOTE, params={'symbols': symbol})  # type: ignore[assignment]
                else:
                    resp = requests.get(self.BASE_QUOTE, params={'symbols': symbol}, timeout=10)
            if resp.status_code == 429:
                self._note_429()
                if cached_data is not None:
                    return cached_data
                raise requests.HTTPError("429 Too Many Requests")
            # Treat common statuses gracefully without noisy exceptions
            if resp.status_code in (401, 403, 404):
                # cache empty to avoid repeated retries for this symbol within TTL
                out: dict = {}
                self._quote_cache[symbol] = (now, out, True)
                return out
            resp.raise_for_status()
            self._note_success()
            data = resp.json() or {}
            result = (data.get('quoteResponse') or {}).get('result') or []
            if not result:
                out: dict = {}
                # Cache empty to avoid repeated hits for missing symbols for a short time (negative TTL)
                self._quote_cache[symbol] = (now, out, True)
                return out
            q = result[0]
            # Normalize to Alpha Vantage-like keys used elsewhere
            price = q.get('regularMarketPrice')
            change = q.get('regularMarketChange')
            change_pct = q.get('regularMarketChangePercent')
            out = {
                '05. price': f"{price}" if price is not None else "0",
                '09. change': f"{change}" if change is not None else "0",
                '10. change percent': f"{change_pct}%" if change_pct is not None else "0%",
            }
            self._quote_cache[symbol] = (now, out, False)
            try:
                self._metrics['quote_miss'] += 1
            except Exception:
                pass
            return out
        except Exception as e:
            # Keep logs minimal to avoid flooding the console (opt-in via env)
            if self._log_errors:
                print(f"Yahoo quote error: {e}")
            if cached_data is not None:
                return cached_data
            # cache empty (negative TTL) to throttle retries briefly
            self._quote_cache[symbol] = (now, {}, True)
            try:
                self._metrics['quote_miss'] += 1
            except Exception:
                pass
            return {}

    def get_time_series(
        self, symbol: str, interval: str = '1day', outputsize: str = 'compact'
    ) -> dict | None:
        """Return Alpha-Vantage-like time series dict built from Yahoo chart API."""
        # Cache check
        now = time.time()
        cache_key = (symbol, interval, outputsize)
        cached_entry = self._series_cache.get(cache_key)
        cached_ts: float | None = None
        cached_data: dict | None = None
        cached_neg = False
        if isinstance(cached_entry, tuple):
            if len(cached_entry) == 3:
                cached_ts, cached_data, cached_neg = cached_entry  # type: ignore[assignment]
            elif len(cached_entry) == 2:
                cached_ts, cached_data = cached_entry  # type: ignore[assignment]
        if cached_ts is not None and cached_data is not None:
            ttl = self._neg_series_ttl if cached_neg else self._series_ttl
            if (now - cached_ts) < ttl:
                try:
                    self._metrics['series_hit'] += 1
                except Exception:
                    pass
                return cached_data

        # Respect rate limit window
        if self._rate_limited():
            if cached_data is not None:
                try:
                    self._metrics['series_stale'] += 1
                except Exception:
                    pass
                return cached_data
            return {'Time Series (Daily)': {}} if interval == '1day' else {}

        try:
            # Map intervals and pick a reasonable range
            if interval in {'1min', '5min', '15min', '30min', '60min', '1hour'}:
                yahoo_interval = {
                    '1min': '1m',
                    '5min': '5m',
                    '15min': '15m',
                    '30min': '30m',
                    '60min': '60m',
                    '1hour': '60m',
                }[interval]
                rng = '5d' if outputsize == 'compact' else '1mo'
                title = f"Time Series ({yahoo_interval})"
            elif interval == '1week':
                yahoo_interval = '1wk'
                rng = '3y'
                title = 'Time Series (Weekly)'
            elif interval == '1month':
                yahoo_interval = '1mo'
                rng = '10y'
                title = 'Time Series (Monthly)'
            else:
                yahoo_interval = '1d'
                rng = '6mo' if outputsize == 'compact' else 'max'
                title = 'Time Series (Daily)'

            params = {
                'interval': yahoo_interval,
                'range': rng,
                'includePrePost': 'false',
                'events': 'div,split',
            }
            if getattr(self, '_cb', None):
                from utils.circuit_breaker import CircuitOpenError  # type: ignore

                try:
                    with self._cb:  # type: ignore[attr-defined]
                        if not getattr(self, '_http_only', False) and getattr(
                            self, '_session', None
                        ):
                            resp = self._session.get(
                                f"{self.BASE_CHART}/{symbol}", params=params, timeout=10
                            )
                        elif getattr(self, '_http', None):
                            resp = self._http.get(f"{self.BASE_CHART}/{symbol}", params=params)  # type: ignore[assignment]
                        else:
                            resp = requests.get(
                                f"{self.BASE_CHART}/{symbol}", params=params, timeout=10
                            )
                except CircuitOpenError:
                    raise requests.HTTPError('Circuit open for Yahoo chart')
            else:
                if not getattr(self, '_http_only', False) and getattr(self, '_session', None):
                    resp = self._session.get(
                        f"{self.BASE_CHART}/{symbol}", params=params, timeout=10
                    )
                elif getattr(self, '_http', None):
                    resp = self._http.get(f"{self.BASE_CHART}/{symbol}", params=params)  # type: ignore[assignment]
                else:
                    resp = requests.get(f"{self.BASE_CHART}/{symbol}", params=params, timeout=10)
            if resp.status_code == 429:
                self._note_429()
                if cached_data is not None:
                    return cached_data
                raise requests.HTTPError("429 Too Many Requests")
            if resp.status_code in (401, 403, 404):
                # cache empty structure to avoid repeated attempts
                out = {title: {}}
                self._series_cache[cache_key] = (now, out, True)
                return out
            resp.raise_for_status()
            self._note_success()
            data = resp.json() or {}
            result = (data.get('chart') or {}).get('result') or []
            if not result:
                out = {title: {}}
                self._series_cache[cache_key] = (now, out, True)
                return out
            r0 = result[0]
            timestamps = r0.get('timestamp') or []
            quotes = ((r0.get('indicators') or {}).get('quote')) or []
            if not timestamps or not quotes:
                out = {title: {}}
                self._series_cache[cache_key] = (now, out, True)
                return out
            q0 = quotes[0]
            opens = q0.get('open') or []
            highs = q0.get('high') or []
            lows = q0.get('low') or []
            closes = q0.get('close') or []
            volumes = q0.get('volume') or []

            # Some intraday ranges use epoch seconds; we'll format to ISO date/time strings
            out: dict[str, dict[str, str]] = {}
            from datetime import datetime, timezone

            for i, ts in enumerate(timestamps):
                try:
                    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                    key = (
                        dt.strftime('%Y-%m-%d %H:%M:%S')
                        if yahoo_interval.endswith('m')
                        else dt.strftime('%Y-%m-%d')
                    )
                    out[key] = {
                        '1. open': (
                            str(opens[i]) if i < len(opens) and opens[i] is not None else '0'
                        ),
                        '2. high': (
                            str(highs[i]) if i < len(highs) and highs[i] is not None else '0'
                        ),
                        '3. low': str(lows[i]) if i < len(lows) and lows[i] is not None else '0',
                        '4. close': (
                            str(closes[i]) if i < len(closes) and closes[i] is not None else '0'
                        ),
                        '5. volume': (
                            str(volumes[i]) if i < len(volumes) and volumes[i] is not None else '0'
                        ),
                    }
                except Exception:
                    continue

            out_wrapped = {title: out}
            self._series_cache[cache_key] = (now, out_wrapped, False)
            try:
                self._metrics['series_miss'] += 1
            except Exception:
                pass
            return out_wrapped
        except Exception as e:
            if self._log_errors:
                print(f"Yahoo time series error: {e}")
            if cached_data is not None:
                return cached_data
            # cache empty to throttle retries (negative TTL)
            try:
                out = {title: {}}
            except Exception:
                out = {}
            self._series_cache[cache_key] = (now, out, True)
            try:
                self._metrics['series_miss'] += 1
            except Exception:
                pass
            return out

    def get_technical_indicators(
        self, symbol: str, indicator: str = 'RSI', interval: str = 'daily'
    ) -> dict | None:
        """Yahoo endpoint does not provide indicator endpoints; return None."""
        return None

    # ----------------- Screeners (day gainers/losers/most actives) -----------------
    def get_predefined_screener(
        self, scr_id: str, count: int = 50, region: str = 'CA'
    ) -> list[dict]:
        """Fetch predefined screener results from Yahoo.

        Common scr_ids: 'day_gainers', 'day_losers', 'most_actives'.
        Region 'CA' limits to Canadian listings.
        """
        try:
            # persistent cache read-through
            try:
                if getattr(self, '_persistent_cache', None):
                    ckey = f"{scr_id}|{int(count)}|{region}"
                    cached = self._persistent_cache.get_if_fresh(
                        'screener', ckey, max_age_s=self._screener_ttl
                    )
                    if isinstance(cached, list) and cached:
                        try:
                            self._metrics['screener_hit'] += 1
                        except Exception:
                            pass
                        return cached
            except Exception:
                pass
            params = {
                'count': str(int(max(1, min(250, count)))),
                'scrIds': scr_id,
                'lang': 'en-CA',
                'region': region,
            }
            url = 'https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved'
            if getattr(self, '_cb', None):
                from utils.circuit_breaker import CircuitOpenError  # type: ignore

                try:
                    with self._cb:  # type: ignore[attr-defined]
                        if not getattr(self, '_http_only', False) and getattr(
                            self, '_session', None
                        ):
                            resp = self._session.get(url, params=params, timeout=12)
                        elif getattr(self, '_http', None):
                            resp = self._http.get(url, params=params)  # type: ignore[assignment]
                        else:
                            resp = requests.get(url, params=params, timeout=12)
                except CircuitOpenError:
                    raise requests.HTTPError('Circuit open for Yahoo screener')
            else:
                if not getattr(self, '_http_only', False) and getattr(self, '_session', None):
                    resp = self._session.get(url, params=params, timeout=12)
                elif getattr(self, '_http', None):
                    resp = self._http.get(url, params=params)  # type: ignore[assignment]
                else:
                    resp = requests.get(url, params=params, timeout=12)
            if resp.status_code == 429:
                self._note_429()
                raise requests.HTTPError('429 Too Many Requests')
            if resp.status_code in (401, 403, 404):
                return []
            resp.raise_for_status()
            self._note_success()
            data = resp.json() or {}
            results = ((data.get('finance') or {}).get('result')) or []
            if not results:
                return []
            quotes = results[0].get('quotes') or []
            out = []
            for q in quotes:
                try:
                    out.append(
                        {
                            'symbol': q.get('symbol'),
                            'name': q.get('shortName') or q.get('longName') or '',
                            'price': float(q.get('regularMarketPrice') or 0),
                            'change': float(q.get('regularMarketChange') or 0),
                            'changePct': float(q.get('regularMarketChangePercent') or 0),
                            'volume': float(q.get('regularMarketVolume') or 0),
                            'exchange': q.get('fullExchangeName') or q.get('exchange') or '',
                        }
                    )
                except Exception:
                    continue
            # write-through
            try:
                if getattr(self, '_persistent_cache', None):
                    ckey = f"{scr_id}|{int(count)}|{region}"
                    self._persistent_cache.set('screener', ckey, out)
            except Exception:
                pass
            try:
                self._metrics['screener_miss'] += 1
            except Exception:
                pass
            return out
        except Exception as e:
            if self._log_errors:
                print(f"Yahoo screener error: {e}")
            # stale-if-error
            try:
                if getattr(self, '_persistent_cache', None):
                    ckey = f"{scr_id}|{int(count)}|{region}"
                    stale = self._persistent_cache.get_any('screener', ckey)
                    if isinstance(stale, list) and stale:
                        return stale
            except Exception:
                pass
            return []


# Sentinel to distinguish omitted arguments from explicit None
_UNSET = object()


class TelegramNotifier:
    """Telegram bot for portfolio notifications."""

    def __init__(self, bot_token: str | None = _UNSET, chat_id: str | None = _UNSET):
        # If args are omitted, fall back to environment; if explicitly None, respect None (treat as unconfigured)
        if bot_token is _UNSET:
            self.bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        else:
            self.bot_token = bot_token  # type: ignore[assignment]
        if chat_id is _UNSET:
            self.chat_id = os.getenv('TELEGRAM_CHAT_ID')
        else:
            self.chat_id = chat_id  # type: ignore[assignment]
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}" if self.bot_token else None
        self._polling = False
        self._last_update_id = None
        # Error tracking for throttling
        self._err_count = 0

    def send_message(self, text: str, parse_mode: str = 'HTML') -> bool:
        """Send message to configured chat."""
        if not (self.base_url and self.chat_id):
            return False

        try:
            url = f"{self.base_url}/sendMessage"
            data = {'chat_id': self.chat_id, 'text': text, 'parse_mode': parse_mode}
            response = requests.post(url, json=data, timeout=10)
            response.raise_for_status()
            return True
        except Exception as e:
            print(f"Telegram error: {e}")
            return False

    def set_bot_commands(self, commands: list[dict[str, str]] | None = None) -> bool:
        """Set bot command menu for clients (best-effort)."""
        if not self.base_url:
            return False
        if commands is None:
            commands = [
                {"command": "start", "description": "Bienvenue / aide"},
                {"command": "help", "description": "Aide"},
                {"command": "insights", "description": "Résumé/Insights du portefeuille"},
                {"command": "advisor", "description": "Conseiller (AI)"},
                {"command": "quote", "description": "Cours d'un symbole"},
                {"command": "signal", "description": "Signal technique SMA 5/20"},
                {"command": "positions", "description": "Positions"},
                {"command": "signals", "description": "Signaux récents"},
                {"command": "movers", "description": "Mouvements marché (CA)"},
                {"command": "opportunites", "description": "Opportunités (CA)"},
            ]
        try:
            url = f"{self.base_url}/setMyCommands"
            data = {"commands": commands}
            resp = requests.post(url, json=data, timeout=10)
            resp.raise_for_status()
            return True
        except Exception as e:
            print(f"Telegram set commands error: {e}")
            return False

    def send_alert(self, title: str, message: str, level: str = "INFO") -> bool:
        """Send formatted alert message."""
        emoji = {"INFO": "ℹ️", "WARN": "⚠️", "ALERT": "🚨"}.get(level, "📊")
        timestamp = datetime.now().strftime("%H:%M:%S")

        # Optional enrichment for TECH_* depending on app_config setting
        tech_prefix = ""
        tech_suffix = ""
        tech_fmt = 'plain'
        try:
            from wsapp_gui.config import app_config  # type: ignore

            tech_fmt = str(app_config.get('integrations.telegram.tech_format', 'plain') or 'plain')
        except Exception:
            tech_fmt = 'plain'

        # Extract code from conventional title "Portfolio Alert - CODE"
        code = None
        try:
            if title and ' - ' in title:
                code = title.split(' - ', 1)[1]
        except Exception:
            code = None
        if code and str(code).startswith('TECH_') and tech_fmt == 'emoji-rich':
            if 'BUY' in code:
                tech_prefix, tech_suffix = '🟢📈 ', ' ✅'
            elif 'SELL' in code:
                tech_prefix, tech_suffix = '🔴📉 ', ' ⚠️'
            else:
                tech_prefix, tech_suffix = '🧠📊 ', ''

        text = (
            f"{emoji} <b>{tech_prefix}{title}{tech_suffix}</b>\n{message}\n\n<i>📅 {timestamp}</i>"
        )
        return self.send_message(text)

    def send_portfolio_summary(self, total_value: float, pnl: float, positions_count: int) -> bool:
        """Send portfolio summary notification."""
        pnl_emoji = "📈" if pnl >= 0 else "📉"
        text = (
            f"📊 <b>Portfolio Summary</b>\n\n"
            f"💰 Total Value: ${total_value:,.2f}\n"
            f"{pnl_emoji} P&L: ${pnl:,.2f}\n"
            f"📋 Positions: {positions_count}\n\n"
            f"<i>📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}</i>"
        )
        return self.send_message(text)

    def send_message_to(self, chat_id: str, text: str, parse_mode: str = 'HTML') -> bool:
        """Send a message to a specific chat id (overrides default)."""
        if not self.base_url:
            return False
        try:
            url = f"{self.base_url}/sendMessage"
            data = {'chat_id': chat_id, 'text': text, 'parse_mode': parse_mode}
            response = requests.post(url, json=data, timeout=10)
            response.raise_for_status()
            return True
        except Exception as e:
            print(f"Telegram error: {e}")
            return False

    # ------------ Inbound chat (optional polling) ------------
    def get_updates(self, timeout: int = 20) -> list[dict]:
        """Fetch new updates via long polling. Returns a list of update dicts.
        Uses offset to avoid duplicates. Requires bot_token.
        """
        if not self.base_url:
            return []
        try:
            params = {'timeout': timeout}
            if self._last_update_id is not None:
                params['offset'] = self._last_update_id + 1
            resp = requests.get(f"{self.base_url}/getUpdates", params=params, timeout=timeout + 5)
            resp.raise_for_status()
            data = resp.json() or {}
            updates = data.get('result', []) or []
            if updates:
                self._last_update_id = updates[-1].get('update_id', self._last_update_id)
            # success: reset error counter
            self._err_count = 0
            return updates
        except Exception as e:
            print(f"Telegram getUpdates error: {e}")
            # mark error to trigger cooldown in polling loop
            try:
                self._err_count = min(8, self._err_count + 1)
            except Exception:
                self._err_count = 1
            return []

    def start_polling(self, handler, allowed_chat_id: str | None = None):
        """Start a background thread to poll Telegram updates and invoke handler(text, chat_id).
        If allowed_chat_id is set, only messages from that chat are processed.
        """
        if not self.base_url:
            return False
        if self._polling:
            return True

        def _loop():
            self._polling = True
            while self._polling:
                updates = self.get_updates(timeout=25)
                for upd in updates:
                    msg = upd.get('message') or {}
                    chat = msg.get('chat') or {}
                    chat_id = str(chat.get('id')) if chat.get('id') is not None else None
                    if allowed_chat_id and chat_id != str(allowed_chat_id):
                        continue
                    text = msg.get('text')
                    if text:
                        try:
                            handler(text, chat_id)
                        except Exception as e:
                            print(f"Telegram handler error: {e}")
                # pause; exponential backoff on consecutive errors
                base = 0.8
                factor = 2 ** max(0, int(getattr(self, '_err_count', 0)))
                delay = min(10.0, base * factor)
                time.sleep(delay)

        t = threading.Thread(target=_loop, daemon=True)
        t.start()
        return True

    def stop_polling(self):
        self._polling = False

    # ------------- Simple command handler: /summary -> send insights -------------
    def start_command_handler(
        self,
        agent,
        allowed_chat_id: str | None = None,
        allowed_chat_ids: list[str] | None = None,
        trade_executor=None,
        strategy_runner=None,
    ):
        """Start polling and handle simple commands like /summary.

        The handler will reply with the portfolio insights using the provided agent.
        """
        if not self.base_url:
            return False

        def _handler(text: str, chat_id: str | None):
            try:
                if not text:
                    return
                # authorization (single or list)
                if allowed_chat_id and chat_id != str(allowed_chat_id):
                    return
                if allowed_chat_ids and (
                    chat_id is None or str(chat_id) not in set(map(str, allowed_chat_ids))
                ):
                    return
                t = text.strip().lower()
                # Shortcuts to shared objects
                _ex = trade_executor
                _am = getattr(agent, 'api_manager', None)
                # Summary/insights
                if t.startswith('/summary') or t.startswith('/insights'):
                    # Prefer public insights() if available; fallback to chat command
                    try:
                        msg = agent.insights()
                    except Exception:
                        msg = agent.chat('insights') if agent else 'Insights non disponibles.'
                    self.send_message_to(chat_id or self.chat_id, msg)
                    return
                # Advisor explicit (alias of insights)
                if t.startswith('/advisor'):
                    try:
                        msg = agent.insights()
                    except Exception:
                        msg = agent.chat('insights') if agent else 'Conseiller indisponible.'
                    self.send_message_to(chat_id or self.chat_id, msg)
                    return
                # Quote for symbol
                if t.startswith('/quote'):
                    parts = text.strip().split()
                    if len(parts) >= 2 and agent and getattr(agent, 'api_manager', None):
                        sym = parts[1].upper()
                        try:
                            q = agent.api_manager.get_quote(sym)
                            price = q.get('05. price', '0') if isinstance(q, dict) else '0'
                            chg = q.get('10. change percent', '0%') if isinstance(q, dict) else '0%'
                            msg = f"{sym}: {price} ({chg})"
                        except Exception:
                            msg = f"Citation indisponible pour {sym}."
                        self.send_message_to(chat_id or self.chat_id, msg)
                    else:
                        self.send_message_to(chat_id or self.chat_id, "Usage: /quote SYM")
                    return
                # Technical signal for symbol (delegates to agent.chat)
                if t.startswith('/signal'):
                    parts = text.strip().split()
                    if len(parts) >= 2 and agent:
                        sym = parts[1].upper()
                        msg = agent.chat(f"signal {sym}")
                        self.send_message_to(chat_id or self.chat_id, msg)
                    else:
                        self.send_message_to(chat_id or self.chat_id, "Usage: /signal SYM")
                    return
                # Positions (top)
                if t.startswith('/positions') or t.startswith('/pos'):
                    msg = agent.chat('positions') if agent else 'Aucune position.'
                    self.send_message_to(chat_id or self.chat_id, msg)
                    return
                # Signals
                if t.startswith('/signals') or t.startswith('/signal'):
                    msg = agent.chat('signals') if agent else 'Aucun signal.'
                    self.send_message_to(chat_id or self.chat_id, msg)
                    return
                # Movers (CA)
                if t.startswith('/movers') or t.startswith('/mouvements'):
                    msg = agent.chat('movers') if agent else 'Non disponible.'
                    self.send_message_to(chat_id or self.chat_id, msg)
                    return
                # Opportunities (CA)
                if t.startswith('/opportunites') or t.startswith('/opportunities'):
                    msg = agent.chat('opportunites') if agent else 'Non disponible.'
                    self.send_message_to(chat_id or self.chat_id, msg)
                    return
                # Help
                if t.startswith('/help') or t == '/start':
                    self.send_message_to(
                        chat_id or self.chat_id,
                        (
                            "Commandes:\n"
                            "/summary | /insights\n"
                            "/advisor\n"
                            "/quote SYM\n"
                            "/signal SYM\n"
                            "/positions\n"
                            "/signals\n"
                            "/movers\n"
                            "/opportunites\n"
                            "— Contrôle —\n"
                            "/status                       (état AutoTrade)\n"
                            "/autotrade on|off            (activer/désactiver)\n"
                            "/mode paper|live [confirm]   (sécurisé: live exige confirm)\n"
                            "/size N                       (taille base ex: 1000)\n"
                            "/buy SYM [qty N|$N] [mkt|limit P|stop P|stoplimit S L]\n"
                            "/sell SYM [qty N|$N] [mkt|limit P|stop P|stoplimit S L]\n"
                            "/metrics                      (compteurs API)\n"
                            "/profile SYM1,SYM2 [series]  (profilage rapide)\n"
                            "/provider show|alpha|yahoo    (source marché)\n"
                        ),
                    )
                    return
                # ---- Control: status ----
                if t.startswith('/status'):
                    msg = []
                    if _ex is not None:
                        try:
                            msg.append(_ex.summary())
                            acts = _ex.last_actions(5)
                            if acts:
                                msg.append("Dernières actions:")
                                msg.extend(f" - {a}" for a in acts)
                        except Exception:
                            pass
                    if _am is not None:
                        try:
                            prov = getattr(_am, 'get_market_provider', lambda: 'unknown')()
                            msg.append(f"Provider: {prov}")
                        except Exception:
                            pass
                    out = "\n".join(msg) or "Aucun état disponible."
                    self.send_message_to(chat_id or self.chat_id, out)
                    return
                # ---- Control: autotrade on/off ----
                if t.startswith('/autotrade'):
                    parts = text.strip().split()
                    if _ex is None:
                        self.send_message_to(chat_id or self.chat_id, "Exécuteur indisponible.")
                        return
                    if len(parts) >= 2:
                        onoff = parts[1].lower()
                        try:
                            enabled = onoff in ('on', '1', 'true', 'yes', 'enable', 'enabled')
                            _ex.configure(enabled=enabled)
                            # Persist preference if GUI config exists
                            try:
                                from wsapp_gui.config import app_config as _cfg  # type: ignore

                                _cfg.set('autotrade.enabled', bool(enabled))
                            except Exception:
                                pass
                            self.send_message_to(
                                chat_id or self.chat_id,
                                f"AutoTrade -> {'ON' if enabled else 'OFF'}",
                            )
                        except Exception as e:
                            self.send_message_to(chat_id or self.chat_id, f"Erreur: {e}")
                    else:
                        self.send_message_to(chat_id or self.chat_id, "Usage: /autotrade on|off")
                    return
                # ---- Control: mode paper|live ----
                if t.startswith('/mode'):
                    parts = text.strip().split()
                    if _ex is None:
                        self.send_message_to(chat_id or self.chat_id, "Exécuteur indisponible.")
                        return
                    if len(parts) >= 2:
                        mode = parts[1].lower()
                        if mode not in ('paper', 'live'):
                            self.send_message_to(
                                chat_id or self.chat_id, "Usage: /mode paper|live [confirm]"
                            )
                            return
                        if mode == 'live' and (len(parts) < 3 or parts[2].lower() != 'confirm'):
                            self.send_message_to(
                                chat_id or self.chat_id,
                                "Sécurité: confirmez avec /mode live confirm",
                            )
                            return
                        try:
                            _ex.configure(mode=mode)
                            try:
                                from wsapp_gui.config import app_config as _cfg  # type: ignore

                                _cfg.set('autotrade.mode', mode)
                            except Exception:
                                pass
                            self.send_message_to(chat_id or self.chat_id, f"Mode -> {mode.upper()}")
                        except Exception as e:
                            self.send_message_to(chat_id or self.chat_id, f"Erreur: {e}")
                    else:
                        self.send_message_to(
                            chat_id or self.chat_id, "Usage: /mode paper|live [confirm]"
                        )
                    return
                # ---- Control: base size ----
                if t.startswith('/size'):
                    parts = text.strip().split()
                    if _ex is None:
                        self.send_message_to(chat_id or self.chat_id, "Exécuteur indisponible.")
                        return
                    if len(parts) >= 2:
                        try:
                            size = float(parts[1].replace(',', ''))
                            _ex.configure_simple(enabled=_ex.enabled, mode=_ex.mode, base_size=size)
                            try:
                                from wsapp_gui.config import app_config as _cfg  # type: ignore

                                _cfg.set('autotrade.base_size', float(size))
                            except Exception:
                                pass
                            self.send_message_to(chat_id or self.chat_id, f"Taille -> {size:.0f}")
                        except Exception as e:
                            self.send_message_to(chat_id or self.chat_id, f"Erreur: {e}")
                    else:
                        self.send_message_to(chat_id or self.chat_id, "Usage: /size N")
                    return
                # ---- Control: provider show|alpha|yahoo ----
                if t.startswith('/provider'):
                    parts = text.strip().split()
                    if _am is None:
                        self.send_message_to(chat_id or self.chat_id, "API manager indisponible.")
                        return
                    if len(parts) == 1 or parts[1].lower() == 'show':
                        prov = getattr(_am, 'get_market_provider', lambda: 'unknown')()
                        self.send_message_to(chat_id or self.chat_id, f"Provider: {prov}")
                        return
                    target = parts[1].lower()
                    try:
                        setf = getattr(_am, 'set_market_provider', None)
                        if callable(setf):
                            newp = setf(target)
                            self.send_message_to(chat_id or self.chat_id, f"Provider -> {newp}")
                        else:
                            self.send_message_to(
                                chat_id or self.chat_id, "Changement provider non supporté."
                            )
                    except Exception as e:
                        self.send_message_to(chat_id or self.chat_id, f"Erreur: {e}")
                    return
                # ---- Diagnostics: metrics ----
                if t.startswith('/metrics'):
                    if _am is None:
                        self.send_message_to(chat_id or self.chat_id, "API manager indisponible.")
                        return
                    try:
                        m = _am.get_metrics_counters()
                    except Exception:
                        m = {}
                    try:
                        cstats = _am.get_cache_stats()
                    except Exception:
                        cstats = {}
                    msg = ["[API Metrics]"]
                    if m:
                        for k, v in m.items():
                            msg.append(f" - {k}: {v}")
                    if cstats:
                        total = cstats.get('total')
                        msg.append(f"[Cache] total rows: {total}")
                        ns = cstats.get('namespaces') or {}
                        for ns_name, info in ns.items():
                            msg.append(f" - {ns_name}: {info.get('count')}")
                    self.send_message_to(chat_id or self.chat_id, "\n".join(msg))
                    return
                # ---- Diagnostics: profile ----
                if t.startswith('/profile'):
                    if _am is None:
                        self.send_message_to(chat_id or self.chat_id, "API manager indisponible.")
                        return
                    parts = text.strip().split()
                    if len(parts) >= 2:
                        syms = [s.strip().upper() for s in parts[1].split(',') if s.strip()]
                    else:
                        syms = []
                    include_series = 'series' in t
                    if not syms:
                        self.send_message_to(
                            chat_id or self.chat_id, "Usage: /profile SYM1,SYM2 [series]"
                        )
                        return
                    try:
                        stats = _am.profile_hot_paths(syms, include_series=include_series)
                        self.send_message_to(chat_id or self.chat_id, json.dumps(stats, indent=2))
                    except Exception as e:
                        self.send_message_to(chat_id or self.chat_id, f"Erreur: {e}")
                    return
                # ---- Orders: /buy and /sell (paper by default) ----
                if t.startswith('/buy') or t.startswith('/sell'):
                    if _ex is None:
                        self.send_message_to(chat_id or self.chat_id, "Exécuteur indisponible.")
                        return
                    parts = text.strip().split()
                    if len(parts) < 2:
                        self.send_message_to(
                            chat_id or self.chat_id,
                            "Usage: /buy SYM [qty N|$N] [mkt|limit P|stop P|stoplimit S L]",
                        )
                        return
                    side = 'buy' if t.startswith('/buy') else 'sell'
                    sym = parts[1].upper()
                    qty = None
                    notional = None
                    order_type = 'market'
                    limit_price = None
                    stop_price = None
                    # parse remaining tokens
                    i = 2
                    while i < len(parts):
                        tok = parts[i].lower()
                        if tok == 'qty' and i + 1 < len(parts):
                            try:
                                qty = float(parts[i + 1].replace(',', ''))
                            except Exception:
                                pass
                            i += 2
                            continue
                        if tok.startswith('$'):
                            try:
                                notional = float(tok[1:].replace(',', ''))
                            except Exception:
                                pass
                            i += 1
                            continue
                        if tok in ('mkt', 'market'):
                            order_type = 'market'
                            i += 1
                            continue
                        if tok == 'limit' and i + 1 < len(parts):
                            order_type = 'limit'
                            try:
                                limit_price = float(parts[i + 1].replace(',', ''))
                            except Exception:
                                pass
                            i += 2
                            continue
                        if tok == 'stop' and i + 1 < len(parts):
                            order_type = 'stop'
                            try:
                                stop_price = float(parts[i + 1].replace(',', ''))
                            except Exception:
                                pass
                            i += 2
                            continue
                        if tok == 'stoplimit' and i + 2 < len(parts):
                            order_type = 'stop_limit'
                            try:
                                stop_price = float(parts[i + 1].replace(',', ''))
                                limit_price = float(parts[i + 2].replace(',', ''))
                            except Exception:
                                pass
                            i += 3
                            continue
                        # numeric without prefix -> assume qty
                        try:
                            val = float(tok.replace(',', ''))
                            # if previously set notional, treat as qty fallback
                            if qty is None and val > 0:
                                qty = val
                        except Exception:
                            pass
                        i += 1
                    try:
                        res = _ex.place_order(
                            symbol=sym,
                            side=side,
                            order_type=order_type,
                            qty=qty,
                            notional=notional,
                            limit_price=limit_price,
                            stop_price=stop_price,
                        )
                        status = res.get('status') if isinstance(res, dict) else None
                        self.send_message_to(
                            chat_id or self.chat_id, f"{side.upper()} {sym} -> {status or 'sent'}"
                        )
                    except Exception as e:
                        self.send_message_to(chat_id or self.chat_id, f"Erreur: {e}")
                    return
                # Not a recognized command: forward raw text to agent.chat
                if agent and text and not t.startswith('/'):
                    try:
                        msg = agent.chat(text)
                    except Exception as e:
                        msg = f"Erreur agent: {e}"
                    self.send_message_to(chat_id or self.chat_id, msg)
                    return
            except Exception as e:
                print(f"Telegram command handler error: {e}")

        # Best-effort: set command menu
        try:
            self.set_bot_commands()
        except Exception:
            pass
        return self.start_polling(_handler, allowed_chat_id=allowed_chat_id)


class APIManager:
    """Central manager for all external APIs."""

    def __init__(self):
        self.news = NewsAPIClient()
        self.alpha_vantage = AlphaVantageClient()
        self.yahoo = YahooFinanceClient()
        # Optional async HTTP client scaffold (may be used by async batch APIs later)
        try:
            from utils.http_client import AsyncHTTPClient  # type: ignore

            self._async_http = AsyncHTTPClient(headers={'Accept': 'application/json'})
        except Exception:
            self._async_http = None  # type: ignore
        # Persistent cache (SQLite)
        try:
            from utils.sqlite_cache import PersistentCache  # type: ignore

            self._cache = PersistentCache(os.getenv('WSAPP_CACHE_DB') or None)
        except Exception:
            self._cache = None  # fail-soft if module not present
        # Inject persistent cache into NewsAPI client for read-through
        try:
            if self._cache and hasattr(self.news, '_persistent_cache'):
                self.news._persistent_cache = self._cache  # type: ignore
        except Exception:
            pass
        # Inject persistent cache into Yahoo client (screener caching)
        try:
            if self._cache and hasattr(self.yahoo, '_persistent_cache'):
                self.yahoo._persistent_cache = self._cache  # type: ignore
        except Exception:
            pass
        # Choose provider: MARKET_DATA_PROVIDER=alpha|yahoo; default: alpha if key configured else yahoo
        provider = os.getenv('MARKET_DATA_PROVIDER')
        if not provider:
            provider = 'alpha' if os.getenv('ALPHA_VANTAGE_KEY') else 'yahoo'
        provider = provider.lower()
        self.market = self.alpha_vantage if provider == 'alpha' else self.yahoo
        self.telegram = TelegramNotifier()
        # Micro-memoization caches for recent results (short-lived)
        self._memo_quote: dict[str, tuple[float, dict]] = {}
        self._memo_series: dict[str, tuple[float, dict]] = {}
        try:
            self._memo_quote_ttl = float(os.getenv('MEMO_QUOTE_TTL_SEC', '5'))
        except Exception:
            self._memo_quote_ttl = 5.0
        try:
            self._memo_series_ttl = float(os.getenv('MEMO_SERIES_TTL_SEC', '10'))
        except Exception:
            self._memo_series_ttl = 10.0
        # Notify rate limiting (per code)
        self._notify_last_ts: dict[str, float] = {}
        try:
            self._notify_min_interval_sec = float(os.getenv('ALERT_MIN_INTERVAL_SEC', '30'))
        except Exception:
            self._notify_min_interval_sec = 30.0
        # Coalescing for TECH_* alerts
        try:
            self._tech_coalesce_window_sec = float(os.getenv('TECH_ALERT_COALESCE_SEC', '15'))
        except Exception:
            self._tech_coalesce_window_sec = 15.0
        # Buffer entries are mutable lists: [ts, code, message, level, sent]
        self._tech_buffer: list[list] = []  # [float, str, str, str, bool]
        self._tech_buffer_lock = threading.Lock()
        self._tech_flush_timer = None
        # Optional: start persistent cache housekeeping in background
        try:
            if getattr(self, '_cache', None):
                self._start_cache_housekeeping_thread()
        except Exception:
            pass
        # Lightweight metrics counters (for diagnostics UI)
        self._metrics = {
            'quote_memo_hit': 0,
            'quote_cache_hit': 0,
            'quote_provider_alpha': 0,
            'quote_provider_yahoo': 0,
            'series_memo_hit': 0,
            'series_cache_hit': 0,
            'series_provider_alpha': 0,
            'series_provider_yahoo': 0,
        }
        # Optional: periodic breaker metrics logging
        try:
            self._start_cb_metrics_logging_thread()
        except Exception:
            pass
        # Capture http-only mode flag (propagated via env)
        try:
            self.httpclient_only = os.getenv('WSAPP_HTTPCLIENT_ONLY', '0').strip().lower() in (
                '1',
                'true',
                'yes',
                'on',
            )
        except Exception:
            self.httpclient_only = False

    # ---- Provider controls ----
    def get_market_provider(self) -> str:
        try:
            return 'alpha' if self.market is self.alpha_vantage else 'yahoo'
        except Exception:
            return 'unknown'

    def set_market_provider(self, provider: str) -> str:
        """Set market data provider to 'alpha' or 'yahoo'. Returns provider actually set.

        If selecting 'alpha' without API key, falls back to 'yahoo'.
        """
        p = (provider or '').strip().lower()
        if p == 'alpha':
            if os.getenv('ALPHA_VANTAGE_KEY'):
                self.market = self.alpha_vantage
                return 'alpha'
            # no key -> fallback
            self.market = self.yahoo
            return 'yahoo'
        # default any other to yahoo
        self.market = self.yahoo
        return 'yahoo'

    # Convenience: start Telegram command polling with an agent
    def start_telegram_commands(self, agent, allowed_chat_id: str | None = None) -> bool:
        return self.telegram.start_command_handler(agent, allowed_chat_id=allowed_chat_id)

    # ---------- Resilient wrappers with fallback ----------
    def _yahoo_quote_with_suffixes(self, symbol: str) -> dict:
        for suf in ("", ".TO", ".CN", ".NE"):
            s = symbol if not suf else f"{symbol}{suf}"
            data = self.yahoo.get_quote(s)
            if self._is_valid_quote(data):
                return data
        return {}

    def _yahoo_series_with_suffixes(self, symbol: str, interval: str, outputsize: str) -> dict:
        for suf in ("", ".TO", ".CN", ".NE"):
            s = symbol if not suf else f"{symbol}{suf}"
            data = self.yahoo.get_time_series(s, interval=interval, outputsize=outputsize)
            if self._is_valid_series(data):
                return data
        return {}

    def _is_valid_quote(self, data: dict | None) -> bool:
        if not data or not isinstance(data, dict):
            return False
        try:
            float(str(data.get('05. price', '0')).replace('%', ''))
            return True
        except Exception:
            return False

    def _is_valid_series(self, data: dict | None) -> bool:
        if not data or not isinstance(data, dict):
            return False
        # Alpha Vantage style keys contain 'Time Series'; Yahoo wrapper uses similar
        for k, v in data.items():
            if 'time series' in k.lower() and isinstance(v, dict) and len(v) > 0:
                return True
        return False

    def get_quote(self, symbol: str) -> dict:
        """Get quote preferring Alpha Vantage; falls back to Yahoo if invalid or unavailable.
        If provider is forced to 'yahoo', uses Yahoo only.
        """
        # Micro-memoization: avoid repeated work within a few seconds
        try:
            m = self._memo_quote.get(symbol)
            if m and (time.time() - m[0]) < self._memo_quote_ttl:
                try:
                    self._metrics['quote_memo_hit'] += 1
                except Exception:
                    pass
                return m[1]
        except Exception:
            pass
        # 1) Try persistent cache (fresh within 60s)
        try:
            if getattr(self, '_cache', None):
                cached = self._cache.get_if_fresh(
                    'quote', symbol, max_age_s=float(os.getenv('CACHE_TTL_QUOTE_SEC', '60'))
                )
                if isinstance(cached, dict) and self._is_valid_quote(cached):
                    try:
                        self._metrics['quote_cache_hit'] += 1
                    except Exception:
                        pass
                    return cached
        except Exception:
            pass

        use_alpha = self.market is self.alpha_vantage
        if use_alpha:
            data = self.alpha_vantage.get_quote(symbol)
            if self._is_valid_quote(data):
                try:
                    self._metrics['quote_provider_alpha'] += 1
                except Exception:
                    pass
                try:
                    if getattr(self, '_cache', None):
                        self._cache.set('quote', symbol, data)
                except Exception:
                    pass
                try:
                    self._memo_quote[symbol] = (time.time(), data)
                except Exception:
                    pass
                return data
            # fallback to Yahoo (+ suffix heuristics)
            data = self._yahoo_quote_with_suffixes(symbol)
            if self._is_valid_quote(data):
                try:
                    self._metrics['quote_provider_yahoo'] += 1
                except Exception:
                    pass
                try:
                    if getattr(self, '_cache', None):
                        self._cache.set('quote', symbol, data)
                except Exception:
                    pass
                try:
                    self._memo_quote[symbol] = (time.time(), data)
                except Exception:
                    pass
                return data
            # stale-if-error from persistent cache
            try:
                if getattr(self, '_cache', None):
                    stale = self._cache.get_any('quote', symbol)
                    if isinstance(stale, dict) and self._is_valid_quote(stale):
                        return stale
            except Exception:
                pass
            return data or {}

        # provider forced to Yahoo
        data = self._yahoo_quote_with_suffixes(symbol)
        if self._is_valid_quote(data):
            try:
                self._metrics['quote_provider_yahoo'] += 1
            except Exception:
                pass
            try:
                if getattr(self, '_cache', None):
                    self._cache.set('quote', symbol, data)
            except Exception:
                pass
            try:
                self._memo_quote[symbol] = (time.time(), data)
            except Exception:
                pass
            return data
        try:
            if getattr(self, '_cache', None):
                stale = self._cache.get_any('quote', symbol)
                if isinstance(stale, dict) and self._is_valid_quote(stale):
                    return stale
        except Exception:
            pass
        return data or {}

    def get_time_series(
        self, symbol: str, interval: str = '1day', outputsize: str = 'compact'
    ) -> dict:
        """Get time series preferring Alpha; falls back to Yahoo on failure. Respects provider override."""
        memo_key = f"{symbol}|{interval}|{outputsize}"
        try:
            m = self._memo_series.get(memo_key)
            if m and (time.time() - m[0]) < self._memo_series_ttl:
                try:
                    self._metrics['series_memo_hit'] += 1
                except Exception:
                    pass
                return m[1]
        except Exception:
            pass
        # 1) Try persistent cache (fresh within 5 minutes for series; configurable)
        cache_key = f"{symbol}|{interval}|{outputsize}"
        try:
            if getattr(self, '_cache', None):
                ttl_series = float(os.getenv('CACHE_TTL_SERIES_SEC', '300'))
                cached = self._cache.get_if_fresh('series', cache_key, max_age_s=ttl_series)
                if isinstance(cached, dict) and self._is_valid_series(cached):
                    try:
                        self._metrics['series_cache_hit'] += 1
                    except Exception:
                        pass
                    return cached
        except Exception:
            pass

        use_alpha = self.market is self.alpha_vantage
        if use_alpha:
            data = self.alpha_vantage.get_time_series(
                symbol, interval=interval, outputsize=outputsize
            )
            if self._is_valid_series(data):
                try:
                    self._metrics['series_provider_alpha'] += 1
                except Exception:
                    pass
                try:
                    if getattr(self, '_cache', None):
                        self._cache.set('series', cache_key, data)
                except Exception:
                    pass
                try:
                    self._memo_series[memo_key] = (time.time(), data)
                except Exception:
                    pass
                return data
            # fallback to Yahoo with suffix heuristics; if intraday empty, retry daily
            data = self._yahoo_series_with_suffixes(
                symbol, interval=interval, outputsize=outputsize
            )
            if self._is_valid_series(data):
                try:
                    self._metrics['series_provider_yahoo'] += 1
                except Exception:
                    pass
                try:
                    if getattr(self, '_cache', None):
                        self._cache.set('series', cache_key, data)
                except Exception:
                    pass
                try:
                    self._memo_series[memo_key] = (time.time(), data)
                except Exception:
                    pass
                return data
            if interval != '1day':
                data = self._yahoo_series_with_suffixes(
                    symbol, interval='1day', outputsize=outputsize
                )
                if self._is_valid_series(data):
                    try:
                        self._metrics['series_provider_yahoo'] += 1
                    except Exception:
                        pass
                    try:
                        if getattr(self, '_cache', None):
                            self._cache.set('series', cache_key, data)
                    except Exception:
                        pass
                    try:
                        self._memo_series[memo_key] = (time.time(), data)
                    except Exception:
                        pass
                    return data
            # stale-if-error from persistent cache
            try:
                if getattr(self, '_cache', None):
                    stale = self._cache.get_any('series', cache_key)
                    if isinstance(stale, dict) and self._is_valid_series(stale):
                        return stale
            except Exception:
                pass
            return {}

        # provider forced to Yahoo
        data = self._yahoo_series_with_suffixes(symbol, interval=interval, outputsize=outputsize)
        if self._is_valid_series(data):
            try:
                self._metrics['series_provider_yahoo'] += 1
            except Exception:
                pass
            try:
                if getattr(self, '_cache', None):
                    self._cache.set('series', cache_key, data)
            except Exception:
                pass
            try:
                self._memo_series[memo_key] = (time.time(), data)
            except Exception:
                pass
            return data
        if interval != '1day':
            data = self._yahoo_series_with_suffixes(symbol, interval='1day', outputsize=outputsize)
            if self._is_valid_series(data):
                try:
                    self._metrics['series_provider_yahoo'] += 1
                except Exception:
                    pass
                try:
                    if getattr(self, '_cache', None):
                        self._cache.set('series', cache_key, data)
                except Exception:
                    pass
                try:
                    self._memo_series[memo_key] = (time.time(), data)
                except Exception:
                    pass
                return data
        # stale-if-error from persistent cache
        try:
            if getattr(self, '_cache', None):
                stale = self._cache.get_any('series', cache_key)
                if isinstance(stale, dict) and self._is_valid_series(stale):
                    return stale
        except Exception:
            pass
        return {}

    # -------------- Diagnostics --------------
    def get_metrics_counters(self) -> dict:
        try:
            return dict(self._metrics)
        except Exception:
            return {}

    def get_market_overview(self, symbols: list[str]) -> dict:
        """Get comprehensive market overview for given symbols."""
        overview = {'quotes': {}, 'news': [], 'timestamp': datetime.now().isoformat()}

        # Get quotes for each symbol
        for symbol in symbols[:5]:  # Limit to avoid API rate limits
            quote = self.get_quote(symbol)
            if quote:
                overview['quotes'][symbol] = quote

        # Get general market news
        news = self.news.get_financial_news("stock market", 5)
        overview['news'] = news

        # Optional metrics log (set YAHOO_LOG_ERRORS=1 to see)
        try:
            if getattr(self.yahoo, '_metrics', None) and bool(
                os.getenv('YAHOO_LOG_ERRORS', '0') in ('1', 'true', 'yes', 'on')
            ):
                m = self.yahoo._metrics  # type: ignore[attr-defined]
                print(
                    f"[yahoo-metrics] quote_hit={m['quote_hit']} miss={m['quote_miss']} stale={m['quote_stale']} | series_hit={m['series_hit']} miss={m['series_miss']} stale={m['series_stale']} | screener_hit={m['screener_hit']} miss={m['screener_miss']}"
                )
        except Exception:
            pass
        return overview

    # ----------------- Metrics Export -----------------
    def get_circuit_breaker_stats(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        try:
            if hasattr(self.yahoo, 'breaker_stats'):
                out['yahoo'] = self.yahoo.breaker_stats()  # type: ignore[attr-defined]
        except Exception:
            out['yahoo'] = {}
        try:
            if hasattr(self.alpha_vantage, 'breaker_stats'):
                out['alpha_vantage'] = self.alpha_vantage.breaker_stats()  # type: ignore[attr-defined]
        except Exception:
            out['alpha_vantage'] = {}
        try:
            if hasattr(self.news, 'breaker_stats'):
                out['newsapi'] = self.news.breaker_stats()  # type: ignore[attr-defined]
        except Exception:
            out['newsapi'] = {}
        return out

    def get_cache_stats(self) -> dict:
        try:
            if getattr(self, '_cache', None):
                return self._cache.stats()  # type: ignore[attr-defined]
        except Exception:
            pass
        return {}

    def _start_cb_metrics_logging_thread(self) -> None:
        try:
            enabled = os.getenv('CB_METRICS_LOG', '0').strip().lower() in ('1', 'true', 'yes', 'on')
            if not enabled:
                return
            try:
                interval = float(os.getenv('CB_METRICS_LOG_INTERVAL_SEC', '60'))
            except Exception:
                interval = 60.0

            def _loop():
                while True:
                    try:
                        time.sleep(max(10.0, interval))
                        stats = self.get_circuit_breaker_stats()
                        y_metrics = getattr(self.yahoo, '_metrics', None)
                        print(f"[cb-metrics] stats={stats} | yahoo_counters={y_metrics}")
                    except Exception:
                        time.sleep(30.0)

            t = threading.Thread(target=_loop, daemon=True)
            t.start()
        except Exception:
            pass

    # ----------------- Lightweight profiling -----------------
    def profile_hot_paths(self, symbols: list[str], *, include_series: bool = False) -> dict:
        """Profile burst requests for quotes (and optionally series) and return timing stats.

        Returns dict with avg_ms, p95_ms for quotes and optionally series.
        Does not alter memo/config; uses current provider and caches.
        """
        import time as _t

        stats: dict[str, dict] = {}
        # Quotes burst
        qt: list[float] = []
        for s in symbols:
            t0 = _t.perf_counter()
            try:
                _ = self.get_quote(s)
            except Exception:
                pass
            qt.append((_t.perf_counter() - t0) * 1000.0)
        if qt:
            qt_sorted = sorted(qt)
            p95 = qt_sorted[min(len(qt_sorted) - 1, int(len(qt_sorted) * 0.95))]
            stats['quotes'] = {'avg_ms': sum(qt) / len(qt), 'p95_ms': p95}
        # Series burst (optional, compact daily)
        if include_series:
            st: list[float] = []
            for s in symbols:
                t0 = _t.perf_counter()
                try:
                    _ = self.get_time_series(s, interval='1day', outputsize='compact')
                except Exception:
                    pass
                st.append((_t.perf_counter() - t0) * 1000.0)
            if st:
                st_sorted = sorted(st)
                p95s = st_sorted[min(len(st_sorted) - 1, int(len(st_sorted) * 0.95))]
                stats['series'] = {'avg_ms': sum(st) / len(st), 'p95_ms': p95s}
        return stats

    # ----------------- Async batch APIs (concurrent fetches) -----------------
    async def aget_quotes(self, symbols: list[str], max_concurrency: int = 5) -> dict[str, dict]:
        """Fetch quotes concurrently for a list of symbols while reusing existing sync logic.

        Concurrency is achieved via asyncio.to_thread to preserve current provider behavior.
        """
        try:
            import asyncio
        except Exception:
            # Fallback: sequential
            return {sym: self.get_quote(sym) for sym in symbols}

        sem = asyncio.Semaphore(max(1, int(max_concurrency)))

        async def _one(sym: str) -> tuple[str, dict]:
            async with sem:
                res = await asyncio.to_thread(self.get_quote, sym)
                return sym, (res or {})

        tasks = [_one(s) for s in symbols]
        out: dict[str, dict] = {}
        for coro in asyncio.as_completed(tasks):
            try:
                k, v = await coro
                out[k] = v
            except Exception:
                continue
        return out

    async def aget_time_series_batch(
        self, reqs: list[tuple[str, str, str]], max_concurrency: int = 3
    ) -> dict[str, dict]:
        """Fetch multiple time series concurrently.

        Each request is a tuple (symbol, interval, outputsize). Result keys are 'symbol|interval|outputsize'.
        """
        try:
            import asyncio
        except Exception:
            # Fallback sequential
            out: dict[str, dict] = {}
            for sym, interval, size in reqs:
                key = f"{sym}|{interval}|{size}"
                out[key] = self.get_time_series(sym, interval=interval, outputsize=size)
            return out

        sem = asyncio.Semaphore(max(1, int(max_concurrency)))

        async def _one(sym: str, interval: str, size: str) -> tuple[str, dict]:
            key = f"{sym}|{interval}|{size}"
            async with sem:
                res = await asyncio.to_thread(self.get_time_series, sym, interval, size)
                return key, (res or {})

        tasks = [_one(sym, interval, size) for sym, interval, size in reqs]
        out: dict[str, dict] = {}
        for coro in asyncio.as_completed(tasks):
            try:
                k, v = await coro
                out[k] = v
            except Exception:
                continue
        return out

    async def aclose(self) -> None:
        """Close async resources if any."""
        try:
            if getattr(self, '_async_http', None):
                await self._async_http.aclose()  # type: ignore[attr-defined]
        except Exception:
            pass

    def notify_alert(self, signal_level: str, signal_code: str, signal_message: str) -> bool:
        """Send alert via Telegram if configured."""
        code_key = str(signal_code or '').strip() or 'GENERAL'
        # Lite per-code rate limiting to avoid bursts
        try:
            last = self._notify_last_ts.get(code_key, 0.0)
            now = time.time()
            if (now - last) < max(0.0, float(getattr(self, '_notify_min_interval_sec', 30.0))):
                return True
        except Exception:
            pass
        # Check app configuration if available
        try:
            from wsapp_gui.config import app_config  # type: ignore

            tg_enabled = bool(app_config.get('integrations.telegram.enabled', False))
            include_tech = bool(app_config.get('integrations.telegram.include_technical', True))
            allow_info = bool(app_config.get('notifications.info', False))
            allow_warn = bool(app_config.get('notifications.warn', True))
            allow_alert = bool(app_config.get('notifications.alert', True))
        except Exception:
            tg_enabled = True  # default to current behavior if config module absent
            include_tech = True
            allow_info = False
            allow_warn = True
            allow_alert = True

        if not tg_enabled:
            return True
        # Level gating
        level = (signal_level or '').upper()
        if level == 'ALERT' and not allow_alert:
            return True
        if level == 'WARN' and not allow_warn:
            return True
        if level == 'INFO' and not allow_info and not str(signal_code or '').startswith('TECH_'):
            return True

        # Coalesce TECH_* alerts into a single batch message within a short window
        if str(signal_code or '').startswith('TECH_') and include_tech:
            try:
                idx = None
                is_first = False
                with self._tech_buffer_lock:
                    is_first = len(self._tech_buffer) == 0
                    # Append buffer item as not-yet-sent
                    self._tech_buffer.append(
                        [time.time(), str(signal_code), str(signal_message), level or 'INFO', False]
                    )
                    idx = len(self._tech_buffer) - 1
                    if self._tech_flush_timer is None or not self._tech_flush_timer.is_alive():
                        delay = max(1.0, float(getattr(self, '_tech_coalesce_window_sec', 15.0)))
                        self._tech_flush_timer = threading.Timer(
                            delay, self._flush_tech_buffer_safe
                        )
                        self._tech_flush_timer.daemon = True
                        self._tech_flush_timer.start()
                # If first in window, send immediately; others are coalesced
                if is_first:
                    ok = self.telegram.send_alert(
                        title=f"Portfolio Alert - {signal_code}",
                        message=signal_message,
                        level=level or 'INFO',
                    )
                    if ok:
                        self._notify_last_ts[code_key] = time.time()
                        try:
                            with self._tech_buffer_lock:
                                if idx is not None and 0 <= idx < len(self._tech_buffer):
                                    self._tech_buffer[idx][4] = True  # mark as sent
                        except Exception:
                            pass
                    return ok
                # Non-first: coalesced, don't send immediately
                return True
            except Exception:
                # Fallback to immediate send if buffering fails
                pass

        # Route WARN/ALERT by default
        if level in ["WARN", "ALERT"]:
            ok = self.telegram.send_alert(
                title=f"Portfolio Alert - {signal_code}", message=signal_message, level=level
            )
            if ok:
                self._notify_last_ts[code_key] = time.time()
            return ok
        # Allow INFO-level technical alerts explicitly (gated earlier by agent).
        # Backward compatible: do not require allow_info for TECH_*.
        if str(signal_code or '').startswith('TECH_') and include_tech:
            ok = self.telegram.send_alert(
                title=f"Portfolio Alert - {signal_code}",
                message=signal_message,
                level=level or 'INFO',
            )
            if ok:
                self._notify_last_ts[code_key] = time.time()
            return ok
        return True

    def _flush_tech_buffer_safe(self) -> None:
        """Thread-safe flush wrapper for TECH_* buffer triggered by timer."""
        try:
            items: list[list] = []
            with self._tech_buffer_lock:
                if not self._tech_buffer:
                    return
                items = list(self._tech_buffer)
                self._tech_buffer.clear()
                # mark timer as consumed
                self._tech_flush_timer = None
            # Build combined message
            try:
                # Only send a batch if there are unsent items
                unsent = [it for it in items if not (len(it) > 4 and bool(it[4]))]
                if not unsent:
                    return
                n = len(unsent)
                title = f"Portfolio Alerts - Technical Signals ({n})"
                # Sort by time
                unsent.sort(key=lambda x: x[0])
                lines: list[str] = []
                for _ts, code, msg, lvl, *_ in unsent:
                    short_msg = (msg or '').strip()
                    if len(short_msg) > 220:
                        short_msg = short_msg[:217] + '...'
                    lines.append(f"• {code}: {short_msg}")
                message = "\n".join(lines)
                # Send as INFO batch
                _ = self.telegram.send_alert(title=title, message=message, level='INFO')
                # Update rate limiter on a synthetic key to reduce bursts
                self._notify_last_ts['TECH_BATCH'] = time.time()
            except Exception:
                pass
        except Exception:
            pass

    def get_enhanced_quote(self, symbol: str) -> dict:
        """Get enhanced quote with news and technical data."""
        result = {
            'symbol': symbol,
            'quote': None,
            'news': [],
            'technical': None,
            'timestamp': datetime.now().isoformat(),
        }

        # Basic quote (with fallback)
        result['quote'] = self.get_quote(symbol)

        # Company news
        result['news'] = self.news.get_company_news(symbol, 3)

        # Technical indicators (RSI)
        # Indicators only available via AlphaVantage for now
        result['technical'] = self.alpha_vantage.get_technical_indicators(symbol, 'RSI')

        return result

    # ----------------- Market Movers (Canada) -----------------
    def get_market_movers_ca(self, top_n: int = 10) -> dict[str, list[dict]]:
        """Return top gainers, losers, and most actives for Canadian market.

        Uses Yahoo predefined screeners with region=CA. Returns dict with keys:
        'gainers', 'losers', 'actives', and 'opportunities' (subset of losers by threshold).
        Each item normalized to keys: symbol, name, price, change, changePct, volume, exchange.
        """
        top_n = int(max(1, min(50, top_n)))
        gainers = self.yahoo.get_predefined_screener('day_gainers', count=top_n, region='CA')
        losers = self.yahoo.get_predefined_screener('day_losers', count=top_n, region='CA')
        actives = self.yahoo.get_predefined_screener('most_actives', count=top_n, region='CA')
        # Opportunities heuristic: strong losers (<= -5%) or large absolute change and decent volume
        opps = [
            q
            for q in losers
            if (
                q.get('changePct', 0) <= -5.0
                or q.get('change', 0) <= -0.5
                or (q.get('changePct', 0) < 0 and q.get('volume', 0) > 200000)
            )
        ]
        # Sort losers/opps ascending by changePct, gainers descending
        gainers.sort(key=lambda x: x.get('changePct', 0), reverse=True)
        losers.sort(key=lambda x: x.get('changePct', 0))
        opps.sort(key=lambda x: x.get('changePct', 0))
        actives.sort(key=lambda x: x.get('volume', 0), reverse=True)
        return {
            'gainers': gainers[:top_n],
            'losers': losers[:top_n],
            'actives': actives[:top_n],
            'opportunities': opps[: top_n // 2 or 1],
        }

    # ----------------- Cache housekeeping (optional) -----------------
    def _run_cache_housekeeping_once(self) -> None:
        try:
            cache = getattr(self, '_cache', None)
            if not cache:
                return
            max_age = float(os.getenv('CACHE_MAX_AGE_SEC', str(7 * 24 * 3600)))
            max_screener = int(os.getenv('CACHE_MAX_SCREENER_ROWS', '100'))
            do_vacuum = os.getenv('CACHE_VACUUM_ON_PURGE', '1').strip().lower() in (
                '1',
                'true',
                'yes',
                'on',
            )
            deleted_old = cache.purge_older_than(max_age)
            deleted_scr = cache.purge_namespace_overflow('screener', max_screener)
            if do_vacuum:
                cache.vacuum()
            if os.getenv('CACHE_LOG_HOUSEKEEPING', '0').strip().lower() in (
                '1',
                'true',
                'yes',
                'on',
            ):
                print(
                    f"[cache] housekeeping: deleted_old={deleted_old} deleted_screener={deleted_scr} vacuum={do_vacuum}"
                )
        except Exception:
            # best-effort only
            pass

    def _start_cache_housekeeping_thread(self) -> None:
        try:
            interval = float(os.getenv('CACHE_HOUSEKEEPING_INTERVAL_SEC', str(24 * 3600)))
        except Exception:
            interval = 24 * 3600.0

        def _loop():
            # run once at start
            try:
                self._run_cache_housekeeping_once()
            except Exception:
                pass
            while True:
                try:
                    time.sleep(max(60.0, interval))
                    self._run_cache_housekeeping_once()
                except Exception:
                    # continue loop even on error
                    time.sleep(300.0)

        t = threading.Thread(target=_loop, daemon=True)
        t.start()

    # Public wrapper for on-demand housekeeping from UI
    def run_cache_housekeeping_once(self) -> None:
        """Run one housekeeping cycle immediately (safe no-op if cache absent)."""
        try:
            self._run_cache_housekeeping_once()
        except Exception:
            pass


__all__ = [
    'NewsAPIClient',
    'AlphaVantageClient',
    'YahooFinanceClient',
    'TelegramNotifier',
    'APIManager',
]
