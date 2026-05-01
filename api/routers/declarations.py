"""
AxOvide — routers/declarations.py
POST /v1/declarations  — Soumet la déclaration finale
GET  /v1/declarations/{confirmation_id} — Récupère une déclaration
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Declaration, ExtractionSession
from schemas import (
    DeclarationRecord,
    DeclarationSubmitRequest,
    DeclarationSubmitResponse,
    ErrorResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["declarations"])


@router.post(
    "/declarations",
    response_model=DeclarationSubmitResponse,
    status_code=201,
    responses={
        400: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
    summary="Soumet la déclaration fiscale finale et la persiste en base",
)
async def submit_declaration(
    body: DeclarationSubmitRequest,
    db:   AsyncSession = Depends(get_db),
):
    # ── Vérifier que la session d'extraction existe ───────────
    session = await db.get(ExtractionSession, body.processing_id)
    if session is None:
        raise HTTPException(
            status_code=400,
            detail=f"processing_id inconnu : {body.processing_id}. "
                   "Effectuez d'abord un appel à POST /v1/extract."
        )

    # ── Vérifier qu'aucune déclaration n'existe déjà ─────────
    existing = await db.execute(
        select(Declaration).where(Declaration.processing_id == body.processing_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail=f"Une déclaration existe déjà pour processing_id {body.processing_id}."
        )

    # ── Créer la déclaration ──────────────────────────────────
    confirmation_id = f"decl_{uuid.uuid4()}"
    now = datetime.now(timezone.utc)

    # Calcul des totaux
    rev = body.revenus
    total_revenus = sum(filter(None, [
        float(rev.revenus_emploi),
        float(rev.revenus_autonome  or 0),
        float(rev.revenus_placement or 0),
        float(rev.revenus_loyer     or 0),
        float(rev.revenus_retraite  or 0),
        float(rev.revenus_assurance or 0),
        float(rev.gains_capital     or 0),
    ]))

    ded = body.deductions
    total_deductions = 0.0
    if ded:
        total_deductions = sum(filter(None, [
            float(ded.cotisation_reer  or 0),
            float(ded.frais_syndicaux  or 0),
            float(ded.frais_garde      or 0),
            float(ded.frais_scolarite  or 0),
            float(ded.frais_medicaux   or 0),
            float(ded.dons             or 0),
        ]))

    decl = Declaration(
        id=confirmation_id,
        processing_id=body.processing_id,
        status="confirmed",
        created_at=now,
        tax_year=session.tax_year,
        app_version=body.app_version,
        submitted_at=body.submitted_at,
        # Identité
        nom=body.identite.nom,
        prenom=body.identite.prenom,
        date_naissance=body.identite.date_naissance,
        langue=body.identite.langue,
        etat_civil=body.identite.etat_civil,
        email=body.identite.email,
        tel=body.identite.tel,
        # Adresse
        adresse=body.adresse.adresse,
        ville=body.adresse.ville,
        code_postal=body.adresse.code_postal,
        # Revenus
        revenus_emploi=float(body.revenus.revenus_emploi),
        impot_retenu_qc=float(body.revenus.impot_retenu_qc),
        total_revenus=round(total_revenus, 2),
        total_deductions=round(total_deductions, 2),
        # Payload complet (sans le NAS en clair)
        full_payload_json=body.model_dump_json(exclude={"identite": {"nas"}}),
    )

    # Hacher le NAS — JAMAIS stocker en clair
    decl.set_nas(body.identite.nas)

    db.add(decl)
    await db.flush()

    logger.info(f"Déclaration confirmée — {confirmation_id} — {body.identite.nom}, {body.identite.prenom}")

    return DeclarationSubmitResponse(
        confirmation_id=confirmation_id,
        processing_id=body.processing_id,
        status="confirmed",
        created_at=now.isoformat(),
        message="Déclaration enregistrée avec succès.",
    )


@router.get(
    "/declarations/{confirmation_id}",
    response_model=DeclarationRecord,
    responses={404: {"model": ErrorResponse}},
    summary="Récupère une déclaration par son identifiant de confirmation",
)
async def get_declaration(
    confirmation_id: str,
    db: AsyncSession = Depends(get_db),
):
    decl = await db.get(Declaration, confirmation_id)
    if not decl:
        raise HTTPException(status_code=404, detail=f"Déclaration {confirmation_id} introuvable.")

    return DeclarationRecord(
        confirmation_id=decl.id,
        processing_id=decl.processing_id,
        status=decl.status,
        created_at=decl.created_at.isoformat(),
        updated_at=decl.updated_at.isoformat() if decl.updated_at else None,
        tax_year=decl.tax_year,
        province="QC",
        identite={
            "nom":        decl.nom,
            "prenom":     decl.prenom,
            "nas_masked": decl.nas_masked,
        },
    )
