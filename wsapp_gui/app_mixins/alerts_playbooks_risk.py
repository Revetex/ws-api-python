from __future__ import annotations

import importlib
from typing import Any

from ..config import app_config


class AlertsMixin:
    def _alerts_generate(self) -> None:
        try:
            engine = getattr(self, 'alerts_engine', None)
            if not engine:
                self.set_status("AlertEngine indisponible", error=True)  # type: ignore[attr-defined]
                return
            sym = (
                (self.var_alert_symbol.get() if getattr(self, 'var_alert_symbol', None) else "")
                .strip()
                .upper()
            )  # type: ignore[attr-defined]
            if not sym:
                self.set_status("Entrez un symbole pour générer les alertes")  # type: ignore[attr-defined]
                return
            alerts = engine.generate(sym)
            self._alerts_raw = [
                (sym, a.kind, float(getattr(a, 'score', 0.0) or 0.0), a.message) for a in alerts
            ]  # type: ignore[attr-defined]
            self._alerts_refresh_view()  # type: ignore[attr-defined]
        except Exception as e:
            self.set_status("Échec génération alertes", error=True, details=str(e))  # type: ignore[attr-defined]

    def _alerts_send_top(self) -> None:
        try:
            tree = getattr(self, 'tree_alerts', None)
            api_manager = getattr(self, 'api_manager', None)
            if tree is None or api_manager is None:
                return
            rows = list(tree.get_children(""))
            if not rows:
                return
            values = tree.item(rows[0], 'values')
            if not values or len(values) < 4:
                return
            sym, kind, message = values[0], values[1], values[3]
            code = f"{str(kind).upper()}_{sym}"
            ok = False
            try:
                ok = bool(api_manager.notify_alert('ALERT', code, str(message)))
            except Exception:
                ok = False
            self.set_status("Alerte envoyée" if ok else "Envoi alerte échoué")  # type: ignore[attr-defined]
        except Exception:
            pass

    def _alerts_apply_filters(
        self, rows: list[tuple[str, str, float, str]]
    ) -> list[tuple[str, str, float, str]]:
        kind = (
            self.var_alert_kind.get() if getattr(self, 'var_alert_kind', None) else "Tous"
        ).strip()  # type: ignore[attr-defined]
        min_score = float(
            self.var_alert_min_score.get() if getattr(self, 'var_alert_min_score', None) else 0.0
        )  # type: ignore[attr-defined]
        group = bool(
            self.var_alert_group_by_symbol.get()
            if getattr(self, 'var_alert_group_by_symbol', None)
            else False
        )  # type: ignore[attr-defined]
        top_n = int(self.var_alert_top_n.get() if getattr(self, 'var_alert_top_n', None) else 10)  # type: ignore[attr-defined]
        filtered = [r for r in rows if (kind == "Tous" or r[1] == kind) and r[2] >= min_score]
        if group:
            best: dict[str, tuple[str, str, float, str]] = {}
            for r in filtered:
                sym = r[0]
                if sym not in best or r[2] > best[sym][2]:
                    best[sym] = r
            filtered = list(best.values())
        filtered.sort(key=lambda x: x[2], reverse=True)
        if top_n > 0:
            filtered = filtered[:top_n]
        return filtered

    def _alerts_refresh_view(self) -> None:
        try:
            tree = getattr(self, 'tree_alerts', None)
            if tree is None:
                return
            rows = self._alerts_apply_filters(getattr(self, '_alerts_raw', []))  # type: ignore[arg-type]
            for iid in list(tree.get_children("")):
                tree.delete(iid)
            for sym, kind, score, msg in rows:
                tree.insert("", "end", values=(sym, kind, f"{score:.2f}", msg))
            try:
                tree.heading("Score", command=lambda t=tree: self.sort_tree(t, "Score", True))  # type: ignore[attr-defined]
                self.sort_tree(tree, "Score", True)  # type: ignore[attr-defined]
            except Exception:
                pass
            self.set_status(f"{len(rows)} alerte(s) affichée(s)")  # type: ignore[attr-defined]
        except Exception:
            pass


