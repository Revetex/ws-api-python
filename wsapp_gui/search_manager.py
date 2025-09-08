"""Module de gestion de la recherche de titres pour l'application Wealthsimple.

Améliorations:
- Gestion d'erreurs robuste
- Cache des résultats de recherche
- Validation des entrées
- Interface utilisateur améliorée
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .app import WSApp

logger = logging.getLogger(__name__)


class SearchManager:
    """Gestionnaire pour les fonctionnalités de recherche de titres."""

    def __init__(self, app: WSApp):
        self.app = app
        self._search_cache: dict[str, tuple[list[dict[str, Any]], datetime]] = {}
        self._cache_ttl = timedelta(minutes=30)  # Cache valide 30 minutes
        self._last_query = ""
        
    def _is_cache_valid(self, query: str) -> bool:
        """Vérifie si le cache est valide pour une requête."""
        if query not in self._search_cache:
            return False
        _, timestamp = self._search_cache[query]
        return datetime.now() - timestamp < self._cache_ttl
        
    def _get_cached_results(self, query: str) -> list[dict[str, Any]] | None:
        """Récupère les résultats en cache."""
        if self._is_cache_valid(query):
            results, _ = self._search_cache[query]
            return results
        return None
        
    def _cache_results(self, query: str, results: list[dict[str, Any]]) -> None:
        """Met en cache les résultats de recherche."""
        self._search_cache[query] = (results, datetime.now())
        # Nettoyer le cache si trop volumineux
        if len(self._search_cache) > 100:
            oldest_key = min(self._search_cache.keys(), 
                           key=lambda k: self._search_cache[k][1])
            del self._search_cache[oldest_key]

    def search_securities(self) -> None:
        """Lance une recherche de titres avec cache et validation."""
        if not hasattr(self.app, 'var_search'):
            logger.error("Variable de recherche non initialisée")
            return
            
        query = self.app.var_search.get().strip()
        if not query:
            self.app.set_status("Veuillez entrer un terme de recherche", error=True)
            return

        # Validation de la requête
        if len(query) < 2:
            self.app.set_status("Le terme de recherche doit contenir au moins 2 caractères", error=True)
            return

        if not self.app.api:
            self.app.set_status("Non connecté à l'API", error=True)
            return

        # Vérifier le cache
        cached_results = self._get_cached_results(query.lower())
        if cached_results is not None:
            self.app._search_results = cached_results
            self._update_search_results()
            self.app.set_status(f"{len(cached_results)} résultat(s) (cache)")
            return

        self._last_query = query
        self.app.set_status(f"Recherche de '{query}'...")
        self._disable_search_ui()

        def worker():
            try:
                results = self.app.api.search_security(query)
                
                # Valider les résultats
                if not isinstance(results, list):
                    results = []
                    
                # Mettre en cache
                self._cache_results(query.lower(), results)
                
                self.app._search_results = results
                self.app.after(0, self._on_search_complete)
                
                status_msg = f"{len(results)} résultat(s) trouvé(s)"
                if len(results) == 0:
                    status_msg += " - essayez un terme différent"
                self.app.after(0, lambda: self.app.set_status(status_msg))
                
            except Exception as e:
                logger.error(f"Erreur de recherche pour '{query}': {e}")
                self.app.after(0, lambda: self._on_search_error(str(e)))

        threading.Thread(target=worker, daemon=True).start()
        
    def _disable_search_ui(self) -> None:
        """Désactive temporairement l'interface de recherche."""
        if hasattr(self.app, 'btn_search'):
            self.app.btn_search.configure(state='disabled', text='Recherche...')
            
    def _enable_search_ui(self) -> None:
        """Réactive l'interface de recherche."""
        if hasattr(self.app, 'btn_search'):
            self.app.btn_search.configure(state='normal', text='Rechercher')
            
    def _on_search_complete(self) -> None:
        """Callback appelé quand la recherche est terminée."""
        self._update_search_results()
        self._enable_search_ui()
        
    def _on_search_error(self, error_msg: str) -> None:
        """Callback appelé en cas d'erreur de recherche."""
        self.app.set_status(f"Erreur de recherche: {error_msg}", error=True)
        self._enable_search_ui()

    def _update_search_results(self) -> None:
        """Met à jour l'affichage des résultats de recherche."""
        if not hasattr(self.app, 'tree_search'):
            logger.warning("Widget tree_search non trouvé")
            return

        # Effacer les résultats précédents
        for item in self.app.tree_search.get_children():
            self.app.tree_search.delete(item)

        # Vérifier que nous avons des résultats
        if not hasattr(self.app, '_search_results') or not self.app._search_results:
            self._set_search_details("Aucun résultat trouvé.")
            return

        # Ajouter les nouveaux résultats avec gestion d'erreurs
        valid_results = 0
        for i, result in enumerate(self.app._search_results):
            try:
                stock = result.get('stock', {})
                symbol = stock.get('symbol', 'N/A')
                name = stock.get('name', 'N/A')
                exchange = stock.get('primaryExchange', 'N/A')
                buyable = "Oui" if result.get('buyable', False) else "Non"

                # Insérer avec un tag pour coloration conditionnelle
                tag = 'buyable' if result.get('buyable', False) else 'not_buyable'
                item_id = self.app.tree_search.insert(
                    '', 'end', 
                    values=(symbol, name, exchange, buyable),
                    tags=(tag,)
                )
                valid_results += 1
                
            except Exception as e:
                logger.warning(f"Erreur formatage résultat {i}: {e}")
                continue
                
        # Configurer les couleurs des tags
        try:
            self.app.tree_search.tag_configure('buyable', foreground='green')
            self.app.tree_search.tag_configure('not_buyable', foreground='gray')
        except Exception:
            pass
            
        if valid_results == 0:
            self._set_search_details("Aucun résultat valide trouvé.")
        else:
            self._set_search_details(f"{valid_results} résultat(s) affiché(s). Double-cliquez pour voir les détails.")

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
