"""Enhanced AI system: analytics, decision-making, context, communication, safety.

This module is additive and does not change existing behavior unless explicitly
enabled by calling code. It can be wired into `AIAgent` or used standalone.

Main components:
- ContextMemory: lightweight conversation/task memory with summarization
- AnalyticsEngine: portfolio metrics, technical/health summaries
- DecisionEngine: rule/policy-based suggestions with safety-aware constraints
- Communicator: clear, structured, bilingual formatting (FR/EN-ready)
- Safety: text moderation heuristics, rate limiting, deterministic mode

No network calls are performed directly; optional API adapter can be provided.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import time
import hashlib
import threading


# ------------------------- Safety Layer ------------------------------------

class Safety:
    """Basic safety guardrails for text and operations.

    - moderate_text: block disallowed content via heuristics
    - rate_limit: prevent abuse by key
    - deterministic: optional seeded hashing to stabilize choices
    """

    def __init__(self, *, max_per_minute: int = 60, deterministic: bool = False):
        self.max_per_minute = max(1, int(max_per_minute))
        self._buckets: Dict[str, List[float]] = {}
        self._lock = threading.Lock()
        self._deterministic = bool(deterministic)

    def moderate_text(self, text: str) -> bool:
        """Return True if text is safe enough to show (after masking).
        Strong profanity is blocked; PII is masked via mask_text().
        """
        if not text:
            return True
        t = text.lower()
        bad = ["fuck", "shit", "bitch", "connard", "salope"]
        if any(w in t for w in bad):
            return False
        return True

    def mask_text(self, text: str) -> str:
        """Lightweight anonymization: mask emails and long digit sequences.
        Keeps the message usable while removing obvious PII.
        """
        try:
            import re as _re
            s = text or ""
            # Mask emails
            s = _re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[email masqué]", s)
            # Mask long digit sequences (phone-like), keep last 2 digits.
            # Accept optional separators between digits; require at least ~8 digits total.
            def _mask_digits(m):
                val = m.group(0)
                digits_only = _re.sub(r"\D", "", val)
                if len(digits_only) <= 6:
                    return val
                return "[numéro masqué]" + digits_only[-2:]

            s = _re.sub(r"\b(?:\d[\s\-.]?){6,}\d\b", _mask_digits, s)
            return s
        except Exception:
            return text

    def _now(self) -> float:
        return time.time()

    def rate_limit(self, key: str) -> bool:
        """Token-bucket like limiter: allow if under quota in last 60s."""
        now = self._now()
        with self._lock:
            arr = self._buckets.setdefault(key, [])
            # drop old
            arr[:] = [t for t in arr if now - t < 60.0]
            if len(arr) >= self.max_per_minute:
                return False
            arr.append(now)
            return True

    def pick(self, options: List[str], *, salt: str = "") -> Optional[str]:
        """Deterministic choice if enabled; otherwise first non-empty option."""
        opts = [o for o in options if o]
        if not opts:
            return None
        if not self._deterministic:
            return opts[0]
        # stable index via hash
        h = hashlib.sha256(("|".join(opts) + "#" + salt).encode("utf-8")).hexdigest()
        idx = int(h[:8], 16) % len(opts)
        return opts[idx]


# ------------------------- Context Memory ----------------------------------

@dataclass
class MemoryItem:
    role: str  # user|assistant|system|event
    text: str
    ts: float = field(default_factory=time.time)


class ContextMemory:
    """Simple rolling memory with summarization and anonymization hooks."""

    def __init__(self, max_items: int = 32):
        self.max_items = max(4, int(max_items))
        self._items: List[MemoryItem] = []

    def add(self, role: str, text: str) -> None:
        if not text:
            return
        self._items.append(MemoryItem(role=role, text=text))
        if len(self._items) > self.max_items:
            # Drop oldest half to maintain context freshness
            self._items = self._items[len(self._items) // 2 :]

    def clear(self) -> None:
        self._items.clear()

    def summarize(self, *, lang: str = "fr") -> str:
        """Return short summary of conversation/context so far."""
        if not self._items:
            return ""
        # Heuristic: keep last 6 messages; prefix older count
        older = max(0, len(self._items) - 6)
        tail = self._items[-6:]
        parts = []
        if older:
            parts.append(f"…{older} msg plus anciens… ")
        for it in tail:
            who = {"user": "U", "assistant": "A", "system": "S", "event": "E"}.get(it.role, "?")
            parts.append(f"[{who}] {it.text.strip()}")
        out = " | ".join(parts)
        return out if lang != "en" else out  # trivial bilingual stub


# ------------------------- Analytics Engine --------------------------------

def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


class AnalyticsEngine:
    """Compute portfolio analytics metrics from positions and optional quotes."""

    def compute_metrics(self, positions: List[Dict[str, Any]], *, cash_symbols: Tuple[str, ...] = ("CAD", "USD")) -> Dict[str, Any]:
        total_value = sum(_safe_float(p.get("value")) for p in positions)
        n_positions = len([p for p in positions if p.get("symbol") not in cash_symbols])
        weights: List[float] = []
        for p in positions:
            sym = str(p.get("symbol") or "").upper()
            if sym in cash_symbols:
                continue
            v = _safe_float(p.get("value"))
            if total_value > 0:
                weights.append(v / total_value)
        hhi = sum(w * w for w in weights) if weights else 0.0
        # Normalize HHI: 1/N to 1 scale -> map to [0,1] (higher worse concentration)
        hhi_norm = hhi  # simple form; downstream labels provide interpretation

        cash_value = sum(_safe_float(p.get("value")) for p in positions if str(p.get("symbol") or "").upper() in cash_symbols)
        cash_ratio = (cash_value / total_value * 100.0) if total_value > 0 else 0.0

        top_share = 0.0
        if weights:
            top_share = max(weights) * 100.0

        # Max drawdown heuristic from provided pnl_abs (if any)
        pnl_abs_vals = [_safe_float(p.get("pnlAbs"), 0.0) for p in positions]
        total_pnl_abs = sum(pnl_abs_vals)

        return {
            "total_value": total_value,
            "n_positions": n_positions,
            "hhi": hhi,
            "hhi_normalized": hhi_norm,
            "cash_ratio": cash_ratio,
            "top_share": top_share,
            "total_pnl_abs": total_pnl_abs,
        }

    def diversification_label(self, hhi_normalized: float) -> str:
        if hhi_normalized <= 0.05:
            return "excellente"
        if hhi_normalized <= 0.10:
            return "bonne"
        if hhi_normalized <= 0.20:
            return "modérée"
        return "faible"


# ------------------------- Decision Engine ---------------------------------

@dataclass
class Decision:
    action: str  # BUY|SELL|HOLD|REBALANCE|INFO
    symbol: Optional[str]
    confidence: float  # 0..1
    rationale: str
    safety_notes: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class DecisionEngine:
    """Rule/policy-based decision engine. No trading side-effects here."""

    def __init__(self, *, safety: Optional[Safety] = None, max_symbol_share_pct: float = 20.0, max_sector_share_pct: float = 40.0):
        self.safety = safety or Safety()
        self.max_symbol_share_pct = float(max_symbol_share_pct)
        self.max_sector_share_pct = float(max_sector_share_pct)

    def suggest(self, positions: List[Dict[str, Any]], *, symbol: Optional[str] = None, metrics: Optional[Dict[str, Any]] = None) -> Decision:
        # Basic policy: if symbol provided and PnL deeply negative -> HOLD/INFO, else BUY small if cash_ratio high.
        chosen_symbol = symbol
        if not chosen_symbol and positions:
            # choose top non-cash by value
            non_cash = [p for p in positions if str(p.get("symbol") or "").upper() not in ("CAD", "USD")]
            non_cash = sorted(non_cash, key=lambda x: _safe_float(x.get("value")), reverse=True)
            chosen_symbol = non_cash[0]["symbol"] if non_cash else None

        # derive metrics if not provided
        if metrics is None:
            metrics = AnalyticsEngine().compute_metrics(positions)
        cr = _safe_float(metrics.get("cash_ratio"), 0.0)
        hhi_n = _safe_float(metrics.get("hhi_normalized"), 0.0)
        diversification = AnalyticsEngine().diversification_label(hhi_n)

        # inspect PnL on chosen symbol
        sym_pnl_pct = None
        if chosen_symbol:
            for p in positions:
                if str(p.get("symbol")).upper() == str(chosen_symbol).upper():
                    sym_pnl_pct = p.get("pnlPct") or p.get("pnl_pct")
                    try:
                        sym_pnl_pct = float(sym_pnl_pct) if sym_pnl_pct is not None else None
                    except Exception:
                        sym_pnl_pct = None
                    break

        safety_notes: List[str] = []
        action = "HOLD"
        conf = 0.55
        rationale_parts = []

        # Technical/RSI enhancements when available on the chosen symbol
        sma5 = sma20 = rsi = None
        pos_value = 0.0
        total_value = _safe_float(metrics.get("total_value"), 0.0)
        sym_sector = None
        for p in positions:
            if chosen_symbol and str(p.get("symbol")).upper() == str(chosen_symbol).upper():
                try:
                    sma5 = _safe_float(p.get("sma5"), None) if p.get("sma5") is not None else None
                    sma20 = _safe_float(p.get("sma20"), None) if p.get("sma20") is not None else None
                    rsi = _safe_float(p.get("rsi"), None) if p.get("rsi") is not None else None
                except Exception:
                    pass
                pos_value = _safe_float(p.get("value"), 0.0)
                sym_sector = p.get("sector")
                break

        # Sector exposure calculation if sector labels provided
        sector_share_pct = None
        if sym_sector:
            try:
                sector_value = sum(_safe_float(pp.get("value"), 0.0) for pp in positions if pp.get("sector") == sym_sector)
                if total_value > 0:
                    sector_share_pct = sector_value / total_value * 100.0
            except Exception:
                sector_share_pct = None

        # Base policy: BUY if lots of cash; HOLD on deep losses
        if cr >= 30.0:
            action = "BUY"
            conf = 0.62
            rationale_parts.append("Cash disponible important (≥30%) pour renforcer.")
        if sym_pnl_pct is not None and sym_pnl_pct <= -15:
            action = "HOLD"
            conf = 0.58
            rationale_parts.append("Perte élevée détectée; éviter l'acharnement.")
        # Technical bias
        if (sma5 is not None and sma20 is not None):
            if sma5 > sma20:
                action = "BUY"
                conf = max(conf, 0.66)
                rationale_parts.append("Biais haussier: SMA5 > SMA20.")
            elif sma5 < sma20:
                action = "SELL"
                conf = max(conf, 0.64)
                rationale_parts.append("Biais baissier: SMA5 < SMA20.")
        if rsi is not None:
            if rsi >= 70:
                rationale_parts.append("RSI élevé (surachat) — prudence.")
                if action == "BUY":
                    action = "HOLD"
                    conf = max(conf, 0.60)
            elif rsi <= 35 and cr >= 15.0:
                rationale_parts.append("RSI bas (survente) — fenêtre de renforcement mesuré.")
                if action != "SELL":
                    action = "BUY"
                    conf = max(conf, 0.65)

        # Risk budgets
        share_pct = (pos_value / total_value * 100.0) if total_value > 0 else None
        if share_pct is not None and share_pct > self.max_symbol_share_pct:
            safety_notes.append(
                f"Poids {share_pct:.1f}% > budget {self.max_symbol_share_pct:.0f}% — envisager réduction."
            )
            action = "SELL" if action != "HOLD" else action
            conf = max(conf, 0.62)
        if sector_share_pct is not None and sector_share_pct > self.max_sector_share_pct:
            safety_notes.append(
                f"Secteur {sym_sector} {sector_share_pct:.1f}% > limite {self.max_sector_share_pct:.0f}% — diversification recommandée."
            )
            if action == "BUY":
                action = "HOLD"
                conf = max(conf, 0.60)

        if diversification in {"faible", "modérée"}:
            safety_notes.append(f"Diversification {diversification}; gérer la concentration.")
        if hhi_n >= 0.20:
            safety_notes.append("Concentration forte mesurée par HHI.")

        if not rationale_parts:
            rationale_parts.append("Aucune alerte majeure; conserver la position.")

        # Safety: rate limit per symbol to avoid spam decisions
        key = f"decision:{chosen_symbol or 'portfolio'}"
        allowed = self.safety.rate_limit(key)
        if not allowed:
            action = "INFO"
            conf = 0.5
            safety_notes.append("Limiteur de débit actif; suggestion non-actionnable.")

        rationale = " ".join(rationale_parts)
        return Decision(action=action, symbol=chosen_symbol, confidence=conf, rationale=rationale, safety_notes=safety_notes, metadata={"cash_ratio": cr, "hhi": hhi_n})


# ------------------------- Communicator ------------------------------------

class Communicator:
    """Format decisions and analytics for clear user-facing text."""

    def __init__(self, *, safety: Optional[Safety] = None):
        self.safety = safety or Safety()

    def format_analytics(self, metrics: Dict[str, Any], *, lang: str = "fr") -> str:
        label = AnalyticsEngine().diversification_label(_safe_float(metrics.get("hhi_normalized"), 0.0))
        msg = (
            f"Valeur: {metrics.get('total_value', 0):,.0f} | #Pos: {int(metrics.get('n_positions', 0))} | "
            f"Cash: {metrics.get('cash_ratio', 0.0):.1f}% | HHI: {metrics.get('hhi_normalized', 0.0):.3f} ({label})"
        )
        return msg

    def format_decision(self, d: Decision, *, context: Optional[str] = None, lang: str = "fr") -> str:
        lines: List[str] = []
        title = {
            "BUY": "Suggestion: Renforcer",
            "SELL": "Suggestion: Réduire",
            "HOLD": "Suggestion: Conserver",
            "REBALANCE": "Suggestion: Rééquilibrer",
            "INFO": "Information",
        }.get(d.action, d.action)
        target = f" sur {d.symbol}" if d.symbol else ""
        lines.append(f"{title}{target}")
        lines.append(f"Confiance: {d.confidence:.2f}")
        if context:
            lines.append(f"Contexte: {context}")
        if d.rationale:
            lines.append(f"Raison: {d.rationale}")
        if d.safety_notes:
            lines.append("Sécurité:")
            for n in d.safety_notes:
                lines.append(f" - {n}")
        out = "\n".join(lines)
        out = self.safety.mask_text(out)
        return out if self.safety.moderate_text(out) else "[Contenu modéré]"


# ------------------------- Facade ------------------------------------------

class EnhancedAI:
    """Convenient facade aggregating all components for easy use."""

    def __init__(self, *, deterministic: bool = False, max_msgs_per_min: int = 120, max_symbol_share_pct: float = 20.0, max_sector_share_pct: float = 40.0):
        self.safety = Safety(max_per_minute=max_msgs_per_min, deterministic=deterministic)
        self.memory = ContextMemory(max_items=32)
        self.analytics = AnalyticsEngine()
        self.decisions = DecisionEngine(safety=self.safety, max_symbol_share_pct=max_symbol_share_pct, max_sector_share_pct=max_sector_share_pct)
        self.comm = Communicator(safety=self.safety)

    def analyze_and_suggest(self, positions: List[Dict[str, Any]], *, focus_symbol: Optional[str] = None, lang: str = "fr") -> Dict[str, str]:
        metrics = self.analytics.compute_metrics(positions)
        ctx = self.memory.summarize(lang=lang)
        dec = self.decisions.suggest(positions, symbol=focus_symbol, metrics=metrics)
        return {
            "analytics": self.comm.format_analytics(metrics, lang=lang),
            "decision": self.comm.format_decision(dec, context=ctx, lang=lang),
        }
