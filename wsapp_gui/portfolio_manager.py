"""Module de gestion du portefeuille pour l'application Wealthsimple."""

from __future__ import annotations
import threading
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from .app import WSApp


class PortfolioManager:
    """Gestionnaire pour les opérations de portefeuille (comptes, positions)."""

    def __init__(self, app: WSApp):
        self.app = app

    def refresh_accounts(self) -> None:
        """Actualise la liste des comptes."""
        if not self.app.api:
            self.app.set_status("Non connecté", error=True)
            return

        self.app.set_status("Chargement des comptes...")

        def worker():
            try:
                accounts = self.app.api.get_accounts()
                self.app.accounts = accounts
                self.app.after(0, self._update_account_list)
                self.app.set_status(f"{len(accounts)} compte(s) chargé(s)")
            except Exception as e:
                self.app.set_status(f"Erreur lors du chargement des comptes: {e}", error=True)

        threading.Thread(target=worker, daemon=True).start()

    def _update_account_list(self) -> None:
        """Met à jour la liste déroulante des comptes."""
        if hasattr(self.app, 'combo_accounts'):
            self.app.combo_accounts['values'] = [
                f"{acc.get('description', 'Compte')} ({acc.get('currency', 'CAD')})"
                for acc in self.app.accounts
            ]
            if self.app.accounts:
                self.app.combo_accounts.current(0)
                self.on_account_selected()

    def on_account_selected(self, _evt=None) -> None:
        """Gère la sélection d'un compte."""
        if not self.app.accounts or not hasattr(self.app, 'combo_accounts'):
            return

        try:
            idx = self.app.combo_accounts.current()
            if 0 <= idx < len(self.app.accounts):
                account = self.app.accounts[idx]
                self.app.current_account_id = account.get('id')
                self.app.set_status(f"Compte sélectionné: {account.get('description', 'N/A')}")
                self.refresh_selected_account_details()
        except Exception as e:
            self.app.set_status(f"Erreur sélection compte: {e}", error=True)

    def refresh_selected_account_details(self):
        """Actualise les détails du compte sélectionné."""
        if not self.app.api or not self.app.current_account_id:
            return

        self.app.set_status("Chargement des positions...")

        def worker():
            try:
                # Charger les positions
                positions = self.app.api.get_positions(self.app.current_account_id)

                # Charger les activités
                activities = self.app.api.get_activities(
                    self.app.current_account_id,
                    how_many=100
                )

                self.app.after(0, lambda: self.update_details(positions, activities))
                self.app.set_status(f"{len(positions)} position(s), {len(activities)} activité(s)")

            except Exception as e:
                self.app.set_status(f"Erreur chargement détails: {e}", error=True)

        threading.Thread(target=worker, daemon=True).start()

    def update_details(self, positions: List[dict], activities: List[dict]):
        """Met à jour l'affichage des positions et activités."""
        self.app._positions_cache = positions
        self.app._activities_cache = activities  # Ajout du cache des activités
        self._fill_positions(positions)
        self._fill_activities(activities)

    def _fill_positions(self, positions: List[dict]) -> None:
        """Remplit le tableau des positions."""
        if not hasattr(self.app, 'tree_positions'):
            return

        # Effacer les données existantes
        for item in self.app.tree_positions.get_children():
            self.app.tree_positions.delete(item)

        # Ajouter les nouvelles positions
        for pos in positions:
            security = pos.get('stock', {})
            symbol = security.get('symbol', 'N/A')
            name = security.get('name', 'N/A')
            quantity = pos.get('quantity', 0)
            market_value = pos.get('market_value', 0)

            self.app.tree_positions.insert('', 'end', values=(
                symbol,
                name,
                f"{quantity:.4f}",
                f"${market_value:.2f}"
            ))

    def _fill_activities(self, activities: List[dict]) -> None:
        """Remplit le tableau des activités."""
        if not hasattr(self.app, 'tree_activities'):
            return

        # Effacer les données existantes
        for item in self.app.tree_activities.get_children():
            self.app.tree_activities.delete(item)

        # Ajouter les nouvelles activités
        for act in activities:
            date = act.get('occurred_at', '')[:10]  # Format YYYY-MM-DD
            activity_type = act.get('type', 'N/A')
            description = act.get('description', 'N/A')
            amount = act.get('amount', 0)

            self.app.tree_activities.insert('', 'end', values=(
                date,
                activity_type,
                description,
                f"${amount:.2f}"
            ))
