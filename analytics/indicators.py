from __future__ import annotations
from typing import List, Sequence, Tuple, Optional


def sma(values: Sequence[float], window: int) -> List[Optional[float]]:
    if window <= 0:
        raise ValueError("window must be > 0")
    out: List[Optional[float]] = [None] * len(values)
    s = 0.0
    for i, v in enumerate(values):
        s += float(v)
        if i >= window:
            s -= float(values[i - window])
        if i >= window - 1:
            out[i] = s / window
    return out


def ema(values: Sequence[float], window: int) -> List[Optional[float]]:
    if window <= 0:
        raise ValueError("window must be > 0")
    out: List[Optional[float]] = [None] * len(values)
    k = 2 / (window + 1)
    ema_prev: Optional[float] = None
    for i, v in enumerate(values):
        x = float(v)
        if ema_prev is None:
            ema_prev = x
        else:
            ema_prev = (x - ema_prev) * k + ema_prev
        out[i] = ema_prev
    # First window-1 values are less meaningful; set to None for consistency
    for i in range(min(window - 1, len(out))):
        out[i] = None
    return out


def rsi(values: Sequence[float], period: int = 14) -> List[Optional[float]]:
    if period <= 0:
        raise ValueError("period must be > 0")
    out: List[Optional[float]] = [None] * len(values)
    gains: List[float] = [0.0] * len(values)
    losses: List[float] = [0.0] * len(values)
    for i in range(1, len(values)):
        delta = float(values[i]) - float(values[i - 1])
        gains[i] = max(0.0, delta)
        losses[i] = max(0.0, -delta)
    # Wilder's smoothing
    avg_gain: Optional[float] = None
    avg_loss: Optional[float] = None
    for i in range(1, len(values)):
        if i < period:
            # seed period using simple average at period boundary
            if i == period - 1:
                avg_gain = sum(gains[1:period]) / period
                avg_loss = sum(losses[1:period]) / period
        else:
            assert avg_gain is not None and avg_loss is not None
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            rs = (avg_gain / avg_loss) if avg_loss and avg_loss != 0 else float('inf')
            out[i] = 100 - (100 / (1 + rs))
    return out


def macd(values: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
    ema_fast = ema(values, fast)
    ema_slow = ema(values, slow)
    macd_line: List[Optional[float]] = [None] * len(values)
    for i in range(len(values)):
        a = ema_fast[i]
        b = ema_slow[i]
        macd_line[i] = (a - b) if (a is not None and b is not None) else None
    # signal line as EMA of macd_line (replace None with previous for stability)
    macd_filled: List[float] = []
    last = 0.0
    for v in macd_line:
        if v is None:
            macd_filled.append(last)
        else:
            last = float(v)
            macd_filled.append(last)
    signal_line = ema(macd_filled, signal)
    hist: List[Optional[float]] = [None if (m is None or s is None) else (m - s) for m, s in zip(macd_line, signal_line)]
    return macd_line, signal_line, hist


def bollinger(values: Sequence[float], window: int = 20, num_std: float = 2.0) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
    # Compute SMA and rolling std deviation without numpy
    ma = sma(values, window)
    out_mid = ma
    out_upper: List[Optional[float]] = [None] * len(values)
    out_lower: List[Optional[float]] = [None] * len(values)
    for i in range(len(values)):
        if i < window - 1:
            continue
        window_vals = [float(x) for x in values[i - window + 1 : i + 1]]
        m = float(out_mid[i]) if out_mid[i] is not None else sum(window_vals) / window
        var = sum((x - m) ** 2 for x in window_vals) / window
        std = var ** 0.5
        out_upper[i] = m + num_std * std
        out_lower[i] = m - num_std * std
    return out_upper, out_mid, out_lower


__all__ = [
    'sma', 'ema', 'rsi', 'macd', 'bollinger',
]
