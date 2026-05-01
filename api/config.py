"""
AxOvide — config.py
─────────────────────────────────────────────────────────────
Source unique de vérité pour toute la configuration.
Lue depuis le fichier .env correspondant à l'environnement.

Usage :
    from config import settings
    print(settings.ANTHROPIC_API_KEY)
─────────────────────────────────────────────────────────────
"""

import os
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Toutes les variables d'environnement du projet.
    Pydantic-settings valide les types au démarrage —
    si une variable obligatoire manque, l'app refuse de démarrer.
    """

    # ── Environnement ────────────────────────────────────────
    ENV: str = "development"

    # ── API Claude ───────────────────────────────────────────
    ANTHROPIC_API_KEY: str
    CLAUDE_MODEL: str = "claude-opus-4-5"

    # ── Serveur ──────────────────────────────────────────────
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    RELOAD: bool = True

    # ── Base de données ──────────────────────────────────────
    DATABASE_URL: str = "sqlite:///./axovide_dev.db"

    # ── Fichiers ─────────────────────────────────────────────
    UPLOAD_DIR: str = "./uploads_dev"
    MAX_FILE_SIZE_CV_MB: int = 10
    MAX_FILE_SIZE_T4_MB: int = 5
    MAX_FILE_SIZE_RL1_MB: int = 5

    # ── CORS ─────────────────────────────────────────────────
    CORS_ORIGINS: str = "chrome-extension://,http://localhost:3000"

    # ── OCR / Extraction ─────────────────────────────────────
    CONFIDENCE_THRESHOLD: float = 0.95
    DEFAULT_TAX_YEAR: int = 2024

    # ── Logging ──────────────────────────────────────────────
    LOG_LEVEL: str = "DEBUG"

    # ── Constantes fixes (non surchargeables) ────────────────
    PROTOCOL_VERSION: str = "1.0.0"
    APP_VERSION: str = "AxOvide-1.0"
    PROVINCE: str = "QC"
    OCR_ENGINE: str = "axovide-ocr/1.0.0"  # moteur = Claude vision

    model_config = SettingsConfigDict(
        # Détermine quel .env charger selon la variable ENV système
        env_file=f".env.{os.getenv('ENV', 'dev')}",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        """Retourne CORS_ORIGINS comme liste."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]

    @property
    def is_production(self) -> bool:
        return self.ENV == "production"

    @property
    def max_file_sizes(self) -> dict[str, int]:
        """Tailles max en octets par type de document."""
        return {
            "cv":  self.MAX_FILE_SIZE_CV_MB  * 1_000_000,
            "t4":  self.MAX_FILE_SIZE_T4_MB  * 1_000_000,
            "rl1": self.MAX_FILE_SIZE_RL1_MB * 1_000_000,
        }


@lru_cache
def get_settings() -> Settings:
    """
    Retourne l'instance unique des settings (singleton).
    @lru_cache garantit qu'on ne lit le .env qu'une seule fois.
    """
    return Settings()


# Instance globale importable directement
settings = get_settings()
