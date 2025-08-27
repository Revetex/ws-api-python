"""Simple circuit breaker utility (sync + async-compatible).

Usage:
    cb = CircuitBreaker(name='yahoo', failure_threshold=5, recovery_time=30)
    with cb:
        resp = client.get(...)

    # async
    async with cb:
        resp = await client.get(...)

    # decorator
    @cb.decorate
    def fetch():
        ...

Notes:
- Thread-safe.
- States: CLOSED -> OPEN -> HALF_OPEN -> CLOSED.
- On OPEN: short-circuit by raising CircuitOpenError.
"""
from __future__ import annotations
import time
import threading
from typing import Any, Callable, Coroutine, TypeVar

T = TypeVar('T')


class CircuitOpenError(RuntimeError):
    pass


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_time: float = 30.0,
        half_open_max_calls: int = 2,
    ) -> None:
        self.name = name
        self.failure_threshold = max(1, int(failure_threshold))
        self.recovery_time = float(recovery_time)
        self.half_open_max_calls = max(1, int(half_open_max_calls))
        self._lock = threading.Lock()
        # state
        self._state = 'CLOSED'  # CLOSED | OPEN | HALF_OPEN
        self._failures = 0
        self._opened_at = 0.0
        self._half_open_inflight = 0
        # metrics
        self._opened_count = 0
        self._closed_count = 0
        self._half_open_count = 0
        # logging toggle (opt-in via env)
        try:
            import os
            self._log = (os.getenv('CB_LOG', '0').strip().lower() in ('1', 'true', 'yes', 'on'))
        except Exception:
            self._log = False

    # -------- state helpers --------
    def _can_pass(self) -> bool:
        now = time.time()
        if self._state == 'OPEN':
            if (now - self._opened_at) >= self.recovery_time:
                self._state = 'HALF_OPEN'
                self._half_open_inflight = 0
                self._half_open_count += 1
                if self._log:
                    print(f"[cb] {self.name} -> HALF_OPEN")
                return True
            return False
        if self._state == 'HALF_OPEN':
            return self._half_open_inflight < self.half_open_max_calls
        return True

    def _on_success(self) -> None:
        if self._state in ('OPEN', 'HALF_OPEN'):
            self._state = 'CLOSED'
            self._failures = 0
            self._half_open_inflight = 0
            self._closed_count += 1
            if self._log:
                print(f"[cb] {self.name} -> CLOSED")
        else:
            self._failures = 0

    def _on_failure(self) -> None:
        if self._state == 'HALF_OPEN':
            self._state = 'OPEN'
            self._opened_at = time.time()
            self._half_open_inflight = 0
            self._opened_count += 1
            if self._log:
                print(f"[cb] {self.name} -> OPEN (half-open fail)")
            return
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._state = 'OPEN'
            self._opened_at = time.time()
            self._opened_count += 1
            if self._log:
                print(f"[cb] {self.name} -> OPEN (threshold)")

    # -------- context managers --------
    def __enter__(self) -> 'CircuitBreaker':
        with self._lock:
            if not self._can_pass():
                raise CircuitOpenError(f"Circuit '{self.name}' is OPEN")
            if self._state == 'HALF_OPEN':
                self._half_open_inflight += 1
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        with self._lock:
            if exc is None:
                self._on_success()
            else:
                self._on_failure()

    async def __aenter__(self) -> 'CircuitBreaker':
        return self.__enter__()

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        return self.__exit__(exc_type, exc, tb)

    # -------- decorators --------
    def decorate(self, fn: Callable[..., T]) -> Callable[..., T]:
        def wrapper(*args: Any, **kwargs: Any) -> T:
            with self:
                return fn(*args, **kwargs)
        return wrapper

    def decorate_async(self, fn: Callable[..., Coroutine[Any, Any, T]]) -> Callable[..., Coroutine[Any, Any, T]]:
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            async with self:
                return await fn(*args, **kwargs)
        return wrapper

    # -------- inspection --------
    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def stats(self) -> dict:
        with self._lock:
            return {
                'name': self.name,
                'state': self._state,
                'failures': self._failures,
                'opened_at': self._opened_at,
                'half_open_inflight': self._half_open_inflight,
                'opened_count': self._opened_count,
                'closed_count': self._closed_count,
                'half_open_count': self._half_open_count,
            }
