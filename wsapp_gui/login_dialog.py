"""Modal login dialog with OTP step for Wealthsimple."""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk
from typing import Callable

from ws_api import WealthsimpleAPI
from ws_api.exceptions import LoginFailedException, OTPRequiredException, WSApiException


class LoginDialog(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        on_success: Callable[[WealthsimpleAPI], None],
        save_session: Callable[..., None],
        *,
        remember_email_key: str | None = None,
        get_config: Callable[[str, object], object] | None = None,
        set_config: Callable[[str, object], None] | None = None,
    ):
        super().__init__(master)
        self.title("Connexion Wealthsimple")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        self._on_success = on_success
        self._save_session = save_session
        self._get = get_config or (lambda k, d=None: d)
        self._set = set_config or (lambda k, v: None)

        self.var_email = tk.StringVar(
            value=str(self._get(remember_email_key or 'auth.email', '') or '')
        )
        self.var_pwd = tk.StringVar()
        self.var_otp = tk.StringVar()
        self.var_status = tk.StringVar(value="")

        frm = ttk.Frame(self, padding=10)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text="Email").grid(row=0, column=0, sticky=tk.W)
        self.ent_email = ttk.Entry(frm, textvariable=self.var_email, width=32)
        self.ent_email.grid(row=0, column=1, pady=2)

        ttk.Label(frm, text="Mot de passe").grid(row=1, column=0, sticky=tk.W)
        self.ent_pwd = ttk.Entry(frm, textvariable=self.var_pwd, width=32, show='*')
        self.ent_pwd.grid(row=1, column=1, pady=2)

        # OTP widgets are created but hidden until the server asks for it
        self.lbl_otp = ttk.Label(frm, text="Code OTP")
        self.ent_otp = ttk.Entry(frm, textvariable=self.var_otp, width=16)

        btns = ttk.Frame(frm)
        btns.grid(row=3, column=0, columnspan=2, pady=(8, 0))
        self.btn_ok = ttk.Button(btns, text="Se connecter", command=self._on_ok)
        self.btn_ok.pack(side=tk.LEFT)
        ttk.Button(btns, text="Annuler", command=self._on_cancel).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(frm, textvariable=self.var_status, foreground='gray').grid(
            row=4, column=0, columnspan=2, sticky=tk.W, pady=(6, 0)
        )

        # Enter submits
        for w in (self.ent_email, self.ent_pwd, self.ent_otp):
            w.bind('<Return>', lambda e: self._on_ok())

        self.after(50, self.ent_email.focus_set)

    def _set_status(self, msg: str, error: bool = False):
        self.var_status.set(msg)

    def _on_cancel(self):
        self.grab_release()
        self.destroy()

    def _on_ok(self):
        email = (self.var_email.get() or '').strip()
        pwd = (self.var_pwd.get() or '').strip()
        otp = (self.var_otp.get() or '').strip() or None
        if not email or not pwd:
            self._set_status("Email et mot de passe requis", True)
            return
        self.btn_ok.configure(state=tk.DISABLED)
        self._set_status("Connexion en cours...")

        def worker():
            try:
                # First attempt: without OTP, will raise OTPRequiredException if needed
                sess = None
                try:
                    sess = WealthsimpleAPI.login(
                        email, pwd, otp_answer=otp, persist_session_fct=self._save_session
                    )
                except OTPRequiredException:
                    if otp:
                        # Provided OTP was missing/invalid; bubble up to ask again
                        raise
                    # Prompt user to enter OTP after email/password submitted

                    def _show_otp():
                        # Reveal OTP row only now
                        try:
                            self.lbl_otp.grid(row=2, column=0, sticky=tk.W, pady=2)
                            self.ent_otp.grid(row=2, column=1, sticky=tk.W, pady=2)
                        except Exception:
                            pass
                        self._set_status(
                            "Code OTP requis — consultez vos SMS / app d'authentification"
                        )
                        self.ent_otp.focus_set()

                    self.after(0, _show_otp)
                    return

                # Create API and verify/refresh token
                api = WealthsimpleAPI.from_token(
                    sess, persist_session_fct=self._save_session, username=email
                )
                # Remember email for next time
                try:
                    self._set('auth.email', email)
                except Exception:
                    pass
                # Success

                def done():
                    self._on_success(api)
                    self._set_status("Connexion réussie")
                    self.grab_release()
                    self.destroy()

                self.after(0, done)
            except OTPRequiredException:
                self.after(
                    0,
                    lambda: [
                        self._set_status("Code OTP invalide ou manquant — réessayez", True),
                        self.ent_otp.focus_set(),
                    ],
                )
            except LoginFailedException as err:
                msg = f"Échec de connexion: {err}"
                self.after(0, lambda: self._set_status(msg, True))
            except WSApiException as err:
                msg = f"Erreur API: {err}"
                self.after(0, lambda: self._set_status(msg, True))
            except Exception as err:
                msg = f"Erreur: {err}"
                self.after(0, lambda: self._set_status(msg, True))
            finally:
                self.after(0, lambda: self.btn_ok.configure(state=tk.NORMAL))

        threading.Thread(target=worker, daemon=True).start()
