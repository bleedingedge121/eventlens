// EventLens — Conversational AI Query Client
// High-reliability, zero-framework vanilla ES6+ module

(() => {
  // ============ OPERATIONAL STATE ============
  let isQuerying = false;
  let copySeq = 0;
  const QUERY_TIMEOUT_MS = 60000;
  const MAX_HISTORY = 20;
  let sessionHistory = [];
  let cachedEventsMap = new Map();

  // Category metadata for UI matching
  const CATEGORY_META = {
    tailgating: { label: 'Tailgating', badgeClass: 'badge--tailgating' },
    person_down: { label: 'Person Down', badgeClass: 'badge--person_down' },
    fighting: { label: 'Fighting', badgeClass: 'badge--fighting' },
    crowd_incident: { label: 'Crowd', badgeClass: 'badge--crowd_incident' },
    suspicious_activity: { label: 'Suspicious', badgeClass: 'badge--suspicious_activity' },
    suicide_risk: { label: 'Suicide / Fall Hazard', badgeClass: 'badge--suicide_risk' }
  };

  // ============ DOM REFERENCES ============
  const $ = (sel, ctx = document) => ctx.querySelector(sel);
  const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

  const els = {
    chatMessages: $('#chat-messages'),
    chatForm: $('#chat-form'),
    chatInput: $('#chat-input'),
    chatSubmit: $('#chat-submit'),
    clearBtn: $('#clear-chat'),
    presetList: $('#preset-list'),
    historyCard: $('#history-card'),
    historyList: $('#history-list'),

    // Modal elements
    modal: $('#event-modal'),
    modalClose: $('#modal-close'),
    modalCategoryBadge: $('#modal-category-badge'),
    modalTitle: $('#modal-title'),
    modalImage: $('#modal-image'),
    modalSummary: $('#modal-summary'),
    modalCamera: $('#modal-camera'),
    modalTimestamp: $('#modal-timestamp'),
    modalConfidence: $('#modal-confidence'),
    modalLatency: $('#modal-latency'),
    modalTracks: $('#modal-tracks'),
    copyEventBtn: $('#copy-event')
  };

  // ============ UTILITIES ============
  const escapeHtml = (str) => {
    if (!str) return '';
    return String(str).replace(/[&<>'"]/g, c => {
      const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' };
      return map[c];
    });
  };

  // Tokenise the RAW sql, escape each piece once. (Regex-over-escaped-HTML corrupted entities like &#39;.)
  const SQL_TOKEN = /('(?:[^']|'')*')|\b(SELECT|FROM|WHERE|AND|OR|ORDER BY|GROUP BY|LIMIT|DESC|ASC|LIKE|BETWEEN|IN|AS|JOIN|ON|COUNT)\b|\b(events)\b|\b(\d+(?:\.\d+)?)\b/gi;
  const highlightSql = (sql) => {
    if (!sql) return '';
    const raw = String(sql);
    let out = '', last = 0;
    for (const m of raw.matchAll(SQL_TOKEN)) {
      const [tok, str, kw, tbl] = m;
      const cls = str ? 'sql-str' : kw ? 'sql-kw' : tbl ? 'sql-tbl' : 'sql-num';
      out += `${escapeHtml(raw.slice(last, m.index))}<span class="${cls}">${escapeHtml(tok)}</span>`;
      last = m.index + tok.length;
    }
    return out + escapeHtml(raw.slice(last));
  };

  const formatTimestamp = (iso) => {
    if (!iso) return '\u2014';
    try {
      return new Date(iso).toLocaleString([], { dateStyle: 'short', timeStyle: 'medium' });
    } catch {
      return iso;
    }
  };

  const formatTime = (iso) => {
    if (!iso) return '\u2014';
    try {
      return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch {
      return iso;
    }
  };

  const scrollToBottom = () => {
    els.chatMessages.scrollTo({
      top: els.chatMessages.scrollHeight,
      behavior: 'smooth'
    });
  };

  const copyToClipboard = (text, btn, originalLabel) => {
    navigator.clipboard.writeText(text).then(() => {
      btn.textContent = 'Copied ✓';
      setTimeout(() => { btn.textContent = originalLabel; }, 1800);
    }).catch(() => {
      btn.textContent = 'Failed';
      setTimeout(() => { btn.textContent = originalLabel; }, 1800);
    });
  };

  // ============ EVENT MODAL ============
  function openEventModal(event) {
    if (!event) return;

    const meta = CATEGORY_META[event.category] || { label: event.category, badgeClass: '' };
    const keyframeSrc = event.keyframe_url || `/frames/${event.id}.jpg`;

    els.modalCategoryBadge.className = `badge ${meta.badgeClass}`;
    els.modalCategoryBadge.textContent = meta.label;
    els.modalTitle.textContent = `Incident Record #${event.id}`;
    els.modalImage.src = keyframeSrc;
    els.modalImage.alt = `Keyframe for ${meta.label} #${event.id}`;
    els.modalSummary.textContent = event.summary;
    els.modalCamera.textContent = event.camera_id;
    els.modalTimestamp.textContent = formatTimestamp(event.timestamp);
    els.modalConfidence.textContent = `${(event.confidence * 100).toFixed(1)}%`;
    els.modalLatency.textContent = `${event.latency_ms || 0} ms`;

    els.modalTracks.innerHTML = event.track_ids && event.track_ids.length
      ? event.track_ids.map(id => `<span class="track-chip">Target #${id}</span>`).join(' ')
      : '<span style="color:var(--text-dim)">None detected</span>';

    els.copyEventBtn.onclick = () => copyToClipboard(JSON.stringify(event, null, 2), els.copyEventBtn, 'Copy JSON');

    els.modal.showModal();
    document.body.style.overflow = 'hidden';
  }

  function closeEventModal() {
    els.modal.close();
    document.body.style.overflow = '';
  }

  // ============ CHAT RENDERING ============
  function appendUserMessage(text) {
    const row = document.createElement('div');
    row.className = 'msg-row msg-row--user';
    row.innerHTML = `
      <div class="msg-avatar msg-avatar--user" aria-hidden="true">OP</div>
      <div class="msg-bubble">
        <p>${escapeHtml(text)}</p>
      </div>`;
    els.chatMessages.appendChild(row);
    scrollToBottom();
  }

  function createLoadingMessage() {
    const row = document.createElement('div');
    row.className = 'msg-row msg-row--assistant loading-row';
    row.setAttribute('role', 'status');
    row.innerHTML = `
      <div class="msg-avatar msg-avatar--assistant" aria-hidden="true">AI</div>
      <div class="msg-bubble">
        <div style="display:flex;align-items:center;gap:10px;color:var(--text-secondary);font-size:0.82rem;">
          <div class="spinner" style="width:16px;height:16px;border-width:2px;"></div>
          <span>Translating question to validated SQLite query and executing…</span>
        </div>
      </div>`;
    els.chatMessages.appendChild(row);
    scrollToBottom();
    return row;
  }

  function appendAssistantMessage(answer, sql, events) {
    const row = document.createElement('div');
    row.className = 'msg-row msg-row--assistant';

    let eventsHtml = '';
    if (events && events.length > 0) {
      // Cache events for modal click retrieval
      events.forEach(ev => cachedEventsMap.set(Number(ev.id), ev));

      const cardsHtml = events.map(ev => {
        const meta = CATEGORY_META[ev.category] || { label: ev.category, badgeClass: '' };
        const keyframeSrc = ev.keyframe_url || `/frames/${ev.id}.jpg`;
        return `
          <div class="chat-event-tile" data-event-id="${ev.id}" tabindex="0" role="button" aria-label="View incident ${ev.id}">
            <img class="chat-event-thumb" src="${escapeHtml(keyframeSrc)}" alt="Event keyframe ${ev.id}" loading="lazy"
              onerror="this.onerror=null;this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'68\\' height=\\'48\\'><rect width=\\'100%\\' height=\\'100%\\' fill=\\'%23080c14\\'/></svg>'">
            <div class="chat-event-info">
              <div class="chat-event-title-line">
                <span class="badge ${meta.badgeClass}">${meta.label}</span>
                <span class="event-camera">${escapeHtml(ev.camera_id)}</span>
                <span class="event-time">${formatTime(ev.timestamp)}</span>
              </div>
              <div class="chat-event-summary-text">${escapeHtml(ev.summary)}</div>
              <div style="font-size:0.65rem;color:var(--text-dim);font-family:var(--font-mono);margin-top:2px;">
                Confidence: ${(ev.confidence * 100).toFixed(0)}%
              </div>
            </div>
          </div>`;
      }).join('');

      eventsHtml = `
        <div class="chat-events-preview">
          <div class="chat-events-header">Matching Incidents (${events.length})</div>
          <div class="chat-events-grid">
            ${cardsHtml}
          </div>
        </div>`;
    }

    const uniqueCopyId = `copy-sql-${++copySeq}`;

    row.innerHTML = `
      <div class="msg-avatar msg-avatar--assistant" aria-hidden="true">AI</div>
      <div class="msg-bubble">
        <p style="font-size:0.88rem;color:var(--text-primary);line-height:1.5;">${escapeHtml(answer)}</p>

        ${sql ? `
          <div class="sql-inspector">
            <div class="sql-inspector-header">
              <span class="sql-tag">
                <svg class="icon-svg icon-svg--sm" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"></polyline></svg>
                Executed Safe SQL
              </span>
              <button class="sql-copy-btn" id="${uniqueCopyId}">
                <svg class="icon-svg icon-svg--sm" viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                <span>Copy SQL</span>
              </button>
            </div>
            <div class="sql-code">${highlightSql(sql)}</div>
          </div>` : ''}

        ${eventsHtml}
      </div>`;

    els.chatMessages.appendChild(row);

    // Attach copy handler for SQL
    if (sql) {
      const copyBtn = $(`#${uniqueCopyId}`, row);
      if (copyBtn) {
        copyBtn.addEventListener('click', () => copyToClipboard(sql, copyBtn, 'Copy SQL'));
      }
    }

    // Attach click handlers to event cards
    $$('.chat-event-tile', row).forEach(tile => {
      const eventId = Number(tile.dataset.eventId);
      const ev = cachedEventsMap.get(eventId);
      if (ev) {
        const handler = () => openEventModal(ev);
        tile.addEventListener('click', handler);
        tile.addEventListener('keydown', e => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            handler();
          }
        });
      }
    });

    scrollToBottom();
  }

  function appendErrorMessage(errText) {
    const row = document.createElement('div');
    row.className = 'msg-row msg-row--assistant';
    row.innerHTML = `
      <div class="msg-avatar msg-avatar--assistant" style="color:var(--accent-rose);" aria-hidden="true">!</div>
      <div class="msg-bubble" style="border-left:3px solid var(--accent-rose);">
        <p style="color:var(--accent-rose);font-weight:600;">Query Execution Error</p>
        <p style="color:var(--text-secondary);font-size:0.82rem;">${escapeHtml(errText)}</p>
      </div>`;
    els.chatMessages.appendChild(row);
    scrollToBottom();
  }

  // ============ QUERY EXECUTION ============
  async function submitQuery(question) {
    const q = question.trim();
    if (!q || isQuerying) return;

    isQuerying = true;
    els.chatSubmit.disabled = true;

    // Add to session history
    if (!sessionHistory.includes(q)) {
      sessionHistory.unshift(q);
      sessionHistory.length = Math.min(sessionHistory.length, MAX_HISTORY);
      updateHistoryUI();
    }

    appendUserMessage(q);
    const loadingElem = createLoadingMessage();

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q }),
        signal: AbortSignal.timeout(QUERY_TIMEOUT_MS)
      });

      loadingElem.remove();

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `Server returned HTTP ${response.status}`);
      }

      const data = await response.json();
      appendAssistantMessage(data.answer, data.sql, data.events);
    } catch (err) {
      loadingElem.remove();
      console.error('[EventLens Chat] Query failed:', err);
      els.chatInput.value ||= q; // never lose the operator's question on failure
      autoResizeTextarea();
      appendErrorMessage(err.name === 'TimeoutError'
        ? 'The query engine took longer than 60 seconds. Try a narrower question.'
        : err.message || 'Unable to connect to local query engine.');
    } finally {
      isQuerying = false;
      els.chatSubmit.disabled = false;
      els.chatInput.focus();
    }
  }

  function updateHistoryUI() {
    if (!sessionHistory.length) {
      els.historyCard.style.display = 'none';
      return;
    }
    els.historyCard.style.display = 'flex';
    els.historyList.innerHTML = sessionHistory.slice(0, 5).map(item => `
      <button class="preset-query-btn history-item-btn" data-query="${escapeHtml(item)}">
        ${escapeHtml(item)}
      </button>
    `).join('');

    $$('.history-item-btn', els.historyList).forEach(btn => {
      btn.addEventListener('click', () => {
        els.chatInput.value = btn.dataset.query;
        submitQuery(btn.dataset.query);
      });
    });
  }

  // ============ AUTO RESIZE TEXTAREA ============
  function autoResizeTextarea() {
    els.chatInput.style.height = 'auto';
    els.chatInput.style.height = Math.min(els.chatInput.scrollHeight, 120) + 'px';
  }

  // ============ INITIALIZE ============
  function init() {
    els.chatMessages.setAttribute('role', 'log');
    els.chatMessages.setAttribute('aria-live', 'polite');

    // Form submission
    els.chatForm.addEventListener('submit', e => {
      e.preventDefault();
      const text = els.chatInput.value;
      els.chatInput.value = '';
      els.chatInput.style.height = 'auto';
      submitQuery(text);
    });

    // Enter to submit, Shift+Enter for newline
    els.chatInput.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        els.chatForm.dispatchEvent(new Event('submit'));
      }
    });

    els.chatInput.addEventListener('input', autoResizeTextarea);

    // Preset query clicks
    els.presetList.addEventListener('click', e => {
      const btn = e.target.closest('.preset-query-btn');
      if (btn && btn.dataset.query) {
        els.chatInput.value = btn.dataset.query;
        submitQuery(btn.dataset.query);
      }
    });

    // Clear history button
    els.clearBtn.addEventListener('click', () => {
      els.chatMessages.innerHTML = `
        <div class="msg-row msg-row--assistant">
          <div class="msg-avatar msg-avatar--assistant" aria-hidden="true">AI</div>
          <div class="msg-bubble">
            <p>History cleared. Ask any new question regarding monitored video feeds, cameras, or incidents.</p>
          </div>
        </div>`;
      cachedEventsMap.clear();
      sessionHistory = [];
      updateHistoryUI();
      els.chatInput.focus();
    });

    // Modal close handlers
    els.modalClose.addEventListener('click', closeEventModal);
    els.modal.addEventListener('click', e => {
      if (e.target === els.modal) closeEventModal();
    });

    // Global keyboard shortcuts
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') {
        if (els.modal.open) {
          closeEventModal();
        } else {
          els.chatInput.blur();
        }
      } else if (e.key === '/' && document.activeElement !== els.chatInput) {
        e.preventDefault();
        els.chatInput.focus();
      }
    });

    // Handle incoming URL search param (e.g. from dashboard "Ask About This Event")
    const urlParams = new URLSearchParams(window.location.search);
    const prefillQuery = urlParams.get('q');
    if (prefillQuery) {
      els.chatInput.value = prefillQuery;
      autoResizeTextarea();
      setTimeout(() => submitQuery(prefillQuery), 150);
    } else {
      els.chatInput.focus();
    }

    console.log('[EventLens] Conversational AI Query engine initialized');
  }

  document.addEventListener('DOMContentLoaded', init);
})();
