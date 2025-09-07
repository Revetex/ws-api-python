"""Module de gestion de la recherche de titres pour l'application Wealthsimple."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .app import WSApp  # updated reference


class SearchManager:
    """Gestionnaire pour les fonctionnalités de recherche de titres."""

    def __init__(self, app: WSApp):
        self.app = app

    def search_securities(self) -> None:
        """Lance une recherche de titres."""
        query = self.app.var_search.get().strip()
        if not query:
            self.app.set_status("Veuillez entrer un terme de recherche", error=True)
            return

        if not self.app.api:
            self.app.set_status("Non connecté", error=True)
            return

        self.app.set_status(f"Recherche de '{query}'...")

        def worker():
            try:
                results = self.app.api.search_security(query)
                self.app._search_results = results
                self.app.after(0, self._update_search_results)
                self.app.set_status(f"{len(results)} résultat(s) trouvé(s)")
            except Exception as e:
                self.app.set_status(f"Erreur de recherche: {e}", error=True)

        threading.Thread(target=worker, daemon=True).start()

    def _update_search_results(self) -> None:
        """Met à jour l'affichage des résultats de recherche."""
        if not hasattr(self.app, 'tree_search'):
            return

        # Effacer les résultats précédents
        for item in self.app.tree_search.get_children():
            self.app.tree_search.delete(item)

        # Ajouter les nouveaux résultats
        for result in self.app._search_results:
            stock = result.get('stock', {})
            symbol = stock.get('symbol', 'N/A')
            name = stock.get('name', 'N/A')
            exchange = stock.get('primaryExchange', 'N/A')
            buyable = "Oui" if result.get('buyable', False) else "Non"

            self.app.tree_search.insert('', 'end', values=(symbol, name, exchange, buyable))

    def open_search_security_details(self) -> None:
        """Ouvre les détails d'un titre sélectionné dans les résultats de recherche."""
        if not hasattr(self.app, 'tree_search'):
            return

        selection = self.app.tree_search.selection()
        if not selection:
            return

        idx = self.app.tree_search.index(selection[0])
        if idx >= len(self.app._search_results):
            return

        security = self.app._search_results[idx]
        security_id = security.get("id")

        if not (self.app.api and security_id):
            return

        self.app.set_status("Chargement des détails du titre...")

        def worker():
            try:
                market_data = self.app.api.get_security_market_data(security_id)
                stock_info = market_data.get('stock', {}) if market_data else {}
                quote_info = market_data.get('quote', {}) if market_data else {}

                details_text = self._format_security_details(security, stock_info, quote_info)

                self.app.after(0, lambda: self._set_search_details(details_text))
                self.app.set_status("Détails du titre chargés")

            except Exception as e:
                self.app.set_status(f"Erreur chargement détails: {e}", error=True)

        threading.Thread(target=worker, daemon=True).start()

    def _format_security_details(self, security: dict, stock_info: dict, quote_info: dict) -> str:
        """Formate les détails d'un titre pour l'affichage."""
        stock = security.get('stock', {})
        symbol = stock.get('symbol', 'N/A')
        name = stock.get('name', 'N/A')
        exchange = stock.get('primaryExchange', 'N/A')

        details = [
            f"Symbole: {symbol}",
            f"Nom: {name}",
            f"Bourse: {exchange}",
            f"Achetable: {'Oui' if security.get('buyable', False) else 'Non'}",
            "",
        ]

        if quote_info:
            last_price = quote_info.get('last', 'N/A')
            bid = quote_info.get('bid', 'N/A')
            ask = quote_info.get('ask', 'N/A')
            volume = quote_info.get('volume', 'N/A')

            details.extend(
                [
                    "--- Cotation ---",
                    f"Dernier prix: {last_price}",
                    f"Offre: {bid}",
                    f"Demande: {ask}",
                    f"Volume: {volume}",
                    "",
                ]
            )

        return "\n".join(details)

    def _set_search_details(self, text: str) -> None:
        """Met à jour le texte des détails de recherche."""
        if hasattr(self.app, 'text_search_details'):
            self.app.text_search_details.delete('1.0', 'end')
            self.app.text_search_details.insert('1.0', text)

    def _discover_click(self, symbol: str) -> None:
        """Gère le clic sur un symbole de découverte."""
        self.app.var_search.set(symbol)
        self.search_securities()
