"""Enhanced logging configuration with file logging and better formatting.

Call setup_logging() early in application start.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys

# Enhanced format with more details
_DEF_FORMAT = "%(asctime)s [%(levelname)8s] %(name)s:%(lineno)d - %(message)s"
_FILE_FORMAT = "%(asctime)s [%(levelname)8s] %(name)s:%(lineno)d - %(message)s"
_SIMPLE_FORMAT = "%(levelname)s: %(message)s"

# Log levels with descriptions
LOG_LEVELS = {
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARNING': logging.WARNING,
    'ERROR': logging.ERROR,
    'CRITICAL': logging.CRITICAL,
}


class WSLogger:
    """Enhanced logger for Wealthsimple application."""

    def __init__(self, name: str = 'ws_app', log_file: str | None = None):
        self.logger = logging.getLogger(name)
        self.log_file = log_file or 'ws_app.log'
        self._configured = False

    def configure(
        self,
        level: int = logging.INFO,
        console_level: int | None = None,
        file_level: int | None = None,
        max_bytes: int = 10 * 1024 * 1024,  # 10MB
        backup_count: int = 5,
    ) -> None:
        """Configure logging with console and file handlers."""
        if self._configured:
            return

        self.logger.setLevel(level)
        formatter = logging.Formatter(_DEF_FORMAT)
        file_formatter = logging.Formatter(_FILE_FORMAT)

        # Remove existing handlers to avoid duplicates
        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(console_level or level)
        console_handler.setFormatter(logging.Formatter(_SIMPLE_FORMAT))
        self.logger.addHandler(console_handler)

        # File handler with rotation
        try:
            file_handler = logging.handlers.RotatingFileHandler(
                self.log_file, maxBytes=max_bytes, backupCount=backup_count, encoding='utf-8'
            )
            file_handler.setLevel(file_level or level)
            file_handler.setFormatter(file_formatter)
            self.logger.addHandler(file_handler)
        except (OSError, PermissionError) as e:
            # Fallback to console only if file logging fails
            console_handler.setFormatter(formatter)
            self.logger.warning(f"Could not setup file logging: {e}")

        self._configured = True

    def get_logger(self) -> logging.Logger:
        """Get the configured logger instance."""
        if not self._configured:
            self.configure()
        return self.logger


# Global logger instance
_logger_instance: WSLogger | None = None


def setup_logging(
    level: str = 'INFO',
    log_file: str | None = None,
    console_level: str | None = None,
    file_level: str | None = None,
) -> logging.Logger:
    """Setup enhanced logging for the application.

    Args:
        level: Default log level ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')
        log_file: Path to log file (default: 'ws_app.log')
        console_level: Console log level (defaults to same as level)
        file_level: File log level (defaults to same as level)

    Returns:
        Configured logger instance
    """
    global _logger_instance

    if _logger_instance is None:
        _logger_instance = WSLogger('ws_app', log_file)

    # Convert string levels to logging constants
    def get_level(lvl: str | None) -> int | None:
        return LOG_LEVELS.get(lvl.upper()) if lvl else None

    _logger_instance.configure(
        level=get_level(level) or logging.INFO,
        console_level=get_level(console_level),
        file_level=get_level(file_level),
    )

    logger = _logger_instance.get_logger()
    logger.info("Logging system initialized")
    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance for a specific module."""
    if _logger_instance is None:
        setup_logging()
    return logging.getLogger(f"ws_app.{name}")


# Backwards compatibility
def get_app_logger() -> logging.Logger:
    """Get the main application logger (backwards compatibility)."""
    return get_logger('app')
