/**
 * AxOvide — popup.js
 * ─────────────────────────────────────────────────────────────
 * Responsabilités :
 *   1. Gérer le drag & drop et la sélection de fichiers
 *   2. Valider chaque fichier (type, taille)
 *   3. Mettre à jour l'UI selon l'état courant
 *   4. Construire le FormData et envoyer au backend FastAPI
 *   5. Afficher le résultat (succès / erreur)
 *
 * Pattern : Module IIFE — rien n'est exposé dans le scope global.
 * Toute la logique est encapsulée, zéro variable globale.
 * ─────────────────────────────────────────────────────────────
 */

(() => {
  'use strict';

  /* ── 1. CONFIGURATION ──────────────────────────────────────
   * Centraliser la config ici : si l'URL change, on ne touche
   * qu'à cet objet. Même principe que les constantes d'env.
   * ──────────────────────────────────────────────────────── */
  const CONFIG = {
    API_URL:      'http://localhost:8000/upload',
    MAX_SIZE_MB:  10,
    ACCEPTED: {
      cv:  ['.pdf', '.doc', '.docx'],
      t4:  ['.pdf'],
      rl1: ['.pdf'],
    },
    MIME_TYPES: {
      '.pdf':  'application/pdf',
      '.doc':  'application/msword',
      '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    },
  };

  /* ── 2. RÉFÉRENCES DOM ─────────────────────────────────────
   * On sélectionne tous les éléments UNE seule fois au départ.
   * Évite de faire des querySelector() répétés dans les handlers.
   * ──────────────────────────────────────────────────────── */
  const DOM = {
    // Zones de dépôt
    zones: {
      cv:  document.getElementById('zone-cv'),
      t4:  document.getElementById('zone-t4'),
      rl1: document.getElementById('zone-rl1'),
    },
    // Inputs fichiers cachés
    inputs: {
      cv:  document.getElementById('input-cv'),
      t4:  document.getElementById('input-t4'),
      rl1: document.getElementById('input-rl1'),
    },
    // Textes d'indice sous chaque zone
    hints: {
      cv:  document.getElementById('hint-cv'),
      t4:  document.getElementById('hint-t4'),
      rl1: document.getElementById('hint-rl1'),
    },
    // Icônes des zones
    icons: {
      cv:  document.getElementById('icon-cv'),
      t4:  document.getElementById('icon-t4'),
      rl1: document.getElementById('icon-rl1'),
    },
    // Boutons de suppression
    removes: {
      cv:  document.getElementById('remove-cv'),
      t4:  document.getElementById('remove-t4'),
      rl1: document.getElementById('remove-rl1'),
    },
    // Messages d'erreur sous chaque zone
    errors: {
      cv:  document.getElementById('error-cv'),
      t4:  document.getElementById('error-t4'),
      rl1: document.getElementById('error-rl1'),
    },
    // UI globale
    counter:   document.getElementById('files-counter'),
    statusBar: document.getElementById('status-bar'),
    statusText: document.getElementById('status-text'),
    btnSubmit:  document.getElementById('btn-submit'),
    btnLabel:   document.getElementById('btn-label'),
  };

  /* ── 3. ÉTAT DE L'APPLICATION ──────────────────────────────
   * Source unique de vérité (single source of truth).
   * L'UI est toujours un reflet de cet objet — jamais l'inverse.
   * ──────────────────────────────────────────────────────── */
  const state = {
    files: {
      cv:  null,   // File | null
      t4:  null,
      rl1: null,
    },
    loading: false,
  };

  /* ── 4. VALIDATION ─────────────────────────────────────────
   * Fonctions pures : prennent un File, retournent un résultat.
   * Aucun effet de bord, facile à tester unitairement.
   * ──────────────────────────────────────────────────────── */

  /**
   * Extrait l'extension d'un nom de fichier en minuscules.
   * @param {string} filename
   * @returns {string} ex: ".pdf"
   */
  const getExtension = (filename) =>
    filename.slice(filename.lastIndexOf('.')).toLowerCase();

  /**
   * Valide un fichier selon le type de document.
   * @param {File} file
   * @param {'cv'|'t4'|'rl1'} docType
   * @returns {{ valid: boolean, error?: string }}
   */
  const validateFile = (file, docType) => {
    const ext = getExtension(file.name);
    const allowed = CONFIG.ACCEPTED[docType];
    const maxBytes = CONFIG.MAX_SIZE_MB * 1024 * 1024;

    if (!allowed.includes(ext)) {
      return {
        valid: false,
        error: `Format non accepté. Formats valides : ${allowed.join(', ')}`,
      };
    }

    if (file.size > maxBytes) {
      return {
        valid: false,
        error: `Fichier trop volumineux. Maximum : ${CONFIG.MAX_SIZE_MB} Mo`,
      };
    }

    if (file.size === 0) {
      return { valid: false, error: 'Le fichier est vide.' };
    }

    return { valid: true };
  };

  /* ── 5. MISE À JOUR DE L'UI ────────────────────────────────
   * Toutes les fonctions qui touchent au DOM sont ici.
   * Séparation claire : validation ≠ UI ≠ réseau.
   * ──────────────────────────────────────────────────────── */

  /**
   * Met à jour une zone de dépôt après sélection d'un fichier.
   * @param {'cv'|'t4'|'rl1'} docType
   * @param {File} file
   */
  const setFileUI = (docType, file) => {
    const zone   = DOM.zones[docType];
    const hint   = DOM.hints[docType];
    const icon   = DOM.icons[docType];
    const remove = DOM.removes[docType];
    const error  = DOM.errors[docType];

    // Nettoyer états précédents
    zone.classList.remove('error');
    zone.classList.add('has-file');
    error.textContent = '';
    error.classList.remove('visible');

    // Afficher le nom du fichier tronqué
    const truncated = file.name.length > 35
      ? file.name.slice(0, 32) + '...'
      : file.name;

    hint.className = 'file-selected-name';
    hint.textContent = `✓ ${truncated}`;

    // Icônes selon le type
    const iconMap = { cv: '✅', t4: '✅', rl1: '✅' };
    icon.textContent = iconMap[docType];

    remove.style.display = 'block';
  };

  /**
   * Remet une zone dans son état initial (pas de fichier).
   * @param {'cv'|'t4'|'rl1'} docType
   */
  const clearFileUI = (docType) => {
    const zone   = DOM.zones[docType];
    const hint   = DOM.hints[docType];
    const icon   = DOM.icons[docType];
    const remove = DOM.removes[docType];
    const error  = DOM.errors[docType];
    const input  = DOM.inputs[docType];

    zone.classList.remove('has-file', 'error');
    hint.className = 'drop-zone-hint';
    error.textContent = '';
    error.classList.remove('visible');

    // Remettre les textes et icônes d'origine
    const defaults = {
      cv:  { hint: 'Glisser-déposer ou cliquer — PDF, DOC, DOCX', icon: '📄' },
      t4:  { hint: 'Glisser-déposer ou cliquer — PDF uniquement',  icon: '🧾' },
      rl1: { hint: 'Glisser-déposer ou cliquer — PDF uniquement',  icon: '📋' },
    };

    hint.textContent = defaults[docType].hint;
    icon.textContent = defaults[docType].icon;
    remove.style.display = 'none';

    // Réinitialiser l'input pour permettre de re-sélectionner le même fichier
    input.value = '';
  };

  /**
   * Affiche une erreur sur une zone spécifique.
   * @param {'cv'|'t4'|'rl1'} docType
   * @param {string} message
   */
  const showZoneError = (docType, message) => {
    const zone  = DOM.zones[docType];
    const error = DOM.errors[docType];

    zone.classList.add('error');
    zone.classList.remove('has-file');
    error.textContent = message;
    error.classList.add('visible');
  };

  /**
   * Met à jour le compteur de fichiers et le bouton d'envoi.
   */
  const updateCounter = () => {
    const count = Object.values(state.files).filter(Boolean).length;
    const strong = DOM.counter.querySelector('strong');
    strong.textContent = count;

    // Activer le bouton uniquement si les 3 fichiers sont présents
    DOM.btnSubmit.disabled = count < 3 || state.loading;
  };

  /**
   * Met à jour la barre de statut.
   * @param {'idle'|'loading'|'success'|'error'} type
   * @param {string} message
   */
  const setStatus = (type, message) => {
    const bar  = DOM.statusBar;
    const text = DOM.statusText;

    // Retirer tous les états
    bar.classList.remove('loading', 'success', 'error');

    // Vider et reconstruire le contenu
    bar.innerHTML = '';

    if (type === 'loading') {
      bar.classList.add('loading');
      const spinner = document.createElement('div');
      spinner.className = 'spinner';
      const span = document.createElement('span');
      span.id = 'status-text';
      span.textContent = message;
      bar.appendChild(spinner);
      bar.appendChild(span);

    } else {
      const icons = {
        idle:    '📎',
        success: '✅',
        error:   '⚠️',
      };

      if (type === 'success') bar.classList.add('success');
      if (type === 'error')   bar.classList.add('error');

      bar.innerHTML = `
        <span class="status-icon">${icons[type] || '📎'}</span>
        <span id="status-text">${message}</span>
      `;
    }
  };

  /* ── 6. LOGIQUE DE SÉLECTION DE FICHIER ────────────────────
   * Point d'entrée unique pour tout ajout de fichier,
   * que ce soit via clic ou drag & drop.
   * ──────────────────────────────────────────────────────── */

  /**
   * Traite un fichier entrant pour un type de document donné.
   * @param {File} file
   * @param {'cv'|'t4'|'rl1'} docType
   */
  const handleFile = (file, docType) => {
    const result = validateFile(file, docType);

    if (!result.valid) {
      showZoneError(docType, result.error);
      state.files[docType] = null;
    } else {
      state.files[docType] = file;
      setFileUI(docType, file);
    }

    updateCounter();
    updateStatusMessage();
  };

  /**
   * Calcule et affiche le message de statut global selon l'état.
   */
  const updateStatusMessage = () => {
    if (state.loading) return;

    const count = Object.values(state.files).filter(Boolean).length;

    if (count === 0) {
      setStatus('idle', 'Sélectionnez vos trois documents pour continuer.');
    } else if (count < 3) {
      const remaining = 3 - count;
      setStatus('idle', `${remaining} document${remaining > 1 ? 's' : ''} manquant${remaining > 1 ? 's' : ''}.`);
    } else {
      setStatus('idle', 'Tous les documents sont prêts. Cliquez sur Envoyer.');
    }
  };

  /* ── 7. DRAG & DROP ────────────────────────────────────────
   * On attache les handlers sur chaque zone individuellement.
   * dragenter/dragleave gèrent la classe visuelle .drag-over.
   * ──────────────────────────────────────────────────────── */

  /**
   * Attache les événements drag & drop sur une zone.
   * @param {'cv'|'t4'|'rl1'} docType
   */
  const attachDragDrop = (docType) => {
    const zone = DOM.zones[docType];

    zone.addEventListener('dragenter', (e) => {
      e.preventDefault();
      zone.classList.add('drag-over');
    });

    zone.addEventListener('dragover', (e) => {
      e.preventDefault(); // Nécessaire pour autoriser le drop
      zone.classList.add('drag-over');
    });

    zone.addEventListener('dragleave', (e) => {
      // Vérifier qu'on quitte vraiment la zone (pas juste un enfant)
      if (!zone.contains(e.relatedTarget)) {
        zone.classList.remove('drag-over');
      }
    });

    zone.addEventListener('drop', (e) => {
      e.preventDefault();
      zone.classList.remove('drag-over');

      const file = e.dataTransfer.files[0];
      if (file) handleFile(file, docType);
    });
  };

  /* ── 8. ENVOI AU BACKEND ───────────────────────────────────
   * Construction du FormData avec les 3 fichiers nommés
   * exactement comme le backend FastAPI s'y attend.
   * ──────────────────────────────────────────────────────── */

  /**
   * Envoie les documents au backend et gère la réponse.
   */
  const submitDocuments = async () => {
    // Sécurité : vérifier une dernière fois avant d'envoyer
    if (!state.files.cv || !state.files.t4 || !state.files.rl1) return;
    if (state.loading) return;

    state.loading = true;
    DOM.btnSubmit.disabled = true;
    DOM.btnLabel.textContent = 'Envoi en cours…';
    setStatus('loading', 'Téléversement des documents…');

    try {
      // Construire le FormData — les clés doivent correspondre
      // exactement aux paramètres FastAPI : cv, t4, rl1
      const formData = new FormData();
      formData.append('cv',  state.files.cv);
      formData.append('t4',  state.files.t4);
      formData.append('rl1', state.files.rl1);

      const response = await fetch(CONFIG.API_URL, {
        method: 'POST',
        body: formData,
        // Ne PAS définir Content-Type manuellement —
        // le navigateur le fait avec le bon boundary multipart
      });

      if (!response.ok) {
        // Erreur HTTP (4xx, 5xx)
        let errorMsg = `Erreur serveur (${response.status})`;
        try {
          const body = await response.json();
          if (body.detail) errorMsg = body.detail;
        } catch (_) { /* réponse non-JSON, garder le message générique */ }
        throw new Error(errorMsg);
      }

      const data = await response.json();

      // Succès
      setStatus('success', `Documents reçus ✓ — Référence : ${data.job_id}`);
      DOM.btnLabel.textContent = 'Documents envoyés ✓';

      // Sauvegarder le job_id pour usage futur (phase 2)
      chrome.storage.local.set({ last_job_id: data.job_id });

    } catch (err) {
      // Erreur réseau ou HTTP
      setStatus('error', err.message || 'Impossible de joindre le serveur.');
      DOM.btnLabel.textContent = 'Réessayer';
      DOM.btnSubmit.disabled = false;

    } finally {
      state.loading = false;
    }
  };

  /* ── 9. INITIALISATION ─────────────────────────────────────
   * Point d'entrée : on attache tous les événements ici.
   * Une seule fonction init() appelée au bas du script.
   * ──────────────────────────────────────────────────────── */

  const init = () => {
    const docTypes = ['cv', 't4', 'rl1'];

    docTypes.forEach((docType) => {

      // ── Clic sur l'input fichier (sélecteur natif)
      DOM.inputs[docType].addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (file) handleFile(file, docType);
      });

      // ── Drag & Drop
      attachDragDrop(docType);

      // ── Accessibilité : Enter/Space sur la zone déclenche l'input
      DOM.zones[docType].addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          DOM.inputs[docType].click();
        }
      });

      // ── Bouton supprimer fichier
      DOM.removes[docType].addEventListener('click', (e) => {
        e.stopPropagation(); // Éviter de rouvrir le sélecteur
        state.files[docType] = null;
        clearFileUI(docType);
        updateCounter();
        updateStatusMessage();
      });
    });

    // ── Bouton envoyer
    DOM.btnSubmit.addEventListener('click', submitDocuments);

    // ── État initial
    updateStatusMessage();
  };

  // Lancement
  init();

})();