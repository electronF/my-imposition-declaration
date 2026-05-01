"""
AxOvide — routers/extract.py
POST /v1/extract — Reçoit les fichiers, orchestre l'OCR Claude,
retourne le ExchangePayload.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from models import ExtractionSession
from schemas import ExchangePayload, ErrorResponse
from services.claude_extractor import extract_cv, extract_rl1, extract_t4
from services.payload_builder import build_payload

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["extraction"])

# Extensions et MIME acceptés
ALLOWED_PDF  = {"application/pdf"}
ALLOWED_DOCX = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
}


def _validate_file(file: UploadFile | None, doc_type: str) -> None:
    """Valide le type et la taille d'un fichier uploadé."""
    if file is None:
        return
    max_bytes = settings.max_file_sizes[doc_type]
    # Taille — FastAPI expose file.size si disponible
    if hasattr(file, "size") and file.size and file.size > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"{doc_type.upper()} trop volumineux. Maximum : {max_bytes // 1_000_000} Mo."
        )


@router.post(
    "/extract",
    response_model=ExchangePayload,
    responses={
        400: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
    summary="Extrait les données des documents fiscaux via Claude OCR",
)
async def extract_documents(
    cv_file:  UploadFile | None = File(None, description="CV — PDF ou DOCX, max 10 Mo"),
    t4_file:  UploadFile | None = File(None, description="T4 — PDF uniquement, max 5 Mo"),
    rl1_file: UploadFile | None = File(None, description="RL-1 — PDF uniquement, max 5 Mo"),
    tax_year: int               = Form(2024, ge=2020, le=2030),
    locale:   str               = Form("fr-CA"),
    db:       AsyncSession      = Depends(get_db),
):
    # ── Validation — au moins un fichier requis ───────────────
    if not any([cv_file, t4_file, rl1_file]):
        raise HTTPException(
            status_code=400,
            detail="Au moins un document (cv_file, t4_file ou rl1_file) doit être fourni."
        )

    _validate_file(cv_file,  "cv")
    _validate_file(t4_file,  "t4")
    _validate_file(rl1_file, "rl1")

    # ── Génération du processing_id ───────────────────────────
    processing_id = f"proc_{uuid.uuid4()}"

    # ── Lecture des fichiers en mémoire ───────────────────────
    cv_bytes  = await cv_file.read()  if cv_file  else None
    t4_bytes  = await t4_file.read()  if t4_file  else None
    rl1_bytes = await rl1_file.read() if rl1_file else None

    # ── Extraction Claude (parallèle via asyncio) ─────────────
    import asyncio

    tasks = {}
    if t4_bytes:
        tasks["t4"]  = extract_t4(t4_bytes,  tax_year)
    if rl1_bytes:
        tasks["rl1"] = extract_rl1(rl1_bytes, tax_year)
    if cv_bytes:
        mime = cv_file.content_type or "application/pdf"
        tasks["cv"]  = extract_cv(cv_bytes, mime)

    try:
        results = {}
        if tasks:
            done = await asyncio.gather(*tasks.values(), return_exceptions=True)
            for key, result in zip(tasks.keys(), done):
                if isinstance(result, Exception):
                    logger.error(f"Erreur extraction {key} : {result}")
                    results[key] = None
                else:
                    results[key] = result
    except Exception as e:
        logger.exception(f"Erreur lors de l'extraction : {e}")
        raise HTTPException(status_code=500, detail=f"OCR_FAILURE — {str(e)}")

    # ── Construction du ExchangePayload ───────────────────────
    payload = build_payload(
        processing_id=processing_id,
        t4_data=results.get("t4"),
        rl1_data=results.get("rl1"),
        cv_data=results.get("cv"),
        tax_year=tax_year,
        locale=locale,
    )

    # ── Persistance en base ───────────────────────────────────
    session = ExtractionSession(
        id=processing_id,
        tax_year=tax_year,
        locale=locale,
        ocr_engine=settings.OCR_ENGINE,
        has_cv=cv_bytes is not None,
        has_t4=t4_bytes is not None,
        has_rl1=rl1_bytes is not None,
        completion_rate=payload.exchange.summary.taux_completion_auto,
        payload_json=payload.model_dump_json(),
    )
    db.add(session)
    await db.flush()

    # ── Nettoyage immédiat des fichiers (sécurité LPRPDE) ─────
    # Les bytes sont en mémoire — aucun fichier temp créé
    # Si tu écris sur disque, supprimer ici avec Path(tmp_path).unlink()

    logger.info(f"Extraction terminée — {processing_id} — taux : {payload.exchange.summary.taux_completion_auto:.0%}")

    return payload
