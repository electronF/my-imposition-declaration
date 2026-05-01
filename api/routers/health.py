"""AxOvide — routers/health.py — GET /v1/health"""

from datetime import datetime, timezone
from fastapi import APIRouter
from schemas import HealthResponse
from config import settings

router = APIRouter(prefix="/v1", tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(
        status="ok",
        version=settings.PROTOCOL_VERSION,
        timestamp=datetime.now(timezone.utc).isoformat(),
        ocr_engine={"available": True, "version": settings.OCR_ENGINE},
    )
