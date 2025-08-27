from __future__ import annotations
import threading
from typing import Callable, Dict, List, Optional, Sequence, Tuple

try:
    from analytics.strategies import MovingAverageCrossStrategy, RSIReversionStrategy, ConfluenceStrategy
    HAS_ANALYTICS = True
except Exception:  # pragma: no cover
    HAS_ANALYTICS = False


class StrategyRunner:
    """Background strategy evaluator that emits alerts for fresh signals.

    Configurable via set_config(); safe no-ops if analytics/APIs are unavailable.
    """

    def __init__(self, api_manager, get_universe: Callable[[], Sequence[str]], send_alert: Callable[[str, str, str], bool], trade_executor=None):
        self.api = api_manager
        self.get_universe = get_universe
        self.send_alert = send_alert
        self.trade_executor = trade_executor
        self.enabled = False
        self.interval_sec = 300
        self.strategy = 'ma_cross'  # 'ma_cross' | 'rsi_reversion' | 'confluence'
        self.params: Dict[str, float] = {
            "fast": 10,
            "slow": 30,
            "rsi_low": 30,
            "rsi_high": 70,
            "rsi_period": 14,
            "rsi_buy": 55,
            "rsi_sell": 45,
        }
        self._thr: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._last_signals: Dict[Tuple[str, str], int] = {}  # (symbol, kind) -> last index processed
        self._last_report: str = ''

    def set_config(self, enabled: bool = None, interval_sec: int = None, strategy: str = None, params: Dict[str, float] = None):
        if enabled is not None:
            self.enabled = bool(enabled)
        if interval_sec is not None:
            self.interval_sec = max(15, int(interval_sec))
        if strategy is not None:
            self.strategy = strategy
        if params is not None:
            self.params.update(params)

    def start(self):
        if self._thr and self._thr.is_alive():
            return
        self._stop.clear()
        self._thr = threading.Thread(target=self._loop, daemon=True)
        self._thr.start()

    def stop(self):
        self._stop.set()

    def run_once(self) -> str:
        if not HAS_ANALYTICS or not self.api:
            self._last_report = 'Analytics or API unavailable; skipped.'
            return self._last_report
        universe = list(self.get_universe() or [])[:50]
        if not universe:
            self._last_report = 'No symbols to evaluate.'
            return self._last_report
        buys = 0
        sells = 0
        checked = 0
        for sym in universe:
            try:
                series = self.api.get_time_series(sym, interval='1day', outputsize='compact') or {}
                closes = self._extract_closes(series)
                if len(closes) < 30:
                    continue
                sigs = self._generate_signals(closes)
                if not sigs:
                    continue
                last_index = len(closes) - 1
                fresh = [s for s in sigs if s.index == last_index]
                for s in fresh:
                    key = (sym, s.kind)
                    if self._last_signals.get(key) == last_index:
                        continue  # already alerted
                    title = f"Strategy Alert - TECH_{s.kind.upper()} {sym}"
                    msg = f"{sym}: {s.reason} (close idx {s.index})"
                    self.send_alert(title, msg, level='ALERT')
                    # optional auto-trade
                    try:
                        if self.trade_executor is not None:
                            self.trade_executor.on_signal(sym, s)
                    except Exception:
                        pass
                    self._last_signals[key] = last_index
                    if s.kind == 'buy':
                        buys += 1
                    else:
                        sells += 1
                checked += 1
            except Exception:
                continue
        extra = ''
        try:
            if self.trade_executor is not None:
                extra = f" | {self.trade_executor.summary()}"
        except Exception:
            extra = ''
        self._last_report = f"Runner: checked={checked} buy={buys} sell={sells}{extra}"
        return self._last_report

    def last_report(self) -> str:
        return self._last_report

    # ---------------- internal ----------------
    def _loop(self):
        while not self._stop.is_set():
            if self.enabled:
                try:
                    self.run_once()
                except Exception:
                    pass
            self._stop.wait(self.interval_sec)

    def _generate_signals(self, closes: Sequence[float]):
        if self.strategy == 'rsi_reversion':
            s = RSIReversionStrategy(
                int(self.params.get('period', 14)),
                int(self.params.get('rsi_low', 30)),
                int(self.params.get('rsi_high', 70)),
                float(self.params.get('min_bandwidth', 0.0) or 0.0),
                int(self.params.get('bb_window', 20) or 20),
            )
            return s.generate(closes)
        if self.strategy == 'confluence':
            fast = int(self.params.get('fast', 10))
            slow = int(self.params.get('slow', 30))
            rp = int(self.params.get('rsi_period', 14))
            rb = int(self.params.get('rsi_buy', 55))
            rs = int(self.params.get('rsi_sell', 45))
            s = ConfluenceStrategy(
                fast, slow, rp, rb, rs,
                float(self.params.get('min_bandwidth', 0.0) or 0.0),
                int(self.params.get('bb_window', 20) or 20),
            )
            return s.generate(closes)
        # default: ma_cross
        fast = int(self.params.get('fast', 10))
        slow = int(self.params.get('slow', 30))
        s = MovingAverageCrossStrategy(
            fast, slow,
            float(self.params.get('min_bandwidth', 0.0) or 0.0),
            int(self.params.get('bb_window', 20) or 20),
        )
        return s.generate(closes)

    @staticmethod
    def _extract_closes(series: Dict) -> List[float]:
        closes: List[float] = []
        try:
            k = next((k for k in series.keys() if 'Time Series' in k), None)
            ts = series.get(k) if k else None
            if isinstance(ts, dict):
                for _d, row in list(sorted(ts.items())):
                    try:
                        closes.append(float(row.get('4. close') or row.get('4. Close') or 0.0))
                    except Exception:
                        pass
        except Exception:
            pass
        return closes


__all__ = ["StrategyRunner"]

