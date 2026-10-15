// EventLens — Security Operations Dashboard Client
// High-reliability, zero-framework vanilla ES6+ module

(() => {
  // ============ OPERATIONAL STATE ============
  let currentCamera = 'cam1';
  let currentCategory = '';
  let searchQuery = '';
  let zonesVisible = true;
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
    tailgating: { label: 'Tailgating', severity: 'warning', badgeClass: 'badge--tailgating' },
    person_down: { label: 'Person Down', severity: 'critical', badgeClass: 'badge--person_down' },
    fighting: { label: 'Fighting', severity: 'critical', badgeClass: 'badge--fighting' },
    crowd_incident: { label: 'Crowd', severity: 'warning', badgeClass: 'badge--crowd_incident' },
    suspicious_activity: { label: 'Suspicious', severity: 'notice', badgeClass: 'badge--suspicious_activity' }
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
    eventFeed: $('#event-feed'),

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

  // ============ HUD CLOCK & FPS ============
  function updateClock() {
    const now = new Date();
    els.hudTime.textContent = now.toTimeString().split(' ')[0];
    els.hudCamera.textContent = `CAM: ${currentCamera.toUpperCase()}`;
  }

  function tickFps() {
    fpsCounter++;
    const now = performance.now();
    if (now - lastFpsTime >= 1000) {
      els.hudFps.textContent = `${fpsCounter} FPS`;
      fpsCounter = 0;
      lastFpsTime = now;
    }
  }

  // ============ EVENT FEED RENDERING ============
  function renderEvents() {
    let filtered = currentEvents;

    if (currentCategory) {
      filtered = filtered.filter(e => e.category === currentCategory);
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
      return;
    }

    els.eventFeed.innerHTML = filtered.map(ev => {
      const meta = CATEGORY_META[ev.category] || { label: ev.category, severity: 'notice', badgeClass: '' };
      const tracksHtml = ev.track_ids && ev.track_ids.length
        ? ev.track_ids.map(id => `<span class="track-chip">#${id}</span>`).join(' ')
        : '';

      const keyframeSrc = ev.keyframe_url || `/frames/${ev.id}.jpg`;

      return `
        <article class="event-item event-item--${ev.category}" data-id="${ev.id}" tabindex="0" role="listitem" aria-label="Incident ${ev.id}: ${meta.label}">
          <div class="event-thumb-wrapper">
            <img class="event-thumb" src="${keyframeSrc}" alt="Keyframe for incident ${ev.id}" loading="lazy"
              onerror="this.onerror=null;this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'104\\' height=\\'64\\'><rect width=\\'100%\\' height=\\'100%\\' fill=\\'%23080c14\\'/><text x=\\'50%\\' y=\\'50%\\' fill=\\'%23475569\\' font-size=\\'9\\' font-family=\\'monospace\\' text-anchor=\\'middle\\' dominant-baseline=\\'middle\\'>NO FRAME</text></svg>'">
          </div>
          <div class="event-body">
            <div class="event-meta">
              <span class="badge ${meta.badgeClass}">${meta.label}</span>
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
  }

  // ============ MODAL INSPECTION ============
  function openModal(eventId) {
    const ev = currentEvents.find(e => e.id === eventId);
    if (!ev) return;

    const meta = CATEGORY_META[ev.category] || { label: ev.category, badgeClass: '' };
    const keyframeSrc = ev.keyframe_url || `/frames/${ev.id}.jpg`;

    els.modalCategoryBadge.className = `badge ${meta.badgeClass}`;
    els.modalCategoryBadge.textContent = meta.label;
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
        const maxId = Math.max(...events.map(e => e.id));
        if (lastEventId !== 0 && maxId > lastEventId) {
          playAlertChime();
        }
        lastEventId = maxId;
      }

      currentEvents = events;
      renderEvents();
      tickFps();
    } catch (err) {
      console.warn('[EventLens] Events fetch failed:', err);
    }
  }

  async function startSource(source) {
    els.startSourceBtn.disabled = true;
    els.startSourceBtn.innerHTML = `
      <div class="spinner" style="width:12px;height:12px;border-width:2px;"></div>
      Connecting…`;

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
    });

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

    // Search query
    els.eventSearch.addEventListener('input', e => {
      searchQuery = e.target.value.trim().toLowerCase();
      renderEvents();
    });

    // Snapshot download
    els.snapshotBtn.addEventListener('click', () => {
      const link = document.createElement('a');
      link.download = `eventlens_${currentCamera}_${Date.now()}.jpg`;
      link.href = els.streamImg.src;
      link.click();
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
        }
        return;
      }

      if (e.key === 'Escape' && els.modal.open) {
        closeModal();
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
    pollTimer = setInterval(() => {
      fetchStats();
      fetchEvents();
    }, 2000);
    clockTimer = setInterval(updateClock, 1000);
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