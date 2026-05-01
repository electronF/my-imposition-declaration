# AxOvide — Rapport technique

**Version** 1.0.0 · **Province** Québec · **Exercice fiscal** 2024
**Stack** Python 3.11 · FastAPI · Claude (Anthropic) · SQLAlchemy · SQLite

---

## Ce que fait le projet

AxOvide est une **extension Chrome** qui automatise le remplissage d'un formulaire de déclaration de revenus québécois. L'utilisateur téléverse ses documents fiscaux (CV, T4, RL-1) et l'extension pré-remplit automatiquement le formulaire grâce à un backend FastAPI qui utilise Claude comme moteur OCR.

---

## Architecture en deux parties

```
Extension Chrome (frontend)          Backend FastAPI (Python)
────────────────────────────         ──────────────────────────────────
popup.html + popup.js                main.py
fileValidator.js                     ├── routers/extract.py
                                     ├── routers/declarations.py
     ① Upload fichiers               ├── routers/health.py
     ──────────────────►             ├── services/claude_extractor.py
                                     ├── services/payload_builder.py
     ◄──────────────────             ├── schemas.py
     ② JSON pré-rempli               ├── models.py
                                     ├── database.py (SQLite)
     ③ Formulaire complété           └── prompts/ (T4, RL-1, CV)
     ──────────────────►
     ◄──────────────────
     ④ confirmation_id
```

---

## Les deux appels API

### 1. `POST /v1/extract` — Extraction OCR

L'extension envoie les 3 fichiers. Le backend les lit, envoie chaque document à Claude avec un prompt spécialisé, croise les données T4 ↔ RL-1, et retourne un `ExchangePayload` structuré.

**Entrée :** `multipart/form-data` avec `cv_file`, `t4_file`, `rl1_file`

**Sortie :** JSON avec 4 blocs :
- `pre_filled` — champs extraits automatiquement (revenus, cotisations, employeur)
- `requires_user` — champs que l'utilisateur doit saisir (NAS, date de naissance, état civil)
- `flags` — anomalies détectées, champs à faible confiance, documents manquants
- `summary` — total revenus, total retenues, taux de remplissage automatique

### 2. `POST /v1/declarations` — Soumission finale

L'extension envoie le formulaire complet (pré-rempli + saisi manuellement). Le backend valide avec Pydantic, hache le NAS (SHA-256), persiste en SQLite, retourne un `confirmation_id`.

---

## Pipeline OCR — comment Claude lit les documents

```
Fichier reçu
     │
     ▼
PDF a du texte natif ?  ──Oui──►  pdfplumber extrait le texte
     │                             │
     Non                           ▼
     │                    Claude lit le texte + prompt
     ▼                             │
Convertir PDF → PNG                ▼
(pdf2image / PIL)         Retourne JSON structuré
     │                    avec valeurs + scores de confiance
     ▼
Claude vision lit l'image
+ prompt spécialisé
     │
     ▼
Retourne JSON structuré
```

**Pourquoi Claude et pas un OCR classique ?**
Les T4 et RL-1 sont souvent des scans de qualité variable. Claude vision comprend la *sémantique* du document — il sait que "Case 14" est un revenu d'emploi, même si la mise en page est différente d'un employeur à l'autre. Un OCR classique (Tesseract) ne fait que lire des pixels sans comprendre la structure fiscale.

---

## Structure des fichiers

```
axovide-backend/
├── main.py                    Point d'entrée — FastAPI + CORS + routeurs
├── config.py                  Variables d'environnement (lues depuis .env.*)
├── database.py                Connexion SQLAlchemy async + session
├── models.py                  3 tables ORM : ExtractionSession, Declaration, DeclarationFlag
├── schemas.py                 Tous les modèles Pydantic (validation + sérialisation)
├── requirements.txt           Dépendances Python avec versions fixées
├── .env.dev                   Config développement (ne pas commiter)
├── .env.preprod               Config préproduction (ne pas commiter)
├── .env.prod                  Config production (ne pas commiter)
├── prompts/
│   ├── extract_t4.txt         Prompt Claude pour lire un T4
│   ├── extract_rl1.txt        Prompt Claude pour lire un RL-1
│   └── extract_cv.txt         Prompt Claude pour extraire identité du CV
├── routers/
│   ├── health.py              GET /v1/health
│   ├── extract.py             POST /v1/extract
│   └── declarations.py        POST /v1/declarations + GET /v1/declarations/{id}
└── services/
    ├── claude_extractor.py    Pipeline OCR : PDF→texte ou PDF→image → Claude → JSON
    └── payload_builder.py     Construit le ExchangePayload depuis les résultats OCR
```

---

## Base de données (SQLite — 3 tables)

| Table | Rôle | Clé primaire |
|---|---|---|
| `extraction_sessions` | 1 ligne par appel `/extract` | `proc_<uuid>` |
| `declarations` | 1 ligne par déclaration soumise | `decl_<uuid>` |
| `declaration_flags` | Flags OCR (anomalies, confiance) | auto-increment |

**Sécurité NAS** : le numéro d'assurance sociale n'est jamais stocké en clair. La colonne `nas_hash` contient le SHA-256, et `nas_last3` contient les 3 derniers chiffres pour affichage masqué (`*** *** 789`).

---

## Démarrage local

```bash
# 1. Installer les dépendances
pip install -r requirements.txt

# 2. Installer poppler (nécessaire pour pdf2image)
# macOS : brew install poppler
# Ubuntu : sudo apt-get install poppler-utils

# 3. Configurer la clé Claude dans .env.dev
# Modifier ANTHROPIC_API_KEY=sk-ant-...

# 4. Démarrer le serveur
ENV=dev python main.py
# ou
uvicorn main:app --reload

# 5. Documentation interactive
# http://localhost:8000/docs
```

---

## Règles de sécurité importantes

1. **Les fichiers PDF ne sont jamais écrits sur disque** — ils sont lus en mémoire et supprimés après extraction
2. **Le NAS ne transite jamais dans le `ExchangePayload`** — il est envoyé uniquement lors de la soumission finale, chiffré en transit (TLS)
3. **Les fichiers `.env.*` ne sont jamais committés** — ajouter `*.env*` dans `.gitignore`
4. **CORS** — seules les extensions Chrome et `localhost` sont autorisées en développement

---

## Codes de réponse

| Code | Signification |
|---|---|
| 200 | Extraction réussie — `ExchangePayload` retourné |
| 201 | Déclaration enregistrée — `confirmation_id` retourné |
| 400 | Aucun fichier fourni ou format non supporté |
| 409 | Déclaration déjà soumise pour ce `processing_id` |
| 422 | Validation Pydantic échouée (NAS mal formaté, etc.) |
| 500 | Erreur Claude OCR ou erreur interne |

---

*AxOvide v1.0 · Backend FastAPI · © 2024 Équipe AxOvide · Confidentiel*
