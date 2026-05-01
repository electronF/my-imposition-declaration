"""
AxOvide — main.py
─────────────────────────────────────────────────────────────
Point d'entrée de l'API FastAPI.
Démarrage : uvicorn main:app --reload --env-file .env.dev
─────────────────────────────────────────────────────────────
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from database import init_db
from routers import declarations, extract, health

# ── Logging ───────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


# ── Cycle de vie de l'application ─────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise la base de données au démarrage."""
    logger.info(f"AxOvide backend démarré — ENV={settings.ENV}")
    await init_db()
    logger.info("Base de données initialisée.")
    yield
    logger.info("AxOvide backend arrêté.")


# ── Application FastAPI ───────────────────────────────────────
app = FastAPI(
    title="AxOvide API",
    description=(
        "Backend de l'extension Chrome AxOvide. "
        "Traite les documents fiscaux (CV, T4, RL-1) via Claude OCR et "
        "retourne un payload structuré pour le remplissage automatique "
        "du formulaire de déclaration de revenus québécois."
    ),
    version=settings.PROTOCOL_VERSION,
    lifespan=lifespan,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
)

# ── CORS — autoriser l'extension Chrome ───────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_origin_regex=r"chrome-extension://.*",  # toutes les extensions Chrome
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# ── Routeurs ──────────────────────────────────────────────────
app.include_router(health.router)
app.include_router(extract.router)
app.include_router(declarations.router)


# ── Démarrage direct ──────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.RELOAD,
    )
