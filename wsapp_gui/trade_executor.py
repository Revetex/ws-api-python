"""Trade execution helpers: paper-trading engine with optional live stubs.

Safe-by-default: live mode is a no-op until wired to a broker API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Dict, List, Optional, Any


@dataclass
class Position:
    symbol: str
    qty: float = 0.0
    avg_price: float = 0.0

    def buy(self, price: float, qty: float) -> None:
        if qty <= 0 or price <= 0:
            return
        total_cost = self.avg_price * self.qty + price * qty
        self.qty += qty
        self.avg_price = (total_cost / self.qty) if self.qty > 0 else 0.0

    def sell(self, price: float, qty: float) -> float:
        if qty <= 0 or price <= 0 or self.qty <= 0:
            return 0.0
        real_qty = min(qty, self.qty)
        proceeds = price * real_qty
        self.qty -= real_qty
        if self.qty == 0:
            self.avg_price = 0.0
        return proceeds


@dataclass
class PaperPortfolio:
    cash: float = 100000.0
    positions: Dict[str, Position] = field(default_factory=dict)

    def position(self, symbol: str) -> Position:
        p = self.positions.get(symbol)
        if not p:
            p = Position(symbol=symbol)
            self.positions[symbol] = p
        return p

    def equity(self, quotes: Dict[str, float] | None = None) -> float:
        val = self.cash
        if quotes:
            for sym, pos in self.positions.items():
                q = quotes.get(sym)
                if q and pos.qty > 0:
                    val += pos.qty * q
        return val


class TradeExecutor:
    """Executes trades from strategy signals.

    Modes:
      - paper: simulated portfolio with cash/positions
      - live: NO-OP stub for safety (can be wired to broker API later)
    """

    def __init__(self, api_manager):
        self.api = api_manager
        self.enabled: bool = False
        self.mode: str = 'paper'  # 'paper' | 'live'
        self.account_id: Optional[str] = None
        self.base_size: float = 1000.0  # fixed notional per trade (in account currency)
        self.max_trades_per_day: int = 10
        # Guardrails
        self.max_position_notional_per_symbol: float = 0.0  # 0 = unlimited
        self.max_position_qty_per_symbol: float = 0.0       # 0 = unlimited
        self._last_trade_day: Optional[date] = None
        self._trade_count_today: int = 0
        self._paper = PaperPortfolio(cash=100000.0)
        self._log: List[str] = []
        # Idempotency ledger: (symbol, kind, index)
        self._ledger: set[tuple] = set()
        # Optional live executor hook: callable(symbol:str, side:str, qty:float|None, price:float, meta:dict) -> None
        self.live_executor = None
        # Load persisted ledger on startup
        self._load_ledger()

    # -------- configuration --------
    def configure(
        self,
        *,
        enabled: Optional[bool] = None,
        mode: Optional[str] = None,
        account_id: Optional[str] = None,
        base_size: Optional[float] = None,
        max_trades_per_day: Optional[int] = None,
        paper_starting_cash: Optional[float] = None,
        max_position_notional_per_symbol: Optional[float] = None,
        max_position_qty_per_symbol: Optional[float] = None,
    ) -> None:
        if enabled is not None:
            self.enabled = bool(enabled)
        if mode is not None:
            self.mode = mode if mode in ('paper', 'live') else 'paper'
        if account_id is not None:
            self.account_id = account_id or None
        if base_size is not None:
            try:
                self.base_size = max(0.0, float(base_size))
            except Exception:
                pass
        if max_trades_per_day is not None:
            try:
                self.max_trades_per_day = max(0, int(max_trades_per_day))
            except Exception:
                pass
        if paper_starting_cash is not None:
            try:
                val = max(0.0, float(paper_starting_cash))
                # reset portfolio if starting cash changes significantly
                if abs(val - self._paper.cash) > 1e-6 and not self._paper.positions:
                    self._paper.cash = val
            except Exception:
                pass
        if max_position_notional_per_symbol is not None:
            try:
                self.max_position_notional_per_symbol = max(0.0, float(max_position_notional_per_symbol))
            except Exception:
                pass
        if max_position_qty_per_symbol is not None:
            try:
                self.max_position_qty_per_symbol = max(0.0, float(max_position_qty_per_symbol))
            except Exception:
                pass

    def set_live_executor(self, executor_callable) -> None:
        """Optionally wire a real live executor later.

        executor_callable(symbol:str, side:str, qty:float|None, price:float, meta:dict) -> None
        """
        self.live_executor = executor_callable

    # -------- public API --------
    def on_signal(self, symbol: str, signal: Any) -> None:  # signal has attributes: kind, index, reason, confidence
        if not self.enabled:
            return
        try:
            self._rotate_trade_counter()
            if self.max_trades_per_day and self._trade_count_today >= self.max_trades_per_day:
                return
            # Idempotency: skip if we've already processed this signal
            key = (symbol, str(getattr(signal, 'kind', '')).lower(), getattr(signal, 'index', None))
            if key in self._ledger:
                return
            # Fetch reference price
            price = self._get_last_price(symbol)
            if price is None or price <= 0:
                self._log.append(f"{datetime.now().isoformat()} | SKIP {symbol} no price")
                return
            if str(signal.kind).lower() == 'buy':
                if self._exec_buy(symbol, price, signal):
                    self._ledger.add(key)
                    self._save_ledger()
            elif str(signal.kind).lower() == 'sell':
                if self._exec_sell(symbol, price, signal):
                    self._ledger.add(key)
                    self._save_ledger()
        except Exception as e:
            self._log.append(f"{datetime.now().isoformat()} | ERROR {symbol}: {e}")

    def summary(self) -> str:
        if self.mode == 'paper':
            open_pos = sum(1 for p in self._paper.positions.values() if p.qty > 0)
            return (
                f"AutoTrade[{self.mode}] cash={self._paper.cash:.2f} positions={open_pos} "
                f"trades_today={self._trade_count_today}/{self.max_trades_per_day}"
            )
        return f"AutoTrade[{self.mode}] enabled={self.enabled} trades_today={self._trade_count_today}/{self.max_trades_per_day}"

    def last_actions(self, n: int = 10) -> List[str]:
        return self._log[-n:]

    # -------- internals --------
    def _rotate_trade_counter(self) -> None:
        today = datetime.now().date()
        if self._last_trade_day != today:
            self._last_trade_day = today
            self._trade_count_today = 0

    def _get_last_price(self, symbol: str) -> Optional[float]:
        try:
            q = self.api.get_quote(symbol) if self.api else None
            if not q or not isinstance(q, dict):
                return None
            # Alpha-style key
            v = q.get('05. price') or q.get('05. Price')
            if v is None:
                # Yahoo-like wrappers may expose different shapes; try common fallbacks
                v = q.get('price') or q.get('regularMarketPrice')
            return float(v) if v is not None else None
        except Exception:
            return None

    def _exec_buy(self, symbol: str, price: float, signal: Any) -> bool:
        if self.mode == 'paper':
            notional = max(0.0, self.base_size)
            if notional <= 0:
                return False
            qty = round(notional / price, 4)
            if qty <= 0:
                return False
            # Cash check
            cost = qty * price
            if self._paper.cash < cost:
                # scale down
                qty = round((self._paper.cash / price), 4)
                cost = qty * price
            if qty <= 0:
                return False
            pos = self._paper.position(symbol)
            # Guardrail: per-symbol max qty/notional
            if self.max_position_qty_per_symbol > 0.0:
                allowed_qty = max(0.0, self.max_position_qty_per_symbol - pos.qty)
                qty = min(qty, round(allowed_qty, 4))
                cost = qty * price
            if self.max_position_notional_per_symbol > 0.0:
                current_notional = pos.qty * pos.avg_price if pos.qty > 0 else 0.0
                allowed_notional = max(0.0, self.max_position_notional_per_symbol - current_notional)
                max_qty_by_notional = round(allowed_notional / price, 4)
                qty = min(qty, max_qty_by_notional)
                cost = qty * price
            if qty <= 0:
                return False
            pos.buy(price, qty)
            self._paper.cash -= cost
            self._trade_count_today += 1
            self._log.append(
                f"{datetime.now().isoformat()} | BUY {symbol} {qty} @ {price:.2f} (conf={getattr(signal, 'confidence', None)})"
            )
            return True
        # live stub: no-op for safety
        self._trade_count_today += 1
        self._log.append(
            f"{datetime.now().isoformat()} | LIVE BUY (stub) {symbol} notional {self.base_size:.2f} @ {price:.2f}"
        )
        try:
            if self.live_executor:
                self.live_executor(symbol, 'buy', None, price, {
                    'base_size': self.base_size,
                    'signal': getattr(signal, 'reason', None),
                })
        except Exception:
            pass
        return True

    def _exec_sell(self, symbol: str, price: float, signal: Any) -> bool:
        if self.mode == 'paper':
            pos = self._paper.position(symbol)
            if pos.qty <= 0:
                # nothing to sell
                return False
            
            # Calculate quantity to sell based on base_size (like buying)
            sell_qty = min(pos.qty, self.base_size / price) if price > 0 else pos.qty
            
            proceeds = pos.sell(price, sell_qty)
            self._paper.cash += proceeds
            self._trade_count_today += 1
            self._log.append(
                f"{datetime.now().isoformat()} | SELL {symbol} {sell_qty:.4f} @ {price:.2f} (proceeds={proceeds:.2f})"
            )
            return True
        # live stub
        self._trade_count_today += 1
        self._log.append(
            f"{datetime.now().isoformat()} | LIVE SELL (stub) {symbol} ALL @ {price:.2f}"
        )
        try:
            if self.live_executor:
                self.live_executor(symbol, 'sell', None, price, {
                    'signal': getattr(signal, 'reason', None),
                })
        except Exception:
            pass
        return True

    def portfolio_snapshot(self, quotes: Dict[str, float] | None = None, include_quotes: bool = False) -> Dict[str, Any]:
        """Return a lightweight snapshot of the paper portfolio for UI rendering."""
        if self.mode != 'paper':
            return {
                'mode': self.mode,
                'cash': None,
                'equity': None,
                'positions': [],
                'quotes': {},
            }
        
        # Fetch current quotes if requested
        current_quotes = {}
        if include_quotes:
            try:
                for sym in self._paper.positions.keys():
                    if self._paper.positions[sym].qty > 0:
                        price = self._get_last_price(sym)
                        if price is not None:
                            current_quotes[sym] = {'last': price}
            except Exception:
                pass
        
        # Override with provided quotes if any
        if quotes:
            for sym, price in quotes.items():
                if sym not in current_quotes:
                    current_quotes[sym] = {}
                current_quotes[sym]['last'] = price
        
        snaps = []
        for sym, pos in self._paper.positions.items():
            if pos.qty <= 0:
                continue
            last = current_quotes.get(sym, {}).get('last') if current_quotes else None
            snaps.append({'symbol': sym, 'qty': pos.qty, 'avg_price': pos.avg_price, 'last': last})
        
        # Calculate equity using current quotes
        quote_prices = {sym: data.get('last', 0) for sym, data in current_quotes.items()}
        eq = self._paper.equity(quote_prices)
        
        return {
            'mode': self.mode,
            'cash': self._paper.cash,
            'equity': eq,
            'positions': snaps,
            'quotes': current_quotes,
        }

    def _load_ledger(self) -> None:
        """Load persisted ledger entries from config."""
        try:
            from .config import app_config
            ledger_data = app_config.get('autotrade.ledger', []) or []
            self._ledger = set()
            for entry in ledger_data:
                if isinstance(entry, dict):
                    symbol = entry.get('symbol')
                    kind = entry.get('kind')
                    index = entry.get('index')
                    if symbol is not None and kind is not None and index is not None:
                        self._ledger.add((symbol, kind, index))
        except Exception:
            pass

    def _save_ledger(self) -> None:
        """Persist current ledger entries to config."""
        try:
            from .config import app_config
            # Convert set to list of dicts for JSON serialization
            ledger_data = []
            for symbol, kind, index in self._ledger:
                ledger_data.append({
                    'timestamp': __import__('time').time(),
                    'symbol': symbol,
                    'kind': kind,
                    'index': index,
                })
            
            # Keep only recent entries (last 100) to prevent unbounded growth
            if len(ledger_data) > 100:
                ledger_data = ledger_data[-100:]
            
            app_config.set('autotrade.ledger', ledger_data)
        except Exception:
            pass


__all__ = ["TradeExecutor", "PaperPortfolio", "Position"]
