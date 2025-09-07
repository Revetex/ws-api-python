"""Media (logos & news images) fetching with caching for the GUI.

Uses optional Pillow; if not installed images won't display but app remains functional.
"""

from __future__ import annotations

import io
import os
import threading
from dataclasses import dataclass
from typing import Callable

import utils.http_client as http_client

try:
    from PIL import Image, ImageTk  # type: ignore

    HAS_PIL = True
except Exception:  # pragma: no cover
    HAS_PIL = False
    Image = None  # type: ignore
    ImageTk = None  # type: ignore


def _finnhub_logo(symbol: str) -> str | None:
    key = os.getenv('FINNHUB_API_KEY')
    if not key:
        return None
    return f"https://finnhub.io/api/logo?symbol={symbol.upper()}&token={key}"


# Map common exchange suffixes to EODHD market codes
_MARKET_MAP: dict[str, str] = {
    'TO': 'CA',  # Toronto (TSX/TSXV)
    'V': 'CA',  # TSXV sometimes ".V"
    'CN': 'CA',  # CSE
    'L': 'UK',  # London
    'DE': 'DE',  # XETRA/Frankfurt
    'PA': 'FR',  # Paris
    'AS': 'NL',  # Amsterdam (Euronext)
    'BR': 'BE',  # Brussels (Euronext)
    'MI': 'IT',  # Milan
    'SW': 'CH',  # SIX Swiss
    'MC': 'ES',  # Madrid
    'HK': 'HK',  # Hong Kong
}


def _normalize_for_eodhd(symbol: str) -> tuple[str, str]:
    """Return (base_symbol, market) for EODHD logo URL.

    Defaults to US market when suffix unknown/absent.
    Examples: SHOP.TO -> (SHOP, CA), AAPL -> (AAPL, US).
    """
    sym = (symbol or '').upper().strip()
    base, market = sym, 'US'
    if '.' in sym:
        base, suffix = sym.split('.', 1)
        market = _MARKET_MAP.get(suffix, 'US')
    return base, market


def _logo_candidates(symbol: str) -> list[str]:
    base, market = _normalize_for_eodhd(symbol)
    urls: list[str] = []
    # Prefer EODHD, which hosts many tickers by market code
    urls.append(f"https://eodhd.com/img/logos/{market}/{base}.png")
    # IEX legacy path (works only for some US tickers)
    if market == 'US':
        urls.append(f"https://storage.googleapis.com/iex/api/logos/{base}.png")
    # Finnhub (if key provided)
    fh = _finnhub_logo(symbol)
    if fh:
        urls.append(fh)
    return urls


