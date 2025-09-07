from __future__ import annotations

from collections.abc import Sequence

from .indicators import bollinger, macd, rsi, sma


class Signal:
    __slots__ = ("index", "kind", "reason", "confidence")

    def __init__(self, index: int, kind: str, reason: str, confidence: float | None = None):
        self.index = index
        self.kind = kind  # 'buy' | 'sell'
        self.reason = reason
        self.confidence = confidence  # 0..1

    def to_dict(self) -> dict:
        d = {"i": self.index, "kind": self.kind, "reason": self.reason}
        if self.confidence is not None:
            d["conf"] = round(float(self.confidence), 4)
        return d


class MovingAverageCrossStrategy:
    """Simple MA crossover: buy when fast crosses above slow, sell when crosses below."""

    def __init__(
        self, fast: int = 10, slow: int = 30, min_bandwidth: float = 0.0, bb_window: int = 20
    ):
        if fast >= slow:
            raise ValueError("fast must be < slow")
        self.fast = fast
        self.slow = slow
        self.min_bandwidth = float(min_bandwidth)
        self.bb_window = int(bb_window)

    def generate(self, closes: Sequence[float]) -> list[Signal]:
        fast_ma = sma(closes, self.fast)
        slow_ma = sma(closes, self.slow)
        up, mid, lo = bollinger(closes, window=self.bb_window)
        sigs: list[Signal] = []
        prev_diff: float | None = None
        for i in range(len(closes)):
            f = fast_ma[i]
            s = slow_ma[i]
            if f is None or s is None:
                continue
            diff = f - s
            # Volatility filter via Bollinger bandwidth
            if self.min_bandwidth > 0.0:
                m = mid[i]
                u = up[i]
                low = lo[i]
                if m is None or u is None or low is None or m == 0:
                    prev_diff = diff
                    continue
                bandwidth = (u - low) / m if m else 0.0
                if bandwidth < self.min_bandwidth:
                    prev_diff = diff
                    continue
            if prev_diff is not None:
                if prev_diff <= 0 and diff > 0:
                    conf = min(1.0, abs(diff) / s) if s else 0.0
                    reason = f"MA{self.fast} cross above MA{self.slow} [conf {conf*100:.0f}%]"
                    sigs.append(Signal(i, 'buy', reason, conf))
                elif prev_diff >= 0 and diff < 0:
                    conf = min(1.0, abs(diff) / s) if s else 0.0
                    reason = f"MA{self.fast} cross below MA{self.slow} [conf {conf*100:.0f}%]"
                    sigs.append(Signal(i, 'sell', reason, conf))
            prev_diff = diff
        return sigs


class RSIReversionStrategy:
    """Buy when RSI < low, sell when RSI > high."""

    def __init__(
        self,
        period: int = 14,
        low: int = 30,
        high: int = 70,
        min_bandwidth: float = 0.0,
        bb_window: int = 20,
    ):
        self.period = period
        self.low = low
        self.high = high
        self.min_bandwidth = float(min_bandwidth)
        self.bb_window = int(bb_window)

    def generate(self, closes: Sequence[float]) -> list[Signal]:
        r = rsi(closes, self.period)
        up, mid, lo = bollinger(closes, window=self.bb_window)
        sigs: list[Signal] = []
        for i, v in enumerate(r):
            if v is None:
                continue
            if self.min_bandwidth > 0.0:
                m = mid[i]
                u = up[i]
                low = lo[i]
                if m is None or u is None or low is None or m == 0:
                    continue
                bandwidth = (u - low) / m if m else 0.0
                if bandwidth < self.min_bandwidth:
                    continue
            if v < self.low:
                conf = min(1.0, (self.low - v) / 20.0)
                sigs.append(
                    Signal(i, 'buy', f"RSI {v:.1f} < {self.low} [conf {conf*100:.0f}%]", conf)
                )
            elif v > self.high:
                conf = min(1.0, (v - self.high) / 20.0)
                sigs.append(
                    Signal(i, 'sell', f"RSI {v:.1f} > {self.high} [conf {conf*100:.0f}%]", conf)
                )
        return sigs


