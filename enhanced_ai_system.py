from __future__ import annotations

import re
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any


# ---------------- Safety & Utilities -----------------
class Safety:
    def __init__(self, max_per_minute: int = 60, deterministic: bool = False):
        self.max_per_minute = int(max_per_minute)
        self._rate_state: dict[str, tuple[int, int]] = {}  # key -> (minute_epoch, count)
        self._deterministic = bool(deterministic)

    def moderate_text(self, text: str) -> bool:
        # Very simple moderation: block strong profanity
        t = (text or "").lower()
        if "fuck" in t:
            return False
        return True

    def mask_text(self, text: str) -> str:
        if not text:
            return text
        out = text
        # Mask emails
        out = re.sub(r"[\w\.-]+@[\w\.-]+", "[email masqué]", out)

        # Mask long digit sequences (likely phone numbers), keep last 2 digits
        def _mask_digits(m: re.Match[str]) -> str:
            s = m.group(0)
            if len(s) >= 11:
                return "[numéro masqué]" + s[-2:]
            return s

        out = re.sub(r"\d{11,}", _mask_digits, out)
        return out

    def rate_limit(self, key: str) -> bool:
        try:
            now = int(time.time())
            minute = now // 60
            ts, count = self._rate_state.get(key, (minute, 0))
            if ts != minute:
                self._rate_state[key] = (minute, 1)
                return True
            if count >= self.max_per_minute:
                return False
            self._rate_state[key] = (minute, count + 1)
            return True
        except Exception:
            # Fail-open on errors
            return True


# ---------------- Analytics -----------------
class AnalyticsEngine:
    def compute_metrics(self, positions: Iterable[dict[str, Any]]) -> dict[str, Any]:
        pos = list(positions or [])
        total_value = float(sum(float(p.get("value") or 0.0) for p in pos))

        # Identify cash positions (CAD, USD)
        def is_cash(p: dict[str, Any]) -> bool:
            return str(p.get("symbol") or "").upper() in {"CAD", "USD"}

        equity_positions = [p for p in pos if not is_cash(p)]
        n_positions = len(equity_positions)
        # Cash ratio
        cash_value = float(sum(float(p.get("value") or 0.0) for p in pos if is_cash(p)))
        cash_ratio = (cash_value / total_value * 100.0) if total_value > 0 else 0.0
        # HHI (normalized): sum of squared shares over equities
        hhi = 0.0
        if total_value > 0 and equity_positions:
            for p in equity_positions:
                share = float(p.get("value") or 0.0) / total_value
                hhi += share * share
        # Normalize to 0..1 relative to 1/n baseline; simple mapping
        hhi_normalized = min(1.0, max(0.0, hhi))
        # Diversification label (coarse)
        if hhi_normalized < 0.15:
            div_label = "Élevée"
        elif hhi_normalized < 0.30:
            div_label = "Moyenne"
        else:
            div_label = "Faible"
        top_share = 0.0
        if total_value > 0 and equity_positions:
            top_value = max(float(p.get("value") or 0.0) for p in equity_positions)
            top_share = top_value / total_value * 100.0
        return {
            "total_value": float(total_value),
            "n_positions": int(n_positions),
            "cash_ratio": float(cash_ratio),
            "hhi_normalized": float(hhi_normalized),
            "diversification_label": div_label,
            "top_share": float(top_share),
        }


# ---------------- Decisioning -----------------
@dataclass
class Decision:
    action: str
    symbol: str | None = None
    confidence: float = 0.5
    rationale: str = ""
    safety_notes: list[str] = field(default_factory=list)


