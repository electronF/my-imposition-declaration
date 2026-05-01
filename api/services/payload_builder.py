"""
AxOvide — services/payload_builder.py
─────────────────────────────────────────────────────────────
Construit le ExchangePayload complet à partir des résultats
bruts retournés par claude_extractor.

Responsabilités :
  1. Mapper les cases T4/RL-1/CV → champs AxOvide
  2. Effectuer le croisement inter-documents (T4 ↔ RL-1)
  3. Détecter les anomalies et champs à faible confiance
  4. Construire le bloc requires_user avec suggestions CV
  5. Calculer le summary
─────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from config import settings
from schemas import (
    ExchangePayload, ExchangeBlock, MetaBlock, DocumentsReceived,
    PreFilledBlock, RequiresUserBlock, FlagsBlock, SummaryBlock,
    SectionEmploi, SectionAutresRevenus, SectionDeductions,
    SectionIdentite, SectionAdresse, SectionFamiliale,
    ExtractedField, RequiredField,
    AnomalyFlag, LowConfidenceFlag, MissingDocumentFlag, SuggestionFlag,
    CrossCheck,
)


# ── Helpers ───────────────────────────────────────────────────

def _f(
    value: Any,
    field_type: str,
    source: str | None,
    source_box: str | None,
    confidence: float | None,
    raw: str | None = None,
    currency: str | None = None,
    cross_check: CrossCheck | None = None,
) -> ExtractedField:
    """Construit un ExtractedField."""
    return ExtractedField(
        value=value,
        type=field_type,
        source=source,
        source_box=source_box,
        confidence=confidence,
        raw=raw,
        currency=currency,
        cross_check=cross_check,
    )


def _null_field(field_type: str = "decimal") -> ExtractedField:
    """Champ non extrait — valeur null, confiance null."""
    return ExtractedField(value=None, type=field_type, source=None,
                          source_box=None, confidence=None, raw=None)


def _get_case(data: dict, case_key: str) -> tuple[Any, float, str]:
    """Extrait value, confidence et raw d'une case."""
    case = (data.get("cases") or {}).get(case_key, {})
    return (
        case.get("value"),
        case.get("confidence", 0.0) or 0.0,
        case.get("raw") or "",
    )


def _to_float(value: Any) -> float | None:
    """Convertit en float ou retourne None."""
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ".").replace(" ", ""))
    except (ValueError, TypeError):
        return None


# ── Croisement inter-documents ────────────────────────────────

def _cross_check(
    val_t4: Any, conf_t4: float,
    val_rl1: Any, conf_rl1: float,
    t4_box: str, rl1_box: str,
) -> tuple[Any, float, str, str | None, CrossCheck | None, AnomalyFlag | None]:
    """
    Croise la valeur d'une case T4 avec son équivalent RL-1.
    Retourne : (valeur_finale, confiance, source, raw, cross_check, anomalie)
    """
    fv_t4  = _to_float(val_t4)
    fv_rl1 = _to_float(val_rl1)

    # Aucune source disponible
    if fv_t4 is None and fv_rl1 is None:
        return None, 0.0, "T4", None, None, None

    # Une seule source disponible
    if fv_t4 is None:
        return fv_rl1, conf_rl1, "RL-1", str(val_rl1), None, None
    if fv_rl1 is None:
        return fv_t4, conf_t4, "T4", str(val_t4), None, None

    # Les deux sources disponibles — croisement
    match = abs(fv_t4 - fv_rl1) < 0.01   # tolérance 1 centime

    cc = CrossCheck(
        source="RL-1",
        source_box=rl1_box,
        value=fv_rl1,
        match=match,
    )

    anomaly = None
    if not match:
        anomaly = AnomalyFlag(
            code="CROSS_DOC_MISMATCH",
            severity="warning",
            field=f"T4_{t4_box}_vs_RL1_{rl1_box}",
            message=f"Écart détecté : T4 case {t4_box} = {fv_t4} ≠ RL-1 case {rl1_box} = {fv_rl1}",
            action="warn",
            value_t4=fv_t4,
            value_rl1=fv_rl1,
        )

    # Source la plus fiable = celle avec la plus haute confiance
    if conf_t4 >= conf_rl1:
        return fv_t4, conf_t4, "T4", str(val_t4), cc, anomaly
    else:
        return fv_rl1, conf_rl1, "RL-1", str(val_rl1), cc, anomaly


# ── Champs requires_user ──────────────────────────────────────

