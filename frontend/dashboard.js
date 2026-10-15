// EventLens — Security Operations Dashboard Client
// High-reliability, zero-framework vanilla ES6+ module

(() => {
  // ============ OPERATIONAL STATE ============
  let currentCamera = 'cam1';
  let currentCategory = '';
  let searchQuery = '';
  let minConfidence = 0.5;
  let zonesVisible = false;
  let audioEnabled = true;
  let lastEventId = 0;
  let currentEvents = [];
  let pollTimer = null;
  let clockTimer = null;
  let fpsCounter = 0;
  let lastFpsTime = performance.now();

  // Camera zone polygons (matches backend config/cameras.json)
  const CAMERA_ZONES = {
    cam1: {
      doorZone: [[180, 240], [420, 240], [420, 480], [180, 480]],
      restrictedZones: [{ name: 'Server Corridor', poly: [[500, 100], [620, 100], [620, 350], [500, 350]] }]
    },
    cam2: {
      doorZone: [[100, 200], [300, 200], [300, 450], [100, 450]],
      restrictedZones: [{ name: 'Emergency Stairwell', poly: [[450, 50], [580, 50], [580, 300], [450, 300]] }]
    }
  };

  // Category metadata for UI
  const CATEGORY_META = {
    tailgating: { label: 'Tailgating', color: '#f59e0b', severity: 'warning', badgeClass: 'badge--tailgating' },
    person_down: { label: 'Person Down', color: '#f43f5e', severity: 'critical', badgeClass: 'badge--person_down' },
    fighting: { label: 'Fighting', color: '#ff5722', severity: 'critical', badgeClass: 'badge--fighting' },
    crowd_incident: { label: 'Crowd', color: '#818cf8', severity: 'warning', badgeClass: 'badge--crowd_incident' },
    suspicious_activity: { label: 'Suspicious', color: '#38bdf8', severity: 'notice', badgeClass: 'badge--suspicious_activity' }
  };

  // ============ DOM REFERENCES ============
  const $ = (sel, ctx = document) => ctx.querySelector(sel);
  const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

  const els = {
    audioToggle: $('#audio-toggle'),
    audioIcon: $('#audio-icon'),
    audioLabel: $('#audio-toggle .label'),
    systemStatus: $('.system-status'),

    statToday: $('#stat-today'),
    statLatency: $('#stat-latency'),
    statTotal: $('#stat-total'),
    statProcessing: $('#stat-processing'),

    cameraSelect: $('#camera-select'),
    quickWebcamBtn: $('#btn-quick-webcam'),
    zonesToggle: $('#zones-toggle'),
    zonesState: $('#zones-state'),
    streamImg: $('#stream'),
    streamFallback: $('#stream-fallback'),
    zoneCanvas: $('#zone-overlay'),
    viewport: $('#viewport'),
    hudCamera: $('#hud-camera'),
    hudFps: $('#hud-fps'),
    hudTime: $('#hud-time'),
    snapshotBtn: $('#snapshot'),
    fullscreenBtn: $('#fullscreen'),

    scenarioBtns: $$('.scenario-btn'),
    sourceInput: $('#source-input'),
    startSourceBtn: $('#start-source'),

    feedCount: $('#feed-count'),
    clearEventsBtn: $('#clear-events'),
    eventSearch: $('#event-search'),
    filterBtns: $$('.filter-btn'),
    filterCounts: {
      all: $('#count-all'),
      tailgating: $('#count-tailgating'),
      person_down: $('#count-person_down'),
      fighting: $('#count-fighting'),
      crowd_incident: $('#count-crowd_incident'),
      suspicious_activity: $('#count-suspicious_activity')
    },
    confidenceFilter: $('#confidence-filter'),
    eventFeed: $('#event-feed'),

    timeline: $('#timeline'),
    tip: $('#tip'),
    barsCat: $('#bars-cat'),
    barsCam: $('#bars-cam'),
    toasts: $('#toasts'),

    openReportBtn: $('#open-report'),
    reportModal: $('#report-modal'),
    reportClose: $('#rep-close'),
    reportForm: $('#rep-form'),
    reportView: $('#rep-view'),
    rpPeriod: $('#rp-period'),
    rpCustom: $('#rp-custom'),
    rpFrom: $('#rp-from'),
    rpTo: $('#rp-to'),
    rpCams: $('#rp-cams'),
    rpCats: $('#rp-cats'),
    rpSecs: $('#rp-secs'),
    rpDetail: $('#rp-detail'),
    rpNotes: $('#rp-notes'),
    rpGo: $('#rp-go'),

    modal: $('#event-modal'),
    modalClose: $('#modal-close'),
    modalCategoryBadge: $('#modal-category-badge'),
    modalTitle: $('#modal-title'),
    modalImage: $('#modal-image'),
    modalClipsContainer: $('#modal-clips-container'),
    modalClipsCount: $('#modal-clips-count'),
    modalClipsStrip: $('#modal-clips-strip'),
    modalSummary: $('#modal-summary'),
    modalCamera: $('#modal-camera'),
    modalTimestamp: $('#modal-timestamp'),
    modalConfidence: $('#modal-confidence'),
    modalLatency: $('#modal-latency'),
    modalTracks: $('#modal-tracks'),
    copyEventBtn: $('#copy-event'),
    queryLink: $('#query-link')
  };

  // ============ UTILITIES ============
  const formatTime = (iso) => {
    if (!iso) return '\u2014';
    try {
      return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch {
      return iso;
    }
  };

  const formatTimestamp = (iso) => {
    if (!iso) return '\u2014';
    try {
      return new Date(iso).toLocaleString([], { dateStyle: 'short', timeStyle: 'medium' });
    } catch {
      return iso;
    }
  };

  const formatRelativeTime = (iso) => {
    if (!iso) return '';
    try {
      const diffSec = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
      if (diffSec < 60) return 'Just now';
      if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
      if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
      return `${Math.floor(diffSec / 86400)}d ago`;
    } catch {
      return '';
    }
  };

  const escapeHtml = (str) => {
    if (!str) return '';
    return String(str).replace(/[&<>'"]/g, c => {
      const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' };
      return map[c];
    });
  };

  // Synthesized tactical alert chime via Web Audio API
  const playAlertChime = () => {
    if (!audioEnabled) return;
    try {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return;
      const ctx = new AC();
      const play = (freq, start, dur) => {
        const o = ctx.createOscillator();
        const g = ctx.createGain();
        o.type = 'sine';
        o.frequency.value = freq;
        g.gain.setValueAtTime(0.04, ctx.currentTime + start);
        g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + start + dur);
        o.connect(g);
        g.connect(ctx.destination);
        o.start(ctx.currentTime + start);
        o.stop(ctx.currentTime + start + dur);
      };
      play(780, 0, 0.09);
      play(1170, 0.08, 0.18);
    } catch {}
  };

  const copyToClipboard = (text, btn, originalLabel) => {
    navigator.clipboard.writeText(text).then(() => {
      btn.textContent = 'Copied ✓';
      setTimeout(() => { btn.textContent = originalLabel; }, 1800);
    }).catch(() => {
      btn.textContent = 'Copy Failed';
      setTimeout(() => { btn.textContent = originalLabel; }, 1800);
    });
  };

  // ============ ZONE OVERLAY RENDERING ============
  function drawZones() {
    const canvas = els.zoneCanvas;
    const container = els.viewport;
    if (!canvas || !container) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = container.getBoundingClientRect();

    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    canvas.style.width = `${rect.width}px`;
    canvas.style.height = `${rect.height}px`;

    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, rect.width, rect.height);

    if (!zonesVisible) return;

    const config = CAMERA_ZONES[currentCamera];
    if (!config) return;

    const scaleX = rect.width / 640;
    const scaleY = rect.height / 480;

    // Door zone — Cyan dashed bounds
    if (config.doorZone) {
      ctx.beginPath();
      config.doorZone.forEach((pt, i) => {
        const x = pt[0] * scaleX;
        const y = pt[1] * scaleY;
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      });
      ctx.closePath();
      ctx.fillStyle = 'rgba(56, 189, 248, 0.08)';
      ctx.fill();
      ctx.strokeStyle = 'rgba(56, 189, 248, 0.85)';
      ctx.lineWidth = 1.8;
      ctx.setLineDash([5, 4]);
      ctx.stroke();
      ctx.setLineDash([]);

      const [fx, fy] = config.doorZone[0];
      ctx.fillStyle = 'rgba(56, 189, 248, 0.95)';
      ctx.font = '600 10px "IBM Plex Mono", monospace';
      ctx.fillText('DOOR ZONE // CH-01', fx * scaleX + 6, fy * scaleY + 14);
    }

    // Restricted zone — Rose dashed bounds
    if (config.restrictedZones) {
      config.restrictedZones.forEach(z => {
        ctx.beginPath();
        z.poly.forEach((pt, i) => {
          const x = pt[0] * scaleX;
          const y = pt[1] * scaleY;
          i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        });
        ctx.closePath();
        ctx.fillStyle = 'rgba(244, 63, 94, 0.08)';
        ctx.fill();
        ctx.strokeStyle = 'rgba(244, 63, 94, 0.85)';
        ctx.lineWidth = 1.8;
        ctx.setLineDash([5, 4]);
        ctx.stroke();
        ctx.setLineDash([]);

        const [fx, fy] = z.poly[0];
        ctx.fillStyle = 'rgba(244, 63, 94, 0.95)';
        ctx.font = '600 10px "IBM Plex Mono", monospace';
        ctx.fillText(z.name.toUpperCase() + ' // RESTRICTED', fx * scaleX + 6, fy * scaleY + 14);
      });
    }
  }

  // ============ HUD CLOCK & TELEMETRY ============
  function updateClock() {
    const now = new Date();
    els.hudTime.textContent = now.toTimeString().split(' ')[0];
    els.hudCamera.textContent = `CAM: ${currentCamera.toUpperCase()}`;
  }

  async function fetchCameraTelemetry() {
    try {
      const res = await fetch(`/api/cameras/${currentCamera}`, { cache: 'no-store' });
      if (!res.ok) return;
      const cam = await res.json();
      const vlm = cam.vlm || {};
      const hudAi = document.getElementById('hud-ai-text');
      const hudAiPill = document.getElementById('hud-ai');

      if (cam && cam.is_active && typeof cam.fps === 'number') {
        const displayFps = cam.fps > 0 ? cam.fps.toFixed(1) : '25.0';
        els.hudFps.textContent = `${displayFps} FPS`;

        if (vlm.is_busy) {
          const hint = (vlm.current_hint || 'Incident').replace(/_/g, ' ').toUpperCase();
          if (els.statProcessing) {
            els.statProcessing.textContent = `🧠 VLM Thinking [${hint}]`;
            els.statProcessing.style.color = '#f59e0b';
          }
          if (hudAi) hudAi.textContent = `VLM ANALYZING: ${hint}`;
          if (hudAiPill) {
            hudAiPill.classList.add('hud-pill--vlm-busy');
            hudAiPill.classList.remove('hud-pill--ai-active');
          }
        } else {
          const tracks = cam.active_tracks || 0;
          if (els.statProcessing) {
            els.statProcessing.textContent = `Active (${tracks} track${tracks !== 1 ? 's' : ''})`;
            els.statProcessing.style.color = 'var(--accent-cyan)';
          }
          if (hudAi) hudAi.textContent = `AI ACTIVE (${tracks} TRK)`;
          if (hudAiPill) {
            hudAiPill.classList.remove('hud-pill--vlm-busy');
            hudAiPill.classList.add('hud-pill--ai-active');
          }
        }
      } else if (cam && !cam.is_active) {
        els.hudFps.textContent = 'STANDBY';
        if (els.statProcessing) {
          els.statProcessing.textContent = 'Standby';
          els.statProcessing.style.color = '';
        }
        if (hudAi) hudAi.textContent = 'STANDBY';
        if (hudAiPill) {
          hudAiPill.classList.remove('hud-pill--vlm-busy');
          hudAiPill.classList.remove('hud-pill--ai-active');
        }
      }
    } catch (err) {}
  }

  // ============ EVENT FEED RENDERING ============
  function renderEvents() {
    let filtered = currentEvents;

    if (currentCategory) {
      filtered = filtered.filter(e => e.category === currentCategory);
    }
    if (minConfidence > 0) {
      filtered = filtered.filter(e => (e.confidence ?? 1) >= minConfidence);
    }
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      filtered = filtered.filter(e =>
        (e.summary && e.summary.toLowerCase().includes(q)) ||
        (e.camera_id && e.camera_id.toLowerCase().includes(q)) ||
        (e.category && e.category.toLowerCase().includes(q)) ||
        String(e.id).includes(q)
      );
    }

    els.feedCount.textContent = filtered.length;

    if (!filtered.length) {
      els.eventFeed.innerHTML = `
        <div class="empty-state">
          <div class="spinner"></div>
          <span>${currentEvents.length ? 'No incidents match current filter criteria.' : 'No incidents recorded yet. Start camera ingestion to begin.'}</span>
        </div>`;
      renderTimeline([]);
      renderBars('#bars-cat', [], e => e.category, c => CATEGORY_META[c]?.label || c, c => CATEGORY_META[c]?.color || 'var(--accent-cyan)');
      renderBars('#bars-cam', [], e => e.camera_id, id => id.toUpperCase(), () => 'var(--accent-cyan)');
      return;
    }

    els.eventFeed.innerHTML = filtered.map(ev => {
      const meta = CATEGORY_META[ev.category] || { label: ev.category, severity: 'notice', badgeClass: '' };
      const tracksHtml = ev.track_ids && ev.track_ids.length
        ? ev.track_ids.map(id => `<span class="track-chip">#${id}</span>`).join(' ')
        : '';

      const keyframeSrc = ev.keyframe_url || `/frames/${ev.id}.jpg`;
      const summaryText = ev.summary || '';
      const isWeapon = /gun|firearm|handgun|pistol|rifle|knife|blade|weapon|brandish|shot|shooting/i.test(summaryText) || summaryText.includes('[WEAPON DETECTED]');
      const weaponBadge = isWeapon
        ? `<span class="badge badge--weapon" title="Weapon or firearm identified in footage"><span class="weapon-dot"></span> WEAPON DETECTED</span>`
        : '';

      return `
        <article class="event-item event-item--${ev.category} ${isWeapon ? 'event-item--weapon' : ''}" data-id="${ev.id}" tabindex="0" role="listitem" aria-label="Incident ${ev.id}: ${meta.label}">
          <div class="event-thumb-wrapper">
            <img class="event-thumb" src="${keyframeSrc}" alt="Keyframe for incident ${ev.id}" loading="lazy"
              onerror="this.onerror=null;this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'104\\' height=\\'64\\'><rect width=\\'100%\\' height=\\'100%\\' fill=\\'%23080c14\\'/><text x=\\'50%\\' y=\\'50%\\' fill=\\'%23475569\\' font-size=\\'9\\' font-family=\\'monospace\\' text-anchor=\\'middle\\' dominant-baseline=\\'middle\\'>NO FRAME</text></svg>'">
          </div>
          <div class="event-body">
            <div class="event-meta">
              <span class="badge ${meta.badgeClass}">${meta.label}</span>
              ${weaponBadge}
              <span class="event-time" title="${formatTimestamp(ev.timestamp)}">${formatTime(ev.timestamp)}${formatRelativeTime(ev.timestamp) ? ` · ${formatRelativeTime(ev.timestamp)}` : ''}</span>
              <span class="event-camera">${ev.camera_id}</span>
            </div>
            <div class="event-summary">${escapeHtml(ev.summary)}</div>
            <div class="event-footer">
              <span>Conf: ${(ev.confidence * 100).toFixed(0)}%</span>
              <span>Latency: ${ev.latency_ms || 0}ms</span>
              ${tracksHtml ? `<span>Tracks: ${tracksHtml}</span>` : ''}
            </div>
          </div>
        </article>`;
    }).join('');

    $$('.event-item', els.eventFeed).forEach(item => {
      const id = Number(item.dataset.id);
      const handler = () => openModal(id);
      item.addEventListener('click', handler);
      item.addEventListener('keydown', e => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          handler();
        }
      });
    });

    // Render Timeline & Distribution Bars
    renderTimeline(filtered);
    renderBars('#bars-cat', filtered, e => e.category, c => CATEGORY_META[c]?.label || c, c => CATEGORY_META[c]?.color || 'var(--accent-cyan)');
    renderBars('#bars-cam', filtered, e => e.camera_id, id => id.toUpperCase(), () => 'var(--accent-cyan)');
  }

  // ============ TOAST NOTIFICATIONS ============
  function showToast(msg, isErr = false) {
    const toasts = els.toasts || $('#toasts');
    if (!toasts) return;
    const t = document.createElement('div');
    t.className = 'toast' + (isErr ? ' toast--err' : '');
    t.textContent = msg;
    toasts.appendChild(t);
    setTimeout(() => {
      t.style.opacity = '0';
      t.style.transform = 'translateX(20px)';
      t.style.transition = 'all 0.3s ease';
      setTimeout(() => t.remove(), 300);
    }, 4000);
  }

  // ============ TIMELINE & DISTRIBUTION CHARTS ============
  function renderTimeline(events) {
    if (!els.timeline) return;
    const W = 1000, H = 200, L = 46, R = 20, T = 16, B = 30;
    const now = Date.now();
    const timestamps = events.map(e => e.timestamp ? new Date(e.timestamp).getTime() : null).filter(t => t != null);
    const minT = timestamps.length ? Math.min(...timestamps) : now - 86400000;
    const maxT = Math.max(now, timestamps.length ? Math.max(...timestamps) : now);
    const t0 = Math.min(minT, now - 3600000);
    const t1 = maxT;

    const x = t => L + ((t - t0) / (t1 - t0 || 1)) * (W - L - R);
    const y = c => T + (1 - (c ?? 0)) * (H - T - B);

    let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Event timeline: ${events.length} events">`;

    [1.0, 0.5, 0.0].forEach(c => {
      s += `<line x1="${L}" x2="${W - R}" y1="${y(c)}" y2="${y(c)}" stroke="#24334a" stroke-dasharray="${c > 0 ? '3 4' : ''}" stroke-width="1"/>
            <text x="${L - 8}" y="${y(c) + 4}" text-anchor="end">${Math.round(c * 100)}%</text>`;
    });

    s += `<line x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}" stroke="#10b981" stroke-width="2"/>`;

    for (let i = 0; i <= 5; i++) {
      const t = t0 + (t1 - t0) * (i / 5);
      const label = new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
      s += `<text x="${x(t)}" y="${H - 8}" text-anchor="${i === 0 ? 'start' : i === 5 ? 'end' : 'middle'}">${label}</text>`;
    }

    if (!events.length) {
      s += `<text x="${W / 2}" y="${H / 2}" text-anchor="middle" fill="#64748b">No incidents in this view range</text>`;
    } else {
      events.forEach(e => {
        const c = typeof e.confidence === 'number' ? e.confidence : 0.5;
        const t = e.timestamp ? new Date(e.timestamp).getTime() : now;
        const low = c < 0.6;
        const col = low ? '#f59e0b' : (CATEGORY_META[e.category]?.color || '#f43f5e');
        s += `<g class="mk" tabindex="0" role="button" data-id="${e.id}" aria-label="${e.category} at ${formatTime(e.timestamp)} on ${e.camera_id}">
          <line x1="${x(t)}" x2="${x(t)}" y1="${y(0)}" y2="${y(c)}" stroke="${col}" stroke-opacity="0.4" stroke-width="1.5"/>
          <circle cx="${x(t)}" cy="${y(c)}" r="6" fill="${col}" stroke="#0c121e" stroke-width="2"/>
        </g>`;
      });
    }

    s += '</svg>';
    els.timeline.innerHTML = s;
  }

  function initTimelineInteractions() {
    if (!els.timeline || !els.tip) return;
    els.timeline.addEventListener('mouseover', e => {
      const g = e.target.closest('.mk');
      if (g) showTimelineTip(g);
    });
    els.timeline.addEventListener('mousemove', e => {
      if (!els.tip.hidden) positionTimelineTip(e.clientX, e.clientY);
    });
    els.timeline.addEventListener('mouseout', () => {
      els.tip.hidden = true;
    });
    els.timeline.addEventListener('click', e => {
      const g = e.target.closest('.mk');
      if (g && g.dataset.id) {
        openModal(Number(g.dataset.id));
      }
    });
  }

  function showTimelineTip(g) {
    const ev = currentEvents.find(x => String(x.id) === String(g.dataset.id));
    if (!ev || !els.tip) return;
    const catLabel = CATEGORY_META[ev.category]?.label || ev.category;
    els.tip.innerHTML = `
      <b>${formatTimestamp(ev.timestamp)} // ${escapeHtml(ev.camera_id.toUpperCase())}</b>
      <div>Incident: <b>${escapeHtml(catLabel)}</b> (${((ev.confidence || 0) * 100).toFixed(0)}%)</div>
      <div style="margin-top:4px; font-size:0.75rem; color:var(--text-secondary);">${escapeHtml(ev.summary || '').slice(0, 120)}</div>
    `;
    els.tip.hidden = false;
  }

  function positionTimelineTip(px, py) {
    if (!els.tip) return;
    const r = els.tip.getBoundingClientRect();
    els.tip.style.left = Math.min(px + 14, window.innerWidth - r.width - 12) + 'px';
    els.tip.style.top = Math.max(8, Math.min(py + 14, window.innerHeight - r.height - 12)) + 'px';
  }

  function renderBars(sel, events, keyFn, labelFn, colFn) {
    const container = $(sel);
    if (!container) return;
    const counts = {};
    events.forEach(e => {
      const k = keyFn(e);
      counts[k] = (counts[k] || 0) + 1;
    });
    const keys = Object.keys(counts).sort((a, b) => counts[b] - counts[a]);
    const maxVal = Math.max(1, ...Object.values(counts));

    if (!keys.length) {
      container.innerHTML = '<div style="color:var(--text-muted); font-size:0.78rem;">No data for current filters.</div>';
      return;
    }

    container.innerHTML = keys.map(k => {
      const count = counts[k];
      const pct = Math.round((count / maxVal) * 100);
      const col = colFn(k);
      return `
        <div class="bar-row">
          <span>${escapeHtml(labelFn(k))}</span>
          <div class="bar-track">
            <div class="bar-fill" style="width:${pct}%; background:${col};"></div>
          </div>
          <span>${count}</span>
        </div>`;
    }).join('');
  }

  // ============ REPORT GENERATION MODULE ============
  const SECS = {
    overview: 'Report Scope & Overview',
    summary: 'Executive Summary',
    stats: 'Operational Incident Breakdown',
    register: 'Chronological Incident Register',
    patterns: 'Tactical Trends & Spatial Clustering',
    limits: 'Audit Assurance & Limitations',
    perf: 'Technical Latency Metrics',
    ai: 'AI Intelligence Assessment & Recommendations'
  };

  function initReportModule() {
    if (!els.openReportBtn || !els.reportModal) return;

    els.openReportBtn.addEventListener('click', () => {
      const cams = [...new Set(['cam1', 'cam2', ...currentEvents.map(e => e.camera_id)])];
      if (els.rpCams) {
        els.rpCams.innerHTML = cams.map(c => `
          <label><input type="checkbox" name="cam" value="${escapeHtml(c)}" checked> ${escapeHtml(c.toUpperCase())}</label>
        `).join('');
      }
      if (els.rpCats) {
        els.rpCats.innerHTML = Object.keys(CATEGORY_META).map(c => `
          <label><input type="checkbox" name="cat" value="${escapeHtml(c)}" checked> ${escapeHtml(CATEGORY_META[c].label)}</label>
        `).join('');
      }
      if (els.rpSecs) {
        els.rpSecs.innerHTML = Object.entries(SECS).map(([k, label]) => `
          <label><input type="checkbox" name="sec" value="${escapeHtml(k)}" checked> ${escapeHtml(label)}</label>
        `).join('');
      }
      if (els.reportForm) els.reportForm.hidden = false;
      if (els.reportView) els.reportView.hidden = true;
      els.reportModal.showModal();
    });

    if (els.reportClose) {
      els.reportClose.addEventListener('click', () => els.reportModal.close());
    }
    els.reportModal.addEventListener('click', e => {
      if (e.target === els.reportModal) els.reportModal.close();
    });

    if (els.rpPeriod) {
      els.rpPeriod.addEventListener('change', e => {
        if (els.rpCustom) els.rpCustom.hidden = e.target.value !== 'custom';
      });
    }

    if (els.reportForm) {
      els.reportForm.addEventListener('submit', async ev => {
        ev.preventDefault();
        const p = els.rpPeriod.value;
        let from, to = Date.now();
        if (p === 'today') {
          from = new Date().setHours(0, 0, 0, 0);
        } else if (p === 'custom') {
          from = Date.parse(els.rpFrom.value);
          to = Date.parse(els.rpTo.value);
        } else {
          from = to - parseInt(p, 10);
        }

        if (isNaN(from) || isNaN(to) || from >= to) {
          showToast('Please specify a valid reporting period.', true);
          return;
        }

        const getChecked = name => [...document.querySelectorAll(`input[name="${name}"]:checked`)].map(i => i.value);
        const cams = getChecked('cam');
        const cats = getChecked('cat');
        const secs = getChecked('sec');

        if (!cams.length || !cats.length) {
          showToast('Select at least one camera and one event category.', true);
          return;
        }

        const submitBtn = els.rpGo;
        if (submitBtn) {
          submitBtn.disabled = true;
          submitBtn.textContent = 'Retrieving incidents…';
        }

        try {
          const res = await fetch(`/api/events?limit=5000&since=${encodeURIComponent(new Date(from).toISOString())}`);
          const data = await res.json();
          const all = data.events || [];
          const evs = all.filter(e => {
            const t = e.timestamp ? new Date(e.timestamp).getTime() : 0;
            return t >= from && t <= to && cams.includes(e.camera_id) && cats.includes(e.category);
          }).sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());

          if (submitBtn) submitBtn.textContent = 'Synthesizing report…';
          const cfg = {
            from, to, cams, cats, secs,
            detail: els.rpDetail.value,
            notes: (els.rpNotes.value || '').trim()
          };

          const reportSections = await buildReport(evs, cfg);
          showReportView(reportSections, evs, cfg);
        } catch (err) {
          showToast(`Report generation failed: ${err.message}`, true);
        } finally {
          if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Generate Report';
          }
        }
      });
    }
  }

  async function aiNarrative(evs, cfg) {
    const rec = evs.slice(-60).map(e => ({
      id: e.id,
      time: e.timestamp,
      camera: e.camera_id,
      category: e.category,
      confidence: e.confidence,
      summary: e.summary
    }));
    const prompt = `Using ONLY the event records below, write a ${cfg.detail === 'full' ? 'detailed' : 'concise'} security intelligence analysis with: executive summary, notable tactical patterns, and prioritized follow-up actions. Do not invent events. ${cfg.notes ? 'Operator guidance: ' + cfg.notes + '. ' : ''}Records (${rec.length} of ${evs.length}): ${JSON.stringify(rec)}`;
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: prompt })
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    return data.answer || 'No narrative generated.';
  }

  async function buildReport(evs, cfg) {
    const n = evs.length;
    const lats = evs.map(e => e.latency_ms).filter(x => typeof x === 'number');
    const lows = evs.filter(e => (e.confidence ?? 1) < 0.6);
    const has = k => cfg.secs.includes(k);
    const isFull = cfg.detail === 'full';
    const isOverview = cfg.detail === 'overview';

    let ai = null, aiErr = null;
    if (has('ai') && n > 0) {
      try {
        ai = await aiNarrative(evs, cfg);
      } catch (e) {
        aiErr = e.message;
      }
    }

    const byCat = {}, byCam = {};
    evs.forEach(e => {
      byCat[e.category] = (byCat[e.category] || 0) + 1;
      byCam[e.camera_id] = (byCam[e.camera_id] || 0) + 1;
    });

    const topCat = Object.entries(byCat).sort((a, b) => b[1] - a[1])[0];
    const topCam = Object.entries(byCam).sort((a, b) => b[1] - a[1])[0];

    const sec = [];

    // Overview
    sec.push([
      'overview', 'Report Scope & Overview',
      `<div class="report-fact">
        <p><b>Reporting Window:</b> ${formatTimestamp(new Date(cfg.from).toISOString())} \u2192 ${formatTimestamp(new Date(cfg.to).toISOString())}<br>
        <b>Cameras Monitored:</b> ${cfg.cams.map(c => c.toUpperCase()).join(', ')}<br>
        <b>Categories Filtered:</b> ${cfg.cats.map(c => CATEGORY_META[c]?.label || c).join(', ')}<br>
        <b>Generated:</b> ${formatTimestamp(new Date().toISOString())}<br>
        <b>Total Incidents Analyzed:</b> <b>${n}</b></p>
      </div>
      ${cfg.notes ? `<p class="muted-text" style="margin-top:6px;"><b>Operator Guidance:</b> ${escapeHtml(cfg.notes)}</p>` : ''}`
    ]);

    // Summary
    sec.push([
      'summary', 'Executive Summary',
      n ? `<div class="report-fact">
            <p>During this period, <b>${n}</b> security incident${n > 1 ? 's were' : ' was'} verified by the VLM pipeline.
            Predominant incident class: <b>${escapeHtml(topCat ? (CATEGORY_META[topCat[0]]?.label || topCat[0]) : 'None')}</b> (${topCat ? topCat[1] : 0} events).
            <b>${lows.length}</b> events registered low confidence (&lt;60%) and are marked for manual operator verification.</p>
           </div>
           ${ai && isOverview ? `<div class="report-ai-block"><span class="ai-badge">Ollama Intelligence Synthesis</span>${escapeHtml(ai)}</div>` : ''}`
        : `<p class="muted-text">No incidents recorded matching the selected filter scope during this time window.</p>`
    ]);

    // Operational Stats
    if (!isOverview && has('stats') && n) {
      const catTable = `
        <table class="report-table">
          <thead><tr><th>Category</th><th>Events</th><th>Ratio</th></tr></thead>
          <tbody>${Object.entries(byCat).sort((a, b) => b[1] - a[1]).map(([c, count]) => `
            <tr>
              <td>${escapeHtml(CATEGORY_META[c]?.label || c)}</td>
              <td class="mono-cell">${count}</td>
              <td class="mono-cell">${((count / n) * 100).toFixed(1)}%</td>
            </tr>`).join('')}
          </tbody>
        </table>`;
      const camTable = `
        <table class="report-table">
          <thead><tr><th>Camera</th><th>Events</th><th>Ratio</th></tr></thead>
          <tbody>${Object.entries(byCam).sort((a, b) => b[1] - a[1]).map(([cam, count]) => `
            <tr>
              <td>${escapeHtml(cam.toUpperCase())}</td>
              <td class="mono-cell">${count}</td>
              <td class="mono-cell">${((count / n) * 100).toFixed(1)}%</td>
            </tr>`).join('')}
          </tbody>
        </table>`;
      sec.push(['stats', 'Operational Incident Breakdown', `<div class="form-row-2"><div>${catTable}</div><div>${camTable}</div></div>`]);
    }

    // Incident Register
    if (!isOverview && has('register') && n) {
      sec.push([
        'register', 'Chronological Incident Register',
        `<table class="report-table">
          <thead><tr><th>Time</th><th>Camera</th><th>Category</th><th>Confidence</th><th>Summary</th><th>ID</th></tr></thead>
          <tbody>${evs.map(e => `
            <tr>
              <td class="mono-cell">${formatTimestamp(e.timestamp)}</td>
              <td class="mono-cell">${escapeHtml(e.camera_id.toUpperCase())}</td>
              <td><span class="badge ${CATEGORY_META[e.category]?.badgeClass || ''}">${escapeHtml(CATEGORY_META[e.category]?.label || e.category)}</span></td>
              <td class="mono-cell">${((e.confidence || 0) * 100).toFixed(0)}%</td>
              <td>${escapeHtml(e.summary || '')}</td>
              <td class="mono-cell"><a href="${e.keyframe_url || `/frames/${e.id}.jpg`}" target="_blank" style="color:var(--accent-cyan);">#${e.id}</a></td>
            </tr>`).join('')}
          </tbody>
        </table>`
      ]);
    }

    // Trends & Patterns
    if (!isOverview && has('patterns') && n) {
      sec.push([
        'patterns', 'Tactical Trends & Spatial Clustering',
        `<div class="report-fact">
          <p>Primary incident concentration identified on <b>${escapeHtml(topCam ? topCam[0].toUpperCase() : 'N/A')}</b> (${topCam ? topCam[1] : 0} events).
          Primary anomaly type: <b>${escapeHtml(topCat ? (CATEGORY_META[topCat[0]]?.label || topCat[0]) : 'N/A')}</b>.</p>
        </div>`
      ]);
    }

    // Limitations
    if (has('limits')) {
      sec.push([
        'limits', 'Audit Assurance & Limitations',
        `<ul>
          <li><b>${lows.length}</b> incident(s) scored confidence &lt;60% and require secondary human officer review.</li>
          <li>All event summaries and classifications are generated offline via local vision-language inference and should be validated against recorded keyframes.</li>
          <li>System stores event triggers only; continuous benign footage is intentionally not recorded per privacy compliance constraints.</li>
        </ul>`
      ]);
    }

    // Latency stats
    if (has('perf') && lats.length) {
      const sorted = [...lats].sort((a, b) => a - b);
      const mean = Math.round(lats.reduce((a, b) => a + b, 0) / lats.length);
      const median = Math.round(sorted[Math.floor(sorted.length / 2)]);
      const p95 = Math.round(sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95))]);
      sec.push([
        'perf', 'Technical Latency Metrics',
        `<p style="font-family:var(--font-mono); font-size:0.8rem; color:var(--text-secondary);">
          Trigger \u2192 Database latency across ${lats.length} incidents: Mean: <b>${mean} ms</b> | Median: <b>${median} ms</b> | 95th Percentile: <b>${p95} ms</b>.
        </p>`
      ]);
    }

    // AI Narrative
    if (!isOverview && ai) {
      sec.push([
        'ai', 'AI Intelligence Assessment & Recommendations',
        `<div class="report-ai-block"><span class="ai-badge">Ollama Multimodal Synthesis</span>${escapeHtml(ai)}</div>
         ${n > 60 ? '<p class="muted-text" style="margin-top:6px; font-size:0.75rem;">* Note: The AI synthesis evaluated the 60 most recent incident records to fit local context budgets.</p>' : ''}`
      ]);
    } else if (has('ai') && aiErr) {
      sec.push(['ai', 'AI Intelligence Assessment', `<p class="muted-text">AI narrative unavailable (${escapeHtml(aiErr)}). Operational metrics and logs remain fully verified.</p>`]);
    }

    // Appendix
    if (isFull && n) {
      sec.push([
        'appx', 'Audit Appendix',
        `<p style="font-family:var(--font-mono); font-size:0.75rem; color:var(--text-muted);">
          Recorded Incident IDs: ${evs.map(e => '#' + e.id).join(', ')}
        </p>`
      ]);
    }

    return sec;
  }

  function showReportView(sections, evs, cfg) {
    if (!els.reportView || !els.reportForm) return;
    els.reportForm.hidden = true;
    els.reportView.hidden = false;

    const downloadFile = (name, type, content) => {
      const blob = new Blob([content], { type });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = name;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    };

    els.reportView.innerHTML = `
      <div>
        <h2 class="rep-title">EventLens Security Intelligence Report</h2>
        <div class="report-meta-header">
          <span>${formatTimestamp(new Date(cfg.from).toISOString())} \u2192 ${formatTimestamp(new Date(cfg.to).toISOString())}</span>
          <span>\u2022</span>
          <span>${evs.length} incidents</span>
          <span>\u2022</span>
          <span style="text-transform:capitalize;">${escapeHtml(cfg.detail)} Report</span>
        </div>
      </div>

      <nav class="report-toc" aria-label="Report Table of Contents">
        ${sections.map(([id, title]) => `<a href="#rep-sec-${id}">${escapeHtml(title)}</a>`).join('')}
      </nav>

      ${sections.map(([id, title, contentHtml]) => `
        <section id="rep-sec-${id}">
          <h3>${escapeHtml(title)}</h3>
          ${contentHtml}
        </section>
      `).join('')}

      <div class="report-actions">
        <button class="btn btn--secondary" id="btn-copy-rep">
          <svg class="icon-svg icon-svg--sm" viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
          Copy Text
        </button>
        <button class="btn btn--secondary" id="btn-export-csv">
          <svg class="icon-svg icon-svg--sm" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
          Export CSV
        </button>
        <button class="btn btn--secondary" id="btn-export-json">
          <svg class="icon-svg icon-svg--sm" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
          Export JSON
        </button>
        <button class="btn btn--secondary" id="btn-print-rep">
          <svg class="icon-svg icon-svg--sm" viewBox="0 0 24 24"><polyline points="6 9 6 2 18 2 18 9"></polyline><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"></path><rect x="6" y="14" width="12" height="8"></rect></svg>
          Print / PDF
        </button>
        <button class="btn btn--primary" id="btn-rep-revise">Revise Parameters</button>
        <button class="btn" id="btn-rep-done">Done</button>
      </div>
    `;

    // Hook TOC navigation
    els.reportView.querySelectorAll('.report-toc a').forEach(a => {
      a.addEventListener('click', e => {
        e.preventDefault();
        const target = els.reportView.querySelector(a.getAttribute('href'));
        if (target) target.scrollIntoView({ behavior: 'smooth' });
      });
    });

    // Hook Action buttons
    $('#btn-copy-rep', els.reportView).addEventListener('click', () => {
      navigator.clipboard.writeText(els.reportView.innerText)
        .then(() => showToast('Report text copied to clipboard'))
        .catch(() => showToast('Copy failed', true));
    });

    $('#btn-export-csv', els.reportView).addEventListener('click', () => {
      const q = v => `"${String(v ?? '').replace(/"/g, '""')}"`;
      const header = 'id,timestamp,camera_id,category,confidence,latency_ms,summary\n';
      const rows = evs.map(e => [
        e.id,
        e.timestamp,
        e.camera_id,
        e.category,
        e.confidence,
        e.latency_ms,
        e.summary
      ].map(q).join(',')).join('\n');
      downloadFile(`eventlens_report_${Date.now()}.csv`, 'text/csv', header + rows);
      showToast('CSV report exported');
    });

    $('#btn-export-json', els.reportView).addEventListener('click', () => {
      downloadFile(`eventlens_report_${Date.now()}.json`, 'application/json', JSON.stringify({
        meta: cfg,
        total_events: evs.length,
        events: evs
      }, null, 2));
      showToast('JSON report exported');
    });

    $('#btn-print-rep', els.reportView).addEventListener('click', () => {
      window.print();
    });

    $('#btn-rep-revise', els.reportView).addEventListener('click', () => {
      els.reportView.hidden = true;
      els.reportForm.hidden = false;
    });

    $('#btn-rep-done', els.reportView).addEventListener('click', () => {
      els.reportModal.close();
    });
  }

  // ============ MODAL INSPECTION ============
  function openModal(eventId) {
    const ev = currentEvents.find(e => e.id === eventId);
    if (!ev) return;

    const meta = CATEGORY_META[ev.category] || { label: ev.category, badgeClass: '' };
    const keyframeSrc = ev.keyframe_url || `/frames/${ev.id}.jpg`;
    const summaryText = ev.summary || '';
    const isWeapon = /gun|firearm|handgun|pistol|rifle|knife|blade|weapon|brandish|shot|shooting/i.test(summaryText) || summaryText.includes('[WEAPON DETECTED]');

    els.modalCategoryBadge.className = `badge ${meta.badgeClass} ${isWeapon ? 'badge--weapon' : ''}`;
    els.modalCategoryBadge.textContent = isWeapon ? `[WEAPON] ${meta.label}` : meta.label;
    els.modalTitle.textContent = `Incident Record #${ev.id}`;
    els.modalImage.src = keyframeSrc;
    els.modalImage.alt = `Keyframe for ${meta.label} #${ev.id}`;
    els.modalSummary.textContent = ev.summary;
    els.modalCamera.textContent = ev.camera_id;
    els.modalTimestamp.textContent = formatTimestamp(ev.timestamp);
    els.modalConfidence.textContent = `${(ev.confidence * 100).toFixed(1)}%`;
    els.modalLatency.textContent = `${ev.latency_ms || 0} ms`;

    els.modalTracks.innerHTML = ev.track_ids && ev.track_ids.length
      ? ev.track_ids.map(id => `<span class="track-chip">Target #${id}</span>`).join(' ')
      : '<span style="color:var(--text-dim)">None detected</span>';

    // Fetch and display multi-frame temporal clip sequence
    if (els.modalClipsContainer && els.modalClipsStrip) {
      els.modalClipsContainer.style.display = 'none';
      els.modalClipsStrip.innerHTML = '';
      fetch(`/api/clips/${ev.id}`)
        .then(r => r.json())
        .then(data => {
          if (data && data.frames && data.frames.length > 0) {
            els.modalClipsContainer.style.display = 'block';
            els.modalClipsCount.textContent = `${data.count} Frames Captured`;
            els.modalClipsStrip.innerHTML = data.frames.map((fPath, idx) => `
              <div class="clip-thumb-wrap" style="flex-shrink:0; width:84px; height:52px; border-radius:3px; overflow:hidden; border:1px solid var(--border-default); cursor:pointer;" title="Click to view Frame ${idx+1}">
                <img src="${fPath}" style="width:100%; height:100%; object-fit:cover;" alt="Sequence frame ${idx+1}" onclick="document.getElementById('modal-image').src='${fPath}'">
              </div>
            `).join('');
          }
        })
        .catch(() => {});
    }

    els.queryLink.href = `chat.html?q=${encodeURIComponent(`Provide full analysis of incident #${ev.id} on ${ev.camera_id}`)}`;

    els.copyEventBtn.onclick = () => copyToClipboard(JSON.stringify(ev, null, 2), els.copyEventBtn, 'Copy JSON');

    els.modal.showModal();
    document.body.style.overflow = 'hidden';
  }

  function closeModal() {
    els.modal.close();
    document.body.style.overflow = '';
  }

  // ============ API COMMUNICATIONS ============
  async function fetchStats() {
    try {
      const res = await fetch('/api/stats', { cache: 'no-store' });
      if (!res.ok) return;
      const s = await res.json();
      els.statToday.textContent = s.events_today ?? '\u2014';
      els.statTotal.textContent = s.total_events ?? '\u2014';
      els.statLatency.textContent = s.avg_latency_ms ? `${s.avg_latency_ms} ms` : '\u2014 ms';
      els.statProcessing.textContent = s.pipeline_status || (s.events_today > 0 ? 'Active' : 'Idle');

      if (s.categories) {
        let total = 0;
        for (const [cat, cnt] of Object.entries(s.categories)) {
          if (els.filterCounts[cat]) els.filterCounts[cat].textContent = cnt;
          total += cnt;
        }
        els.filterCounts.all.textContent = total;
      }
    } catch (err) {
      console.warn('[EventLens] Stats fetch failed:', err);
    }
  }

  async function fetchEvents() {
    try {
      const res = await fetch('/api/events?limit=50', { cache: 'no-store' });
      if (!res.ok) return;
      const data = await res.json();
      const events = data.events || [];

      if (events.length) {
        const newEvents = events.filter(e => e.id > lastEventId);
        // Only alert audio if a new verified event with confidence >= 65% is recorded
        if (lastEventId !== 0 && newEvents.some(e => (e.confidence ?? 0) >= 0.65)) {
          playAlertChime();
        }
        lastEventId = Math.max(...events.map(e => e.id));
      }

      currentEvents = events;
      renderEvents();
    } catch (err) {
      console.warn('[EventLens] Events fetch failed:', err);
    }
  }

  async function startSource(source) {
    els.startSourceBtn.disabled = true;
    els.startSourceBtn.innerHTML = `
      <div class="spinner" style="width:12px;height:12px;border-width:2px;"></div>
      Connecting…`;

    // If webcam source requested, auto-disable synthetic lobby overlay zones
    const isWebcam = source === '0' || source.toLowerCase().includes('webcam');
    if (isWebcam) {
      zonesVisible = false;
      if (els.zonesToggle) els.zonesToggle.setAttribute('aria-pressed', 'false');
      if (els.zonesState) els.zonesState.textContent = 'Off';
      drawZones();
    }

    try {
      const res = await fetch('/api/source', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ camera_id: currentCamera, source })
      });
      const data = await res.json();

      if (data.success) {
        els.viewport.classList.remove('offline');
        els.streamImg.src = `/stream/${currentCamera}?t=${Date.now()}`;
        els.startSourceBtn.textContent = 'Active ✓';
        setTimeout(() => {
          els.startSourceBtn.innerHTML = `
            <svg class="icon-svg icon-svg--sm" viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3"/></svg>
            Start Ingestion`;
          els.startSourceBtn.disabled = false;
        }, 2200);
      } else {
        throw new Error(data.detail || 'Ingestion worker failed to start');
      }
    } catch (err) {
      console.error('[EventLens] Ingestion error:', err);
      alert(`Source ingestion failed: ${err.message}`);
      els.startSourceBtn.innerHTML = `
        <svg class="icon-svg icon-svg--sm" viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3"/></svg>
        Start Ingestion`;
      els.startSourceBtn.disabled = false;
    }
  }

  // ============ EVENT LISTENERS & SHORTCUTS ============
  function initHandlers() {
    // Camera stream selector
    els.cameraSelect.addEventListener('change', e => {
      currentCamera = e.target.value;
      els.streamImg.src = `/stream/${currentCamera}?t=${Date.now()}`;
      drawZones();
      fetchEvents();
      fetchCameraTelemetry();
    });

    // Quick Live Webcam button
    if (els.quickWebcamBtn) {
      els.quickWebcamBtn.addEventListener('click', () => {
        els.sourceInput.value = '0';
        startSource('0');
      });
    }

    // Zones toggle
    els.zonesToggle.addEventListener('click', () => {
      zonesVisible = !zonesVisible;
      els.zonesToggle.setAttribute('aria-pressed', zonesVisible);
      els.zonesState.textContent = zonesVisible ? 'On' : 'Off';
      drawZones();
    });

    // Audio toggle
    els.audioToggle.addEventListener('click', () => {
      audioEnabled = !audioEnabled;
      els.audioToggle.setAttribute('aria-label', `Toggle alert audio (${audioEnabled ? 'ON' : 'OFF'})`);
      els.audioToggle.title = `Alert audio: ${audioEnabled ? 'ON' : 'OFF'} (Key: M)`;
      els.audioLabel.textContent = audioEnabled ? 'Audio On' : 'Muted';

      if (audioEnabled) {
        els.audioIcon.innerHTML = `
          <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path>
          <path d="M13.73 21a2 2 0 0 1-3.46 0"></path>`;
        els.audioToggle.classList.remove('active');
      } else {
        els.audioIcon.innerHTML = `
          <path d="M13.73 21a2 2 0 0 1-3.46 0"></path>
          <path d="M18.63 13A17.89 17.89 0 0 1 18 8"></path>
          <path d="M6.26 6.26A5.86 5.86 0 0 0 6 8c0 7-3 9-3 9h14"></path>
          <path d="M1 1l22 22"></path>`;
        els.audioToggle.classList.add('active');
      }
    });

    // Quick scenario buttons
    els.scenarioBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        const src = btn.dataset.src;
        els.sourceInput.value = src;
        startSource(src);
      });
    });

    // Source start
    els.startSourceBtn.addEventListener('click', () => {
      const src = els.sourceInput.value.trim() || '0';
      startSource(src);
    });
    els.sourceInput.addEventListener('keydown', e => {
      if (e.key === 'Enter') {
        startSource(els.sourceInput.value.trim() || '0');
      }
    });

    // Filter tabs
    els.filterBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        els.filterBtns.forEach(b => {
          b.classList.remove('active');
          b.setAttribute('aria-pressed', 'false');
        });
        btn.classList.add('active');
        btn.setAttribute('aria-pressed', 'true');
        currentCategory = btn.dataset.category;
        renderEvents();
      });
    });

    // Confidence threshold filter
    if (els.confidenceFilter) {
      els.confidenceFilter.addEventListener('change', e => {
        minConfidence = parseFloat(e.target.value) || 0;
        renderEvents();
      });
    }

    // Search query
    els.eventSearch.addEventListener('input', e => {
      searchQuery = e.target.value.trim().toLowerCase();
      renderEvents();
    });

    // Snapshot download
    els.snapshotBtn.addEventListener('click', () => {
      try {
        const img = els.streamImg;
        const canvas = document.createElement('canvas');
        canvas.width = img.naturalWidth || 640;
        canvas.height = img.naturalHeight || 360;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(img, 0, 0);
        const link = document.createElement('a');
        link.download = `eventlens_${currentCamera}_${Date.now()}.png`;
        link.href = canvas.toDataURL('image/png');
        link.click();
        showToast(`Captured snapshot on ${currentCamera.toUpperCase()}`);
      } catch {
        const link = document.createElement('a');
        link.download = `eventlens_${currentCamera}_${Date.now()}.jpg`;
        link.href = els.streamImg.src;
        link.click();
        showToast(`Captured frame on ${currentCamera.toUpperCase()}`);
      }
    });

    // Fullscreen toggle
    els.fullscreenBtn.addEventListener('click', () => {
      if (!document.fullscreenElement) {
        els.viewport.requestFullscreen().catch(console.warn);
      } else {
        document.exitFullscreen();
      }
    });
    document.addEventListener('fullscreenchange', () => setTimeout(drawZones, 200));

    // Modal close
    els.modalClose.addEventListener('click', closeModal);
    els.modal.addEventListener('click', e => {
      if (e.target === els.modal) closeModal();
    });

    // Initialize Timeline Interactions & Report Module
    initTimelineInteractions();
    initReportModule();

    // Clear incidents feed
    if (els.clearEventsBtn) {
      els.clearEventsBtn.addEventListener('click', async () => {
        if (!confirm('Clear all recorded incidents from database and feed?')) return;
        try {
          const res = await fetch('/api/events', { method: 'DELETE' });
          if (res.ok) {
            currentEvents = [];
            renderEvents();
            fetchStats();
            showToast('All recorded incidents cleared');
          }
        } catch (err) {
          console.error('[EventLens] Failed to clear incidents:', err);
          showToast('Failed to clear incidents', true);
        }
      });
    }

    // Stream error recovery
    els.streamImg.addEventListener('error', () => {
      els.viewport.classList.add('offline');
    });
    els.streamImg.addEventListener('load', () => {
      els.viewport.classList.remove('offline');
    });

    // Global Tactical Keyboard Shortcuts
    document.addEventListener('keydown', e => {
      // Ignore if user is currently typing in an input or textarea
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) {
        if (e.key === 'Escape') {
          e.target.blur();
          if (els.modal.open) closeModal();
          if (els.reportModal && els.reportModal.open) els.reportModal.close();
        }
        return;
      }

      if (e.key === 'Escape') {
        if (els.modal.open) closeModal();
        if (els.reportModal && els.reportModal.open) els.reportModal.close();
      } else if (e.key === '/' || e.key === '?') {
        e.preventDefault();
        els.eventSearch.focus();
      } else if (e.key === 'z' || e.key === 'Z') {
        els.zonesToggle.click();
      } else if (e.key === 'm' || e.key === 'M') {
        els.audioToggle.click();
      } else if (e.key === '1') {
        els.cameraSelect.value = 'cam1';
        els.cameraSelect.dispatchEvent(new Event('change'));
      } else if (e.key === '2') {
        els.cameraSelect.value = 'cam2';
        els.cameraSelect.dispatchEvent(new Event('change'));
      } else if (e.key === 'f' || e.key === 'F') {
        els.fullscreenBtn.click();
      }
    });

    window.addEventListener('resize', drawZones);
  }

  // ============ POLLING LOOP ============
  function startPolling() {
    fetchStats();
    fetchEvents();
    fetchCameraTelemetry();
    pollTimer = setInterval(() => {
      fetchStats();
      fetchEvents();
    }, 2000);
    clockTimer = setInterval(() => {
      updateClock();
      fetchCameraTelemetry();
    }, 1000);
  }

  function stopPolling() {
    clearInterval(pollTimer);
    clearInterval(clockTimer);
  }

  // ============ INITIALIZE ============
  document.addEventListener('DOMContentLoaded', () => {
    initHandlers();
    updateClock();
    drawZones();
    startPolling();
    console.log('[EventLens] Dashboard initialized with SOC keyboard navigation');
  });

  window.addEventListener('beforeunload', stopPolling);
})();