class DecisionEngine:
    def __init__(
        self,
        safety: Safety | None = None,
        max_symbol_share_pct: float = 25.0,
        max_sector_share_pct: float = 35.0,
    ):
        self.safety = safety or Safety()
        self.max_symbol_share_pct = float(max_symbol_share_pct)
        self.max_sector_share_pct = float(max_sector_share_pct)

    def _sector_shares(
        self, positions: list[dict[str, Any]], total_value: float
    ) -> dict[str, float]:
        shares: dict[str, float] = {}
        if total_value <= 0:
            return shares
        for p in positions:
            sym = str(p.get("symbol") or "").upper()
            if sym in {"CAD", "USD"}:
                continue
            sec = str(p.get("sector") or "Other")
            val = float(p.get("value") or 0.0)
            shares[sec] = shares.get(sec, 0.0) + (val / total_value * 100.0)
        return shares

    def suggest(
        self,
        positions: list[dict[str, Any]],
        symbol: str | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> Decision:
        positions = list(positions or [])
        total_value = float(sum(float(p.get("value") or 0.0) for p in positions))
        metrics = metrics or AnalyticsEngine().compute_metrics(positions)
        cash_ratio = float(metrics.get("cash_ratio") or 0.0)
        # Pick focus symbol if not specified
        sym = symbol or (positions[0].get("symbol") if positions else None)
        sym = str(sym) if sym else None
        # Baseline rule: if enough cash -> BUY; SMA bullish can reinforce rationale
        action = "HOLD"
        rationale: list[str] = []
        if cash_ratio >= 30.0:
            action = "BUY"
            rationale.append("Cash disponible >= 30%")
        if sym:
            p = next((x for x in positions if str(x.get("symbol")) == sym), None)
            sma5 = (p or {}).get("sma5")
            sma20 = (p or {}).get("sma20")
            if sma5 is not None and sma20 is not None and float(sma5) > float(sma20):
                if "BUY" not in action:
                    action = "BUY"
                rationale.append("SMA5 > SMA20")
        # Symbol budget
        notes: list[str] = []
        if sym and total_value > 0:
            sym_val = float(
                next(
                    (
                        float(p.get("value") or 0.0)
                        for p in positions
                        if str(p.get("symbol")) == sym
                    ),
                    0.0,
                )
            )
            sym_share = sym_val / total_value * 100.0
            if sym_share > self.max_symbol_share_pct:
                # Overweight: SELL dominates
                action = "SELL"
                notes.append(f"Poids {sym} {sym_share:.1f}% > {self.max_symbol_share_pct:.1f}%")
        # Sector constraint: note overweight; if action was BUY, downgrade to HOLD
        sector_shares = self._sector_shares(positions, total_value)
        if sym:
            p = next((x for x in positions if str(x.get("symbol")) == sym), None)
            sector = str((p or {}).get("sector") or "Other")
            sec_share = float(sector_shares.get(sector, 0.0))
            if sec_share > self.max_sector_share_pct:
                notes.append(
                    f"Secteur {sector} {sec_share:.1f}% > {self.max_sector_share_pct:.1f}%"
                )
                if action == "BUY":
                    action = "HOLD"
        return Decision(
            action=action,
            symbol=sym,
            confidence=0.7 if action != "HOLD" else 0.5,
            rationale="; ".join(rationale),
            safety_notes=notes,
        )


# ---------------- Communicator -----------------
class Communicator:
    def __init__(self, safety: Safety | None = None):
        self.safety = safety or Safety()

    def format_decision(self, d: Decision, context: str | None = None) -> str:
        ctx = context or ""
        text = f"Action: {d.action} | Symbole: {d.symbol or '-'} | Confiance: {d.confidence:.2f}\n{d.rationale}"
        if d.safety_notes:
            text += "\n" + "\n".join(f"Note: {n}" for n in d.safety_notes)
        if ctx:
            text += f"\nContexte: {ctx}"
        # Moderate and mask
        if not self.safety.moderate_text(text):
            return "[Contenu modéré]"
        return self.safety.mask_text(text)


# ---------------- Context memory -----------------
class ContextMemory:
    def __init__(self, max_items: int = 8):
        self.max_items = int(max_items)
        self._items: list[tuple[str, str]] = []  # (role, text)

    def add(self, role: str, text: str) -> None:
        self._items.append((str(role), str(text)))
        if len(self._items) > self.max_items:
            # keep only the last max_items
            self._items = self._items[-self.max_items :]

    def summarize(self) -> str:
        if not self._items:
            return ""
        items = list(self._items)
        prefix = ""
        if len(items) > self.max_items:
            prefix = "… "
            items = items[-self.max_items :]
        # Use role markers
        parts = []
        for role, txt in items:
            marker = "[U]" if role.lower().startswith("user") else "[A]"
            parts.append(f"{marker} {txt}")
        return prefix + " | ".join(parts)


# ---------------- Facade -----------------
class EnhancedAI:
    def __init__(self, deterministic: bool = False):
        self.safety = Safety(deterministic=deterministic)
        self.memory = ContextMemory()
        self._deterministic = bool(deterministic)

    def analyze_and_suggest(
        self,
        positions: Iterable[dict[str, Any]],
        focus_symbol: str | None = None,
        lang: str = "fr",
    ) -> dict[str, str]:
        pos = list(positions or [])
        ae = AnalyticsEngine()
        m = ae.compute_metrics(pos)
        de = DecisionEngine(safety=self.safety)
        d = de.suggest(pos, symbol=focus_symbol, metrics=m)
        # Compose user-facing strings
        analytics = (
            f"Valeur totale: {m['total_value']:,.2f} | #Pos: {m['n_positions']} | Cash: {m['cash_ratio']:.1f}%\n"
            f"Diversification: {m['hhi_normalized']:.3f} ({m['diversification_label']}) | Top: {m['top_share']:.1f}%"
        )
        decision_txt = Communicator(self.safety).format_decision(d)
        return {"analytics": analytics, "decision": decision_txt}
