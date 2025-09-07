from __future__ import annotations

import json
import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk


class DiagnosticsPanel:
    """Diagnostics tab: cache stats, circuit breakers, housekeeping, export."""

    def __init__(self, app):
        self.app = app
        self.tab = None
        self.text = None

    def build(self, notebook: ttk.Notebook):
        tab = ttk.Frame(notebook)
        notebook.add(tab, text='Diagnostics')
        self.tab = tab

        bar = ttk.Frame(tab)
        bar.pack(fill=tk.X, padx=4, pady=4)
        ttk.Button(bar, text='Actualiser stats', command=self.refresh).pack(side=tk.LEFT)
        ttk.Button(bar, text='Nettoyage cache', command=self.housekeeping_now).pack(
            side=tk.LEFT, padx=6
        )
        ttk.Button(bar, text='Exporter JSON', command=self.export_json).pack(side=tk.LEFT)

        self.text = tk.Text(tab, height=14, wrap='word')
        scr = ttk.Scrollbar(tab, orient='vertical', command=self.text.yview)
        self.text.configure(yscrollcommand=scr.set, state=tk.DISABLED)
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0), pady=(0, 6))
        scr.pack(side=tk.RIGHT, fill=tk.Y)

        try:
            self.refresh()
        except Exception:
            pass

    # ------------------- Actions -------------------
    def _snapshot(self) -> dict:
        am = getattr(self.app, 'api_manager', None)
        snap: dict[str, object] = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
        }
        try:
            snap['httpclient_only'] = bool(getattr(am, 'httpclient_only', False)) if am else False
        except Exception:
            pass
        try:
            snap['cache'] = am.get_cache_stats() if am else {}
        except Exception as e:  # noqa
            snap['cache_error'] = str(e)
        try:
            snap['circuit_breakers'] = am.get_circuit_breaker_stats() if am else {}
        except Exception as e:  # noqa
            snap['circuit_breakers_error'] = str(e)
        return snap

    def refresh(self):
        try:
            pretty = json.dumps(self._snapshot(), indent=2, ensure_ascii=False)
        except Exception as e:  # noqa
            pretty = f"Erreur récupération diagnostics: {e}"
        if not self.text:
            return
        self.text.configure(state=tk.NORMAL)
        self.text.delete('1.0', tk.END)
        self.text.insert(tk.END, pretty + '\n')
        self.text.see(tk.END)
        self.text.configure(state=tk.DISABLED)

    def housekeeping_now(self):
        if not getattr(self.app, 'api_manager', None):
            self.app.set_status("APIs externes non disponibles", error=True)
            return

        def worker():
            try:
                self.app.api_manager.run_cache_housekeeping_once()
                self.app.after(
                    0, lambda: (self.app.set_status('Nettoyage cache terminé'), self.refresh())
                )
            except Exception as e:
                self.app.after(
                    0, lambda e=e: self.app.set_status(f"Erreur nettoyage cache: {e}", error=True)
                )

        threading.Thread(target=worker, daemon=True).start()

    def export_json(self):
        try:
            snap = self._snapshot()
        except Exception as e:  # noqa
            self.app.set_status(f"Erreur collecte diagnostics: {e}", error=True)
            return
        path = filedialog.asksaveasfilename(
            title='Exporter diagnostics JSON',
            defaultextension='.json',
            filetypes=[('JSON', '*.json')],
        )
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(snap, f, ensure_ascii=False, indent=2)
            messagebox.showinfo('Export', 'Diagnostics exportés')
        except Exception as e:
            self.app.set_status(f"Erreur export JSON: {e}", error=True)


__all__ = ["DiagnosticsPanel"]