def _required(
    form_id: str,
    field_type: str,
    block_reason: str,
    suggestion: str | None = None,
    cv_extracted: str | None = None,
    confidence_cv: float | None = None,
    pattern: str | None = None,
    enum_values: list[str] | None = None,
    max_length: int | None = None,
    min_val: float | None = None,
    max_val: float | None = None,
) -> RequiredField:
    return RequiredField(
        value=None,
        type=field_type,
        auto_fill_blocked=True,
        block_reason=block_reason,
        form_id=form_id,
        suggestion=suggestion,
        cv_extracted=cv_extracted,
        confidence_cv=confidence_cv,
        pattern=pattern,
        enum_values=enum_values,
        max_length=max_length,
        min=min_val,
        max=max_val,
    )


# ══════════════════════════════════════════════════════════════
# BUILDER PRINCIPAL
# ══════════════════════════════════════════════════════════════

def build_payload(
    processing_id: str,
    t4_data: dict | None,
    rl1_data: dict | None,
    cv_data: dict | None,
    tax_year: int = 2024,
    locale: str = "fr-CA",
) -> ExchangePayload:
    """
    Construit le ExchangePayload complet à partir des
    résultats bruts des extracteurs Claude.
    """
    anomalies:   list[AnomalyFlag]         = []
    low_conf:    list[LowConfidenceFlag]   = []
    missing:     list[MissingDocumentFlag] = []
    suggestions: list[SuggestionFlag]      = []

    threshold = settings.CONFIDENCE_THRESHOLD

    # ── Helpers internes ──────────────────────────────────────

    def _check_low_conf(field_name: str, value: Any, conf: float, raw: str):
        """Enregistre un flag si confidence < seuil."""
        if conf is not None and conf < threshold and value is not None:
            low_conf.append(LowConfidenceFlag(
                field=field_name,
                confidence=conf,
                threshold=threshold,
                message=f"Confiance faible ({conf:.2f}) pour le champ {field_name}. Vérification manuelle recommandée.",
                raw_ocr=raw,
                corrected=value,
            ))

    # ── Extraction des données T4 ─────────────────────────────
    t4 = t4_data or {}
    rl1 = rl1_data or {}
    cv = cv_data or {}

    # ── Revenus emploi bruts (T4 case 14 ↔ RL-1 case A) ──────
    v14, c14, r14 = _get_case(t4, "case_14")
    vA,  cA,  rA  = _get_case(rl1, "case_A")
    rev_val, rev_conf, rev_src, rev_raw, rev_cc, rev_anom = _cross_check(
        v14, c14, vA, cA, "14", "A"
    )
    if rev_anom: anomalies.append(rev_anom)
    _check_low_conf("revenus_emploi_bruts", rev_val, rev_conf, rev_raw or "")

    # ── Cotisation RRQ (RL-1 case B en priorité) ─────────────
    v26, c26, r26 = _get_case(t4, "case_26")
    vB,  cB,  rB  = _get_case(rl1, "case_B")
    rrq_val  = _to_float(vB) if vB is not None else _to_float(v26)
    rrq_conf = cB if vB is not None else c26
    rrq_src  = "RL-1" if vB is not None else "T4"
    _check_low_conf("cotisation_rrq", rrq_val, rrq_conf, rB or r26)

    # ── Cotisation RQAP (RL-1 case H en priorité) ────────────
    v56, c56, r56 = _get_case(t4, "case_56")
    vH,  cH,  rH  = _get_case(rl1, "case_H")
    rqap_val  = _to_float(vH) if vH is not None else _to_float(v56)
    rqap_conf = cH if vH is not None else c56
    rqap_src  = "RL-1" if vH is not None else "T4"
    _check_low_conf("cotisation_rqap", rqap_val, rqap_conf, rH or r56)

    # ── Cotisation AE (T4 case 18 ↔ RL-1 case C) ─────────────
    v18, c18, r18 = _get_case(t4, "case_18")
    vC,  cC,  rC  = _get_case(rl1, "case_C")
    ae_val, ae_conf, ae_src, ae_raw, ae_cc, ae_anom = _cross_check(
        v18, c18, vC, cC, "18", "C"
    )
    if ae_anom: anomalies.append(ae_anom)

    # ── Impôt provincial (RL-1 case E — source unique) ────────
    vE, cE, rE = _get_case(rl1, "case_E")
    _check_low_conf("impot_provincial_retenu", _to_float(vE), cE, rE)

    # ── Impôt fédéral (T4 case 22 — source unique) ────────────
    v22, c22, r22 = _get_case(t4, "case_22")
    _check_low_conf("impot_federal_retenu", _to_float(v22), c22, r22)

    # ── Cotisation syndicale (T4 44 ↔ RL-1 F) ────────────────
    v44, c44, r44 = _get_case(t4, "case_44")
    vF,  cF,  rF  = _get_case(rl1, "case_F")
    syn_val, syn_conf, syn_src, syn_raw, syn_cc, syn_anom = _cross_check(
        v44, c44, vF, cF, "44", "F"
    )
    if syn_anom: anomalies.append(syn_anom)

    # ── Avantages imposables (T4 40 ↔ RL-1 L) ────────────────
    v40, c40, r40 = _get_case(t4, "case_40")
    vL,  cL,  rL  = _get_case(rl1, "case_L")
    av_val, av_conf, av_src, av_raw, av_cc, av_anom = _cross_check(
        v40, c40, vL, cL, "40", "L"
    )
    if av_anom: anomalies.append(av_anom)

    # ── Employeur ─────────────────────────────────────────────
    emp_nom = (t4.get("employeur") or {}).get("nom")
    emp_neq = (t4.get("employeur") or {}).get("neq")
    emp_c_nom = (t4.get("employeur") or {}).get("confidence_nom", 0.0) or 0.0
    emp_c_neq = (t4.get("employeur") or {}).get("confidence_neq", 0.0) or 0.0

    # ── Extraction CV ─────────────────────────────────────────
    cv_id   = cv.get("identite", {})
    cv_addr = cv.get("coordonnees", {})

    def _cv_val(section: dict, key: str) -> str | None:
        return (section.get(key) or {}).get("value")

    def _cv_conf(section: dict, key: str) -> float | None:
        return (section.get(key) or {}).get("confidence")

    cv_prenom     = _cv_val(cv_id, "prenom")
    cv_nom        = _cv_val(cv_id, "nom")
    cv_langue     = _cv_val(cv_id, "langue_cv")
    cv_adresse    = _cv_val(cv_addr, "adresse")
    cv_ville      = _cv_val(cv_addr, "ville")
    cv_code_post  = _cv_val(cv_addr, "code_postal")
    cv_email      = _cv_val(cv_addr, "email")

    # Suggestions CV
    if cv_adresse or cv_ville or cv_code_post:
        suggestions.append(SuggestionFlag(
            code="ADDRESS_FROM_CV",
            message="Une adresse a été détectée sur le CV et est disponible en suggestion."
        ))
    if cv_langue:
        suggestions.append(SuggestionFlag(
            code="LANG_INFERRED",
            message=f"Langue '{cv_langue}' inférée depuis la langue de rédaction du CV."
        ))

    # ── Missing documents ─────────────────────────────────────
    missing.append(MissingDocumentFlag(
        code="MISSING_REER_RECEIPT",
        severity="info",
        message="Aucun reçu REER (T4RSP) fourni. Requis pour déduire les cotisations REER."
    ))
    missing.append(MissingDocumentFlag(
        code="MISSING_T5",
        severity="info",
        message="Aucun relevé T5 fourni. Requis si vous avez des revenus de placements."
    ))

    # ══ Construire pre_filled ══════════════════════════════════

    pre_filled = PreFilledBlock(
        section_emploi=SectionEmploi(
            employeur=_f(emp_nom, "string", "T4", "case_54", emp_c_nom, str(emp_nom or "")),
            neq_employeur=_f(emp_neq, "string", "T4", "case_54", emp_c_neq, str(emp_neq or "")),
            revenus_emploi_bruts=_f(rev_val, "decimal", rev_src, f"case_{rev_src=='T4' and '14' or 'A'}", rev_conf, rev_raw, "CAD", rev_cc),
            cotisation_rrq=_f(_to_float(rrq_val), "decimal", rrq_src, "case_B", rrq_conf, rB or r26, "CAD"),
            cotisation_rqap=_f(_to_float(rqap_val), "decimal", rqap_src, "case_H", rqap_conf, rH or r56, "CAD"),
            cotisation_ae=_f(ae_val, "decimal", ae_src, f"case_{ae_src=='T4' and '18' or 'C'}", ae_conf, ae_raw, "CAD", ae_cc),
            impot_provincial_retenu=_f(_to_float(vE), "decimal", "RL-1", "case_E", cE, rE, "CAD"),
            impot_federal_retenu=_f(_to_float(v22), "decimal", "T4", "case_22", c22, r22, "CAD"),
            cotisation_syndicale=_f(syn_val, "decimal", syn_src, f"case_{syn_src=='T4' and '44' or 'F'}", syn_conf, syn_raw, "CAD", syn_cc),
            avantages_imposables=_f(av_val, "decimal", av_src, f"case_{av_src=='T4' and '40' or 'L'}", av_conf, av_raw, "CAD", av_cc),
        ),
        section_autres_revenus=SectionAutresRevenus(
            revenus_autonome=_null_field("decimal"),
            revenus_placement=_null_field("decimal"),
        ),
        section_deductions=SectionDeductions(
            cotisation_reer=_null_field("decimal"),
            frais_syndicaux=_f(syn_val, "decimal", syn_src, None, syn_conf, syn_raw, "CAD"),
        ),
    )

    # ══ Construire requires_user ═══════════════════════════════

    requires_user = RequiresUserBlock(
        section_identite=SectionIdentite(
            nom=_required("nom", "string",
                "LEGAL_PRIVACY — Nom légal : doit être confirmé par le déclarant.",
                suggestion=cv_nom, cv_extracted=cv_nom,
                confidence_cv=_cv_conf(cv_id, "nom"), max_length=100),
            prenom=_required("prenom", "string",
                "LEGAL_PRIVACY — Prénom légal : doit être confirmé par le déclarant.",
                suggestion=cv_prenom, cv_extracted=cv_prenom,
                confidence_cv=_cv_conf(cv_id, "prenom"), max_length=100),
            nas=_required("nas", "string",
                "SENSITIVE_ID — Le NAS est une donnée ultra-sensible. Jamais extrait automatiquement.",
                pattern=r"^\d{3} \d{3} \d{3}$"),
            ddn=_required("ddn", "date",
                "SENSITIVE_ID — La date de naissance n'est pas présente sur les documents fiscaux canadiens."),
            langue=_required("langue", "enum",
                "PREFERENCE — Langue de correspondance. Suggestion basée sur la langue du CV.",
                suggestion=cv_langue,
                cv_extracted=cv_langue,
                confidence_cv=_cv_conf(cv_id, "langue_cv"),
                enum_values=["fr", "en"]),
            etat_civil=_required("etat-civil", "enum",
                "PERSONAL — État civil non disponible sur les documents fiscaux.",
                enum_values=["celibataire", "marie", "separe", "divorce", "veuf"]),
        ),
        section_adresse=SectionAdresse(
            adresse=_required("adresse", "string",
                "LEGAL_PRIVACY — L'adresse fiscale peut différer de l'adresse du CV.",
                suggestion=cv_adresse, cv_extracted=cv_adresse,
                confidence_cv=_cv_conf(cv_addr, "adresse")),
            ville=_required("ville", "string",
                "LEGAL_PRIVACY — Ville fiscale : doit être confirmée.",
                suggestion=cv_ville, cv_extracted=cv_ville,
                confidence_cv=_cv_conf(cv_addr, "ville"), max_length=100),
            code_postal=_required("code-postal", "string",
                "LEGAL_PRIVACY — Code postal fiscal : doit être confirmé.",
                suggestion=cv_code_post, cv_extracted=cv_code_post,
                confidence_cv=_cv_conf(cv_addr, "code_postal"),
                pattern=r"^[A-Z]\d[A-Z] \d[A-Z]\d$"),
        ),
        section_familiale=SectionFamiliale(
            nb_enfants=_required("nb-enfants", "integer",
                "PERSONAL — Nombre d'enfants non disponible sur les documents fiscaux.",
                min_val=0, max_val=20),
            conjoint_revenu=_required("conjoint-revenu", "decimal",
                "THIRD_PARTY — Revenu du conjoint : appartient à un tiers."),
            statut_residence=_required("locataire", "enum",
                "PERSONAL — Statut de résidence non disponible sur les documents fiscaux.",
                enum_values=["locataire", "proprietaire", "autre"]),
        ),
    )

    # ══ Calculer le summary ════════════════════════════════════

    # Compter les champs pré-remplis (value != null)
    pre_values = [
        rev_val, rrq_val, rqap_val, ae_val,
        _to_float(vE), _to_float(v22), syn_val,
        emp_nom, emp_neq,
    ]
    champs_pre  = sum(1 for v in pre_values if v is not None)
    champs_user = 12   # nombre fixe de champs requires_user
    champs_total = champs_pre + champs_user

    total_revenus   = float(rev_val or 0)
    total_retenues  = float(_to_float(vE) or 0) + float(_to_float(v22) or 0)

    summary = SummaryBlock(
        total_revenus_connus=round(total_revenus, 2),
        total_retenues_connues=round(total_retenues, 2),
        champs_pre_remplis=champs_pre,
        champs_utilisateur=champs_user,
        champs_total=champs_total,
        taux_completion_auto=round(champs_pre / champs_total, 2) if champs_total > 0 else 0.0,
        currency="CAD",
    )

    # ══ Assembler le payload ═══════════════════════════════════

    return ExchangePayload(
        meta=MetaBlock(
            protocol_version=settings.PROTOCOL_VERSION,
            generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            processing_id=processing_id,
            documents_received=DocumentsReceived(
                cv=cv_data is not None,
                t4=t4_data is not None,
                rl1=rl1_data is not None,
            ),
            ocr_engine=settings.OCR_ENGINE,
            locale=locale,
            tax_year=tax_year,
            province="QC",
        ),
        exchange=ExchangeBlock(
            pre_filled=pre_filled,
            requires_user=requires_user,
            flags=FlagsBlock(
                anomalies=anomalies,
                low_confidence_fields=low_conf,
                missing_documents=missing,
                suggestions=suggestions,
            ),
            summary=summary,
        ),
    )
