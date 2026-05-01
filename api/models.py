"""
AxOvide — models.py
─────────────────────────────────────────────────────────────
3 tables SQLAlchemy :
  - ExtractionSession  : chaque appel POST /v1/extract
  - Declaration        : chaque déclaration finale soumise
  - DeclarationFlag    : flags OCR liés à une session
─────────────────────────────────────────────────────────────
"""

import hashlib
from datetime import datetime, date
from sqlalchemy import (
    String, Integer, Float, Boolean, Text, DateTime,
    Date, Numeric, ForeignKey, event
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base


# ── TABLE 1 : Sessions d'extraction ──────────────────────────

class ExtractionSession(Base):
    """
    Enregistre chaque appel à POST /v1/extract.
    Clé primaire : processing_id (proc_<uuid4>).
    Le payload JSON complet est stocké pour audit.
    """
    __tablename__ = "extraction_sessions"

    # Identifiant unique — format : proc_<uuid4>
    id: Mapped[str] = mapped_column(String, primary_key=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    tax_year:   Mapped[int]  = mapped_column(Integer, nullable=False, default=2024)
    province:   Mapped[str]  = mapped_column(String(2), default="QC")
    locale:     Mapped[str]  = mapped_column(String(5), default="fr-CA")
    ocr_engine: Mapped[str]  = mapped_column(String, default="axovide-ocr/1.0.0")

    # Documents reçus
    has_cv:  Mapped[bool] = mapped_column(Boolean, default=False)
    has_t4:  Mapped[bool] = mapped_column(Boolean, default=False)
    has_rl1: Mapped[bool] = mapped_column(Boolean, default=False)

    # Taux de remplissage automatique (0.0 - 1.0)
    completion_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ExchangePayload sérialisé en JSON (pour audit et replay)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relations
    declaration: Mapped["Declaration | None"] = relationship(
        back_populates="session", uselist=False
    )
    flags: Mapped[list["DeclarationFlag"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


# ── TABLE 2 : Déclarations finales ───────────────────────────

class Declaration(Base):
    """
    Enregistre chaque déclaration finale soumise via POST /v1/declarations.
    Clé primaire : confirmation_id (decl_<uuid4>).
    Clé étrangère : processing_id → extraction_sessions.id
    """
    __tablename__ = "declarations"

    # Identifiant unique — format : decl_<uuid4>
    id: Mapped[str] = mapped_column(String, primary_key=True)

    # Lien vers la session d'extraction
    processing_id: Mapped[str] = mapped_column(
        String, ForeignKey("extraction_sessions.id"), nullable=False
    )

    status: Mapped[str] = mapped_column(String, default="confirmed")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    tax_year:   Mapped[int]  = mapped_column(Integer, nullable=False, default=2024)
    app_version: Mapped[str | None] = mapped_column(String, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # ── Identité ─────────────────────────────────────────────
    nom:    Mapped[str | None] = mapped_column(String(100), nullable=True)
    prenom: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # NAS : jamais en clair — SHA-256 + 3 derniers chiffres pour affichage
    nas_hash:  Mapped[str | None] = mapped_column(String(64), nullable=True)
    nas_last3: Mapped[str | None] = mapped_column(String(3),  nullable=True)

    date_naissance: Mapped[date | None] = mapped_column(Date, nullable=True)
    langue:     Mapped[str | None] = mapped_column(String(2), nullable=True)
    etat_civil: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email:      Mapped[str | None] = mapped_column(String(255), nullable=True)
    tel:        Mapped[str | None] = mapped_column(String(30), nullable=True)

    # ── Adresse ──────────────────────────────────────────────
    adresse:     Mapped[str | None] = mapped_column(String(300), nullable=True)
    ville:       Mapped[str | None] = mapped_column(String(100), nullable=True)
    code_postal: Mapped[str | None] = mapped_column(String(7),   nullable=True)

    # ── Revenus principaux ───────────────────────────────────
    revenus_emploi:  Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    impot_retenu_qc: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    total_revenus:   Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    total_deductions: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)

    # Payload complet JSON (toutes les données soumises)
    full_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relations
    session: Mapped["ExtractionSession"] = relationship(back_populates="declaration")

    def set_nas(self, nas_plain: str) -> None:
        """
        Hache le NAS et stocke les 3 derniers chiffres.
        Le NAS en clair n'est JAMAIS persisté.
        """
        normalized = nas_plain.replace(" ", "")
        self.nas_hash  = hashlib.sha256(normalized.encode()).hexdigest()
        self.nas_last3 = normalized[-3:] if len(normalized) >= 3 else normalized

    @property
    def nas_masked(self) -> str:
        """Retourne le NAS masqué pour affichage : *** *** 789"""
        if not self.nas_last3:
            return "*** *** ***"
        return f"*** *** {self.nas_last3}"


# ── TABLE 3 : Flags d'extraction ─────────────────────────────

class DeclarationFlag(Base):
    """
    Stocke les flags OCR émis lors de l'extraction.
    Liés à une session d'extraction (processing_id).
    Permet l'audit de qualité et le reporting.
    """
    __tablename__ = "declaration_flags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    processing_id: Mapped[str] = mapped_column(
        String, ForeignKey("extraction_sessions.id"), nullable=False
    )

    # Type : "anomaly" | "low_confidence" | "missing" | "suggestion"
    flag_type: Mapped[str] = mapped_column(String(20), nullable=False)

    # Code machine : "CROSS_DOC_MISMATCH", "OCR_FAILURE", etc.
    code: Mapped[str] = mapped_column(String(50), nullable=False)

    # Sévérité : "error" | "warning" | "info"
    severity: Mapped[str] = mapped_column(String(10), nullable=False, default="info")

    # Champ concerné (nullable si flag global)
    field: Mapped[str | None] = mapped_column(String(100), nullable=True)

    message: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # Relations
    session: Mapped["ExtractionSession"] = relationship(back_populates="flags")
