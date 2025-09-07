"""Performance monitoring and optimization utilities."""

from __future__ import annotations

import cProfile
import functools
import pstats
import time
from collections import defaultdict
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any, Callable

from utils.logging_setup import get_logger

logger = get_logger('performance')


class PerformanceMonitor:
    """Monitor application performance and identify bottlenecks."""

    def __init__(self):
        self._timings: dict[str, list[float]] = defaultdict(list)
        self._counters: dict[str, int] = defaultdict(int)
        self._active_timers: dict[str, float] = {}

    @contextmanager
    def timer(self, name: str) -> Generator[None, None, None]:
        """Context manager for timing code blocks."""
        start_time = time.perf_counter()
        try:
            yield
        finally:
            end_time = time.perf_counter()
            duration = end_time - start_time
            self._timings[name].append(duration)
            logger.debug(f"Timer '{name}': {duration:.4f}s")

    def start_timer(self, name: str) -> None:
        """Start a manual timer."""
        self._active_timers[name] = time.perf_counter()

    def stop_timer(self, name: str) -> float:
        """Stop a manual timer and return duration."""
        if name not in self._active_timers:
            logger.warning(f"Timer '{name}' was not started")
            return 0.0

        start_time = self._active_timers.pop(name)
        duration = time.perf_counter() - start_time
        self._timings[name].append(duration)
        logger.debug(f"Timer '{name}': {duration:.4f}s")
        return duration

    def increment_counter(self, name: str, amount: int = 1) -> None:
        """Increment a performance counter."""
        self._counters[name] += amount

    def get_stats(self) -> dict[str, Any]:
        """Get performance statistics."""
        stats = {}

        for name, times in self._timings.items():
            if times:
                stats[name] = {
                    'count': len(times),
                    'total': sum(times),
                    'avg': sum(times) / len(times),
                    'min': min(times),
                    'max': max(times),
                }

        for name, count in self._counters.items():
            stats[name] = {'count': count}

        return stats

    def reset(self) -> None:
        """Reset all performance data."""
        self._timings.clear()
        self._counters.clear()
        self._active_timers.clear()

    def log_stats(self) -> None:
        """Log current performance statistics."""
        stats = self.get_stats()
        if not stats:
            logger.info("No performance data collected")
            return

        logger.info("Performance Statistics:")
        for name, data in stats.items():
            if 'avg' in data:
                logger.info(
                    f"  {name}: count={data['count']}, "
                    f"avg={data['avg']:.4f}s, "
                    f"total={data['total']:.4f}s"
                )
            else:
                logger.info(f"  {name}: count={data['count']}")


def profile_function(func: Callable) -> Callable:
    """Decorator to profile a function's performance."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        profiler = cProfile.Profile()
        profiler.enable()

        try:
            result = func(*args, **kwargs)
            return result
        finally:
            profiler.disable()
            stats = pstats.Stats(profiler)
            stats.sort_stats('cumulative')

            # Log top 10 most time-consuming functions
            logger.info(f"Profile results for {func.__name__}:")
            stats.print_stats(10)

    return wrapper


def timed_cache(max_age: float = 300.0):
    """Decorator that caches function results with time-based expiration."""

    def decorator(func: Callable) -> Callable:
        cache: dict[tuple, tuple[Any, float]] = {}

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Create cache key from arguments
            key = (args, tuple(sorted(kwargs.items())))

            # Check if cached result exists and is still valid
            if key in cache:
                result, timestamp = cache[key]
                if time.time() - timestamp < max_age:
                    logger.debug(f"Cache hit for {func.__name__}")
                    return result

            # Compute new result
            result = func(*args, **kwargs)
            cache[key] = (result, time.time())

            # Clean up old cache entries periodically
            if len(cache) > 100:  # Simple cleanup threshold
                cache.clear()  # For simplicity, clear all; could be more selective

            return result

        return wrapper

    return decorator


class AsyncWorkerPool:
    """Simple worker pool for background tasks."""

    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers
        self._active_workers = 0

    def submit(self, func: Callable, *args, **kwargs) -> None:
        """Submit a task to be executed in background."""
        import threading

        def worker():
            try:
                func(*args, **kwargs)
            except Exception as e:
                logger.error(f"Background task failed: {e}")
            finally:
                self._active_workers -= 1

        if self._active_workers < self.max_workers:
            self._active_workers += 1
            thread = threading.Thread(target=worker, daemon=True)
            thread.start()
        else:
            logger.warning("Worker pool at capacity, task queued but not executed")


# Global performance monitor instance
_performance_monitor = PerformanceMonitor()


def get_performance_monitor() -> PerformanceMonitor:
    """Get the global performance monitor instance."""
    return _performance_monitor


def monitor_performance(name: str):
    """Decorator to monitor function performance."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with _performance_monitor.timer(name):
                return func(*args, **kwargs)

        return wrapper

    return decorator


# Convenience functions
def start_timer(name: str) -> None:
    """Start a global timer."""
    _performance_monitor.start_timer(name)


def stop_timer(name: str) -> float:
    """Stop a global timer and return duration."""
    return _performance_monitor.stop_timer(name)


def increment_counter(name: str, amount: int = 1) -> None:
    """Increment a global counter."""
    _performance_monitor.increment_counter(name, amount)


def log_performance_stats() -> None:
    """Log current performance statistics."""
    _performance_monitor.log_stats()
