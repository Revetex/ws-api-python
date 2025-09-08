"""Module de gestion de l'export pour l'application Wealthsimple.

Améliorations:
- Gestion d'erreurs robuste
- Noms de fichiers automatiques avec timestamps
- Validation des données avant export
- Support de formats multiples
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import TYPE_CHECKING, Any

from .ui_utils import format_money

if TYPE_CHECKING:
    from .app import WSApp

logger = logging.getLogger(__name__)


class ExportManager:
    """Gestionnaire pour les fonctionnalités d'export de données."""

    def __init__(self, app: WSApp):
        self.app = app
        self.default_format = 'csv'
        
    def _generate_filename(self, base_name: str, extension: str = 'csv') -> str:
        """Génère un nom de fichier avec timestamp."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{base_name}_{timestamp}.{extension}"
        
    def _validate_data(self, data: list, data_type: str) -> bool:
        """Valide les données avant export."""
        if not data:
            self.app.set_status(f"Aucune {data_type} à exporter", error=True)
            return False
        return True
        
    def _safe_export(self, export_func, *args, **kwargs) -> bool:
        """Exécute un export avec gestion d'erreurs."""
        try:
            return export_func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Erreur lors de l'export: {e}")
            self.app.set_status(f"Erreur export: {e}", error=True)
            return False

    def export_positions_csv(self) -> bool:
        """Exporte les positions vers un fichier CSV."""
        positions = getattr(self.app, '_positions_cache', [])
        if not self._validate_data(positions, "position"):
            return False

        default_filename = self._generate_filename("positions")
        filename = filedialog.asksaveasfilename(
            defaultextension=".csv",
            initialvalue=default_filename,
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            title="Exporter les positions",
        )

        if not filename:
            return False

        return self._safe_export(self._write_positions_csv, filename, positions)

    def _write_positions_csv(self, filename: str, positions: list[dict[str, Any]]) -> bool:
        """Écrit les positions dans un fichier CSV."""
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)

            # En-têtes
            headers = [
                'Symbole', 'Nom', 'Quantité', 'Valeur marchande', 'Devise',
                'Prix moyen', 'Gain/Perte', 'Pourcentage', 'Date export'
            ]
            writer.writerow(headers)

            # Données
            export_time = datetime.now().isoformat()
            for pos in positions:
                try:
                    security = pos.get('stock', {})
                    symbol = security.get('symbol', 'N/A')
                    name = security.get('name', 'N/A')
                    quantity = float(pos.get('quantity', 0))
                    market_value = float(pos.get('market_value', 0))
                    currency = pos.get('currency') or getattr(self.app, 'base_currency', 'CAD')
                    book_value = float(pos.get('book_value', 0))
                    
                    gain_loss = market_value - book_value if market_value and book_value else 0
                    avg_price = book_value / quantity if quantity and book_value else 0
                    percentage = (gain_loss / book_value * 100) if book_value else 0

                    writer.writerow([
                        symbol, name, f"{quantity:.4f}", f"{market_value:.2f}", currency,
                        f"{avg_price:.2f}", f"{gain_loss:.2f}", f"{percentage:.2f}%", export_time
                    ])
                except (ValueError, TypeError) as e:
                    logger.warning(f"Erreur traitement position {symbol}: {e}")
                    continue

        self.app.set_status(f"Positions exportées vers {Path(filename).name}")
        messagebox.showinfo("Export réussi", f"Positions exportées vers:\n{filename}")
        return True

    def export_activities_csv(self):
        """Exporte les activités vers un fichier CSV."""
        if not hasattr(self.app, '_activities_cache') or not self.app._activities_cache:
            self.app.set_status("Aucune activité à exporter", error=True)
            return

        filename = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            title="Exporter les activités",
        )

        if not filename:
            return

        try:
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)

                # En-têtes
                writer.writerow(
                    [
                        'Date',
                        'Type',
                        'Description',
                        'Symbole',
                        'Quantité',
                        'Montant',
                        'Devise',
                        'Statut',
                    ]
                )

                # Données
                for act in self.app._activities_cache:
                    date = act.get('occurred_at', '')[:10]  # Format YYYY-MM-DD
                    activity_type = act.get('type', 'N/A')
                    description = act.get('description', 'N/A')
                    symbol = act.get('symbol', 'N/A')
                    quantity = act.get('quantity', '')
                    amount = act.get('amount', 0)
                    currency = act.get('currency', 'CAD')
                    status = act.get('status', 'N/A')

                    writer.writerow(
                        [
                            date,
                            activity_type,
                            description,
                            symbol,
                            quantity,
                            f"{amount:.2f}",
                            currency,
                            status,
                        ]
                    )

            self.app.set_status(f"Activités exportées vers {filename}")
            messagebox.showinfo("Export réussi", f"Activités exportées vers:\n{filename}")

        except Exception as e:
            self.app.set_status("Erreur export activités", error=True, details=repr(e))

    def export_search_results_csv(self):
        """Exporte les résultats de recherche vers un fichier CSV."""
        if not hasattr(self.app, '_search_results') or not self.app._search_results:
            self.app.set_status("Aucun résultat de recherche à exporter", error=True)
            return

        filename = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            title="Exporter les résultats de recherche",
        )

        if not filename:
            return

        try:
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)

                # En-têtes
                writer.writerow(['Symbole', 'Nom', 'Bourse', 'Achetable', 'ID sécurité'])

                # Données
                for result in self.app._search_results:
                    stock = result.get('stock', {})
                    symbol = stock.get('symbol', 'N/A')
                    name = stock.get('name', 'N/A')
                    exchange = stock.get('primaryExchange', 'N/A')
                    buyable = "Oui" if result.get('buyable', False) else "Non"
                    security_id = result.get('id', 'N/A')

                    writer.writerow([symbol, name, exchange, buyable, security_id])

            self.app.set_status(f"Résultats de recherche exportés vers {filename}")
            messagebox.showinfo("Export réussi", f"Résultats exportés vers:\n{filename}")

        except Exception as e:
            self.app.set_status("Erreur export recherche", error=True, details=repr(e))

    def generate_portfolio_report(self):
        """Génère un rapport complet du portefeuille."""
        if not hasattr(self.app, '_positions_cache') or not self.app._positions_cache:
            self.app.set_status("Aucune position disponible pour le rapport", error=True)
            return

        filename = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="Générer rapport de portefeuille",
        )

        if not filename:
            return

        try:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write("RAPPORT DE PORTEFEUILLE WEALTHSIMPLE\n")
                f.write("=" * 50 + "\n")
                f.write(f"Généré le: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

                if self.app.current_account_id and self.app.accounts:
                    # Trouver le compte actuel
                    current_account = None
                    for acc in self.app.accounts:
                        if acc.get('id') == self.app.current_account_id:
                            current_account = acc
                            break

                    if current_account:
                        f.write(f"Compte: {current_account.get('description', 'N/A')}\n")
                        f.write(f"Devise: {current_account.get('currency', 'CAD')}\n\n")

                f.write("POSITIONS:\n")
                f.write("-" * 30 + "\n")

                total_value = 0
                for pos in self.app._positions_cache:
                    security = pos.get('stock', {})
                    symbol = security.get('symbol', 'N/A')
                    name = security.get('name', 'N/A')
                    quantity = pos.get('quantity', 0)
                    market_value = pos.get('market_value', 0)
                    currency = pos.get('currency', 'CAD')

                    f.write(f"• {symbol} - {name}\n")
                    f.write(f"  Quantité: {quantity:.4f}\n")
                    f.write(
                        f"  Valeur: {format_money(market_value, currency, with_symbol=False)}\n\n"
                    )

                    total_value += market_value

                f.write(
                    f"VALEUR TOTALE DU PORTEFEUILLE: {format_money(total_value, self.app.base_currency, with_symbol=False)}\n"
                )

            self.app.set_status(f"Rapport généré: {filename}")
            messagebox.showinfo(
                "Rapport généré", f"Rapport de portefeuille sauvegardé:\n{filename}"
            )

        except Exception as e:
            self.app.set_status("Erreur génération rapport", error=True, details=repr(e))
