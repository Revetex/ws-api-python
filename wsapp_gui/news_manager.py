"""Module de gestion des actualités et données intraday pour l'application Wealthsimple."""

from __future__ import annotations
import threading
import webbrowser
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from .app import WSApp  # updated reference


class NewsManager:
    """Gestionnaire pour les actualités et données de marché intraday."""

    def __init__(self, app: WSApp):
        self.app = app
        self._news_cache: List[dict] = []

    def load_intraday(self) -> None:
        """Charge les données intraday pour un symbole."""
        symbol = self.app.var_intraday_symbol.get().strip()
        if not symbol:
            self.app.set_status("Veuillez entrer un symbole", error=True)
            return

        if not self.app.api:
            self.app.set_status("Non connecté", error=True)
            return

        self.app.set_status(f"Chargement données intraday pour {symbol}...")

        def worker():
            try:
                # Rechercher le titre par symbole
                search_results = self.app.api.search_security(symbol)
                if not search_results:
                    self.app.set_status(f"Aucun résultat pour {symbol}", error=True)
                    return

                security_id = search_results[0].get('id')
                if not security_id:
                    self.app.set_status("ID de sécurité non trouvé", error=True)
                    return

                # Charger les données historiques
                historical_data = self.app.api.get_security_historical_quotes(
                    security_id,
                    time_range='1d'
                )

                self.app.after(0, lambda: self._show_intraday(historical_data, symbol))
                self.app.set_status(f"Données intraday chargées pour {symbol}")

            except Exception as e:
                self.app.set_status(f"Erreur chargement intraday: {e}", error=True)

        threading.Thread(target=worker, daemon=True).start()

    def _show_intraday(self, data: List[dict], symbol: str) -> None:
        """Affiche les données intraday dans l'interface."""
        if not data:
            self.app.set_status("Aucune donnée intraday disponible", error=True)
            return

        # Utiliser le contrôleur de graphiques pour afficher les données
        if hasattr(self.app, 'chart'):
            try:
                self.app.chart.plot_intraday(data, symbol)
            except Exception as e:
                self.app.set_status(f"Erreur affichage graphique: {e}", error=True)

    def load_news(self) -> None:
        """Charge les actualités financières."""
        self.app.set_status("Chargement des actualités...")

        def worker():
            try:
                # Simulation de chargement d'actualités
                # Dans une vraie implémentation, ceci ferait appel à une API d'actualités
                fake_news = [
                    {
                        'title': 'Marché en hausse aujourd\'hui',
                        'source': 'Financial Times',
                        'url': 'https://example.com/news1',
                        'published_at': '2025-08-16T10:00:00Z'
                    },
                    {
                        'title': 'Résultats trimestriels positifs',
                        'source': 'Bloomberg',
                        'url': 'https://example.com/news2',
                        'published_at': '2025-08-16T09:30:00Z'
                    }
                ]

                self._news_cache = fake_news
                self.app.after(0, lambda: self._show_news(fake_news))
                self.app.set_status(f"{len(fake_news)} actualité(s) chargée(s)")

            except Exception as e:
                self.app.set_status(f"Erreur chargement actualités: {e}", error=True)

        threading.Thread(target=worker, daemon=True).start()

    def _show_news(self, articles: List[dict]) -> None:
        """Affiche les actualités dans l'interface."""
        if not hasattr(self.app, 'tree_news'):
            return

        # Effacer les actualités précédentes
        for item in self.app.tree_news.get_children():
            self.app.tree_news.delete(item)

        # Ajouter les nouvelles actualités
        for article in articles:
            title = article.get('title', 'N/A')
            source = article.get('source', 'N/A')
            date = article.get('published_at', '')[:10]  # Format YYYY-MM-DD

            self.app.tree_news.insert('', 'end', values=(
                title,
                source,
                date
            ))

    def open_news_url(self):
        """Ouvre l'URL de l'actualité sélectionnée."""
        if not hasattr(self.app, 'tree_news'):
            return

        selection = self.app.tree_news.selection()
        if not selection:
            return

        idx = self.app.tree_news.index(selection[0])
        if idx >= len(self._news_cache):
            return

        article = self._news_cache[idx]
        url = article.get('url')

        if url:
            try:
                webbrowser.open(url)
            except Exception as e:
                self.app.set_status(f"Erreur ouverture URL: {e}", error=True)