class BriefingPrefsMixin:
    def _apply_briefing_prefs(self) -> None:
        try:
            enabled = bool(
                self.var_briefing_enabled.get()
                if getattr(self, 'var_briefing_enabled', None)
                else True
            )  # type: ignore[attr-defined]
            minutes = int(
                self.var_briefing_interval_min.get()
                if getattr(self, 'var_briefing_interval_min', None)
                else 10
            )  # type: ignore[attr-defined]
            seconds = max(60, minutes * 60)
            app_config.set('briefing.enabled', enabled)
            app_config.set('briefing.interval_sec', seconds)
            scheduler = getattr(self, 'scheduler', None)
            if scheduler:
                if enabled and getattr(self, 'briefing', None):
                    scheduler.add_job("daily-brief", float(seconds), self._emit_briefing)  # type: ignore[attr-defined]
                else:
                    scheduler.add_job("daily-brief", 1e9, lambda: None)
            self.set_status("Préférences briefing appliquées")  # type: ignore[attr-defined]
        except Exception:
            pass


class RiskPrefsMixin:
    def _apply_risk_settings(self) -> None:
        try:
            risk = getattr(self, 'risk', None)
            if not risk or not getattr(risk, 'limits', None):
                self.set_status("Gestion des risques non disponible", error=True)  # type: ignore[attr-defined]
                return
            lim = risk.limits
            setattr(lim, 'kill_switch', bool(self.var_risk_kill_switch.get()))  # type: ignore[attr-defined]
            setattr(lim, 'per_symbol_limit', float(self.var_risk_per_symbol.get()))  # type: ignore[attr-defined]
            setattr(lim, 'max_gross_exposure', float(self.var_risk_gross.get()))  # type: ignore[attr-defined]
            self.set_status("Paramètres de risque appliqués")  # type: ignore[attr-defined]
        except Exception:
            pass


class PlaybooksMixin:
    def _playbooks_preview(self, name: str, threshold_pct: float = 5.0) -> list[Any]:
        actions: list[Any] = []
        try:
            pm = getattr(self, 'portfolio_manager', None)
            if not pm or not hasattr(pm, 'get_positions'):
                return actions
            try:
                positions = list(pm.get_positions())  # type: ignore[attr-defined]
            except Exception:
                positions = []
            if not positions:
                return actions
            norm: list[dict[str, Any]] = []
            for p in positions:
                sym = str(
                    (getattr(p, 'symbol', None) if not isinstance(p, dict) else p.get('symbol'))
                    or ''
                )
                qraw = (
                    getattr(p, 'quantity', None) if not isinstance(p, dict) else p.get('quantity')
                )
                praw = getattr(p, 'price', None) if not isinstance(p, dict) else p.get('price')
                try:
                    qty = float(qraw) if qraw is not None else 0.0
                except Exception:
                    qty = 0.0
                try:
                    price = float(praw) if praw is not None else 0.0
                except Exception:
                    price = 0.0
                if sym:
                    norm.append({'symbol': sym, 'quantity': qty, 'price': price})
            mod = importlib.import_module('wsapp_gui.app')
            pb_cut_losses = getattr(mod, 'pb_cut_losses', None)
            pb_lock_in_gains = getattr(mod, 'pb_lock_in_gains', None)
            pb_rebalance_to_targets = getattr(mod, 'pb_rebalance_to_targets', None)
            if name == "Couper les pertes" and pb_cut_losses:
                try:
                    res = pb_cut_losses(norm, threshold_pct)  # type: ignore[misc]
                    actions = list(res) if res else []
                except Exception:
                    actions = []
            elif name == "Prendre des gains" and pb_lock_in_gains:
                try:
                    res = pb_lock_in_gains(norm, threshold_pct)  # type: ignore[misc]
                    actions = list(res) if res else []
                except Exception:
                    actions = []
            elif name == "Rééquilibrer" and pb_rebalance_to_targets:
                try:
                    res = pb_rebalance_to_targets(norm, {})  # type: ignore[misc]
                    actions = list(res) if res else []
                except Exception:
                    actions = []
        except Exception:
            actions = []
        return actions

    def _playbooks_apply(self, actions: list[Any]) -> None:
        try:
            if not actions:
                self.set_status("Aucune action à appliquer")  # type: ignore[attr-defined]
                return
            msg_lines = [f"[Playbook] {len(actions)} action(s):"]
            for a in actions:
                msg_lines.append(f"- {a}")
            self._append_chat("\n".join(line for line in msg_lines) + "\n")  # type: ignore[attr-defined]
            audit = getattr(self, 'audit', None)
            if audit:
                try:
                    audit.write('playbook', details={'actions': actions})
                except Exception:
                    pass
            try:
                te = getattr(self, 'trade_executor', None)
                if te and hasattr(te, 'preview_actions'):
                    te.preview_actions(actions)
            except Exception:
                pass
            self.set_status("Playbook appliqué en mode sécurisé (dry-run)")  # type: ignore[attr-defined]
        except Exception:
            pass
