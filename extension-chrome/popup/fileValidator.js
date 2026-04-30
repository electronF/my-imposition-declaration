/**
 * AxOvide — fileValidator.js
 * ─────────────────────────────────────────────────────────────
 * Module de validation des fichiers fiscaux.
 *
 * Principes :
 *   - Fonctions PURES uniquement : entrée → sortie, zéro effet de bord
 *   - Aucun accès au DOM, aucun fetch, aucune dépendance externe
 *   - Chaque fonction est testable unitairement de façon isolée
 *   - Exporté comme objet immuable (Object.freeze)
 *
 * Utilisation dans popup.js :
 *   const result = FileValidator.validate(file, 't4');
 *   if (!result.valid) console.error(result.errors);
 * ─────────────────────────────────────────────────────────────
 */

const FileValidator = (() => {
  'use strict';

  /* ── 1. RÈGLES PAR TYPE DE DOCUMENT ───────────────────────
   * Chaque type de document a ses propres contraintes.
   * Centraliser ici : un seul endroit à modifier si les règles
   * métier changent (ex: accepter les JPEG pour le CV).
   * ──────────────────────────────────────────────────────── */
  const RULES = Object.freeze({
    cv: Object.freeze({
      label:       'Curriculum Vitae',
      extensions:  Object.freeze(['.pdf', '.doc', '.docx']),
      mimeTypes:   Object.freeze([
        'application/pdf',
        'application/msword',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      ]),
      maxSizeMb:   10,
      minSizeByte: 0.01,
    }),

    t4: Object.freeze({
      label:       'Feuillet T4',
      extensions:  Object.freeze(['.pdf']),
      mimeTypes:   Object.freeze(['application/pdf']),
      maxSizeMb:   10,
      minSizeByte: 0.01,
    }),

    rl1: Object.freeze({
      label:       'Relevé 1',
      extensions:  Object.freeze(['.pdf']),
      mimeTypes:   Object.freeze(['application/pdf']),
      maxSizeMb:   10,
      minSizeByte: 0.01,
    }),
  });

  /* ── 2. UTILITAIRES PURS ───────────────────────────────────
   * Petites fonctions sans état, réutilisables partout.
   * ──────────────────────────────────────────────────────── */

  /**
   * Extrait l'extension d'un nom de fichier, en minuscules.
   * @param {string} filename
   * @returns {string}  ex: ".pdf", ".docx"
   */
  const getExtension = (filename) => {
    const lastDot = filename.lastIndexOf('.');
    if (lastDot === -1 || lastDot === filename.length - 1) return '';
    return filename.slice(lastDot).toLowerCase();
  };

  /**
   * Formate une taille en octets en chaîne lisible.
   * @param {number} bytes
   * @returns {string}  ex: "2.4 Mo", "850 Ko"
   */
  const formatSize = (bytes) => {
    if (bytes >= 1_000_000) return `${(bytes / 1_000_000).toFixed(1)} Mo`;
    if (bytes >= 1_000)     return `${Math.round(bytes / 1_000)} Ko`;
    return `${bytes} octets`;
  };

  /**
   * Vérifie si le type MIME est cohérent avec l'extension déclarée.
   * Les navigateurs exposent le MIME via file.type — on cross-checke
   * avec l'extension pour détecter les fichiers renommés.
   * @param {string} extension   ex: ".pdf"
   * @param {string} mimeType    ex: "application/pdf"
   * @returns {boolean}
   */
  const isMimeConsistent = (extension, mimeType) => {
    const MAP = {
      '.pdf':  ['application/pdf'],
      '.doc':  ['application/msword', ''],           // vieux Word peut avoir MIME vide
      '.docx': [
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/zip',   // certains OS exposent .docx comme zip
        '',
      ],
    };
    const allowed = MAP[extension] || [];
    // Si le navigateur ne rapporte pas de MIME (chaîne vide), on fait confiance à l'extension
    if (mimeType === '') return true;
    return allowed.includes(mimeType);
  };

  /* ── 3. VALIDATIONS ATOMIQUES ──────────────────────────────
   * Chaque fonction valide UN seul aspect du fichier.
   * Pattern : retourne null si OK, ou un message d'erreur string.
   * ──────────────────────────────────────────────────────── */

  /**
   * Vérifie que docType est connu.
   * @param {string} docType
   * @returns {string|null}
   */
  const checkDocType = (docType) => {
    if (!RULES[docType]) {
      return `Type de document inconnu : "${docType}". Types acceptés : ${Object.keys(RULES).join(', ')}.`;
    }
    return null;
  };

  /**
   * Vérifie que file est bien un objet File natif.
   * @param {*} file
   * @returns {string|null}
   */
  const checkIsFile = (file) => {
    if (!(file instanceof File)) {
      return 'L\'entrée n\'est pas un fichier valide.';
    }
    return null;
  };

  /**
   * Vérifie l'extension du fichier.
   * @param {File}   file
   * @param {string} docType
   * @returns {string|null}
   */
  const checkExtension = (file, docType) => {
    const rules = RULES[docType];
    const ext   = getExtension(file.name);

    if (ext === '') {
      return `Le fichier n'a pas d'extension. Formats acceptés pour ${rules.label} : ${rules.extensions.join(', ')}.`;
    }
    if (!rules.extensions.includes(ext)) {
      return `Extension "${ext}" non acceptée pour ${rules.label}. Formats valides : ${rules.extensions.join(', ')}.`;
    }
    return null;
  };

  /**
   * Vérifie la cohérence entre extension et type MIME.
   * @param {File}   file
   * @param {string} docType
   * @returns {string|null}
   */
  const checkMime = (file, docType) => {
    const ext = getExtension(file.name);
    if (!isMimeConsistent(ext, file.type)) {
      return `Le contenu du fichier ne correspond pas à son extension "${ext}". Le fichier semble avoir été renommé.`;
    }
    return null;
  };

  /**
   * Vérifie que le fichier n'est pas vide.
   * @param {File}   file
   * @param {string} docType
   * @returns {string|null}
   */
  const checkNotEmpty = (file, docType) => {
    const rules = RULES[docType];
    if (file.size < rules.minSizeByte) {
      return 'Le fichier est vide (0 octet). Vérifiez que le document est complet.';
    }
    return null;
  };

  /**
   * Vérifie que la taille ne dépasse pas le maximum autorisé.
   * @param {File}   file
   * @param {string} docType
   * @returns {string|null}
   */
  const checkSize = (file, docType) => {
    const rules    = RULES[docType];
    const maxBytes = rules.maxSizeMb * 1_000_000;

    if (file.size > maxBytes) {
      return `Fichier trop volumineux : ${formatSize(file.size)}. Maximum autorisé : ${rules.maxSizeMb} Mo.`;
    }
    return null;
  };

  /**
   * Vérifie que le nom de fichier ne contient pas de caractères dangereux.
   * Prévention basique contre des noms de fichiers malformés.
   * @param {File} file
   * @returns {string|null}
   */
  const checkFilename = (file) => {
    // Nom trop long (limite FAT32/NTFS/ext4 = 255 chars)
    if (file.name.length > 255) {
      return 'Le nom du fichier est trop long (maximum 255 caractères).';
    }
    // Caractères de contrôle ASCII ou null bytes
    if (/[\x00-\x1F\x7F]/.test(file.name)) {
      return 'Le nom du fichier contient des caractères non valides.';
    }
    return null;
  };

  /* ── 4. VALIDATEUR PRINCIPAL ───────────────────────────────
   * Exécute toutes les validations en séquence.
   * S'arrête à la première erreur (fail-fast) pour ne pas
   * noyer l'utilisateur sous plusieurs messages simultanés.
   * ──────────────────────────────────────────────────────── */

  /**
   * Valide un fichier pour un type de document donné.
   *
   * @param {File}   file     - Le fichier à valider (objet File natif)
   * @param {string} docType  - 'cv' | 't4' | 'rl1'
   *
   * @returns {{
   *   valid:    boolean,
   *   errors:   string[],   // vide si valid === true
   *   warnings: string[],   // avertissements non bloquants
   *   meta: {
   *     filename:  string,
   *     extension: string,
   *     sizeMb:    number,
   *     mimeType:  string,
   *     docType:   string,
   *     label:     string,
   *   }
   * }}
   */
  const validate = (file, docType) => {
    const errors   = [];
    const warnings = [];

    // ── Validations bloquantes (dans l'ordre logique)
    const checks = [
      () => checkDocType(docType),
      () => checkIsFile(file),
      () => checkFilename(file),
      () => checkExtension(file, docType),
      () => checkMime(file, docType),
      () => checkNotEmpty(file, docType),
      () => checkSize(file, docType),
    ];

    for (const check of checks) {
      const error = check();
      if (error) {
        errors.push(error);
        // Fail-fast : on arrête dès la première erreur bloquante
        break;
      }
    }

    // ── Avertissements non bloquants (seulement si pas d'erreur)
    if (errors.length === 0) {
      // Fichier très petit pour un PDF fiscal (< 10 Ko) — peut être corrompu
      if (file.size < 10_000 && getExtension(file.name) === '.pdf') {
        warnings.push('Ce PDF est très petit (< 10 Ko). Vérifiez qu\'il n\'est pas corrompu ou vide.');
      }
      // Nom de fichier qui ne ressemble pas au document attendu (heuristique douce)
      const nameLower = file.name.toLowerCase();
      const heuristics = {
        t4:  ['t4', 'feuillet', 'revenus-emploi'],
        rl1: ['rl1', 'rl-1', 'releve', 'relevé'],
        cv:  ['cv', 'curriculum', 'resume', 'résumé'],
      };
      const keywords = heuristics[docType] || [];
      const matches  = keywords.some((kw) => nameLower.includes(kw));
      if (!matches && docType !== 'cv') {
        warnings.push(
          `Le nom du fichier "${file.name}" ne semble pas correspondre à un ${RULES[docType].label}. Vérifiez que vous avez sélectionné le bon document.`
        );
      }
    }

    // ── Métadonnées retournées pour logging/affichage
    const meta = {
      filename:  file?.name  ?? '',
      extension: file ? getExtension(file.name) : '',
      sizeMb:    file ? parseFloat((file.size / 1_000_000).toFixed(2)) : 0,
      mimeType:  file?.type ?? '',
      docType,
      label:     RULES[docType]?.label ?? docType,
    };

    return {
      valid: errors.length === 0,
      errors,
      warnings,
      meta,
    };
  };

  /* ── 5. VALIDATEUR DE LOT ──────────────────────────────────
   * Valide les 3 fichiers ensemble.
   * Utile pour la vérification finale avant envoi.
   * ──────────────────────────────────────────────────────── */

  /**
   * Valide un objet contenant les 3 fichiers requis.
   *
   * @param {{ cv: File|null, t4: File|null, rl1: File|null }} files
   * @returns {{
   *   valid:   boolean,
   *   results: { cv: object, t4: object, rl1: object },
   *   summary: string,
   * }}
   */
  const validateAll = (files) => {
    const docTypes = ['cv', 't4', 'rl1'];
    const results  = {};
    let   allValid = true;

    for (const docType of docTypes) {
      const file = files[docType];

      if (!file) {
        // Fichier manquant — erreur explicite
        results[docType] = {
          valid:    false,
          errors:   [`Le document ${RULES[docType].label} est manquant.`],
          warnings: [],
          meta:     { filename: '', extension: '', sizeMb: 0, mimeType: '', docType, label: RULES[docType].label },
        };
        allValid = false;
      } else {
        results[docType] = validate(file, docType);
        if (!results[docType].valid) allValid = false;
      }
    }

    const validCount   = docTypes.filter((t) => results[t].valid).length;
    const summary      = allValid
      ? `3/3 documents valides — prêts à l'envoi.`
      : `${validCount}/3 documents valides — corriger les erreurs avant l'envoi.`;

    return { valid: allValid, results, summary };
  };

  /* ── 6. API PUBLIQUE ───────────────────────────────────────
   * On n'expose que ce que popup.js a besoin d'utiliser.
   * Object.freeze empêche toute modification accidentelle
   * depuis l'extérieur du module.
   * ──────────────────────────────────────────────────────── */
  return Object.freeze({
    validate,
    validateAll,
    getRules:     () => RULES,          // lecture seule des règles
    formatSize,                         // utile pour l'affichage UI
    getExtension,                       // utile pour les icônes selon type
  });

})();
