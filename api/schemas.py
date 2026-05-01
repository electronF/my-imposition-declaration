"""
AxOvide — schemas.py
─────────────────────────────────────────────────────────────
Tous les schémas Pydantic v2 du projet.

Convention :
  - *Request  → validation des données entrantes
  - *Response → sérialisation des données sortantes
  - *Block    → sous-objets du ExchangePayload
─────────────────────────────────────────────────────────────
"""

from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from pydantic import BaseModel, Field, model_validator, EmailStr


# ══════════════════════════════════════════════════════════════
# BLOCS COMMUNS DU EXCHANGE PAYLOAD
# ══════════════════════════════════════════════════════════════

class CrossCheck(BaseModel):
    """Résultat du croisement inter-documents (T4 ↔ RL-1)."""
    source:     Literal["T4", "RL-1", "CV"]
    source_box: str
    value:      Any | None
    match:      bool


class ExtractedField(BaseModel):
    """
    Champ pré-rempli automatiquement depuis un document source.
    Chaque champ du bloc pre_filled suit cette structure.
    """
    value:      Any | None = None
    type:       str
    currency:   str | None = None          # "CAD" pour les montants
    source:     Literal["T4", "RL-1", "CV"] | None = None
    source_box: str | None = None
    confidence: float | None = Field(None, ge=0.0, le=1.0)
    raw:        str | None = None          # texte brut OCR
    cross_check: CrossCheck | None = None


class RequiredField(BaseModel):
    """
    Champ qui nécessite une saisie obligatoire de l'utilisateur.
    auto_fill_blocked est TOUJOURS true.
    """
    value:             None = None         # toujours null
    type:              str
    auto_fill_blocked: Literal[True] = True
    block_reason:      str
    form_id:           str
    suggestion:        str | None = None   # suggestion issue du CV
    cv_extracted:      str | None = None
    confidence_cv:     float | None = Field(None, ge=0.0, le=1.0)
    pattern:           str | None = None   # regex validation client
    enum_values:       list[str] | None = None
    max_length:        int | None = None
    min:               float | None = None
    max:               float | None = None


# ── Blocs pre_filled ─────────────────────────────────────────

class SectionEmploi(BaseModel):
    employeur:               ExtractedField
    neq_employeur:           ExtractedField
    revenus_emploi_bruts:    ExtractedField
    cotisation_rrq:          ExtractedField
    cotisation_rqap:         ExtractedField
    cotisation_ae:           ExtractedField
    impot_provincial_retenu: ExtractedField
    impot_federal_retenu:    ExtractedField
    cotisation_syndicale:    ExtractedField
    avantages_imposables:    ExtractedField


class SectionAutresRevenus(BaseModel):
    revenus_autonome:  ExtractedField
    revenus_placement: ExtractedField


class SectionDeductions(BaseModel):
    cotisation_reer: ExtractedField
    frais_syndicaux: ExtractedField


class PreFilledBlock(BaseModel):
    section_emploi:        SectionEmploi
    section_autres_revenus: SectionAutresRevenus
    section_deductions:    SectionDeductions


# ── Blocs requires_user ──────────────────────────────────────

class SectionIdentite(BaseModel):
    nom:       RequiredField
    prenom:    RequiredField
    nas:       RequiredField
    ddn:       RequiredField
    langue:    RequiredField
    etat_civil: RequiredField


class SectionAdresse(BaseModel):
    adresse:     RequiredField
    ville:       RequiredField
    code_postal: RequiredField


class SectionFamiliale(BaseModel):
    nb_enfants:       RequiredField
    conjoint_revenu:  RequiredField
    statut_residence: RequiredField


class RequiresUserBlock(BaseModel):
    section_identite: SectionIdentite
    section_adresse:  SectionAdresse
    section_familiale: SectionFamiliale


# ── Flags ────────────────────────────────────────────────────

class AnomalyFlag(BaseModel):
    code:      Literal["CROSS_DOC_MISMATCH", "OCR_FAILURE", "UNSUPPORTED_FORMAT"]
    severity:  Literal["error", "warning", "info"]
    field:     str
    message:   str
    action:    Literal["block", "warn", "none"]
    value_t4:  float | None = None
    value_rl1: float | None = None


class LowConfidenceFlag(BaseModel):
    field:      str
    confidence: float
    threshold:  float = 0.95
    message:    str
    raw_ocr:    str
    corrected:  Any | None


class MissingDocumentFlag(BaseModel):
    code:     Literal["MISSING_T5", "MISSING_REER_RECEIPT", "MISSING_T2202", "MISSING_T4E", "MISSING_RL3"]
    severity: Literal["error", "warning", "info"] = "info"
    message:  str


class SuggestionFlag(BaseModel):
    code:    Literal["ADDRESS_FROM_CV", "LANG_INFERRED", "EMPLOYER_MULTIPLE_T4"]
    message: str


class FlagsBlock(BaseModel):
    anomalies:            list[AnomalyFlag]        = []
    low_confidence_fields: list[LowConfidenceFlag] = []
    missing_documents:    list[MissingDocumentFlag] = []
    suggestions:          list[SuggestionFlag]      = []


# ── Summary ──────────────────────────────────────────────────

class SummaryBlock(BaseModel):
    total_revenus_connus:   float
    total_retenues_connues: float
    champs_pre_remplis:     int
    champs_utilisateur:     int
    champs_total:           int
    taux_completion_auto:   float = Field(ge=0.0, le=1.0)
    currency:               Literal["CAD"] = "CAD"


