from __future__ import annotations

import json
import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .app import WSApp


class DiagnosticsPanel:
    """Panneau de diagnostics: statistiques cache, circuit breakers, maintenance, export."""

    def __init__(self, app: WSApp):
        self.app = app
        self.tab: ttk.Frame | None = None
        self.text: tk.Text | None = None
        self.refresh_button: ttk.Button | None = None
        self.auto_refresh = False
        self.refresh_interval = 30000  # 30 secondes

    def build(self, notebook: ttk.Notebook) -> None:
        """Construit l'interface du panneau de diagnostics."""
        tab = ttk.Frame(notebook)
        notebook.add(tab, text='Diagnostics')
        self.tab = tab

        # Barre d'outils
        toolbar = ttk.Frame(tab)
        toolbar.pack(fill=tk.X, padx=4, pady=4)

        # Boutons d'action
        self.refresh_button = ttk.Button(
            toolbar, text='Actualiser stats', command=self.refresh
        )
        self.refresh_button.pack(side=tk.LEFT)

        ttk.Button(
            toolbar, text='Nettoyage cache', command=self.housekeeping_now
        ).pack(side=tk.LEFT, padx=6)

        ttk.Button(
            toolbar, text='Exporter JSON', command=self.export_json
        ).pack(side=tk.LEFT)

        # Séparateur
        ttk.Separator(toolbar, orient='vertical').pack(side=tk.LEFT, fill=tk.Y, padx=8)

        # Option d'actualisation automatique
        self.auto_refresh_var = tk.BooleanVar()
        ttk.Checkbutton(
            toolbar,
            text='Auto-refresh (30s)',
            variable=self.auto_refresh_var,
            command=self._toggle_auto_refresh
        ).pack(side=tk.LEFT)

        # Zone de texte avec scrollbar
        text_frame = ttk.Frame(tab)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))

        self.text = tk.Text(text_frame, height=14, wrap='word', font=('Consolas', 9))
        scrollbar = ttk.Scrollbar(text_frame, orient='vertical', command=self.text.yview)
        self.text.configure(yscrollcommand=scrollbar.set, state=tk.DISABLED)

        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Initialiser avec les données
        try:
            self.refresh()
        except Exception as e:
            self._set_text(f"Erreur initialisation diagnostics: {e}")

    # ------------------- Actions -------------------

    def _toggle_auto_refresh(self) -> None:
        """Active/désactive l'actualisation automatique."""
        self.auto_refresh = self.auto_refresh_var.get()
        if self.auto_refresh:
            self._schedule_auto_refresh()

    def _schedule_auto_refresh(self) -> None:
        """Programme la prochaine actualisation automatique."""
        if self.auto_refresh and self.app:
            self.app.after(self.refresh_interval, self._auto_refresh_callback)

    def _auto_refresh_callback(self) -> None:
        """Callback pour l'actualisation automatique."""
        if self.auto_refresh:
            try:
                self.refresh()
            except Exception:
                pass  # Ignorer les erreurs en mode auto
            self._schedule_auto_refresh()

    def _set_text(self, content: str) -> None:
        """Met à jour le contenu du texte."""
        if not self.text:
            return

        self.text.configure(state=tk.NORMAL)
        self.text.delete('1.0', tk.END)
        self.text.insert(tk.END, content + '\n')
        self.text.see(tk.END)
        self.text.configure(state=tk.DISABLED)

    def _snapshot(self) -> dict[str, Any]:
        """Capture un instantané des diagnostics système."""
        am = getattr(self.app, 'api_manager', None)
        snap: dict[str, Any] = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'app_info': {
                'api_manager_available': am is not None,
                'auto_refresh': self.auto_refresh,
            }
        }

        # Informations sur l'API manager
        if am:
            try:
                snap['httpclient_only'] = bool(getattr(am, 'httpclient_only', False))
            except Exception as e:
                snap['httpclient_error'] = str(e)

            # Statistiques du cache
            try:
                snap['cache'] = am.get_cache_stats()
            except Exception as e:
                snap['cache_error'] = str(e)

            # Statistiques des circuit breakers
            try:
                snap['circuit_breakers'] = am.get_circuit_breaker_stats()
            except Exception as e:
                snap['circuit_breakers_error'] = str(e)
        else:
            snap['message'] = "API Manager non disponible - fonctionnalités limitées"

        return snap

    def refresh(self) -> None:
        """Actualise l'affichage des diagnostics."""
        if self.refresh_button:
            self.refresh_button.configure(state='disabled', text='Actualisation...')

        try:
            snap = self._snapshot()
            pretty = json.dumps(snap, indent=2, ensure_ascii=False)
            self._set_text(pretty)

            # Mettre à jour le statut
            if hasattr(self.app, 'set_status'):
                self.app.set_status("Diagnostics actualisés")

        except Exception as e:
            error_msg = f"Erreur récupération diagnostics: {e}"
            self._set_text(error_msg)
            if hasattr(self.app, 'set_status'):
                self.app.set_status(error_msg, error=True)
        finally:
            if self.refresh_button:
                self.refresh_button.configure(state='normal', text='Actualiser stats')

    def housekeeping_now(self) -> None:
        """Lance le nettoyage du cache."""
        if not getattr(self.app, 'api_manager', None):
            if hasattr(self.app, 'set_status'):
                self.app.set_status("APIs externes non disponibles", error=True)
            return

        def worker():
            try:
                self.app.api_manager.run_cache_housekeeping_once()
                self.app.after(
                    0, lambda: (
                        self.app.set_status('Nettoyage cache terminé') if hasattr(self.app, 'set_status') else None,
                        self.refresh()
                    )
                )
            except Exception as e:
                error_msg = f"Erreur nettoyage cache: {e}"
                self.app.after(
                    0, lambda: self.app.set_status(error_msg, error=True) if hasattr(self.app, 'set_status') else None
                )

        threading.Thread(target=worker, daemon=True).start()

    def export_json(self) -> None:
        """Exporte les diagnostics vers un fichier JSON."""
        try:
            snap = self._snapshot()
        except Exception as e:
            if hasattr(self.app, 'set_status'):
                self.app.set_status(f"Erreur collecte diagnostics: {e}", error=True)
            return

        # Générer un nom de fichier avec timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_filename = f"diagnostics_{timestamp}.json"

        path = filedialog.asksaveasfilename(
            title='Exporter diagnostics JSON',
            defaultextension='.json',
            initialvalue=default_filename,
            filetypes=[('JSON', '*.json'), ('Tous les fichiers', '*.*')],
        )
        if not path:
            return

        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(snap, f, ensure_ascii=False, indent=2)
            messagebox.showinfo('Export réussi', f'Diagnostics exportés vers:\n{path}')
            if hasattr(self.app, 'set_status'):
                self.app.set_status("Export diagnostics terminé")
        except Exception as e:
            error_msg = f"Erreur export JSON: {e}"
            messagebox.showerror('Erreur export', error_msg)
            if hasattr(self.app, 'set_status'):
                self.app.set_status(error_msg, error=True)


__all__ = ["DiagnosticsPanel"]
