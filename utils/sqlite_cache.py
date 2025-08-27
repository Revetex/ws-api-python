"""Lightweight persistent SQLite cache (namespaced key-value JSON).

Usage:
    from utils.sqlite_cache import PersistentCache
    cache = PersistentCache(db_path=None)  # default to WSAPP_CACHE_DB or ./cache.sqlite3
    cache.set('quote', 'AAPL', {'price': 123})
    val = cache.get_if_fresh('quote', 'AAPL', max_age_s=60.0)

Design:
- Single table `cache` with (namespace, key) composite PK and JSON value.
- `updated_at` stores UNIX epoch seconds. TTL handled by callers.
- Thread-safe via a lock; SQLite connection uses WAL and check_same_thread=False.
- Fail-soft: all methods catch exceptions and return None/False to avoid crashing callers.
"""
from __future__ import annotations
import os
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional, Tuple


class PersistentCache:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = self._resolve_db_path(db_path)
        # Ensure directory exists
        try:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        self._lock = threading.Lock()
        try:
            self._conn = sqlite3.connect(self.db_path, timeout=5.0, isolation_level=None, check_same_thread=False)
            with self._conn:
                self._conn.execute('PRAGMA journal_mode=WAL;')
                self._conn.execute('PRAGMA synchronous=NORMAL;')
                self._conn.execute(
                    'CREATE TABLE IF NOT EXISTS cache ('
                    'namespace TEXT NOT NULL,'
                    'key TEXT NOT NULL,'
                    'value TEXT NOT NULL,'
                    'updated_at REAL NOT NULL,'
                    'PRIMARY KEY(namespace, key)'
                    ');'
                )
                self._conn.execute('CREATE INDEX IF NOT EXISTS idx_cache_ns ON cache(namespace);')
        except Exception:
            # If connection fails, set to None; methods will fail-soft
            self._conn = None

    def _resolve_db_path(self, db_path: Optional[str]) -> str:
        if db_path:
            return db_path
        env_path = os.getenv('WSAPP_CACHE_DB') or os.getenv('CACHE_DB_PATH')
        if env_path:
            return env_path
        # default to workspace root ./cache.sqlite3
        try:
            base = Path(__file__).resolve().parent.parent  # project root (utils/..)
            return str(base / 'cache.sqlite3')
        except Exception:
            return 'cache.sqlite3'

    def get_raw(self, namespace: str, key: str) -> Optional[Tuple[Any, float]]:
        """Return (value_obj, updated_at_epoch) or None."""
        if not self._conn:
            return None
        try:
            with self._lock:
                cur = self._conn.execute('SELECT value, updated_at FROM cache WHERE namespace=? AND key=?', (namespace, key))
                row = cur.fetchone()
            if not row:
                return None
            val_txt, updated_at = row
            try:
                val_obj = json.loads(val_txt)
            except Exception:
                val_obj = val_txt
            return val_obj, float(updated_at)
        except Exception:
            return None

    def get_if_fresh(self, namespace: str, key: str, max_age_s: float) -> Optional[Any]:
        """Return value if record exists and is newer than max_age_s; else None."""
        rec = self.get_raw(namespace, key)
        if not rec:
            return None
        val, updated_at = rec
        try:
            age = time.time() - updated_at
            if age <= max_age_s:
                return val
            return None
        except Exception:
            return None

    def get_any(self, namespace: str, key: str) -> Optional[Any]:
        """Return value regardless of age; None if missing or on error."""
        rec = self.get_raw(namespace, key)
        return rec[0] if rec else None

    def set(self, namespace: str, key: str, value: Any) -> bool:
        if not self._conn:
            return False
        try:
            payload = json.dumps(value, separators=(',', ':'), ensure_ascii=False)
        except Exception:
            try:
                payload = str(value)
            except Exception:
                payload = ''
        try:
            with self._lock:
                self._conn.execute(
                    'INSERT INTO cache(namespace, key, value, updated_at) VALUES(?,?,?,?) '
                    'ON CONFLICT(namespace, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at;',
                    (namespace, key, payload, time.time()),
                )
            return True
        except Exception:
            return False

    def delete(self, namespace: str, key: str) -> bool:
        if not self._conn:
            return False
        try:
            with self._lock:
                self._conn.execute('DELETE FROM cache WHERE namespace=? AND key=?', (namespace, key))
            return True
        except Exception:
            return False

    def clear_namespace(self, namespace: str) -> bool:
        if not self._conn:
            return False
        try:
            with self._lock:
                self._conn.execute('DELETE FROM cache WHERE namespace=?', (namespace,))
            return True
        except Exception:
            return False

    # ---- Maintenance ----
    def purge_older_than(self, max_age_s: float) -> int:
        """Delete rows older than now - max_age_s; returns number of rows deleted."""
        if not self._conn:
            return 0
        try:
            cutoff = time.time() - float(max_age_s)
            with self._lock:
                cur = self._conn.execute('DELETE FROM cache WHERE updated_at < ?', (cutoff,))
                return cur.rowcount if hasattr(cur, 'rowcount') else 0
        except Exception:
            return 0

    def purge_namespace_overflow(self, namespace: str, max_rows: int) -> int:
        """Ensure namespace has at most max_rows by deleting oldest extras; returns deleted count."""
        if not self._conn:
            return 0
        try:
            max_rows = max(1, int(max_rows))
            with self._lock:
                cur = self._conn.execute('SELECT COUNT(*) FROM cache WHERE namespace=?', (namespace,))
                n = int(cur.fetchone()[0] or 0)
                excess = max(0, n - max_rows)
                if excess <= 0:
                    return 0
                # Delete oldest 'excess' rows
                self._conn.execute(
                    'DELETE FROM cache WHERE rowid IN ('
                    'SELECT rowid FROM cache WHERE namespace=? ORDER BY updated_at ASC LIMIT ?'
                    ')',
                    (namespace, excess),
                )
                return excess
        except Exception:
            return 0

    def vacuum(self) -> bool:
        if not self._conn:
            return False
        try:
            with self._lock:
                self._conn.execute('VACUUM;')
            return True
        except Exception:
            return False

    def stats(self) -> dict:
        """Return basic statistics about the cache: total rows, per-namespace counts, and last update per namespace."""
        if not self._conn:
            return {}
        try:
            with self._lock:
                cur = self._conn.execute('SELECT COUNT(*) FROM cache')
                total = int(cur.fetchone()[0] or 0)
                cur2 = self._conn.execute('SELECT namespace, COUNT(*) AS n, MAX(updated_at) AS last FROM cache GROUP BY namespace')
                per_ns = {}
                for ns, n, last in cur2.fetchall() or []:
                    per_ns[str(ns)] = {
                        'count': int(n or 0),
                        'last_updated_at': float(last or 0.0),
                    }
            return {'total': total, 'namespaces': per_ns}
        except Exception:
            return {}

    def close(self) -> None:
        try:
            if self._conn:
                self._conn.close()
        except Exception:
            pass