# ── Meta ─────────────────────────────────────────────────────

class DocumentsReceived(BaseModel):
    cv:  bool
    t4:  bool
    rl1: bool


class MetaBlock(BaseModel):
    protocol_version:   str = "1.0.0"
    generated_at:       str
    processing_id:      str
    documents_received: DocumentsReceived
    ocr_engine:         str
    locale:             Literal["fr-CA", "en-CA"] = "fr-CA"
    tax_year:           int
    province:           Literal["QC"] = "QC"


# ── ExchangePayload complet ──────────────────────────────────

class ExchangeBlock(BaseModel):
    pre_filled:    PreFilledBlock
    requires_user: RequiresUserBlock
    flags:         FlagsBlock
    summary:       SummaryBlock


class ExchangePayload(BaseModel):
    """Réponse complète de POST /v1/extract."""
    meta:     MetaBlock
    exchange: ExchangeBlock


# ══════════════════════════════════════════════════════════════
# SCHÉMAS DE REQUÊTE — POST /v1/extract
# ══════════════════════════════════════════════════════════════

class ExtractQueryParams(BaseModel):
    """Paramètres optionnels de la requête d'extraction."""
    tax_year: int = Field(2024, ge=2020, le=2030)
    locale:   Literal["fr-CA", "en-CA"] = "fr-CA"


# ══════════════════════════════════════════════════════════════
# SCHÉMAS DE REQUÊTE — POST /v1/declarations
# ══════════════════════════════════════════════════════════════

class IdentiteModel(BaseModel):
    nom:            str    = Field(..., max_length=100)
    prenom:         str    = Field(..., max_length=100)
    nas:            str    = Field(..., pattern=r"^\d{3} \d{3} \d{3}$")
    date_naissance: date
    langue:         Literal["fr", "en"]
    etat_civil:     Literal["celibataire", "marie", "separe", "divorce", "veuf"]
    email:          EmailStr | None = None
    tel:            str | None = None


class AdresseModel(BaseModel):
    adresse:     str
    ville:       str    = Field(..., max_length=100)
    code_postal: str    = Field(..., pattern=r"^[A-Z]\d[A-Z] \d[A-Z]\d$")


class RevenusModel(BaseModel):
    employeur:         str | None     = None
    neq:               str | None     = None
    revenus_emploi:    Decimal        = Field(..., ge=0)
    cotisation_rq:     Decimal | None = Field(None, ge=0)
    cotisation_rqap:   Decimal | None = Field(None, ge=0)
    cotisation_ae:     Decimal | None = Field(None, ge=0)
    impot_retenu_qc:   Decimal        = Field(..., ge=0)
    impot_retenu_fed:  Decimal | None = Field(None, ge=0)
    revenus_autonome:  Decimal | None = Field(None, ge=0)
    revenus_placement: Decimal | None = Field(None, ge=0)
    revenus_loyer:     Decimal | None = Field(None, ge=0)
    revenus_retraite:  Decimal | None = Field(None, ge=0)
    revenus_assurance: Decimal | None = Field(None, ge=0)
    gains_capital:     Decimal | None = Field(None, ge=0)


class DeductionsModel(BaseModel):
    cotisation_reer:  Decimal | None = Field(None, ge=0)
    frais_syndicaux:  Decimal | None = Field(None, ge=0)
    frais_garde:      Decimal | None = Field(None, ge=0)
    frais_scolarite:  Decimal | None = Field(None, ge=0)
    frais_medicaux:   Decimal | None = Field(None, ge=0)
    dons:             Decimal | None = Field(None, ge=0)


class SituationFamilialeModel(BaseModel):
    nb_enfants:        int | None     = Field(None, ge=0, le=20)
    conjoint_revenu:   Decimal | None = Field(None, ge=0)
    credit_solidarite: Literal["oui", "non"] | None = None
    statut_residence:  Literal["locataire", "proprietaire", "autre"] | None = None
    loyer_paye:        Decimal | None = Field(None, ge=0)
    taxes_municipales: Decimal | None = Field(None, ge=0)


class AttestationModel(BaseModel):
    acceptee:       Literal[True]    # False → 422
    signature:      str
    date_signature: date


class DeclarationSubmitRequest(BaseModel):
    processing_id:       str      = Field(..., pattern=r"^proc_[0-9a-f-]{36}$")
    app_version:         str
    submitted_at:        datetime
    identite:            IdentiteModel
    adresse:             AdresseModel
    revenus:             RevenusModel
    deductions:          DeductionsModel | None = None
    situation_familiale: SituationFamilialeModel | None = None
    attestation:         AttestationModel
    notes:               str | None = Field(None, max_length=2000)


# ══════════════════════════════════════════════════════════════
# SCHÉMAS DE RÉPONSE
# ══════════════════════════════════════════════════════════════

class DeclarationSubmitResponse(BaseModel):
    confirmation_id: str
    processing_id:   str
    status:          Literal["received", "processing", "confirmed", "error"]
    created_at:      str
    message:         str


class DeclarationRecord(BaseModel):
    confirmation_id: str
    processing_id:   str
    status:          str
    created_at:      str
    updated_at:      str | None
    tax_year:        int
    province:        str = "QC"
    identite: dict | None = None
    revenus_summary: SummaryBlock | None = None


class HealthResponse(BaseModel):
    status:    Literal["ok", "degraded", "down"]
    version:   str
    timestamp: str
    ocr_engine: dict


class ErrorResponse(BaseModel):
    error:         str
    detail:        str | Any
    processing_id: str | None = None
