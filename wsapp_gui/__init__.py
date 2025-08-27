"""GUI package refactor.

Expose WSApp and modular managers.
"""
from .app import WSApp
from .charts import ChartController
from .agent_ui import AgentUI
from .theming import PALETTES, apply_palette
from .config import app_config

# Gestionnaires modulaires
from .login_manager import LoginManager
from .portfolio_manager import PortfolioManager
from .search_manager import SearchManager
from .news_manager import NewsManager
from .chat_manager import ChatManager
from .ui_builder import UIBuilder
from .export_manager import ExportManager

__all__ = [
    "WSApp",
    "ChartController",
    "AgentUI",
    "PALETTES",
    "apply_palette",
    "app_config",
    "LoginManager",
    "PortfolioManager",
    "SearchManager",
    "NewsManager",
    "ChatManager",
    "UIBuilder",
    "ExportManager"
]
