"""AI Agent skeleton for portfolio monitoring, signals, strategies, chat.

Features (current):
 - Local rule-based signals (PnL thresholds, concentration, cash ratio)
 - Chat stub (echo / help) ready for future Gemini integration
 - Event ingestion: on_positions
 - External APIs: News, Alpha Vantage, Telegram notifications

Future integration (Gemini 1.5 Flash):
 Implement call_gemini(prompt: str, system: str) using Google API client.
 The UI can toggle between local rules and LLM suggestions.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Tuple
import os
import time
import json
import re

try:
    import requests  # type: ignore
    HAS_REQUESTS = True
except Exception:  # pragma: no cover - should always be present per requirements
    HAS_REQUESTS = False

try:
    from external_apis import APIManager
    HAS_EXTERNAL_APIS = True
except ImportError:
    HAS_EXTERNAL_APIS = False
    APIManager = None


@dataclass
class Position:
    symbol: str
    name: str
    quantity: float
    value: float
    currency: Optional[str] = None
    pnl_abs: Optional[float] = None
    pnl_pct: Optional[float] = None


@dataclass
class Signal:
    ts: float
    level: str  # INFO/WARN/ALERT
    code: str
    message: str
    meta: Dict = field(default_factory=dict)


class AIAgent:
    def __init__(
        self,
        pnl_warn_pct: float = 5.0,
        pnl_alert_pct: float = 15.0,
        enable_gemini: bool = True,
        enable_notifications: bool = True,
        data_only: bool = False,
    ):
        self.pnl_warn_pct = pnl_warn_pct
        self.pnl_alert_pct = pnl_alert_pct
        self.history: List[Signal] = []
        self.last_positions: List[Position] = []
        # Data-only mode (no heuristics, no LLMs). Env override: DATA_ONLY=1
        self.data_only = bool(data_only or os.getenv('DATA_ONLY', '0') == '1')
        self._gemini_key = (
            os.getenv('GEMINI_API_KEY') if enable_gemini else None
        )
        self._gemini_model = 'gemini-1.5-flash'
        self._gemini_available = False

        # External APIs
        self.api_manager = APIManager() if HAS_EXTERNAL_APIS else None
        # Ensure this stays a boolean, not an object reference
        self.enable_notifications = bool(
            enable_notifications and self.api_manager is not None
        )

        if self._gemini_key and not self.data_only:
            try:  # Lazy import; keep optional
                import google.generativeai as genai  # type: ignore
                genai.configure(api_key=self._gemini_key)
                self._genai = genai
                self._gemini_available = True
            except Exception:
                self._gemini_available = False

        # --- Ollama (local LLM) ---
        # Use environment variable OLLAMA_MODEL to override default.
        # Example: set OLLAMA_MODEL=huihui_ai/acereason-nemotron-abliterated:7b
        self._ollama_model = os.getenv(
            'OLLAMA_MODEL', 'huihui_ai/acereason-nemotron-abliterated:7b'
        )
        # Allow disabling via OLLAMA_DISABLE=1
        self._ollama_enabled = (os.getenv('OLLAMA_DISABLE', '0') != '1') and (not self.data_only)
        self._ollama_endpoint = os.getenv(
            'OLLAMA_ENDPOINT', 'http://localhost:11434'
        ).rstrip('/')
        self._ollama_available_checked = False
        self._ollama_available = False
        # Conversation memory (light) for multi‑tour context
        self._history: List[Tuple[str, str]] = []  # (role, text)
        self._history_max = 8
        # Cached metrics (recomputed on new positions)
        self._last_metrics = {}  # type: Dict[str, Any]
        # Optional predicate to decide if notifications are allowed (injected by UI)
        self.notifications_allowed = None  # optional predicate callable returning bool
        # Allow sending technical alerts (e.g., SMA BUY/SELL) to external notifiers
        self.allow_technical_alerts = True
        # If GUI config is present, respect Telegram technical include setting
        try:
            from wsapp_gui.config import app_config  # type: ignore
            self.allow_technical_alerts = bool(
                app_config.get('integrations.telegram.include_technical', True)
            )
        except Exception:
            pass
        # Technical signal cache to reduce API calls: symbol -> (ts, {signal,r5,r20})
        self._tech_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._tech_ttl_sec = 900  # 15 minutes
        # Rate-limit technical alerts emission per symbol
        self._last_tech_emit: Dict[str, float] = {}
        self._tech_emit_ttl_sec = 3600  # 1 hour
        # --- Enhanced AI (feature-flagged) ---
        self._enhanced_ai = None
        try:
            cfg_enabled = False
            try:
                from wsapp_gui.config import app_config  # type: ignore
                cfg_enabled = bool(app_config.get('ai.enhanced', False))
            except Exception:
                cfg_enabled = False
            if (cfg_enabled or os.getenv('AI_ENHANCED', '0') == '1') and not self.data_only:
                from enhanced_ai_system import EnhancedAI  # type: ignore
                # deterministic=False for some variety; rate-limit defaults are fine
                self._enhanced_ai = EnhancedAI(deterministic=False)
        except Exception:
            self._enhanced_ai = None

    def _enrich_symbol_metrics(self, symbol: Optional[str]) -> Dict[str, Any]:
        """Return real-data metrics for a symbol: price, SMA5/20, RSI (if available),
        distance to SMA20, and 6-month high/low. Safe on errors. Data-only friendly.
        """
        out: Dict[str, Any] = {}
        if not symbol or not self.api_manager:
            return out
        sym = str(symbol).upper()
        # Quote (price)
        try:
            q = self.api_manager.get_quote(sym) or {}
            price_s = q.get('05. price')
            if price_s is not None:
                try:
                    out['price'] = float(str(price_s).replace('%', ''))
                except Exception:
                    pass
        except Exception:
            pass
        # SMA
        try:
            sres = self._sma_signal_cached(sym)
            if isinstance(sres, dict):
                r5 = sres.get('r5')
                r20 = sres.get('r20')
                if isinstance(r5, (int, float)):
                    out['sma5'] = float(r5)
                if isinstance(r20, (int, float)):
                    out['sma20'] = float(r20)
                if 'price' in out and isinstance(out.get('sma20'), (int, float)) and out['sma20']:
                    try:
                        out['dist_sma20_pct'] = ((out['price'] / out['sma20']) - 1.0) * 100.0
                    except Exception:
                        pass
        except Exception:
            pass
        # RSI (compute locally from compact daily series)
        try:
            series = self.api_manager.get_time_series(sym, interval='1day', outputsize='compact') or {}
            ts = None
            for k, v in series.items():
                if isinstance(v, dict) and 'time series' in k.lower():
                    ts = v
                    break
            if isinstance(ts, dict) and ts:
                items = sorted(ts.items())  # ascending by date
                closes: list[float] = []
                dates: list[str] = []
                for d, row in items:
                    try:
                        c = float(row.get('4. close') or row.get('close') or 0.0)
                    except Exception:
                        c = 0.0
                    closes.append(c)
                    dates.append(str(d))
                rsi_vals = self._calculate_rsi(closes, period=14)
                if rsi_vals:
                    out['rsi'] = float(rsi_vals[-1])
                    # Align date index: rsi starts after (period) entries
                    idx = len(dates) - 1
                    out['rsi_date'] = dates[idx] if idx >= 0 else None
        except Exception:
            pass
        # 6-month high/low from daily compact series (Yahoo fallback handles compact ~6mo)
        try:
            series = self.api_manager.get_time_series(sym, interval='1day', outputsize='compact') or {}
            ts = None
            for k, v in series.items():
                if 'time series' in k.lower() and isinstance(v, dict):
                    ts = v
                    break
            if isinstance(ts, dict) and ts:
                closes: list = []
                for _d, row in ts.items():
                    try:
                        closes.append(float(row.get('4. close') or 0.0))
                    except Exception:
                        continue
                if closes:
                    out['range_6m_low'] = min(closes)
                    out['range_6m_high'] = max(closes)
        except Exception:
            pass
        return out

    # --- Local indicator helpers ---
    def _calculate_rsi(self, prices: List[float], period: int = 14) -> List[float]:
        if not prices or len(prices) < period + 1:
            return []
        gains: List[float] = []
        losses: List[float] = []
        for i in range(1, len(prices)):
            ch = prices[i] - prices[i - 1]
            gains.append(max(0.0, ch))
            losses.append(max(0.0, -ch))
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        rsi: List[float] = []
        # Wilder smoothing
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            if avg_loss == 0:
                rsi.append(100.0)
            else:
                rs = avg_gain / avg_loss
                rsi.append(100 - (100 / (1 + rs)))
        return rsi

    # --- Public API ---
    def on_positions(self, positions: List[dict]):
        self.last_positions = [
            Position(
                symbol=p.get('symbol'),
                name=p.get('name'),
                quantity=float(p.get('quantity') or 0),
                value=float(p.get('value') or 0),
                currency=p.get('currency'),
                pnl_abs=p.get('pnlAbs'),
                pnl_pct=p.get('pnlPct'),
            )
            for p in positions
            if p.get('symbol')
        ]
        self._compute_metrics()
        self._generate_signals()

    def get_signals(self) -> List[Signal]:
        return list(self.history)[-200:]

    def generate_market_signals(self) -> List[Signal]:
        """Return fresh signals based on last known positions.

        Safe no-op if no positions. This mirrors internal rule-based checks
        and returns only new signals added since the last call.
        """
        before = len(self.history)
        try:
            # Re-run generation using current positions snapshot
            self._generate_signals()
        except Exception:
            pass
        return self.history[before:]

    def chat(self, prompt: str) -> str:
        prompt_l = prompt.strip().lower()
        if not prompt_l:
            return "Posez une question sur votre portefeuille."
        if prompt_l in {"help", "aide", "?"}:
            return (
                "Commandes disponibles:\n"
                "  resume            -> Résumé rapide NLV & nombre de positions\n"
                "  top               -> Top 5 par valeur\n"
                "  risques           -> Répartition principales positions\n"
                "  diversification   -> Indice HHI & classification\n"
                "  allocation        -> Cash ratio & répartition actions vs cash\n"
                "  insights          -> Synthèse: santé, gagnants/perdants, alertes\n"
                "  movers            -> Gagnants/Perdants/Actifs du marché CA\n"
                "  opportunites      -> Opportunités détectées marché CA\n"
                "  rebalance         -> Suggestion de rééquilibrage (non-liée)\n"
                "  health            -> Check-up du portefeuille\n"
                "  signals           -> Derniers signaux générés\n"
                "  signal(s) <SYM>   -> Signal technique SMA pour un symbole (ex: signal AAPL)\n"
                "  backtest <SYM>    -> Backtest SMA(5/20) quotidien pour un symbole\n"
                "  reset             -> Effacer le contexte de conversation\n"
                "  <SYMBOLE>         -> Infos enrichies sur un symbole (ex: AAPL)\n"
                "Intégré: analyse locale + LLM (Ollama/Gemini) si disponible."
            )
        if prompt_l == 'reset':
            self._history.clear()
            return "Contexte de conversation ré-initialisé."
        if prompt_l == 'resume':
            total = sum(p.value for p in self.last_positions)
            return (
                f"Valeur totale ~ {total:,.2f}. Positions: "
                f"{len(self.last_positions)}"
            )
        if prompt_l == 'top':
            tops = sorted(
                self.last_positions,
                key=lambda p: p.value,
                reverse=True,
            )[:5]
            lines = []
            for p in tops:
                if p.pnl_pct is not None:
                    lines.append(
                        f"{p.symbol}: {p.value:,.2f} ({p.pnl_pct:.1f}%)"
                    )
                else:
                    lines.append(f"{p.symbol}: {p.value:,.2f}")
            return '\n'.join(lines)
        if prompt_l == 'risques':
            return self._risk_summary()
        if prompt_l == 'diversification':
            m = self._last_metrics or self._compute_metrics()
            return (
                "Diversification (Herfindahl-Hirschman): "
                f"{m.get('hhi_normalized'):.3f} ({m.get('diversification_label')})\n"
                f"Positions: {m.get('n_positions')} | Top position: {m.get('top_share'):.1f}%"
            )
        if prompt_l == 'allocation':
            m = self._last_metrics or self._compute_metrics()
            return (
                f"Cash: {m.get('cash_ratio'):.1f}% | Actions: {100 - m.get('cash_ratio'):.1f}% | "
                f"#Pos: {m.get('n_positions')}"
            )
        if prompt_l == 'insights':
            # If enhanced AI is enabled, return enriched analytics + decision
            try:
                if getattr(self, '_enhanced_ai', None) is not None:
                    positions = [
                        {
                            'symbol': p.symbol,
                            'name': p.name,
                            'quantity': p.quantity,
                            'value': p.value,
                            'currency': p.currency,
                            'pnlAbs': p.pnl_abs,
                            'pnlPct': p.pnl_pct,
                        }
                        for p in self.last_positions
                    ]
                    res = self._enhanced_ai.analyze_and_suggest(positions, lang='fr')
                    if isinstance(res, dict):
                        a = (res.get('analytics') or '').strip()
                        d = (res.get('decision') or '').strip()
                        return (a + "\n\n" + d).strip() or self._insights()
            except Exception:
                pass
            return self._insights()
        if prompt_l == 'positions':
            tops = sorted(self.last_positions, key=lambda x: x.value, reverse=True)[:10]
            if not tops:
                return "Aucune position."
            total = sum(p.value for p in self.last_positions) or 1.0
            lines = ["Positions (top):"]
            for p in tops:
                share = p.value / total * 100.0
                pnl_s = f" ({p.pnl_pct:.1f}%)" if (p.pnl_pct is not None) else ""
                lines.append(f" - {p.symbol:<6} {p.value:>10,.0f} ({share:4.1f}%){pnl_s}")
            return "\n".join(lines)
        if prompt_l in {'movers', 'mouvements'}:
            return self._market_movers()
        if prompt_l in {'opportunites', 'opportunités', 'opportunities'}:
            return self._market_opportunities()
        if prompt_l in {'rebalance', 'rééquilibrage', 'reequilibrage'}:
            return self._rebalance_suggestion()
        if prompt_l in {'health', 'santé', 'sante'}:
            return self._health_check()
        # Signals intent: support colloquial/embedded phrasing (e.g., "y a tu des signaux?", "ya tu des signal")
        if (
            prompt_l.startswith('signals')
            or prompt_l.startswith('signal')
            or re.search(r"\bsignaux?\b", prompt_l) is not None
        ):
            # Support optional symbol after the word
            parts = prompt.strip().split()
            if len(parts) >= 2 and parts[0].lower().startswith('signal'):
                sym = parts[1].upper()
                bt = self._sma_signal_cached(sym)
                if isinstance(bt, str):
                    return bt
                sig_txt = bt.get('signal', 'HOLD')
                r5 = bt.get('r5', None)
                r20 = bt.get('r20', None)
                return (
                    f"Signal SMA(5/20) {sym}: {sig_txt} (SMA5={r5:.2f} SMA20={r20:.2f})"
                    if (r5 is not None and r20 is not None)
                    else f"Signal SMA(5/20) {sym}: {sig_txt}"
                )
            # Otherwise return recent portfolio signals + quick tech for top 3
            sigs = self.get_signals()[-7:]
            lines = []
            if sigs:
                lines.append(f"{len(sigs)} signal(s) récents:")
                for s in sigs:
                    lines.append(self._format_signal_for_chat(s))
            # Technical snapshot for top 3 non-cash symbols
            tops = [p for p in sorted(self.last_positions, key=lambda x: x.value, reverse=True) if p.symbol not in ('CAD', 'USD')][:3]
            tech_lines = []
            if tops:
                tech_lines.append("Tech SMA(5/20):")
                for p in tops:
                    bt = self._sma_signal_cached(p.symbol)
                    if isinstance(bt, dict):
                        r5 = bt.get('r5')
                        r20 = bt.get('r20')
                        if r5 is not None and r20 is not None:
                            tech_lines.append(f" - {p.symbol}: {bt.get('signal', 'HOLD')} (SMA5={r5:.2f}, SMA20={r20:.2f})")
                        else:
                            tech_lines.append(f" - {p.symbol}: {bt.get('signal', 'HOLD')}")
            # Compose output prioritizing clarity
            if lines and tech_lines:
                return "\n".join(lines + [""] + tech_lines)
            if lines:
                return "\n".join(lines)
            if tech_lines:
                return "\n".join(["Aucune alerte interne."] + tech_lines)
            return "Aucun signal pour le moment."

        # Backtest requests
        if 'backtest' in prompt_l or 'backtesting' in prompt_l or 'backterté' in prompt_l or 'backterte' in prompt_l:
            # Try to extract a symbol from the text or pick largest non-cash
            sym_list = self._find_symbols_in_text(prompt)
            sym = None
            if sym_list:
                sym = sym_list[0]
            else:
                for p in sorted(self.last_positions, key=lambda x: x.value, reverse=True):
                    if p.symbol not in ('CAD', 'USD'):
                        sym = p.symbol
                        break
            if not sym:
                return "Aucun symbole identifié pour le backtest (ajoutez ex: 'backtest AAPL')."
            res = self._backtest_sma(sym)
            if isinstance(res, str):
                return res
            return (
                f"Backtest SMA(5/20) {sym}:\n"
                f"  - Trades: {res['trades']} | CAGR: {res['cagr']:.2f}% | MaxDD: {res['max_dd']:.1f}%\n"
                f"  - vs Buy&Hold: {res['bh_return']:.2f}% | Strat: {res['strat_return']:.2f}%\n"
                f"  - Signal courant: {res['last_signal']}"
            )

        # Check if asking for specific symbol info (only if it's in the portfolio)
        symbol_upper = prompt.upper().strip()
        if len(symbol_upper) <= 5 and symbol_upper.isalpha():
            portfolio_symbols = {p.symbol.upper() for p in self.last_positions if p.symbol}
            if symbol_upper in portfolio_symbols:
                return self._get_symbol_info(symbol_upper)

        # If LLM available, try it; otherwise produce a natural local reply
        # Preference order: Ollama (local), then Gemini; fallback to local natural
        if self.data_only:
            answer = self._chat_local_natural(prompt)
        else:
            enriched_prompt = self._augment_user_prompt(prompt)
            answer = None
            if self._ollama_enabled and self._ensure_ollama_available():
                answer = self._chat_ollama(enriched_prompt)
            if (not answer or (isinstance(answer, str) and answer.startswith('('))) and self._gemini_available:
                answer = self._chat_gemini(enriched_prompt)
            if not answer or (isinstance(answer, str) and answer.startswith('(')):
                answer = self._chat_local_natural(prompt)
        # Track in history
        self._append_history('user', prompt)
        self._append_history('assistant', answer)
        return answer

    def _format_signal_for_chat(self, s: Signal) -> str:
        """Formatte un signal avec détails utiles (qty, raison, prévision, horizon, SL/TP)."""
        base = f"[{s.level}] {s.code}: {s.message}"
        meta = s.meta or {}
        # Collect optional fields
        qty_abs = meta.get('qty_abs')
        qty_pct = meta.get('qty_pct')
        reason = meta.get('reason')
        forecast = meta.get('forecast')
        horizon = meta.get('horizon')
        sl = meta.get('stop_loss')
        tp = meta.get('take_profit')
        # Numeric enrichments
        price = meta.get('price')
        sma5 = meta.get('sma5')
        sma20 = meta.get('sma20')
        dist20 = meta.get('dist_sma20_pct')
        rsi = meta.get('rsi')
        rsi_date = meta.get('rsi_date')
        r6l = meta.get('range_6m_low')
        r6h = meta.get('range_6m_high')
        pos_val = meta.get('position_value')
        pos_share = meta.get('position_share')
        pnl_pct = meta.get('pnl_pct')
        cash_ratio = meta.get('cash_ratio')
        npos = meta.get('n_positions')
        hhi_n = meta.get('hhi')
        top_share = meta.get('top_share')
        parts = []
        if qty_abs is not None and qty_pct is not None:
            try:
                parts.append(f"Quantité: ≈{qty_abs:,.0f} (≈{qty_pct:.1f}% du PF)")
            except Exception:
                parts.append(f"Quantité: ≈{qty_abs} (≈{qty_pct}% du PF)")
        elif qty_pct is not None:
            try:
                parts.append(f"Quantité: ≈{qty_pct:.1f}% du PF")
            except Exception:
                parts.append(f"Quantité: ≈{qty_pct}% du PF)")
        if reason:
            parts.append(f"Raison: {reason}")
        if forecast:
            parts.append(f"Prévision: {forecast}")
        if horizon:
            parts.append(f"Horizon: {horizon}")
        if sl:
            parts.append(f"Stop-loss: {sl}")
        if tp:
            parts.append(f"Take-profit: {tp}")
        # Append numeric facts compactly
        num_lines: list[str] = []
        try:
            if price is not None:
                num_lines.append(f"Prix: {price:.2f}")
        except Exception:
            pass
        try:
            if sma5 is not None and sma20 is not None:
                num_lines.append(f"SMA5/SMA20: {float(sma5):.2f}/{float(sma20):.2f}")
        except Exception:
            pass
        try:
            if dist20 is not None:
                num_lines.append(f"Écart vs SMA20: {float(dist20):+.1f}%")
        except Exception:
            pass
        try:
            if rsi is not None:
                lbl = "RSI" if not rsi_date else f"RSI ({rsi_date})"
                num_lines.append(f"{lbl}: {float(rsi):.1f}")
        except Exception:
            pass
        try:
            if r6l is not None and r6h is not None:
                num_lines.append(f"Range 6m: {float(r6l):.2f}-{float(r6h):.2f}")
        except Exception:
            pass
        try:
            if pos_val is not None:
                if pnl_pct is not None:
                    num_lines.append(f"Position: {float(pos_val):,.0f} ({float(pnl_pct):+.1f}%)")
                else:
                    num_lines.append(f"Position: {float(pos_val):,.0f}")
        except Exception:
            pass
        try:
            if pos_share is not None:
                num_lines.append(f"Poids: {float(pos_share)*100:.1f}%")
        except Exception:
            pass
        try:
            if cash_ratio is not None:
                num_lines.append(f"Cash: {float(cash_ratio)*100:.1f}%")
        except Exception:
            pass
        try:
            if npos is not None and hhi_n is not None and top_share is not None:
                num_lines.append(f"Diversif: HHI {float(hhi_n):.3f} | Top {float(top_share):.1f}% | #Pos {int(npos)}")
        except Exception:
            pass
        if num_lines:
            parts.append(" | ".join(num_lines))
        if parts:
            return base + "\n  - " + "\n  - ".join(parts)
        return base

    # --- Metrics & context helpers ---
    def _compute_metrics(self) -> Dict[str, Any]:
        if not self.last_positions:
            self._last_metrics = {
                'n_positions': 0,
                'cash_ratio': 0.0,
                'hhi': 0.0,
                'hhi_normalized': 0.0,
                'diversification_label': 'N/A',
                'top_share': 0.0,
            }
            return self._last_metrics
        total = sum(p.value for p in self.last_positions) or 1.0
        shares = [(p.value / total) for p in self.last_positions if p.value > 0]
        hhi = sum(s * s for s in shares)
        # Normalize HHI to 0-1 scale using (HHI - 1/N)/(1 - 1/N)
        n = len(shares)
        norm = 0.0
        if n > 1:
            norm = (hhi - 1.0 / n) / (1 - 1.0 / n)
            norm = max(0.0, min(1.0, norm))
        if norm < 0.15:
            label = 'Bonne'
        elif norm < 0.30:
            label = 'Moyenne'
        else:
            label = 'Faible'
        cash_total = sum(
            p.value for p in self.last_positions if p.symbol in ('CAD', 'USD')
        )
        cash_ratio = (cash_total / total) * 100
        top_share = max(shares) * 100 if shares else 0.0
        self._last_metrics = {
            'n_positions': len(self.last_positions),
            'cash_ratio': cash_ratio,
            'hhi': hhi,
            'hhi_normalized': norm,
            'diversification_label': label,
            'top_share': top_share,
        }
        return self._last_metrics

    def _append_history(self, role: str, text: str):
        self._history.append((role, text.strip()))
        if len(self._history) > self._history_max * 2:
            # keep last N exchanges (user+assistant)
            self._history = self._history[-self._history_max * 2 :]

    def _augment_user_prompt(self, user_prompt: str) -> str:
        # Build a richer system + context prompt for LLMs
        metrics = self._last_metrics or self._compute_metrics()
        portfolio_ctx = self._build_portfolio_context()
        history_lines = []
        for role, txt in self._history[-6:]:  # last 3 exchanges
            history_lines.append(f"{role}: {txt}")
        history_block = "\n".join(history_lines) if history_lines else "(aucune)"
        return (
            "Tu es un assistant financier francophone concis. "
            "Ne donne pas de conseils réglementés; réponds avec une tonalité pédagogique.\n"
            f"Métriques: HHI_norm={metrics.get('hhi_normalized'):.3f} Diversification={metrics.get('diversification_label')} "
            f"Cash={metrics.get('cash_ratio'):.1f}% Positions={metrics.get('n_positions')} TopShare={metrics.get('top_share'):.1f}%\n"
            f"Portefeuille:\n{portfolio_ctx}\n"
            f"Historique conversation (récent):\n{history_block}\n"
            f"Question utilisateur: {user_prompt}\n"
            "Réponse:"
        )

    # --- Gemini ---
    def _chat_gemini(self, user_prompt: str) -> str:
        try:
            if not self._gemini_available:
                return "Gemini non disponible (clé API manquante)."
            # Build concise portfolio context
            lines = []
            for p in sorted(
                self.last_positions, key=lambda x: x.value, reverse=True
            )[:25]:
                lines.append(
                    f"{p.symbol} qty={p.quantity} val={p.value:.2f} "
                    f"pnl={p.pnl_pct or 0:.2f}%"
                )
            context = "\n".join(lines)
            system = (
                "Tu es un assistant financier. Analyse le portefeuille et "
                "réponds brièvement en français. Si l'utilisateur demande un "
                "symbole, donne un résumé basé sur les données disponibles; "
                "ne fabrique pas de données de marché en temps réel."
            )
            model = self._genai.GenerativeModel(self._gemini_model)
            resp = model.generate_content(
                [
                    {"role": "user", "parts": [system]},
                    {
                        "role": "user",
                        "parts": [
                            (
                                f"Portefeuille:\n{context}\n\nQuestion: "
                                f"{user_prompt}"
                            )
                        ],
                    },
                ]
            )
            if hasattr(resp, 'text') and resp.text:
                return resp.text.strip()
            return "(Gemini) Réponse vide."
        except Exception as e:  # noqa
            return f"(Gemini erreur) {e}"

    # --- Ollama ---
    def _ensure_ollama_available(self) -> bool:
        """Lazy-check availability of local Ollama server.

        We try only once per session (unless forced) to avoid UI latency.
        """
        if not self._ollama_enabled or not HAS_REQUESTS:
            return False
        if self._ollama_available_checked:
            return self._ollama_available
        self._ollama_available_checked = True
        try:
            # Quick /api/tags call (cheaper than generate) to see if server responds
            r = requests.get(f"{self._ollama_endpoint}/api/tags", timeout=1.5)
            if r.status_code == 200:
                self._ollama_available = True
        except Exception:
            self._ollama_available = False
        return self._ollama_available

    def _build_portfolio_context(self, max_symbols: int = 25) -> str:
        lines = []
        for p in sorted(self.last_positions, key=lambda x: x.value, reverse=True)[:max_symbols]:
            pnl = f"{p.pnl_pct:.2f}%" if p.pnl_pct is not None else "NA"
            lines.append(
                f"{p.symbol} qty={p.quantity} val={p.value:.2f} pnl={pnl} curr={p.currency or ''}"
            )
        return "\n".join(lines) or "(aucune position)"

    def _find_symbols_in_text(self, text: str) -> List[str]:
        if not self.last_positions:
            return []
        text_up = text.upper()
        # Build regex to match whole-word or non-alnum-bounded symbols to avoid partial matches inside common words
        # Allow letters/numbers and common ticker separators (.-_)
        symbols = [p.symbol.upper() for p in self.last_positions if p.symbol]
        found = []
        for s in symbols:
            try:
                if not s:
                    continue
                # word boundary for alnum/underscore; also match when surrounded by start/end or non-alnum
                pattern = rf"(?<![A-Z0-9_.-]){re.escape(s)}(?![A-Z0-9_.-])"
                if re.search(pattern, text_up):
                    found.append(s)
            except Exception:
                continue
        # Deduplicate but keep order
        seen = set()
        uniq = []
        for s in found:
            if s not in seen:
                uniq.append(s)
                seen.add(s)
        return uniq[:3]

    def _chat_local_natural(self, prompt: str) -> str:
        """Heuristic, wallet-aware French response without LLM."""
        m = self._last_metrics or self._compute_metrics()
        npos = m.get('n_positions', 0)
        cash = m.get('cash_ratio', 0.0)
        hhi_n = m.get('hhi_normalized', 0.0)
        div_lbl = m.get('diversification_label', 'N/A')
        top_share = m.get('top_share', 0.0)
        total_val = sum(p.value for p in self.last_positions)
        top_positions = sorted(self.last_positions, key=lambda x: x.value, reverse=True)[:5]
        top_lines = []
        for p in top_positions:
            pnl_s = f" ({p.pnl_pct:.1f}%)" if p.pnl_pct is not None else ""
            top_lines.append(f"{p.symbol} {p.value:,.0f}{pnl_s}")

        pl = prompt.lower().strip()

        # Small talk and generic conversation
        greetings = {"salut", "bonjour", "bonsoir", "hello", "hey", "yo", "coucou"}
        pleasantries = {"merci", "thanks", "ok", "d'accord", "dac", "super", "cool"}
        if not pl or pl in greetings:
            return (
                "Bonjour! Je suis votre assistant financier. "
                "Posez-moi une question sur votre portefeuille (ex: 'resume', 'risques', 'top', 'AAPL') ou tapez 'aide'."
            )
        if pl in pleasantries or pl.endswith("merci"):
            return "Avec plaisir. Souhaitez-vous un résumé, les risques, ou des infos sur un symbole précis?"
        # Symbol-specific ask embedded in text
        sym_asks = self._find_symbols_in_text(prompt)
        if sym_asks:
            snippets = []
            for s in sym_asks[:2]:
                try:
                    snippets.append(self._get_symbol_info(s))
                except Exception:
                    pass
            if snippets:
                return "\n\n".join(snippets)

        if any(k in pl for k in ["perf", "pnl", "gain", "perte", "comment ça va", "comment ca va", "comment va"]):
            best = None
            worst = None
            have_pct = [p for p in self.last_positions if p.pnl_pct is not None]
            if have_pct:
                best = max(have_pct, key=lambda x: x.pnl_pct)
                worst = min(have_pct, key=lambda x: x.pnl_pct)
            head = f"Valeur ~ {total_val:,.0f}. #Positions: {npos}. "
            tail = []
            if best:
                tail.append(f"Meilleure: {best.symbol} {best.pnl_pct:.1f}%")
            if worst:
                tail.append(f"Moins bonne: {worst.symbol} {worst.pnl_pct:.1f}%")
            return head + " | ".join(tail) if tail else head + "(pas de PnL disponible)"

        if "risque" in pl or "concentr" in pl:
            return (
                f"Risque de concentration: part max {top_share:.1f}%. "
                f"Indice HHI normalisé {hhi_n:.3f} ({div_lbl})."
            )

        if "diversif" in pl:
            return f"Diversification: HHI_norm {hhi_n:.3f} ({div_lbl}). Top position {top_share:.1f}% sur {npos} positions."

        if "cash" in pl or "liquid" in pl or "trésorerie" in pl or "tresorerie" in pl:
            return f"Trésorerie ~ {cash:.1f}% ; Investi ~ {100 - cash:.1f}%. Valeur totale ~ {total_val:,.0f}."

        if "allocation" in pl or "répartition" in pl or "repartition" in pl:
            return f"Allocation actuelle: Cash {cash:.1f}% vs Actifs {100 - cash:.1f}%. Top: {', '.join(top_lines[:3])}."

        # Default: guidance instead of forcing a portfolio analysis
        return (
            "Je peux vous donner un résumé ('resume'), les 'risques', la 'diversification', "
            "l' 'allocation', ou des infos sur un symbole présent dans votre portefeuille (ex: AAPL). "
            "Tapez 'aide' pour la liste. Ajoutez 'signal AAPL' ou 'backtest AAPL' pour l'analyse technique."
        )

    # --- Technicals & backtesting helpers ---
    def _sma_signal(self, symbol: str, fast: int = 5, slow: int = 20):
        if not self.api_manager:
            return "Données de marché indisponibles."
        try:
            data = self.api_manager.get_time_series(symbol, interval='1day', outputsize='compact') or {}
            # Find the time series dict regardless of exact key
            series = None
            for k, v in data.items():
                if 'time series' in k.lower():
                    series = v
                    break
            if not series:
                return f"Séries indisponibles pour {symbol}."
            # Extract closes in chronological order
            items = sorted(series.items())
            closes = []
            for _dt, row in items:
                try:
                    c = float(row.get('4. close') or row.get('close') or 0)
                except Exception:
                    c = 0.0
                closes.append(c)
            if len(closes) < slow + 2:
                return f"Historique insuffisant pour {symbol}."
            
            def sma(arr, w):
                out = []
                acc = 0.0
                for i, v in enumerate(arr):
                    acc += v
                    if i >= w:
                        acc -= arr[i - w]
                    if i >= w - 1:
                        out.append(acc / w)
                return out
            sma_fast = sma(closes, fast)
            sma_slow = sma(closes, slow)
            # Align ends
            # Last comparable values
            r5 = sma_fast[-1]
            r20 = sma_slow[-1]
            prev5 = sma_fast[-2]
            prev20 = sma_slow[-2]
            signal = 'HOLD'
            if prev5 <= prev20 and r5 > r20:
                signal = 'BUY'
            elif prev5 >= prev20 and r5 < r20:
                signal = 'SELL'
            return {'signal': signal, 'r5': r5, 'r20': r20}
        except Exception as e:
            return f"Erreur technique {symbol}: {e}"

    def _backtest_sma(self, symbol: str, fast: int = 5, slow: int = 20):
        """Simple daily SMA crossover backtest with no fees/slippage.
        Returns dict with stats or string error.
        """
        if not self.api_manager:
            return "Données de marché indisponibles."
        try:
            data = self.api_manager.get_time_series(symbol, interval='1day', outputsize='compact') or {}
            series = None
            for k, v in data.items():
                if 'time series' in k.lower():
                    series = v
                    break
            if not series:
                return f"Séries indisponibles pour {symbol}."
            items = sorted(series.items())
            closes = []
            for _dt, row in items:
                try:
                    c = float(row.get('4. close') or row.get('close') or 0)
                except Exception:
                    c = 0.0
                closes.append(c)
            if len(closes) < slow + 2:
                return f"Historique insuffisant pour {symbol}."
            # Compute SMA arrays
            
            def sma(arr, w):
                out = []
                acc = 0.0
                for i, v in enumerate(arr):
                    acc += v
                    if i >= w:
                        acc -= arr[i - w]
                    if i >= w - 1:
                        out.append(acc / w)
                return out
            sma_fast = sma(closes, fast)
            sma_slow = sma(closes, slow)
            # Build positions: 1 if fast>slow else 0; use next-day open/close proxy with close-to-close trading
            pos = []
            for i in range(len(closes)):
                idx_fast = i - (fast - 1)
                idx_slow = i - (slow - 1)
                if idx_fast < 0 or idx_slow < 0:
                    pos.append(0)
                    continue
                f = sma_fast[idx_fast]
                s = sma_slow[idx_slow]
                pos.append(1 if f > s else 0)
            # Daily returns
            rets = [0.0]
            for i in range(1, len(closes)):
                if closes[i-1] <= 0:
                    rets.append(0.0)
                else:
                    rets.append((closes[i] / closes[i-1]) - 1.0)
            strat_rets = [p * r for p, r in zip(pos, rets)]
            # Equity curves
            
            def cum_return(rs):
                acc = 1.0
                for r in rs:
                    acc *= (1.0 + r)
                return (acc - 1.0) * 100.0
            bh_ret = cum_return(rets)
            strat_ret = cum_return(strat_rets)
            # CAGR approximation (assume ~252 trading days/year)
            years = max(1e-9, len(rets) / 252.0)
            cagr = (1.0 + strat_ret/100.0) ** (1.0/years) - 1.0
            # Max drawdown of strategy
            eq = []
            acc = 1.0
            for r in strat_rets:
                acc *= (1.0 + r)
                eq.append(acc)
            peak = 1.0
            max_dd = 0.0
            for v in eq:
                peak = max(peak, v)
                dd = (v/peak - 1.0) * 100.0
                if dd < max_dd:
                    max_dd = dd
            last_sig = self._sma_signal(symbol, fast=fast, slow=slow)
            sig = last_sig.get('signal') if isinstance(last_sig, dict) else 'HOLD'
            # Estimate trades by counting position changes
            trades = 0
            prev = 0
            for p in pos:
                if p != prev:
                    trades += 1
                    prev = p
            return {
                'bh_return': bh_ret,
                'strat_return': strat_ret,
                'cagr': cagr * 100.0,
                'max_dd': max_dd,
                'trades': trades // 2 if trades > 0 else 0,
                'last_signal': sig,
            }
        except Exception as e:
            return f"Erreur backtest {symbol}: {e}"

    def _sma_signal_cached(self, symbol: str, fast: int = 5, slow: int = 20) -> Any:
        """Cached wrapper around _sma_signal to limit API calls."""
        now = time.time()
        ent = self._tech_cache.get(symbol)
        if ent and (now - ent[0]) < self._tech_ttl_sec:
            return ent[1]
        res = self._sma_signal(symbol, fast=fast, slow=slow)
        if isinstance(res, dict):
            self._tech_cache[symbol] = (now, res)
        return res

    def _build_recommendations(self, code: str, meta: Dict[str, Any]) -> Dict[str, Any]:
        """Construit des recommandations indicatives (quantité, raison, SL/TP, horizon).
        Ceci n'est pas un conseil d'investissement. Heuristiques simples.
        """
        total = sum(p.value for p in self.last_positions) or 0.0
        cash_total = sum(p.value for p in self.last_positions if p.symbol in ('CAD', 'USD'))
        out: Dict[str, Any] = {}

        def clamp_qty(desired_abs: float, max_pct: float = 0.05) -> Tuple[float, float]:
            if total <= 0:
                return (0.0, 0.0)
            cap_abs = total * max_pct
            q = max(0.0, min(desired_abs, cap_abs))
            return (q, (q / total) * 100.0 if total > 0 else 0.0)

        code_u = (code or '').upper()
        sym = (meta or {}).get('symbol')

        def pos_of(symbol: Optional[str]) -> Optional[Position]:
            if not symbol:
                return None
            for p in self.last_positions:
                if (p.symbol or '').upper() == str(symbol).upper():
                    return p
            return None

        if code_u == 'TECH_BUY':
            desired = cash_total * 0.25  # 25% du cash disponible
            qty_abs, qty_pct = clamp_qty(desired, max_pct=0.05)  # cap à 5% du PF
            out.update({
                'qty_abs': qty_abs,
                'qty_pct': qty_pct,
                'reason': 'Croisement haussier SMA(5) > SMA(20).',
                'forecast': 'Poursuite haussière si volumes confirment.',
                'horizon': '1 à 4 semaines',
                'stop_loss': 'Sous SMA20 ou ~-5% du prix d’entrée',
                'take_profit': '~+8 à +12% ou résistance récente',
            })
        elif code_u == 'TECH_SELL':
            p = pos_of(sym)
            val = p.value if p else 0.0
            qty_abs = val * 0.5  # alléger ~50%
            qty_pct = (qty_abs / total) * 100.0 if total > 0 else None
            out.update({
                'qty_abs': qty_abs if total > 0 else None,
                'qty_pct': qty_pct,
                'reason': 'Croisement baissier SMA(5) < SMA(20).',
                'forecast': 'Risque de correction court terme.',
                'horizon': '1 à 4 semaines',
                'stop_loss': 'Si maintien: stop serré au-dessus de SMA20 (~+3%)',
                'take_profit': '—',
            })
        elif code_u == 'PNL_RUN':
            p = pos_of(meta.get('symbol'))
            val = p.value if p else 0.0
            qty_abs = val * 0.25
            qty_pct = (qty_abs / total) * 100.0 if total > 0 else None
            out.update({
                'qty_abs': qty_abs if total > 0 else None,
                'qty_pct': qty_pct,
                'reason': 'Gain marqué atteint.',
                'forecast': 'Consolidation possible après rallye.',
                'horizon': 'Jours à semaines',
                'stop_loss': 'Stop suiveur sous plus bas 10 jours ou ~-5%.',
                'take_profit': 'Prise partielle +10 à +20% cumulée.',
            })
        elif code_u in {'PNL_DOWN', 'PNL_DROP'}:
            p = pos_of(meta.get('symbol'))
            val = p.value if p else 0.0
            qty_abs = val * (0.25 if code_u == 'PNL_DOWN' else 0.4)
            qty_pct = (qty_abs / total) * 100.0 if total > 0 else None
            out.update({
                'qty_abs': qty_abs if total > 0 else None,
                'qty_pct': qty_pct,
                'reason': 'Baisse notable du PnL.',
                'forecast': 'Poursuite baissière si supports cèdent.',
                'horizon': 'Jours à semaines',
                'stop_loss': f"Stop à ~{- self.pnl_warn_pct if code_u == 'PNL_DOWN' else - self.pnl_alert_pct:.0f}% du prix",
                'take_profit': '—',
            })
        elif code_u == 'CONCENTRATION':
            share = float(meta.get('share') or 0.0)
            p = pos_of(meta.get('symbol'))
            delta = 0.0
            if total > 0 and p:
                target = 0.20
                if share > target:
                    delta = (share - target) * total
            out.update({
                'qty_abs': delta if delta > 0 else None,
                'qty_pct': (delta / total) * 100.0 if delta > 0 and total > 0 else None,
                'reason': 'Poids de position au-dessus d’un seuil prudent.',
                'forecast': 'Risque idiosyncratique accru.',
                'horizon': 'Structurel',
                'stop_loss': '—',
                'take_profit': 'Allègement progressif vers 20% du PF.',
            })
        elif code_u == 'CASH_HIGH':
            deploy = max(0.0, cash_total - total * 0.50)
            qty_abs, qty_pct = clamp_qty(deploy, max_pct=0.10)
            out.update({
                'qty_abs': qty_abs,
                'qty_pct': qty_pct,
                'reason': 'Trésorerie surdimensionnée.',
                'forecast': 'Déploiement graduel pour réduire le cash drag.',
                'horizon': 'Semaines à mois',
                'stop_loss': '—',
                'take_profit': '—',
            })
        elif code_u == 'CASH_LOW':
            out.update({
                'qty_abs': None,
                'qty_pct': None,
                'reason': 'Marge de manœuvre réduite (cash faible).',
                'forecast': 'Limiter nouvelles entrées; privilégier la flexibilité.',
                'horizon': 'Court terme',
                'stop_loss': 'Prioriser stops plus serrés (~-3 à -5%).',
                'take_profit': '—',
            })
        elif code_u == 'LOW_DIVERSIFICATION':
            out.update({
                'qty_abs': None,
                'qty_pct': None,
                'reason': 'Diversification faible (HHI élevé).',
                'forecast': 'Risque de volatilité spécifique.',
                'horizon': 'Structurel',
                'stop_loss': '—',
                'take_profit': '—',
            })
        return out

    def _chat_ollama(self, user_prompt: str) -> Optional[str]:
        """Query local Ollama model. Returns None if failure (so caller can fallback)."""
        if not self._ollama_available and not self._ensure_ollama_available():
            return None
        try:
            if not HAS_REQUESTS:
                return None
            payload: Dict[str, Any] = {
                "model": self._ollama_model,
                "prompt": user_prompt,
                "stream": False,
                # Could add: temperature, top_p, etc.
            }
            r = requests.post(
                f"{self._ollama_endpoint}/api/generate",
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=45,
            )
            if r.status_code != 200:
                return f"(Ollama erreur HTTP {r.status_code})"
            data = r.json()
            txt = data.get('response') or data.get('message') or ''
            if not txt:
                return "(Ollama réponse vide)"
            return txt.strip()
        except Exception as e:  # noqa
            # Mark unavailable so we do not retry each message
            self._ollama_available = False
            return f"(Ollama erreur) {e}"

    # --- Internal ---
    def _emit(self, level: str, code: str, message: str, **meta):
        # Enrichit le message avec explications simples selon le code
        explanations = {
            'CONCENTRATION': "Risque: une seule position représente une part élevée du portefeuille (diversifier).",
            'PNL_DROP': "Alerte: perte importante - vérifier news / niveaux de support avant action.",
            'PNL_DOWN': "Surveillance: perte modérée - envisager stop ou réduction si tendance continue.",
            'PNL_RUN': "Gain significatif - penser à sécuriser une partie (take profit partiel).",
            'CASH_LOW': "Trésorerie très basse - peu de marge pour saisir de nouvelles opportunités.",
            'CASH_HIGH': "Beaucoup de cash - capital oisif, évaluer allocation graduelle.",
            'LOW_DIVERSIFICATION': "Nombre de positions / répartition insuffisante - augmenter diversification graduelle."
        }
        if code in explanations and explanations[code] not in message:
            message = f"{message} | {explanations[code]}"
        # Ajoute des recommandations standardisées (indicatif, non-conseil) si non data-only
        if not self.data_only:
            try:
                rec = self._build_recommendations(code, meta)
                if isinstance(rec, dict) and rec:
                    meta.update(rec)
            except Exception:
                pass
        sig = Signal(time.time(), level, code, message, meta)
        self.history.append(sig)

        # Send notification via Telegram if enabled
        allowed = True
        # First, apply local gating for technical alerts
        try:
            if code.startswith('TECH_') and not self.allow_technical_alerts:
                allowed = False
        except Exception:
            pass
        try:
            if callable(self.notifications_allowed):
                allowed = bool(self.notifications_allowed()) and allowed
        except Exception:
            allowed = True
        if self.enable_notifications and self.api_manager and allowed:
            try:
                self.api_manager.notify_alert(level, code, message)
            except Exception as e:
                print(f"Notification error: {e}")

    def _generate_signals(self):
        if not self.last_positions:
            return
        total = sum(p.value for p in self.last_positions) or 1.0
        # Concentration
        for p in self.last_positions:
            share = p.value / total
            if share > 0.25:
                meta = {
                    'symbol': p.symbol,
                    'share': share,
                    'position_value': p.value,
                    'position_share': share,
                    'pnl_pct': p.pnl_pct,
                }
                self._emit(
                    'WARN',
                    'CONCENTRATION',
                    f"Concentration élevée: {p.symbol} {share*100:.1f}%",
                    **meta,
                )
        # PnL thresholds
        for p in self.last_positions:
            if p.pnl_pct is None:
                continue
            if p.pnl_pct <= -self.pnl_alert_pct:
                meta = {
                    'symbol': p.symbol,
                    'position_value': p.value,
                    'position_share': (p.value / total) if total else None,
                    'pnl_pct': p.pnl_pct,
                }
                self._emit(
                    'ALERT',
                    'PNL_DROP',
                    f"{p.symbol} perte {p.pnl_pct:.1f}%",
                    **meta,
                )
            elif p.pnl_pct <= -self.pnl_warn_pct:
                meta = {
                    'symbol': p.symbol,
                    'position_value': p.value,
                    'position_share': (p.value / total) if total else None,
                    'pnl_pct': p.pnl_pct,
                }
                self._emit(
                    'WARN',
                    'PNL_DOWN',
                    f"{p.symbol} -{p.pnl_pct:.1f}%",
                    **meta,
                )
            elif p.pnl_pct >= self.pnl_alert_pct:
                meta = {
                    'symbol': p.symbol,
                    'position_value': p.value,
                    'position_share': (p.value / total) if total else None,
                    'pnl_pct': p.pnl_pct,
                }
                self._emit(
                    'INFO',
                    'PNL_RUN',
                    f"{p.symbol} +{p.pnl_pct:.1f}%",
                    **meta,
                )
        # Cash ratio
        cash_total = sum(
            p.value for p in self.last_positions if p.symbol in ('CAD', 'USD')
        )
        cash_ratio = cash_total / total
        if cash_ratio < 0.02:
            self._emit(
                'WARN',
                'CASH_LOW',
                f"Trésorerie faible {cash_ratio*100:.1f}%",
                cash_ratio=cash_ratio,
                cash_total=cash_total,
                total_value=total,
            )
        elif cash_ratio > 0.60:
            self._emit(
                'INFO',
                'CASH_HIGH',
                f"Trésorerie élevée {cash_ratio*100:.1f}%",
                cash_ratio=cash_ratio,
                cash_total=cash_total,
                total_value=total,
            )
        # Diversification (Herfindahl index)
        m = self._last_metrics or self._compute_metrics()
        if m.get('n_positions', 0) > 0 and m.get('hhi_normalized', 0) > 0.30:
            self._emit(
                'WARN',
                'LOW_DIVERSIFICATION',
                f"HHI norm {m.get('hhi_normalized'):.3f} (top {m.get('top_share'):.1f}%)",
                hhi=m.get('hhi_normalized'),
                top_share=m.get('top_share'),
                n_positions=m.get('n_positions'),
            )
        # Technical BUY/SELL alerts (rate-limited) for top holdings
        top_non_cash = [p for p in sorted(self.last_positions, key=lambda x: x.value, reverse=True) if p.symbol not in ('CAD', 'USD')][:5]
        now_ts = time.time()
        for p in top_non_cash:
            last_emit = self._last_tech_emit.get(p.symbol, 0)
            if now_ts - last_emit < self._tech_emit_ttl_sec:
                continue
            sig = self._sma_signal_cached(p.symbol)
            if isinstance(sig, dict):
                s = sig.get('signal')
                if s == 'BUY':
                    meta = {'symbol': p.symbol}
                    try:
                        meta.update(self._enrich_symbol_metrics(p.symbol))
                    except Exception:
                        pass
                    self._emit('INFO', 'TECH_BUY', f"SMA(5/20) BUY {p.symbol}", **meta)
                    self._last_tech_emit[p.symbol] = now_ts
                elif s == 'SELL':
                    meta = {'symbol': p.symbol}
                    try:
                        meta.update(self._enrich_symbol_metrics(p.symbol))
                    except Exception:
                        pass
                    self._emit('WARN', 'TECH_SELL', f"SMA(5/20) SELL {p.symbol}", **meta)
                    self._last_tech_emit[p.symbol] = now_ts

    # --- Portfolio insights & market context ---
    def _insights(self) -> str:
        m = self._last_metrics or self._compute_metrics()
        total_val = sum(p.value for p in self.last_positions)
        best = None
        worst = None
        have_pct = [p for p in self.last_positions if p.pnl_pct is not None]
        if have_pct:
            best = max(have_pct, key=lambda x: x.pnl_pct)
            worst = min(have_pct, key=lambda x: x.pnl_pct)
        parts = [
            f"Valeur ~ {total_val:,.0f} | Cash {m.get('cash_ratio'):.1f}%",
            f"Diversif: HHI_norm {m.get('hhi_normalized'):.3f} ({m.get('diversification_label')})",
        ]
        if best:
            parts.append(f"Meilleure: {best.symbol} {best.pnl_pct:.1f}%")
        if worst:
            parts.append(f"Moins bonne: {worst.symbol} {worst.pnl_pct:.1f}%")
        # Recent internal signals
        sigs = self.get_signals()[-5:]
        if sigs:
            parts.append("Signaux: " + ", ".join(f"{s.code}" for s in sigs))
        return " | ".join(parts)

    # Public wrapper for external callers (e.g., Telegram command)
    def insights(self) -> str:
        # Prefer enhanced output when available
        try:
            if getattr(self, '_enhanced_ai', None) is not None:
                positions = [
                    {
                        'symbol': p.symbol,
                        'name': p.name,
                        'quantity': p.quantity,
                        'value': p.value,
                        'currency': p.currency,
                        'pnlAbs': p.pnl_abs,
                        'pnlPct': p.pnl_pct,
                    }
                    for p in self.last_positions
                ]
                res = self._enhanced_ai.analyze_and_suggest(positions, lang='fr')
                if isinstance(res, dict):
                    a = (res.get('analytics') or '').strip()
                    d = (res.get('decision') or '').strip()
                    return (a + "\n\n" + d).strip() or self._insights()
        except Exception:
            pass
        return self._insights()

    def _market_movers(self, top_n: int = 10) -> str:
        if not self.api_manager:
            return "Données externes indisponibles."
        try:
            data = self.api_manager.get_market_movers_ca(top_n=top_n) or {}

            def fmt(lst, label):
                if not lst:
                    return f"{label}: n/a"
                items = [f"{x.get('symbol')} {x.get('change_pct', 0):+.1f}%" for x in lst[:5]]
                return f"{label}: " + ", ".join(items)
            return "\n".join([
                fmt(data.get('gainers') or [], 'Gagnants'),
                fmt(data.get('losers') or [], 'Perdants'),
                fmt(data.get('actives') or [], 'Actifs'),
                fmt(data.get('opportunities') or [], 'Opportunités'),
            ])
        except Exception as e:
            return f"(movers) {e}"

    def _market_opportunities(self, top_n: int = 10) -> str:
        if not self.api_manager:
            return "Données externes indisponibles."
        try:
            data = self.api_manager.get_market_movers_ca(top_n=top_n) or {}
            opps = data.get('opportunities') or []
            if not opps:
                return "Aucune opportunité détectée (critères: baisses marquées, volumes élevés)."
            lines = ["Opportunités potentielles:"]
            for x in opps[:8]:
                sym = x.get('symbol')
                chg = x.get('change_pct', 0)
                vol = x.get('volume', 0)
                lines.append(f" - {sym}: {chg:+.1f}% vol={vol}")
            return "\n".join(lines)
        except Exception as e:
            return f"(opportunités) {e}"

    def _rebalance_suggestion(self) -> str:
        m = self._last_metrics or self._compute_metrics()
        total = sum(p.value for p in self.last_positions) or 1.0
        if total <= 0 or not self.last_positions:
            return "Portefeuille vide."
        top = sorted(self.last_positions, key=lambda x: x.value, reverse=True)
        top_share = m.get('top_share', 0.0)
        cash = m.get('cash_ratio', 0.0)
        suggestions = []
        if top_share > 25.0 and len(top) > 1:
            target = 20.0
            delta = (top_share - target) / 100.0 * total
            suggestions.append(
                f"Trim {top[0].symbol} ~{delta:,.0f} (de {top_share:.1f}% vers {target:.0f}%)"
            )
        if cash > 60.0 and len(top) > 2:
            # Allocate a small portion into next top 2 equities
            deploy = (cash - 50.0) / 100.0 * total
            if deploy > 0:
                half = deploy / 2
                suggestions.append(
                    f"Déployer ~{deploy:,.0f} en 2 étapes: {top[1].symbol} ~{half:,.0f}, {top[2].symbol} ~{half:,.0f}"
                )
        if not suggestions:
            return "Rééquilibrage: rien d’évident; allocation cohérente."
        return "; ".join(suggestions) + " (indicatif, non-conseil)."

    def _health_check(self) -> str:
        m = self._last_metrics or self._compute_metrics()
        checks = []
        checks.append(
            f"Cash {'OK' if 5.0 <= m.get('cash_ratio', 0) <= 60.0 else 'ATTN'} ({m.get('cash_ratio', 0):.1f}%)"
        )
        checks.append(
            f"Diversif {'OK' if m.get('hhi_normalized', 0) < 0.30 else 'ATTN'} (HHI {m.get('hhi_normalized', 0):.3f})"
        )
        checks.append(
            f"Taille positions {'OK' if m.get('top_share', 0) <= 25.0 else 'ATTN'} (Top {m.get('top_share', 0):.1f}%)"
        )
        return " | ".join(checks)

    def _risk_summary(self) -> str:
        if not self.last_positions:
            return "Aucune position."
        total = sum(p.value for p in self.last_positions) or 1.0
        lines = []
        for p in sorted(
            self.last_positions, key=lambda x: x.value, reverse=True
        )[:10]:
            share = p.value / total * 100
            lines.append(f"{p.symbol:<8} {share:5.1f}% {p.value:>12,.2f}")
        m = self._last_metrics or self._compute_metrics()
        lines.append(
            f"HHI norm: {m.get('hhi_normalized'):.3f} | Diversification: {m.get('diversification_label')}"
        )
        return '\n'.join(lines)

    def _get_symbol_info(self, symbol: str) -> str:
        """Get enhanced info for a specific symbol using external APIs."""
        if not self.api_manager:
            # Fallback to portfolio data only
            for p in self.last_positions:
                if p.symbol.upper() == symbol:
                    pnl_str = f" ({p.pnl_pct:.1f}%)" if (p.pnl_pct is not None) else ""
                    return f"{symbol}: {p.value:,.2f} {p.currency or 'CAD'}{pnl_str}"
            return f"Symbole {symbol} non trouvé dans le portefeuille."

        try:
            # Get enhanced data from external APIs
            enhanced = self.api_manager.get_enhanced_quote(symbol)

            result_lines = [f"📊 {symbol} - Analyse complète:"]

            # Portfolio position if exists
            portfolio_pos = None
            for p in self.last_positions:
                if p.symbol.upper() == symbol:
                    portfolio_pos = p
                    break

            if portfolio_pos:
                pnl_str = f" ({portfolio_pos.pnl_pct:.1f}%)" if (portfolio_pos.pnl_pct is not None) else ""
                result_lines.append(f"📈 Position: {portfolio_pos.value:,.2f} {portfolio_pos.currency or 'CAD'}{pnl_str}")

            # Market quote
            quote = enhanced.get('quote')
            if quote:
                price = quote.get('05. price', 'N/A')
                change = quote.get('09. change', 'N/A')
                change_pct = quote.get('10. change percent', 'N/A')
                result_lines.append(f"💰 Prix: {price} ({change}, {change_pct})")

            # News headlines
            news = enhanced.get('news', [])
            if news:
                result_lines.append("📰 Actualités récentes:")
                for article in news[:2]:
                    title = article.get('title', '')[:50] + '...' if len(article.get('title', '')) > 50 else article.get('title', '')
                    result_lines.append(f"  • {title}")

            # Technical indicator (RSI)
            technical = enhanced.get('technical')
            if technical and 'Technical Analysis: RSI' in technical:
                rsi_data = technical['Technical Analysis: RSI']
                if rsi_data:
                    latest_date = max(rsi_data.keys()) if rsi_data else None
                    if latest_date:
                        rsi_value = rsi_data[latest_date].get('RSI', 'N/A')
                        result_lines.append(f"📊 RSI: {rsi_value}")

            return '\n'.join(result_lines)

        except Exception as e:
            return f"Erreur lors de la récupération des données pour {symbol}: {e}"

    # Convenience for UI/tests: return last N signals as dicts
    def get_signals_dict(self, max_n: int = 50) -> List[Dict[str, Any]]:
        sigs = self.get_signals()[-max_n:]
        out: List[Dict[str, Any]] = []
        for s in sigs:
            out.append({
                'ts': s.ts,
                'level': s.level,
                'code': s.code,
                'message': s.message,
                'meta': s.meta,
            })
        return out


__all__ = ["AIAgent", "Signal", "Position"]
