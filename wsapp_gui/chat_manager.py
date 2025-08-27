"""Module de gestion du chat et des signaux IA pour l'application Wealthsimple."""

from __future__ import annotations
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .app import WSApp


class ChatManager:
    """Gestionnaire pour l'interface de chat et les signaux IA."""

    def __init__(self, app: WSApp):
        self.app = app

    def _chat_send(self) -> None:
        """Envoie un message dans le chat IA."""
        message = self.app.var_chat.get().strip()
        if not message:
            return

        # Afficher le message de l'utilisateur
        self._append_chat(f"Vous: {message}")
        self.app.var_chat.set("")  # Effacer le champ de saisie

        # Désactiver les entrées et afficher un statut
        try:
            if hasattr(self.app, 'btn_chat_send'):
                self.app.btn_chat_send.configure(state='disabled')
            if hasattr(self.app, 'ent_chat'):
                self.app.ent_chat.configure(state='disabled')
            if hasattr(self.app, 'lbl_chat_status'):
                self.app.lbl_chat_status.configure(text='Réponse en cours…')
        except Exception:
            pass

        # Traiter le message avec l'agent IA
        def worker():
            try:
                if self.app.agent:
                    # Utilise l'API publique de l'agent
                    response = self.app.agent.chat(message)
                    self.app.after(0, lambda: self._append_chat(f"Agent: {response}"))
                else:
                    self.app.after(0, lambda: self._append_chat("Agent: Agent IA non disponible"))
            except Exception as err:
                error_msg = f"Agent: Erreur - {err}"
                self.app.after(0, lambda: self._append_chat(error_msg))
            finally:
                # Réactiver UI
                def _reenable():
                    try:
                        if hasattr(self.app, 'btn_chat_send'):
                            self.app.btn_chat_send.configure(state='normal')
                        if hasattr(self.app, 'ent_chat'):
                            self.app.ent_chat.configure(state='normal')
                            try:
                                self.app.ent_chat.focus_set()
                            except Exception:
                                pass
                        if hasattr(self.app, 'lbl_chat_status'):
                            self.app.lbl_chat_status.configure(text='')
                    except Exception:
                        pass
                self.app.after(0, _reenable)

        threading.Thread(target=worker, daemon=True).start()

    def _append_chat(self, text: str) -> None:
        """Ajoute un message au chat."""
        # Privilégier la méthode dédiée de l'app si disponible (gère l'état du widget)
        if hasattr(self.app, '_append_chat'):
            try:
                self.app._append_chat(text + '\n')
                return
            except Exception:
                pass
        # Fallback direct si nécessaire
        if hasattr(self.app, 'txt_chat'):
            try:
                self.app.txt_chat.configure(state='normal')
                self.app.txt_chat.insert('end', text + '\n')
                self.app.txt_chat.see('end')
                self.app.txt_chat.configure(state='disabled')
            except Exception:
                pass

    def update_movers(self, top_n: int = 5) -> None:
        """Met à jour les plus gros mouvements du marché."""
        if not self.app.api:
            self.app.set_status("Non connecté", error=True)
            return

        self.app.set_status("Chargement des mouvements du marché...")

        def worker():
            try:
                # Simulation de données de mouvements du marché
                # Dans une vraie implémentation, ceci ferait appel à une API de marché
                fake_movers = [
                    {'symbol': 'AAPL', 'change': '+2.5%', 'price': '150.25'},
                    {'symbol': 'MSFT', 'change': '+1.8%', 'price': '280.50'},
                    {'symbol': 'GOOGL', 'change': '-0.5%', 'price': '2650.00'},
                    {'symbol': 'TSLA', 'change': '+3.2%', 'price': '245.75'},
                    {'symbol': 'NVDA', 'change': '+1.1%', 'price': '420.30'},
                ]

                self.app.after(0, lambda: self._show_movers(fake_movers[:top_n]))
                self.app.set_status(f"Top {top_n} mouvements chargés")

            except Exception as e:
                self.app.set_status(f"Erreur chargement mouvements: {e}", error=True)

        threading.Thread(target=worker, daemon=True).start()

    def _show_movers(self, movers: list) -> None:
        """Affiche les mouvements du marché."""
        if not hasattr(self.app, 'tree_gainers'):
            return

        # Effacer les données précédentes
        for item in self.app.tree_gainers.get_children():
            self.app.tree_gainers.delete(item)

        # Ajouter les nouveaux mouvements
        for mover in movers:
            symbol = mover.get('symbol', 'N/A')
            change = mover.get('change', 'N/A')
            price = mover.get('price', 'N/A')

            self.app.tree_gainers.insert('', 'end', values=(
                symbol,
                price,
                change
            ))

    def _update_notify_prefs(self) -> None:
        """Met à jour les préférences de notification."""
        # Hook: implémenter la persistance si nécessaire
        self.app.set_status("Préférences de notification mises à jour")

    def _refresh_ai_signals_periodic(self):
        """Actualise périodiquement les signaux IA."""
        try:
            if self.app.agent:
                # Générer des signaux IA périodiques
                signals = self.app.agent.generate_market_signals()
                if signals:
                    self._append_chat(f"Signaux IA: {signals}")
        except Exception:
            # Ignorer les erreurs pour ne pas perturber l'interface
            pass

        # Programmer la prochaine actualisation (toutes les 5 minutes)
        self.app.after(300000, self._refresh_ai_signals_periodic)
