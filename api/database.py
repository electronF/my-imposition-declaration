"""
AxOvide — database.py
─────────────────────────────────────────────────────────────
Connexion SQLAlchemy + gestion de session.
Utilise SQLite en mode asynchrone via aiosqlite.
─────────────────────────────────────────────────────────────
"""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from config import settings

# ── Convertir sqlite:/// → sqlite+aiosqlite:/// pour le mode async
_db_url = settings.DATABASE_URL.replace("sqlite:///", "sqlite+aiosqlite:///")

# ── Moteur asynchrone
engine = create_async_engine(
    _db_url,
    echo=(settings.ENV == "development"),   # log SQL en dev uniquement
    connect_args={"check_same_thread": False},
)

# ── Fabrique de sessions
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# ── Base déclarative pour tous les modèles ORM
class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    """
    Dépendance FastAPI — injectée dans chaque route.
    Garantit que la session est fermée après chaque requête.

    Usage dans un router :
        async def my_route(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """
    Crée toutes les tables au démarrage si elles n'existent pas.
    Appelé depuis main.py dans l'événement lifespan.
    """
    # Import ici pour éviter les imports circulaires
    import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
