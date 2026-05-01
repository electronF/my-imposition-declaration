"""
AxOvide — services/claude_extractor.py
─────────────────────────────────────────────────────────────
Pipeline d'extraction OCR via Claude (Anthropic).

Stratégie par document :
  1. Tenter l'extraction texte native (pdfplumber / python-docx)
  2. Si texte insuffisant ou PDF image → convertir en image et
     envoyer à Claude vision (claude-opus-4-5 supporte les images)
  3. Parser la réponse JSON de Claude
  4. Retourner un dict structuré avec scores de confiance

Claude est utilisé pour TOUT l'OCR — y compris les PDFs scannés
(images) qui sont les cas les plus fréquents pour les T4 et RL-1.
─────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
from pathlib import Path
from typing import Any

import anthropic
import pdfplumber
from PIL import Image

from config import settings

logger = logging.getLogger(__name__)

# ── Client Anthropic (singleton) ─────────────────────────────
_client: anthropic.AsyncAnthropic | None = None


def get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


# ── Chargement des prompts ────────────────────────────────────

def _load_prompt(name: str, **kwargs) -> str:
    """Charge un prompt depuis /prompts/ et applique les substitutions."""
    path = Path(__file__).parent.parent / "prompts" / f"{name}.txt"
    text = path.read_text(encoding="utf-8")
    for key, val in kwargs.items():
        text = text.replace("{" + key + "}", str(val))
    return text


# ── Utilitaires PDF → image ───────────────────────────────────

def _pdf_has_text(pdf_bytes: bytes, min_chars: int = 50) -> bool:
    """
    Vérifie si un PDF contient suffisamment de texte extractible.
    Un PDF scanné retourne moins de min_chars caractères.
    """
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            total = sum(len(p.extract_text() or "") for p in pdf.pages)
            return total >= min_chars
    except Exception:
        return False


def _pdf_to_images_base64(pdf_bytes: bytes, dpi: int = 200) -> list[str]:
    """
    Convertit chaque page d'un PDF en image PNG encodée en base64.
    Utilisé quand le PDF est un scan (pas de texte natif).

    DPI 200 = bon compromis qualité/taille pour Claude vision.
    Claude accepte des images jusqu'à 5 Mo par image.
    """
    try:
        from pdf2image import convert_from_bytes
        images = convert_from_bytes(pdf_bytes, dpi=dpi, fmt="png")
        result = []
        for img in images:
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            result.append(base64.standard_b64encode(buf.getvalue()).decode())
        return result
    except ImportError:
        logger.warning("pdf2image non disponible — fallback PIL")
        return _pdf_to_images_pil_fallback(pdf_bytes)
    except Exception as e:
        logger.error(f"Erreur conversion PDF→image : {e}")
        return []


def _pdf_to_images_pil_fallback(pdf_bytes: bytes) -> list[str]:
    """Fallback si pdf2image/poppler non disponible."""
    try:
        img = Image.open(io.BytesIO(pdf_bytes))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return [base64.standard_b64encode(buf.getvalue()).decode()]
    except Exception:
        return []


def _extract_text_native(pdf_bytes: bytes) -> str:
    """Extrait le texte natif d'un PDF (non-scanné)."""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            return "\n".join(p.extract_text() or "" for p in pdf.pages)
    except Exception:
        return ""


def _extract_docx_text(docx_bytes: bytes) -> str:
    """Extrait le texte d'un fichier DOCX (pour les CV)."""
    try:
        import docx
        doc = docx.Document(io.BytesIO(docx_bytes))
        return "\n".join(p.text for p in doc.paragraphs)
    except Exception:
        return ""


# ── Parsing de la réponse Claude ─────────────────────────────

def _parse_claude_json(response_text: str) -> dict[str, Any]:
    """
    Extrait et parse le JSON de la réponse Claude.
    Claude peut parfois wrapper le JSON dans des balises markdown.
    """
    # Retirer les balises markdown si présentes
    clean = re.sub(r"```(?:json)?\s*", "", response_text).strip()
    clean = clean.rstrip("```").strip()

    try:
        return json.loads(clean)
    except json.JSONDecodeError as e:
        logger.error(f"Impossible de parser le JSON Claude : {e}\nRéponse : {clean[:500]}")
        return {}


# ── Appel Claude avec texte ───────────────────────────────────

async def _call_claude_text(prompt: str, text_content: str) -> dict[str, Any]:
    """Appel Claude avec du texte natif extrait."""
    client = get_client()

    message = await client.messages.create(
        model=settings.CLAUDE_MODEL,
        max_tokens=2000,
        messages=[
            {
                "role": "user",
                "content": f"{prompt}\n\nVoici le contenu du document :\n\n{text_content}"
            }
        ]
    )

    return _parse_claude_json(message.content[0].text)


# ── Appel Claude avec images (vision) ────────────────────────

