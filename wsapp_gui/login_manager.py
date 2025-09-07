"""Module de gestion de l'authentification pour l'application Wealthsimple."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from run_ws import load_session, save_session
from ws_api import WealthsimpleAPI
from ws_api.exceptions import (
    LoginFailedException,
    OTPRequiredException,
    WSApiException,
)

if TYPE_CHECKING:
    from .app import WSApp  # updated reference


class LoginManager:
    """Gestionnaire pour les opérations d'authentification."""

    def __init__(self, app: WSApp):
        self.app = app

    def try_auto_login(self) -> None:
        """Tentative de connexion automatique avec une session sauvegardée."""
        try:
            sess = load_session()
            if sess:
                self.app.set_status("Connexion automatique...")

                def worker():
                    try:
                        api = WealthsimpleAPI.from_token(sess, save_session)
                        self.app.api = api
                        self.app.set_status("Connecté automatiquement")
                        self.app.after(0, self.app.refresh_accounts)
                    except Exception as e:
                        self.app.set_status(f"Échec connexion auto: {e}", error=True)

                threading.Thread(target=worker, daemon=True).start()
            else:
                self.app.set_status("Aucune session sauvegardée")
        except Exception as e:
            self.app.set_status(f"Erreur lors du chargement de la session: {e}", error=True)

    def login_clicked(self) -> None:
        """Gère le clic sur le bouton de connexion."""
        email = self.app.var_email.get().strip()
        password = self.app.var_password.get().strip()
        otp = self.app.var_otp.get().strip()

        if not email or not password:
            self.app.set_status("Email et mot de passe requis", error=True)
            return

        self.app.btn_login.config(state="disabled")
        self.app.set_status("Connexion en cours...")

        def worker():
            try:
                sess = WealthsimpleAPI.login(email, password, otp, save_session)
                api = WealthsimpleAPI.from_token(sess, save_session)
                self.app.api = api
                self.app.set_status("Connexion réussie")
                self.app.after(0, self.app.refresh_accounts)
            except OTPRequiredException:
                self.app.set_status("Code OTP requis", error=True)
            except LoginFailedException as e:
                self.app.set_status(f"Échec de connexion: {e}", error=True)
            except WSApiException as e:
                self.app.set_status(f"Erreur API: {e}", error=True)
            except Exception as e:
                self.app.set_status(f"Erreur: {e}", error=True)
            finally:
                self.app.after(0, lambda: self.app.btn_login.config(state="normal"))

        threading.Thread(target=worker, daemon=True).start()
