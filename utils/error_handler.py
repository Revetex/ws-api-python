"""Enhanced error handling and user feedback system."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
from typing import Any, Callable

from .logging_setup import get_logger

logger = get_logger('error_handler')


class WSError(Exception):
    """Base exception for Wealthsimple application errors."""

    def __init__(
        self,
        message: str,
        user_message: str | None = None,
        error_code: str | None = None,
        recoverable: bool = False,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.user_message = user_message or message
        self.error_code = error_code
        self.recoverable = recoverable
        self.details = details or {}

    def __str__(self) -> str:
        if self.error_code:
            return f"[{self.error_code}] {self.message}"
        return self.message


class NetworkError(WSError):
    """Network-related errors."""

    pass


class AuthenticationError(WSError):
    """Authentication and authorization errors."""

    pass


class ValidationError(WSError):
    """Data validation errors."""

    pass


class ConfigurationError(WSError):
    """Configuration-related errors."""

    pass


class ErrorHandler:
    """Centralized error handling and user feedback system."""

    def __init__(self, app: tk.Tk | None = None):
        self.app = app
        self._error_callbacks: dict[str, list[Callable]] = {}
        self._recovery_actions: dict[str, Callable] = {}

    def register_error_callback(self, error_type: str, callback: Callable[[WSError], None]) -> None:
        """Register a callback for specific error types."""
        if error_type not in self._error_callbacks:
            self._error_callbacks[error_type] = []
        self._error_callbacks[error_type].append(callback)

    def register_recovery_action(self, error_code: str, action: Callable[[], None]) -> None:
        """Register a recovery action for specific error codes."""
        self._recovery_actions[error_code] = action

    def handle_error(
        self, error: Exception, context: str = "", show_dialog: bool = True, log_error: bool = True
    ) -> None:
        """Handle an error with appropriate user feedback and logging."""
        # Convert to WSError if not already
        if not isinstance(error, WSError):
            ws_error = self._classify_error(error)
        else:
            ws_error = error

        # Log the error
        if log_error:
            self._log_error(ws_error, context)

        # Call error-specific callbacks
        error_type = type(ws_error).__name__
        if error_type in self._error_callbacks:
            for callback in self._error_callbacks[error_type]:
                try:
                    callback(ws_error)
                except Exception as cb_error:
                    logger.error(f"Error in callback: {cb_error}")

        # Show user feedback
        if show_dialog and self.app:
            self._show_error_dialog(ws_error)

    def _classify_error(self, error: Exception) -> WSError:
        """Classify a generic exception into a WSError type."""
        error_msg = str(error)
        error_type = type(error).__name__

        # Network-related errors
        if any(
            keyword in error_msg.lower()
            for keyword in ['connection', 'timeout', 'network', 'http', 'api']
        ):
            return NetworkError(
                f"Network error: {error_msg}",
                user_message="Problème de connexion réseau. Vérifiez votre connexion internet.",
                recoverable=True,
            )

        # Authentication errors
        if any(
            keyword in error_msg.lower()
            for keyword in ['auth', 'login', 'credential', 'token', 'unauthorized']
        ):
            return AuthenticationError(
                f"Authentication error: {error_msg}",
                user_message="Erreur d'authentification. Vérifiez vos identifiants.",
                recoverable=True,
            )

        # Configuration errors
        if any(keyword in error_msg.lower() for keyword in ['config', 'setting', 'parameter']):
            return ConfigurationError(
                f"Configuration error: {error_msg}",
                user_message="Erreur de configuration. Vérifiez les paramètres de l'application.",
            )

        # Generic error
        return WSError(
            f"{error_type}: {error_msg}", user_message="Une erreur inattendue s'est produite."
        )

    def _log_error(self, error: WSError, context: str) -> None:
        """Log an error with appropriate level."""
        log_msg = f"{context}: {error.message}" if context else error.message

        if isinstance(error, (NetworkError, AuthenticationError)) and error.recoverable:
            logger.warning(log_msg)
        else:
            logger.error(log_msg)

        if error.details:
            logger.debug(f"Error details: {error.details}")

    def _show_error_dialog(self, error: WSError) -> None:
        """Show an error dialog to the user."""
        if not self.app:
            return

        title = "Erreur"
        if isinstance(error, NetworkError):
            title = "Erreur de connexion"
        elif isinstance(error, AuthenticationError):
            title = "Erreur d'authentification"
        elif isinstance(error, ValidationError):
            title = "Erreur de validation"
        elif isinstance(error, ConfigurationError):
            title = "Erreur de configuration"

        message = error.user_message

        # Add recovery option if available
        if error.recoverable and error.error_code and error.error_code in self._recovery_actions:
            message += "\n\nVoulez-vous essayer de corriger automatiquement ?"

            if messagebox.askyesno(title, message):
                try:
                    self._recovery_actions[error.error_code]()
                    return
                except Exception as recovery_error:
                    logger.error(f"Recovery action failed: {recovery_error}")
                    messagebox.showerror(
                        "Erreur de récupération",
                        "La correction automatique a échoué. Veuillez réessayer manuellement.",
                    )
            return

        # Show error message
        messagebox.showerror(title, message)

    def safe_execute(self, func: Callable, *args, context: str = "", **kwargs) -> Any:
        """Execute a function safely with error handling."""
        try:
            return func(*args, **kwargs)
        except Exception as e:
            self.handle_error(e, context)
            return None


# Global error handler instance
_error_handler: ErrorHandler | None = None


def get_error_handler(app: tk.Tk | None = None) -> ErrorHandler:
    """Get the global error handler instance."""
    global _error_handler
    if _error_handler is None:
        _error_handler = ErrorHandler(app)
    elif app and _error_handler.app is None:
        _error_handler.app = app
    return _error_handler


def handle_error(
    error: Exception, context: str = "", show_dialog: bool = True, log_error: bool = True
) -> None:
    """Global error handling function."""
    handler = get_error_handler()
    handler.handle_error(error, context, show_dialog, log_error)


def safe_execute(func: Callable, *args, context: str = "", **kwargs) -> Any:
    """Global safe execution function."""
    handler = get_error_handler()
    return handler.safe_execute(func, *args, context=context, **kwargs)