class ConfluenceStrategy:
    """Composite strategy: MA cross confirmed by RSI and MACD histogram.

    - Buy when MA(fast) crosses above MA(slow) AND RSI >= rsi_buy AND MACD hist > 0
    - Sell when MA(fast) crosses below MA(slow) AND RSI <= rsi_sell AND MACD hist < 0
    """

    def __init__(
        self,
        fast: int = 10,
        slow: int = 30,
        rsi_period: int = 14,
        rsi_buy: int = 55,
        rsi_sell: int = 45,
        min_bandwidth: float = 0.0,
        bb_window: int = 20,
    ):
        if fast >= slow:
            raise ValueError("fast must be < slow")
        if not (0 < rsi_sell < rsi_buy < 100):
            raise ValueError("rsi thresholds invalid")
        self.fast = fast
        self.slow = slow
        self.rsi_period = rsi_period
        self.rsi_buy = rsi_buy
        self.rsi_sell = rsi_sell
        self.min_bandwidth = float(min_bandwidth)
        self.bb_window = int(bb_window)

    def generate(self, closes: Sequence[float]) -> list[Signal]:
        fast_ma = sma(closes, self.fast)
        slow_ma = sma(closes, self.slow)
        r = rsi(closes, self.rsi_period)
        _macd, _sig, hist = macd(closes)
        up, mid, lo = bollinger(closes, window=self.bb_window)
        sigs: list[Signal] = []
        prev_diff: float | None = None
        for i in range(len(closes)):
            f = fast_ma[i]
            s = slow_ma[i]
            if f is None or s is None:
                continue
            diff = f - s
            h = hist[i] if i < len(hist) else None
            rv = r[i] if i < len(r) else None
            # Volatility filter
            if self.min_bandwidth > 0.0:
                m = mid[i]
                u = up[i]
                low = lo[i]
                if m is None or u is None or low is None or m == 0:
                    prev_diff = diff
                    continue
                bandwidth = (u - low) / m if m else 0.0
                if bandwidth < self.min_bandwidth:
                    prev_diff = diff
                    continue
            if prev_diff is not None and h is not None and rv is not None:
                # Cross up with confirmations
                if prev_diff <= 0 and diff > 0 and rv >= self.rsi_buy and h > 0:
                    confirms = 3
                    base = confirms / 3.0
                    dist_ma = min(1.0, abs(diff) / s) if s else 0.0
                    dist_rsi = min(1.0, (rv - self.rsi_buy) / 20.0)
                    conf = min(1.0, base * 0.6 + 0.2 * dist_ma + 0.2 * dist_rsi)
                    sigs.append(
                        Signal(
                            i,
                            'buy',
                            f"Confluence: MA{self.fast}/{self.slow} up + RSI {rv:.1f} + MACD>0 [conf {conf*100:.0f}%]",
                            conf,
                        )
                    )
                # Cross down with confirmations
                elif prev_diff >= 0 and diff < 0 and rv <= self.rsi_sell and h < 0:
                    confirms = 3
                    base = confirms / 3.0
                    dist_ma = min(1.0, abs(diff) / s) if s else 0.0
                    dist_rsi = min(1.0, (self.rsi_sell - rv) / 20.0)
                    conf = min(1.0, base * 0.6 + 0.2 * dist_ma + 0.2 * dist_rsi)
                    sigs.append(
                        Signal(
                            i,
                            'sell',
                            f"Confluence: MA{self.fast}/{self.slow} down + RSI {rv:.1f} + MACD<0 [conf {conf*100:.0f}%]",
                            conf,
                        )
                    )
            prev_diff = diff
        return sigs


__all__ = [
    'Signal',
    'MovingAverageCrossStrategy',
    'RSIReversionStrategy',
    'ConfluenceStrategy',
]
