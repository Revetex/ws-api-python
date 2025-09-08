"""Configuration et préférences de l'application Wealthsimple.

Améliorations:
- Fusion récursive des valeurs par défaut (sans écraser l'existant)
- Valeurs par défaut explicites pour les préférences Telegram (include_technical, tech_format)
- Validation des valeurs de configuration
- Gestion d'erreurs améliorée
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class AppConfig:
    """Gestionnaire de configuration de l'application."""

    def __init__(self, config_file: str = "ws_app_config.json"):
        self.config_file = Path(config_file)
        self.config: dict[str, Any] = {}
        self.load_config()

    def load_config(self) -> None:
        """Charge la configuration depuis le fichier."""
        if self.config_file.exists():
            try:
                with open(self.config_file, encoding='utf-8') as f:
                    self.config = json.load(f)
                logger.debug(f"Configuration chargée depuis {self.config_file}")
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(f"Erreur lors du chargement de la configuration: {e}")
                self.config = {}

        # Valeurs par défaut
        self._set_defaults()

    def _merge_defaults(self, cfg: dict[str, Any], defaults: dict[str, Any]) -> None:
        """Fusionne récursivement les valeurs par défaut dans la config.
        
        Ajoute uniquement les clés manquantes sans écraser les valeurs existantes.
        """
        for key, def_val in defaults.items():
            if key not in cfg:
                cfg[key] = def_val
            else:
                if isinstance(def_val, dict) and isinstance(cfg.get(key), dict):
                    self._merge_defaults(cfg[key], def_val)

    def _set_defaults(self) -> None:
        """Définit les valeurs par défaut (non destructif)."""
        defaults: dict[str, Any] = {
            'theme': 'light',
            'ui': {
                'font': {
                    'size': 10,
                    'family': 'Segoe UI',
                },
            },
            'media': {
                'cache_ttl_sec': 3600,
                'detail_logo_px': 64,
            },
            'notifications': {
                'info': False,
                'warn': True,
                'alert': True,
            },
            'ai': {
                'enhanced': True,  # Active le Conseiller (Enhanced AI)
            },
            'window': {
                'width': 1200,
                'height': 800,
                'x': None,
                'y': None,
            },
            'auto_login': True,
            'refresh_interval': 300000,  # 5 minutes en ms
            'export': {
                'default_format': 'csv',
                'include_headers': True,
            },
            # Préférences d'intégration
            'integrations': {
                'telegram': {
                    'enabled': False,
                    'chat_id': '',
                    'include_technical': True,
                    'tech_format': 'plain',
                }
            },
        }

        self._merge_defaults(self.config, defaults)

    def save_config(self) -> None:
        """Sauvegarde la configuration dans le fichier."""
        try:
            # Créer le répertoire parent si nécessaire
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            logger.debug(f"Configuration sauvegardée dans {self.config_file}")
        except OSError as e:
            logger.error(f"Erreur sauvegarde config: {e}")
            print(f"Erreur sauvegarde config: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """Récupère une valeur de configuration."""
        keys = key.split('.')
        value = self.config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def set(self, key: str, value: Any) -> None:
        """Définit une valeur de configuration."""
        if not key:
            raise ValueError("La clé ne peut pas être vide")
            
        keys = key.split('.')
        config = self.config

        # Naviguer/créer la structure imbriquée
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            elif not isinstance(config[k], dict):
                # Convertir en dict si ce n'en est pas un
                config[k] = {}
            config = config[k]

        config[keys[-1]] = value
        self.save_config()

    def get_window_geometry(self) -> str:
        """Retourne la géométrie de la fenêtre."""
        width = self.get('window.width', 1200)
        height = self.get('window.height', 800)
        x = self.get('window.x')
        y = self.get('window.y')

        geometry = f"{width}x{height}"
        if x is not None and y is not None:
            geometry += f"+{x}+{y}"

        return geometry

    def save_window_geometry(self, geometry: str) -> None:
        """Sauvegarde la géométrie de la fenêtre."""
        try:
            # Parse geometry string (e.g., "1200x800+100+50")
            if '+' in geometry:
                size_part, pos_part = geometry.split('+', 1)
                if '+' in pos_part:
                    x, y = pos_part.split('+', 1)
                    self.set('window.x', int(x))
                    self.set('window.y', int(y))
            else:
                size_part = geometry

            if 'x' in size_part:
                width, height = size_part.split('x')
                self.set('window.width', int(width))
                self.set('window.height', int(height))

        except (ValueError, IndexError):
            # En cas d'erreur de parsing, ignorer
            logger.warning(f"Impossible de parser la géométrie: {geometry}")
            pass

    def validate_config(self) -> bool:
        """Valide la configuration et corrige les valeurs invalides."""
        valid = True
        
        # Valider les dimensions de fenêtre
        width = self.get('window.width', 1200)
        height = self.get('window.height', 800)
        
        if not isinstance(width, int) or width < 400:
            self.set('window.width', 1200)
            valid = False
            
        if not isinstance(height, int) or height < 300:
            self.set('window.height', 800)
            valid = False
            
        # Valider le format technique Telegram
        tech_format = self.get('integrations.telegram.tech_format', 'plain')
        if tech_format not in ['plain', 'emoji-rich']:
            self.set('integrations.telegram.tech_format', 'plain')
            valid = False
            
        # Valider le thème
        theme = self.get('theme', 'light')
        if theme not in ['light', 'dark']:
            self.set('theme', 'light')
            valid = False
            
        return valid
        
    def reset_to_defaults(self) -> None:
        """Remet la configuration aux valeurs par défaut."""
        self.config = {}
        self._set_defaults()
        logger.info("Configuration remise aux valeurs par défaut")


# Instance globale de configuration
app_config = AppConfig()
