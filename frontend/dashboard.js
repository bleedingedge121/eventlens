// EventLens — Professional Security Operations Dashboard Client
// Zero-framework, high-reliability ES6+ module inspired by Verkada, Frigate & Linear

(() => {
  'use strict';

  // ============ OPERATIONAL STATE ============
  let currentCamera = 'cam1';
  let currentCategory = '';
  let currentStatus = '';
  let searchQuery = '';
  let overlayMode = 'incidents'; // 'incidents' | 'all' | 'off'
  let audioEnabled = true;
  let lastEventsSig = null;
  let currentEvents = [];
  let pollTimer = null;
  let statsTimer = null;
  let selectedIncident = null;
  let isDemoActive = false;
  let isScrubbing = false;

  let taxonomy = [
    { id: 'fighting', label: 'Fighting', severity: 'critical', color: '#ef4444' },
    { id: 'person_down', label: 'Person Down', severity: 'high', color: '#f97316' },
    { id: 'tailgating', label: 'Tailgating', severity: 'medium', color: '#eab308' },
    { id: 'crowd_incident', label: 'Crowd Surge', severity: 'medium', color: '#3b82f6' },
    { id: 'suspicious_activity', label: 'Suspicious Activity', severity: 'low', color: '#8b5cf6' }
  ];

  // Helper selectors
  const $ = (sel, ctx = document) => ctx.querySelector(sel);
  const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

  // DOM Elements
  const els = {
    // Top Bar Telemetry
    statToday: $('#stat-today'),
    statOpen: $('#stat-open'),
    statLatency: $('#stat-latency'),
    statFps: $('#stat-fps'),
    statVram: $('#stat-vram'),
    demoBadge: $('#demo-badge'),

    // Overlay Toggles
    btnOverlayIncidents: $('#btn-overlay-incidents'),
    btnOverlayAll: $('#btn-overlay-all'),
    btnOverlayOff: $('#btn-overlay-off'),

    // Sources Dialog
    btnOpenSources: $('#btn-open-sources'),
    sourcesDialog: $('#sources-dialog'),
    sourcesDialogClose: $('#sources-dialog-close'),
    sourceInput: $('#source-input'),
    startSourceBtn: $('#start-source'),

    // Query AI Dialog
    btnQueryAi: $('#btn-query-ai'),
    queryDialog: $('#query-dialog'),
    queryDialogClose: $('#query-dialog-close'),
    chatForm: $('#chat-form'),
    chatInput: $('#chat-input'),
    queryResponse: $('#query-response'),
    queryAnswer: $('#query-answer'),
    querySql: $('#query-sql'),
    querySqlWrap: $('#query-sql-wrap'),
    queryEventCount: $('#query-event-count'),
    queryEventsList: $('#query-events-list'),

    // Camera list & Viewport
    cameraList: $('#camera-list'),
    btnAddCamera: $('#btn-add-camera'),
    cameraModal: $('#camera-modal'),
    camModalClose: $('#cam-modal-close'),
    camModalCancel: $('#cam-modal-cancel'),
    camForm: $('#cam-form'),

    streamImg: $('#stream'),
    streamFallback: $('#stream-fallback'),
    detectionCanvas: $('#detection-canvas'),
    hudCamId: $('#hud-cam-id'),
    hudPts: $('#hud-pts'),
    hudFrame: $('#hud-frame'),
    btnSnapshot: $('#snapshot'),
    btnFullscreen: $('#fullscreen'),

    // Timeline Scrubber
    nvrSlider: $('#nvr-slider'),
    timelineMarkers: $('#timeline-markers'),
    timelineTimeDisplay: $('#timeline-time-display'),
    nvrPlayPause: $('#nvr-play-pause'),
    nvrPlayIcon: $('#nvr-play-icon'),
    nvrStepBack: $('#nvr-step-back'),
    nvrStepFwd: $('#nvr-step-fwd'),
    nvrLiveSnap: $('#nvr-live-snap'),

    // Incident Ledger
    feedCount: $('#feed-count'),
    clearEventsBtn: $('#clear-events'),
    eventSearch: $('#event-search'),
    taxonomyFilters: $('#taxonomy-filters'),
    statusTabs: $$('.status-tab'),
    eventFeed: $('#event-feed'),

    // Incident Drawer
    incidentDrawer: $('#incident-drawer'),
    drawerClose: $('#drawer-close'),
    drawerCategoryBadge: $('#drawer-category-badge'),
    drawerId: $('#drawer-id'),
    drawerStatusBadge: $('#drawer-status-badge'),
    drawerKeyframe: $('#drawer-keyframe'),
    drawerVideo: $('#drawer-video'),
    drawerMediaTabs: $('#drawer-media-tabs'),
    btnShowKeyframe: $('#btn-show-keyframe'),
    btnShowClip: $('#btn-show-clip'),
    drawerSummary: $('#drawer-summary'),
    drawerConfidence: $('#drawer-confidence'),
    drawerCamera: $('#drawer-camera'),
    drawerTime: $('#drawer-time'),
    drawerDuration: $('#drawer-duration'),
    drawerTracks: $('#drawer-tracks'),
    drawerLatency: $('#drawer-latency'),
    drawerTagsSection: $('#drawer-tags-section'),
    drawerTags: $('#drawer-tags'),
    btnActionDismiss: $('#btn-action-dismiss'),
    btnActionAck: $('#btn-action-ack'),
    btnActionEscalate: $('#btn-action-escalate'),

    // Report
    openReportBtn: $('#open-report'),
    reportModal: $('#report-modal'),
    repModalClose: $('#rep-modal-close'),
    reportView: $('#report-view'),

    // Audio
    audioToggle: $('#audio-toggle'),
    audioSound: $('#alert-sound'),
  };

  // Audio state
  let audioContext = null;
  const playAlertTone = (severity = 'medium') => {
    if (!audioEnabled) return;
    try {
      if (els.audioSound) {
        els.audioSound.currentTime = 0;
        els.audioSound.play().catch(() => {});
      }
    } catch (_) {}
  };

  // Format timestamps
  const formatTime = (iso) => {
    if (!iso) return '--:--:--';
    try {
      const d = new Date(iso);
      return d.toTimeString().split(' ')[0];
    } catch (_) {
      return iso;
    }
  };

  const getTaxonomyMeta = (cat) => {
    const found = taxonomy.find(t => t.id === cat);
    return found || { id: cat, label: cat.replace('_', ' '), severity: 'low', color: '#6b7280' };
  };

  // ============ TAXONOMY LOADER ============
  const loadTaxonomy = async () => {
    try {
      const res = await fetch('/api/taxonomy');
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data.categories) && data.categories.length > 0) {
          taxonomy = data.categories;
        }
      }
    } catch (e) {
      console.warn('Taxonomy load notice:', e);
    }
    renderTaxonomyFilters();
  };

  const renderTaxonomyFilters = () => {
    els.taxonomyFilters.innerHTML = `
      <button class="filter-pill ${currentCategory === '' ? 'active' : ''}" data-category="">All</button>
      ${taxonomy.map(t => `
        <button class="filter-pill ${currentCategory === t.id ? 'active' : ''}" data-category="${t.id}" style="--cat-color:${t.color};">
          ${t.label}
        </button>
      `).join('')}
    `;

    $$('.filter-pill', els.taxonomyFilters).forEach(btn => {
      btn.addEventListener('click', () => {
        $$('.filter-pill', els.taxonomyFilters).forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        currentCategory = btn.dataset.category || '';
        renderIncidentFeed();
      });
    });
  };

  // ============ STATS TELEMETRY ============
  const fetchStats = async () => {
    try {
      const res = await fetch('/api/stats');
      if (!res.ok) return;
      const data = await res.json();

      els.statToday.textContent = data.events_today ?? 0;
      els.statOpen.textContent = data.open_incidents ?? 0;
      els.statLatency.textContent = `${Math.round(data.p50_latency_ms || data.avg_latency_ms || 0)} ms`;
      els.statFps.textContent = (data.fps !== undefined ? Number(data.fps).toFixed(1) : '25.0');

      if (data.vram_used_mb && data.vram_total_mb) {
        const usedGb = (data.vram_used_mb / 1024).toFixed(1);
        const totalGb = (data.vram_total_mb / 1024).toFixed(1);
        els.statVram.textContent = `${usedGb} / ${totalGb} GB`;
      }
    } catch (_) {}
  };

  // ============ CAMERA STATUS & SCRUBBER ============
  const updateCameraStatus = async () => {
    try {
      const res = await fetch(`/api/cameras/${currentCamera}`);
      if (!res.ok) return;
      const data = await res.json();

      if (data.pts_sec !== undefined) {
        const s = Math.floor(data.pts_sec % 60);
        const m = Math.floor((data.pts_sec / 60) % 60);
        const h = Math.floor(data.pts_sec / 3600);
        const ptsStr = `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
        els.hudPts.textContent = `PTS ${ptsStr}`;
        els.timelineTimeDisplay.textContent = ptsStr;
      }

      if (data.frame_idx !== undefined) {
        els.hudFrame.textContent = `FRM #${String(data.frame_idx).padStart(5, '0')}`;
      }

      if (!isScrubbing && data.progress_ratio !== undefined) {
        els.nvrSlider.value = Math.round(data.progress_ratio * 1000);
      }

      if (data.is_paused !== undefined) {
        els.nvrPlayIcon.textContent = data.is_paused ? '▶' : '⏸';
      }

      // Draw detection canvas according to overlayMode
      renderDetectionOverlay(data.active_detections || []);
    } catch (_) {}
  };

  // Canvas Detection Overlay (1px corner brackets, no confidence text on normal tracks)
  const renderDetectionOverlay = (detections = []) => {
    const canvas = els.detectionCanvas;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    ctx.clearRect(0, 0, width, height);

    if (overlayMode === 'off' || !detections.length) return;

    // Determine active incident tracks
    const activeIncidentTracks = new Set();
    const recentIncidents = currentEvents.slice(0, 3);
    recentIncidents.forEach(ev => {
      (ev.track_ids || []).forEach(tid => activeIncidentTracks.add(tid));
    });

    detections.forEach(det => {
      const box = det.box || [];
      const tid = det.track_id;
      const isIncidentTrack = activeIncidentTracks.has(tid);

      // If "incidents only" mode, skip normal tracks
      if (overlayMode === 'incidents' && !isIncidentTrack) {
        return;
      }

      // Scale coordinates if required
      const [x1, y1, x2, y2] = box;
      const bx = x1;
      const by = y1;
      const bw = x2 - x1;
      const bh = y2 - y1;

      // Color: severity color if incident track, else subtle neutral
      const strokeColor = isIncidentTrack ? '#ef4444' : 'rgba(255, 255, 255, 0.45)';
      ctx.strokeStyle = strokeColor;
      ctx.lineWidth = 1;

      // Draw 1px corner brackets (Verkada / Military style)
      const bracketLen = Math.min(12, bw / 3, bh / 3);

      // Top-Left
      ctx.beginPath();
      ctx.moveTo(bx, by + bracketLen);
      ctx.lineTo(bx, by);
      ctx.lineTo(bx + bracketLen, by);
      ctx.stroke();

      // Top-Right
      ctx.beginPath();
      ctx.moveTo(bx + bw - bracketLen, by);
      ctx.lineTo(bx + bw, by);
      ctx.lineTo(bx + bw, by + bracketLen);
      ctx.stroke();

      // Bottom-Left
      ctx.beginPath();
      ctx.moveTo(bx, by + bh - bracketLen);
      ctx.lineTo(bx, by + bh);
      ctx.lineTo(bx + bracketLen, by + bh);
      ctx.stroke();

      // Bottom-Right
      ctx.beginPath();
      ctx.moveTo(bx + bw - bracketLen, by + bh);
      ctx.lineTo(bx + bw, by + bh);
      ctx.lineTo(bx + bw, by + bh - bracketLen);
      ctx.stroke();

      // Small minimal track ID label only
      ctx.font = '10px "IBM Plex Mono", monospace';
      ctx.fillStyle = strokeColor;
      ctx.fillText(`#${tid}`, bx, Math.max(12, by - 4));
    });
  };

  // ============ INCIDENTS FEED ============
  const fetchEvents = async () => {
    try {
      const res = await fetch(`/api/events?limit=150`);
      if (!res.ok) return;
      const data = await res.json();
      const events = Array.isArray(data.events) ? data.events : [];

      // Check signature for new arrivals
      const sig = events.slice(0, 10).map(e => `${e.id}:${e.occurrences}:${e.status}`).join('|');
      if (sig !== lastEventsSig) {
        if (lastEventsSig !== null && events.length > currentEvents.length) {
          playAlertTone();
        }
        lastEventsSig = sig;
        currentEvents = events;
        renderIncidentFeed();
        renderTimelineMarkers();
      }
    } catch (_) {}
  };

  const renderIncidentFeed = () => {
    const list = els.eventFeed;
    if (!list) return;

    let filtered = currentEvents.filter(e => {
      // Category filter
      if (currentCategory && e.category !== currentCategory) return false;
      // Status filter
      if (currentStatus && (e.status || 'new') !== currentStatus) return false;
      // Search query
      if (searchQuery) {
        const q = searchQuery.toLowerCase();
        const text = `${e.category} ${e.summary} ${e.camera_id} ${(e.track_ids || []).join(' ')}`.toLowerCase();
        if (!text.includes(q)) return false;
      }
      return true;
    });

    els.feedCount.textContent = filtered.length;

    if (!filtered.length) {
      list.innerHTML = `
        <div class="empty-state">
          <span>No incidents matching active filters.</span>
        </div>
      `;
      return;
    }

    list.innerHTML = filtered.map(ev => {
      const meta = getTaxonomyMeta(ev.category);
      const isDismissed = (ev.status === 'dismissed');
      const isAck = (ev.status === 'acknowledged');
      const occCount = ev.occurrences || 1;
      const statusLabel = isDismissed ? 'Dismissed' : (isAck ? 'Ack' : 'New');
      const statusClass = isDismissed ? 'card-status-tag--dismissed' : (isAck ? 'card-status-tag--ack' : 'card-status-tag--new');

      return `
        <div class="incident-card ${isDismissed ? 'dismissed' : ''}" data-id="${ev.id}">
          <div class="card-top">
            <div class="card-category-wrap">
              <span class="severity-dot" style="background:${meta.color};"></span>
              <span class="card-category">${meta.label}</span>
            </div>
            <div class="card-meta-right">
              <span>${formatTime(ev.timestamp)}</span>
            </div>
          </div>
          <p class="card-summary">${escapeHtml(ev.summary || 'Incident verified by VLM.')}</p>
          <div class="card-footer">
            <span class="card-camera">${ev.camera_id ? ev.camera_id.toUpperCase() : 'CAM 01'}</span>
            ${occCount > 1 ? `<span class="card-occurrences">${occCount}x</span>` : ''}
            <span class="card-status-tag ${statusClass}">${statusLabel}</span>
          </div>
        </div>
      `;
    }).join('');

    // Attach click listeners to cards
    $$('.incident-card', list).forEach(card => {
      card.addEventListener('click', () => {
        const id = Number(card.dataset.id);
        openIncidentDrawer(id);
      });
    });
  };

  // Render Timeline Colored Markers
  const renderTimelineMarkers = () => {
    const wrap = els.timelineMarkers;
    if (!wrap) return;

    if (!currentEvents.length) {
      wrap.innerHTML = '';
      return;
    }

    // Map events across slider (mock distribution or modulo index)
    wrap.innerHTML = currentEvents.slice(0, 50).map((ev, idx) => {
      const meta = getTaxonomyMeta(ev.category);
      const pct = (idx * 19.3) % 100;
      return `<div class="timeline-marker-tick" style="left:${pct.toFixed(1)}%; background:${meta.color};" title="${meta.label} at ${formatTime(ev.timestamp)}"></div>`;
    }).join('');
  };

  // ============ INCIDENT DETAIL DRAWER ============
  const openIncidentDrawer = (eventId) => {
    const ev = currentEvents.find(e => e.id === eventId);
    if (!ev) return;
    selectedIncident = ev;

    const meta = getTaxonomyMeta(ev.category);
    els.drawerCategoryBadge.textContent = meta.label;
    els.drawerCategoryBadge.style.color = meta.color;
    els.drawerId.textContent = `#${ev.id}`;
    els.drawerStatusBadge.textContent = (ev.status || 'new').toUpperCase();

    // Keyframe & Clip setup
    const keyframeUrl = ev.keyframe_url || `/frames/${ev.id}.jpg`;
    els.drawerKeyframe.src = keyframeUrl;
    els.drawerKeyframe.style.display = 'block';

    const clipUrl = `/clips/${ev.id}/clip.mp4`;
    els.drawerVideo.src = clipUrl;
    els.drawerVideo.style.display = 'none';
    els.drawerMediaTabs.style.display = 'flex';
    els.btnShowKeyframe.classList.add('active');
    els.btnShowClip.classList.remove('active');

    // Observation & Evidence
    els.drawerSummary.textContent = ev.summary || 'Verified security event observed in frame viewport.';
    els.drawerConfidence.textContent = `${Math.round((ev.confidence || 0.85) * 100)}%`;
    els.drawerCamera.textContent = (ev.camera_id || 'CAM1').toUpperCase();
    els.drawerTime.textContent = formatTime(ev.timestamp);

    const occ = ev.occurrences || 1;
    els.drawerDuration.textContent = occ > 1 ? `${occ} occurrences (extended incident)` : 'Single trigger';
    els.drawerTracks.textContent = (ev.track_ids && ev.track_ids.length) ? ev.track_ids.map(t => `#${t}`).join(', ') : 'None';
    els.drawerLatency.textContent = `${ev.latency_ms || 320} ms`;

    // Tags
    if (ev.tags && Array.isArray(ev.tags) && ev.tags.length > 0) {
      els.drawerTagsSection.style.display = 'flex';
      els.drawerTags.innerHTML = ev.tags.map(t => `<span class="drawer-tag">${escapeHtml(t)}</span>`).join('');
    } else {
      els.drawerTagsSection.style.display = 'none';
    }

    els.incidentDrawer.classList.add('open');
    els.incidentDrawer.setAttribute('aria-hidden', 'false');
  };

  const closeIncidentDrawer = () => {
    els.incidentDrawer.classList.remove('open');
    els.incidentDrawer.setAttribute('aria-hidden', 'true');
    els.drawerVideo.pause();
    selectedIncident = null;
  };

  // Status updates (Acknowledge / Dismiss / Escalate)
  const setIncidentStatus = async (status) => {
    if (!selectedIncident) return;
    try {
      const res = await fetch(`/api/events/${selectedIncident.id}/status`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status })
      });
      if (res.ok) {
        selectedIncident.status = status;
        els.drawerStatusBadge.textContent = status.toUpperCase();
        fetchEvents();
        fetchStats();
      }
    } catch (e) {
      console.warn('Status update error:', e);
    }
  };

  // ============ EVENT LISTENERS & WIRING ============
  const setupEventListeners = () => {
    // Drawer tab toggle
    els.btnShowKeyframe.addEventListener('click', () => {
      els.btnShowKeyframe.classList.add('active');
      els.btnShowClip.classList.remove('active');
      els.drawerKeyframe.style.display = 'block';
      els.drawerVideo.style.display = 'none';
      els.drawerVideo.pause();
    });

    els.btnShowClip.addEventListener('click', () => {
      els.btnShowClip.classList.add('active');
      els.btnShowKeyframe.classList.remove('active');
      els.drawerKeyframe.style.display = 'none';
      els.drawerVideo.style.display = 'block';
      els.drawerVideo.play().catch(() => {});
    });

    els.drawerClose.addEventListener('click', closeIncidentDrawer);

    // Drawer action buttons
    els.btnActionDismiss.addEventListener('click', () => setIncidentStatus('dismissed'));
    els.btnActionAck.addEventListener('click', () => setIncidentStatus('acknowledged'));
    els.btnActionEscalate.addEventListener('click', () => setIncidentStatus('escalated'));

    // Status filter tabs
    els.statusTabs.forEach(tab => {
      tab.addEventListener('click', () => {
        els.statusTabs.forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        currentStatus = tab.dataset.status || '';
        renderIncidentFeed();
      });
    });

    // Search field
    els.eventSearch.addEventListener('input', (e) => {
      searchQuery = e.target.value.trim();
      renderIncidentFeed();
    });

    // Clear events
    els.clearEventsBtn.addEventListener('click', async () => {
      if (confirm('Clear all verified incident records from audit ledger?')) {
        await fetch('/api/events', { method: 'DELETE' });
        currentEvents = [];
        renderIncidentFeed();
        renderTimelineMarkers();
        fetchStats();
      }
    });

    // Overlay mode toggles
    els.btnOverlayIncidents.addEventListener('click', () => {
      overlayMode = 'incidents';
      els.btnOverlayIncidents.classList.add('active');
      els.btnOverlayAll.classList.remove('active');
      els.btnOverlayOff.classList.remove('active');
    });

    els.btnOverlayAll.addEventListener('click', () => {
      overlayMode = 'all';
      els.btnOverlayAll.classList.add('active');
      els.btnOverlayIncidents.classList.remove('active');
      els.btnOverlayOff.classList.remove('active');
    });

    els.btnOverlayOff.addEventListener('click', () => {
      overlayMode = 'off';
      els.btnOverlayOff.classList.add('active');
      els.btnOverlayIncidents.classList.remove('active');
      els.btnOverlayAll.classList.remove('active');
      renderDetectionOverlay([]);
    });

    // Sources Dialog
    els.btnOpenSources.addEventListener('click', () => els.sourcesDialog.showModal());
    els.sourcesDialogClose.addEventListener('click', () => els.sourcesDialog.close());

    // Ingestion from Sources dialog
    els.startSourceBtn.addEventListener('click', async () => {
      const src = els.sourceInput.value.trim();
      if (!src) return;
      await startIngestion(src);
      els.sourcesDialog.close();
    });

    // Scenario and Dataset buttons
    $$('.scenario-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const src = btn.dataset.src;
        if (src) {
          isDemoActive = true;
          els.demoBadge.style.display = 'inline-block';
          await startIngestion(src);
          if (els.sourcesDialog.open) els.sourcesDialog.close();
        }
      });
    });

    // Query AI Dialog
    els.btnQueryAi.addEventListener('click', () => els.queryDialog.showModal());
    els.queryDialogClose.addEventListener('click', () => els.queryDialog.close());

    els.chatForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const q = els.chatInput.value.trim();
      if (!q) return;
      await runChatQuery(q);
    });

    $$('.preset-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const q = btn.dataset.q;
        if (q) {
          els.chatInput.value = q;
          await runChatQuery(q);
        }
      });
    });

    // Camera list switching
    $$('.camera-item').forEach(item => {
      item.addEventListener('click', () => {
        $$('.camera-item').forEach(i => i.classList.remove('active'));
        item.classList.add('active');
        currentCamera = item.dataset.cam || 'cam1';
        els.hudCamId.textContent = currentCamera.toUpperCase();
        els.streamImg.src = `/stream/${currentCamera}`;
      });
    });

    // Timeline Scrubbing controls
    els.nvrPlayPause.addEventListener('click', async () => {
      try {
        const res = await fetch(`/api/cameras/${currentCamera}/playback`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ paused: els.nvrPlayIcon.textContent === '⏸' })
        });
        if (res.ok) {
          els.nvrPlayIcon.textContent = els.nvrPlayIcon.textContent === '⏸' ? '▶' : '⏸';
        }
      } catch (_) {}
    });

    els.nvrSlider.addEventListener('input', () => { isScrubbing = true; });
    els.nvrSlider.addEventListener('change', async (e) => {
      isScrubbing = false;
      const ratio = Number(e.target.value) / 1000;
      await fetch(`/api/cameras/${currentCamera}/seek`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ratio })
      });
    });

    els.nvrLiveSnap.addEventListener('click', async () => {
      await fetch(`/api/cameras/${currentCamera}/seek`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ratio: 1.0 })
      });
      els.nvrSlider.value = 1000;
    });

    // Keyboard Shortcuts
    window.addEventListener('keydown', (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        els.queryDialog.showModal();
      } else if (e.key === 'Escape') {
        if (els.incidentDrawer.classList.contains('open')) closeIncidentDrawer();
      } else if (e.key === 'm' || e.key === 'M') {
        audioEnabled = !audioEnabled;
      } else if (e.key === ' ') {
        e.preventDefault();
        els.nvrPlayPause.click();
      } else if (e.key === '/') {
        e.preventDefault();
        els.eventSearch.focus();
      }
    });

    // Report
    els.openReportBtn.addEventListener('click', () => openReportModal());
    els.repModalClose.addEventListener('click', () => els.reportModal.close());
  };

  // Start Ingestion Helper
  const startIngestion = async (source) => {
    try {
      await fetch('/api/source', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ camera_id: currentCamera, source })
      });
      els.streamImg.src = `/stream/${currentCamera}?t=${Date.now()}`;
    } catch (e) {
      console.warn('Ingestion error:', e);
    }
  };

  // Chat Query Helper
  const runChatQuery = async (question) => {
    els.queryResponse.style.display = 'block';
    els.queryAnswer.textContent = 'Analyzing question and querying database…';
    els.querySqlWrap.style.display = 'none';
    els.queryEventsList.innerHTML = '';

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question })
      });
      if (!res.ok) throw new Error('Query request failed');
      const data = await res.json();

      els.queryAnswer.textContent = data.answer || 'Query completed.';
      if (data.sql) {
        els.querySqlWrap.style.display = 'block';
        els.querySql.textContent = data.sql;
      }

      const evs = data.events || [];
      els.queryEventCount.textContent = evs.length;
      if (evs.length > 0) {
        els.queryEventsList.innerHTML = evs.slice(0, 10).map(e => `
          <div class="query-event-item" style="padding:6px; background:var(--bg-surface); border-radius:4px; font-size:0.75rem;">
            <b>#${e.id} [${e.category}]</b> ${escapeHtml(e.summary)} <span style="color:var(--text-muted); float:right;">${formatTime(e.timestamp)}</span>
          </div>
        `).join('');
      }
    } catch (err) {
      els.queryAnswer.textContent = `Error: ${err.message}`;
    }
  };

  // Report Modal Generator
  const openReportModal = async () => {
    els.reportModal.showModal();
    els.reportView.innerHTML = `
      <div class="empty-state">
        <div class="spinner"></div>
        <span>Compiling executive security intelligence briefing…</span>
      </div>
    `;

    try {
      const res = await fetch('/api/report/narrative', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ events: currentEvents, detail: 'executive' })
      });
      const data = await res.json();
      const narrative = data.narrative || 'No incidents recorded for reporting.';

      els.reportView.innerHTML = `
        <div style="display:flex; flex-direction:column; gap:12px;">
          <h4 style="font-size:0.9rem; font-weight:600;">Executive Security Incident Briefing</h4>
          <p style="white-space:pre-wrap; line-height:1.5; font-size:0.8rem; color:var(--text-primary); background:var(--bg-surface); padding:12px; border-radius:6px; border:1px solid var(--border-subtle);">
            ${escapeHtml(narrative)}
          </p>
          <div style="display:flex; justify-content:flex-end; gap:8px;">
            <button class="btn btn--secondary" onclick="window.print()">Print Report</button>
            <button class="btn btn--primary" id="btn-copy-report">Copy Text</button>
          </div>
        </div>
      `;

      $('#btn-copy-report', els.reportView).addEventListener('click', () => {
        navigator.clipboard.writeText(narrative);
        alert('Report copied to clipboard');
      });
    } catch (err) {
      els.reportView.innerHTML = `<p style="color:var(--severity-critical);">Failed to generate report: ${err.message}</p>`;
    }
  };

  const escapeHtml = (str) => {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  };

  // ============ INITIALIZATION ============
  const init = async () => {
    setupEventListeners();
    await loadTaxonomy();
    fetchStats();
    fetchEvents();

    // Fast status loop (250ms) for video telemetry & detection overlay
    setInterval(updateCameraStatus, 250);

    // Ledger poll (2000ms)
    pollTimer = setInterval(fetchEvents, 2000);

    // Stats poll (3000ms)
    statsTimer = setInterval(fetchStats, 3000);
  };

  window.addEventListener('DOMContentLoaded', init);
})();