PLACEHOLDER_PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00@\x00\x00\x00@\x08\x06\x00\x00\x00szz\xf4\x00\x00\x00\x19tEXtSoftware\x00Python PIL\x94\xc7\xce|\x00\x00\x00\xc0IDATx\x9c\xed\xd7A\x0e\x80 \x0c\x04A\xd1\xff\x9f\xb9F\xfa\x94\x8d\n\xb4\n\x14\x07\x88\x13B~~\x17\xe7\\\x81I\xb2,\xcb\xb2,\xcb\xb2,\xcb\xb2,\xcb\xf2?\x1d\xc7q\x1cG\xffG\x9d\xe3\x00\x80\x94R\xfe\x8f;\xc6\x18c\x8c1\xc6\x18c\x8c\xf1\xff\xa3N\x0b!\x84\x10B\x08!\x84\x10B\x08!\x84\x10B\x08!\x84\x10B\x08!\x84xR\xea?\x8eo\x84W\x8a\xe3\x00\x00\x00\x00IEND\xaeB`\x82"


@dataclass
class MediaCacheEntry:
    image_tk: object | None
    raw_bytes: bytes
    width: int
    height: int


class MediaManager:
    def __init__(
        self, max_logo_px: int = 64, detail_logo_px: int | None = None, ttl_sec: float | None = None
    ):
        self.max_logo_px = max_logo_px
        self.detail_logo_px = detail_logo_px or max(64, max_logo_px)
        self._logo_cache: dict[str, MediaCacheEntry] = {}
        self._img_cache: dict[str, MediaCacheEntry] = {}
        # tiny in-memory age tracking
        self._logo_cache_ts: dict[str, float] = {}
        self._img_cache_ts: dict[str, float] = {}
        try:
            import time as _t

            self._now = _t.time  # inject for tests
        except Exception:  # pragma: no cover
            self._now = lambda: 0.0  # type: ignore
        # TTL
        try:
            # env override first, else constructor, else sane default
            import os as _os

            env_ttl = _os.getenv('MEDIA_CACHE_TTL_SEC')
            self._ttl = (
                float(env_ttl) if env_ttl else (float(ttl_sec) if ttl_sec is not None else 3600.0)
            )
        except Exception:
            self._ttl = 3600.0
        # shared HTTP client with retries/backoff
        try:
            self._http = http_client.HTTPClient(
                headers={'Accept': '*/*'}, timeout=8.0, retries=2, backoff=0.25
            )
        except Exception:  # pragma: no cover
            self._http = None  # type: ignore

    # Runtime setters so Settings UI can apply without restart
    def set_ttl(self, ttl_sec: float) -> None:
        try:
            self._ttl = max(0.0, float(ttl_sec))
        except Exception:
            pass

    def set_detail_logo_px(self, px: int) -> None:
        try:
            self.detail_logo_px = max(16, int(px))
        except Exception:
            pass

    def get_logo_async(
        self, symbol: str, cb: Callable[[object | None], None], *, large: bool = False
    ):
        symbol = (symbol or '').upper().strip()
        if not symbol:
            cb(None)
            return
        # cache hit with TTL
        ent = self._logo_cache.get(symbol)
        ts = self._logo_cache_ts.get(symbol, 0.0)
        if ent and (self._now() - ts) < self._ttl:
            cb(ent.image_tk)
            return

        def worker():
            try:
                img = self._fetch_logo(symbol, large=large)
                cb(img)
            except Exception:
                cb(None)

        # Under pytest, run synchronously to avoid flaky thread scheduling in CI
        if os.environ.get('PYTEST_CURRENT_TEST'):
            worker()
        else:
            threading.Thread(target=worker, daemon=True).start()

    def _fetch_logo(self, symbol: str, large: bool = False):
        candidates = _logo_candidates(symbol)
        for url in candidates:
            try:
                r = self._http.get(url) if self._http else None
                headers = getattr(r, 'headers', {}) or {}
                ctype = str(headers.get('content-type', '')).lower()
                status = getattr(r, 'status_code', None)
                if status == 200:
                    ok = False
                    if ctype.startswith('image'):
                        ok = True
                    else:
                        data = getattr(r, 'content', b'') or b''
                        if (
                            data.startswith(b'\x89PNG')
                            or data.startswith(b'\xff\xd8')
                            or data[:4] in (b'GIF8',)
                        ):
                            ok = True
                    if ok:
                        return self._store_logo(symbol, getattr(r, 'content', b''), large=large)
            except Exception:
                continue
        return self._store_logo(symbol, PLACEHOLDER_PNG, large=large)

    def _store_logo(self, symbol: str, content: bytes, large: bool = False):
        if HAS_PIL:
            try:
                im = Image.open(io.BytesIO(content)).convert('RGBA')
                target = self.detail_logo_px if large else self.max_logo_px
                im.thumbnail((target, target))
                tk_img = ImageTk.PhotoImage(im)
                self._logo_cache[symbol] = MediaCacheEntry(tk_img, content, im.width, im.height)
                self._logo_cache_ts[symbol] = self._now()
                return tk_img
            except Exception:
                pass
        self._logo_cache[symbol] = MediaCacheEntry(None, content, 0, 0)
        self._logo_cache_ts[symbol] = self._now()
        return None

    def get_image_async(self, url: str, max_width: int, cb: Callable[[object | None], None]):
        if not url:
            cb(None)
            return
        ent = self._img_cache.get(url)
        ts = self._img_cache_ts.get(url, 0.0)
        if ent and (self._now() - ts) < self._ttl:
            cb(ent.image_tk)
            return

        def worker():
            try:
                r = self._http.get(url) if self._http else None
                ctype = str(getattr(r, 'headers', {}).get('content-type', '')).lower()
                if getattr(r, 'status_code', None) == 200 and ctype.startswith('image') and HAS_PIL:
                    data = getattr(r, 'content', b'')
                    im = Image.open(io.BytesIO(data))
                    if im.width > max_width:
                        ratio = max_width / im.width
                        im = im.resize((max_width, int(im.height * ratio)))
                    tk_img = ImageTk.PhotoImage(im)
                    self._img_cache[url] = MediaCacheEntry(tk_img, data, im.width, im.height)
                    self._img_cache_ts[url] = self._now()
                    cb(tk_img)
                    return
            except Exception:
                pass
            cb(None)

        threading.Thread(target=worker, daemon=True).start()


__all__ = ['MediaManager']