async def _call_claude_vision(prompt: str, images_b64: list[str]) -> dict[str, Any]:
    """
    Appel Claude avec images encodées en base64.
    Utilisé pour les PDFs scannés (images).
    Claude claude-opus-4-5 supporte le vision multi-image.
    """
    client = get_client()

    # Construction du message multi-image
    content: list[dict] = []

    for img_b64 in images_b64:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": img_b64,
            }
        })

    content.append({"type": "text", "text": prompt})

    message = await client.messages.create(
        model=settings.CLAUDE_MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": content}]
    )

    return _parse_claude_json(message.content[0].text)


# ══════════════════════════════════════════════════════════════
# EXTRACTEURS PAR TYPE DE DOCUMENT
# ══════════════════════════════════════════════════════════════

async def extract_t4(file_bytes: bytes, tax_year: int = 2024) -> dict[str, Any]:
    """
    Extrait les données d'un feuillet T4.

    Stratégie :
      1. PDF avec texte → extraction native → Claude texte
      2. PDF scanné (image) → conversion PNG → Claude vision
    """
    prompt = _load_prompt("extract_t4", tax_year=tax_year)
    is_image_based = False

    if _pdf_has_text(file_bytes):
        logger.info("T4 : extraction texte native")
        text = _extract_text_native(file_bytes)
        result = await _call_claude_text(prompt, text)
    else:
        logger.info("T4 : PDF image détecté → Claude vision")
        is_image_based = True
        images = _pdf_to_images_base64(file_bytes)
        if not images:
            logger.error("T4 : impossible de convertir le PDF en images")
            return _empty_t4_result(tax_year)
        result = await _call_claude_vision(prompt, images)

    result["is_image_based"] = is_image_based
    return result


async def extract_rl1(file_bytes: bytes, tax_year: int = 2024) -> dict[str, Any]:
    """
    Extrait les données d'un relevé RL-1.
    Même stratégie que le T4.
    """
    prompt = _load_prompt("extract_rl1", tax_year=tax_year)
    is_image_based = False

    if _pdf_has_text(file_bytes):
        logger.info("RL-1 : extraction texte native")
        text = _extract_text_native(file_bytes)
        result = await _call_claude_text(prompt, text)
    else:
        logger.info("RL-1 : PDF image détecté → Claude vision")
        is_image_based = True
        images = _pdf_to_images_base64(file_bytes)
        if not images:
            return _empty_rl1_result(tax_year)
        result = await _call_claude_vision(prompt, images)

    result["is_image_based"] = is_image_based
    return result


async def extract_cv(file_bytes: bytes, mime_type: str = "application/pdf") -> dict[str, Any]:
    """
    Extrait les informations d'identité depuis un CV (PDF ou DOCX).

    Pour les DOCX : extraction texte native sans vision.
    Pour les PDF  : même stratégie que T4/RL-1.
    """
    prompt = _load_prompt("extract_cv")

    # DOCX — extraction texte native
    if "wordprocessingml" in mime_type or mime_type == "application/msword":
        logger.info("CV : DOCX détecté → extraction texte native")
        text = _extract_docx_text(file_bytes)
        if text.strip():
            return await _call_claude_text(prompt, text)

    # PDF avec texte
    if _pdf_has_text(file_bytes):
        logger.info("CV : PDF texte → extraction native")
        text = _extract_text_native(file_bytes)
        return await _call_claude_text(prompt, text)

    # PDF image
    logger.info("CV : PDF image détecté → Claude vision")
    images = _pdf_to_images_base64(file_bytes)
    if not images:
        return _empty_cv_result()
    return await _call_claude_vision(prompt, images)


# ── Résultats vides (fallback en cas d'échec) ─────────────────

def _null_field(raw: str = "") -> dict:
    return {"value": None, "raw": raw, "confidence": 0.0}


def _empty_t4_result(tax_year: int) -> dict:
    cases = {f"case_{c}": _null_field() for c in ["14","18","22","26","40","44","54","55","56"]}
    return {
        "document_type": "T4", "tax_year": tax_year,
        "employeur": {"nom": None, "neq": None, "confidence_nom": 0.0, "confidence_neq": 0.0},
        "cases": cases, "is_image_based": True,
        "ocr_notes": "Échec de conversion — document non traitable"
    }


def _empty_rl1_result(tax_year: int) -> dict:
    cases = {f"case_{c}": _null_field() for c in ["A","B","C","E","F","G","H","I","L"]}
    return {
        "document_type": "RL-1", "tax_year": tax_year,
        "employeur": {"nom": None, "id_revenu_quebec": None, "confidence_nom": 0.0, "confidence_id": 0.0},
        "cases": cases, "is_image_based": True,
        "ocr_notes": "Échec de conversion — document non traitable"
    }


def _empty_cv_result() -> dict:
    null = {"value": None, "confidence": None}
    return {
        "document_type": "CV",
        "identite": {"prenom": null, "nom": null, "langue_cv": null},
        "coordonnees": {
            "adresse": null, "ville": null, "province": null,
            "code_postal": null, "email": null, "telephone": null
        },
        "ocr_notes": "Échec de conversion — document non traitable"
    }
