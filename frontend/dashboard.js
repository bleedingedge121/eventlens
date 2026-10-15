// EventLens — Dashboard Client Logic
// Professional, minimal, zero-framework vanilla JS

(() => {
  // ============ STATE ============
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

  // Camera zone definitions (match backend config/cameras.json)
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
    audioIcon: $('#audio-toggle .icon'),
    audioLabel: $('#audio-toggle .label'),
    systemStatus: $('.system-status'),
    navLinks: $$('.nav-primary a'),

    statToday: $('#stat-today'),
    statLatency: $('#stat-latency'),
    statTotal: $('#stat-total'),
    statProcessing: $('#stat-processing'),

    cameraSelect: $('#camera-select'),
    zonesToggle: $('#zones-toggle'),
    zonesState: $('#zones-state'),
    streamImg: $('#stream'),
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
    try { return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }); }
    catch { return iso; }
  };

  const formatTimestamp = (iso) => {
    if (!iso) return '\u2014';
    try { return new Date(iso).toLocaleString([], { dateStyle: 'short', timeStyle: 'medium' }); }
    catch { return iso; }
  };

  const escapeHtml = (str) => {
    if (!str) return '';
    return String(str).replace(/[&<>'"]/g, c => {
      const map = { '&': '&', '<': '<', '>': '>', "'": ''', '"': '"' };
      return map[c];
    });
  };

  const playChime = () => {
    if (!audioEnabled) return;
    try {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return;
      const ctx = new AC();
      const play = (freq, start, dur) => {
        const o = ctx.createOscillator(), g = ctx.createGain();
        o.type = 'sine'; o.frequency.value = freq;
        g.gain.setValueAtTime(0.06, ctx.currentTime + start);
        g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + start + dur);
        o.connect(g); g.connect(ctx.destination);
        o.start(ctx.currentTime + start); o.stop(ctx.currentTime + start + dur);
      };
      play(880, 0, 0.12); play(1320, 0.1, 0.2);
    } catch {}
  };

  const copyToClipboard = (text, btn, originalLabel) => {
    navigator.clipboard.writeText(text).then(() => {
      btn.textContent = 'Copied';
      setTimeout(() => { btn.textContent = originalLabel; }, 1500);
    });
  };

  // ============ ZONE OVERLAY RENDERING ============
  function drawZones() {
    const canvas = els.zoneCanvas;
    const container = els.viewport;
    if (!canvas || !container || !zonesVisible) {
      if (canvas) { const ctx = canvas.getContext('2d'); ctx.clearRect(0, 0, canvas.width, canvas.height); }
      return;
    }

    const rect = container.getBoundingClientRect();
    canvas.width = rect.width;
    canvas.height = rect.height;

    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const config = CAMERA_ZONES[currentCamera];
    if (!config) return;

    const scaleX = canvas.width / 640;
    const scaleY = canvas.height / 480;

    // Door zone — cyan
    if (config.doorZone) {
      ctx.beginPath();
      config.doorZone.forEach((pt, i) => {
        const x = pt[0] * scaleX, y = pt[1] * scaleY;
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      });
      ctx.closePath();
      ctx.fillStyle = 'rgba(0, 212, 255, 0.1)';
      ctx.fill();
      ctx.strokeStyle = 'rgba(0, 212, 255, 0.8)';
      ctx.lineWidth = 2; ctx.setLineDash([6, 4]); ctx.stroke(); ctx.setLineDash([]);
      const [fx, fy] = config.doorZone[0];
      ctx.fillStyle = 'rgba(0, 212, 255, 0.95)';
      ctx.font = '10px var(--font-mono)';
      ctx.fillText('DOOR ZONE', fx * scaleX + 6, fy * scaleY + 14);
    }

    // Restricted zones — rose
    if (config.restrictedZones) {
      config.restrictedZones.forEach(z => {
        ctx.beginPath();
        z.poly.forEach((pt, i) => {
          const x = pt[0] * scaleX, y = pt[1] * scaleY;
          i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        });
        ctx.closePath();
        ctx.fillStyle = 'rgba(255, 71, 126, 0.1)';
        ctx.fill();
        ctx.strokeStyle = 'rgba(255, 71, 126, 0.85)';
        ctx.lineWidth = 2; ctx.setLineDash([6, 4]); ctx.stroke(); ctx.setLineDash([]);
        const [fx, fy] = z.poly[0];
        ctx.fillStyle = 'rgba(255, 71, 126, 0.95)';
        ctx.font = '10px var(--font-mono)';
        ctx.fillText(z.name.toUpperCase(), fx * scaleX + 6, fy * scaleY + 14);
      });
    }
  }

  // ============ HUD CLOCK ============
  function updateClock() {
    const now = new Date();
    els.hudTime.textContent = now.toTimeString().split(' ')[0];
    els.hudCamera.textContent = `CAM: ${currentCamera.slice(-1)}`;
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

  // ============ EVENT RENDERING ============
  function renderEvents() {
    let filtered = currentEvents;

    if (currentCategory) {
      filtered = filtered.filter(e => e.category === currentCategory);
    }
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      filtered = filtered.filter(e =>
        e.summary.toLowerCase().includes(q) ||
        e.camera_id.toLowerCase().includes(q) ||
        e.category.toLowerCase().includes(q) ||
        String(e.id).includes(q)
      );
    }

    els.feedCount.textContent = filtered.length;

    if (!filtered.length) {
      els.eventFeed.innerHTML = `
        <div class="empty-state">
          <div class="spinner"></div>
          <span>${currentEvents.length ? 'No incidents match current filters.' : 'No incidents recorded yet.'}</span>
        </div>`;
      return;
    }

    els.eventFeed.innerHTML = filtered.map(ev => {
      const meta = CATEGORY_META[ev.category] || { label: ev.category, severity: 'notice', badgeClass: '' };
      const tracksHtml = ev.track_ids?.length
        ? ev.track_ids.map(id => `<span class="track-chip">#${id}</span>`).join(' ')
        : '';

      return `
        <article class="event-item event-item--${meta.severity}" data-id="${ev.id}" tabindex="0" role="listitem">
          <div class="event-thumb-wrapper">
            <img class="event-thumb" src="${ev.keyframe_url}" alt="Keyframe for incident ${ev.id}"
              onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'112\\' height=\\'68\\'><rect width=\\'100%\\' height=\\'100%\\' fill=\\'%23060b14\\'/></svg>'">
          </div>
          <div class="event-body">
            <div class="event-meta">
              <span class="badge ${meta.badgeClass}">${meta.label}</span>
              <span class="event-time">${formatTime(ev.timestamp)}</span>
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
      item.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handler(); } });
    });
  }

  // ============ MODAL ============
  function openModal(eventId) {
    const ev = currentEvents.find(e => e.id === eventId);
    if (!ev) return;

    const meta = CATEGORY_META[ev.category] || { label: ev.category, badgeClass: '' };

    els.modalCategoryBadge.className = `badge ${meta.badgeClass}`;
    els.modalCategoryBadge.textContent = meta.label;
    els.modalTitle.textContent = `Incident #${ev.id}`;
    els.modalImage.src = ev.keyframe_url;
    els.modalImage.alt = `Keyframe for ${meta.label} incident #${ev.id}`;
    els.modalSummary.textContent = ev.summary;
    els.modalCamera.textContent = ev.camera_id;
    els.modalTimestamp.textContent = formatTimestamp(ev.timestamp);
    els.modalConfidence.textContent = `${(ev.confidence * 100).toFixed(1)}%`;
    els.modalLatency.textContent = `${ev.latency_ms || 0} ms`;

    els.modalTracks.innerHTML = ev.track_ids?.length
      ? ev.track_ids.map(id => `<span class="track-chip">Track #${id}</span>`).join(' ')
      : '<span style="color:var(--text-dim)">None</span>';

    els.queryLink.href = `chat.html?q=${encodeURIComponent(`Tell me about incident #${ev.id} on ${ev.camera_id}`)}`;

    els.copyEventBtn.onclick = () => copyToClipboard(JSON.stringify(ev, null, 2), els.copyEventBtn, 'Copy JSON');

    els.modal.showModal();
    document.body.style.overflow = 'hidden';
  }

  function closeModal() {
    els.modal.close();
    document.body.style.overflow = '';
  }

  // ============ API CALLS ============
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
        if (lastEventId !== 0 && maxId > lastEventId) playChime();
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
    els.startSourceBtn.textContent = 'Connecting\u2026';

    try {
      const res = await fetch('/api/source', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ camera_id: currentCamera, source })
      });
      const data = await res.json();

      if (data.success) {
        els.streamImg.src = `/stream/${currentCamera}?t=${Date.now()}`;
        els.startSourceBtn.textContent = 'Active';
        setTimeout(() => { els.startSourceBtn.textContent = 'Start Ingestion'; els.startSourceBtn.disabled = false; }, 2000);
      } else {
        throw new Error(data.detail || 'Failed to start source');
      }
    } catch (err) {
      console.error('[EventLens] Source start failed:', err);
      alert(`Failed to start camera: ${err.message}`);
      els.startSourceBtn.textContent = 'Start Ingestion';
      els.startSourceBtn.disabled = false;
    }
  }

  // ============ EVENT HANDLERS ============
  function initHandlers() {
    els.cameraSelect.addEventListener('change', e => {
      currentCamera = e.target.value;
      els.streamImg.src = `/stream/${currentCamera}?t=${Date.now()}`;
      drawZones();
      fetchEvents();
    });

    els.zonesToggle.addEventListener('click', () => {
      zonesVisible = !zonesVisible;
      els.zonesToggle.setAttribute('aria-pressed', zonesVisible);
      els.zonesState.textContent = zonesVisible ? 'On' : 'Off';
      drawZones();
    });

    els.audioToggle.addEventListener('click', () => {
      audioEnabled = !audioEnabled;
      els.audioToggle.setAttribute('aria-label', `Toggle alert audio (${audioEnabled ? 'ON' : 'OFF'})`);
      els.audioToggle.title = `Alert audio: ${audioEnabled ? 'ON' : 'OFF'}`;
      els.audioIcon.textContent = audioEnabled ? '🔔' : '🔕';
      els.audioLabel.textContent = audioEnabled ? 'Audio' : 'Muted';
      els.audioToggle.style.borderColor = audioEnabled ? 'var(--border-default)' : 'var(--accent-rose)';
    });

    els.scenarioBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        els.sourceInput.value = btn.dataset.src;
        startSource(btn.dataset.src);
      });
    });

    els.startSourceBtn.addEventListener('click', () => {
      const src = els.sourceInput.value.trim() || '0';
      startSource(src);
    });
    els.sourceInput.addEventListener('keydown', e => { if (e.key === 'Enter') startSource(els.sourceInput.value.trim() || '0'); });

    els.eventSearch.addEventListener('input', e => {
      searchQuery = e.target.value.trim().toLowerCase();
      renderEvents();
    });

    els.filterBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        els.filterBtns.forEach(b => { b.classList.remove('active'); b.setAttribute('aria-pressed', 'false'); });
        btn.classList.add('active');
        btn.setAttribute('aria-pressed', 'true');
        currentCategory = btn.dataset.category;
        renderEvents();
      });
    });

    els.snapshotBtn.addEventListener('click', () => {
      const link = document.createElement('a');
      link.download = `eventlens_${currentCamera}_${Date.now()}.jpg`;
      link.href = els.streamImg.src;
      link.click();
    });

    els.fullscreenBtn.addEventListener('click', () => {
      if (!document.fullscreenElement) {
        els.viewport.requestFullscreen().catch(console.warn);
      } else {
        document.exitFullscreen();
      }
    });
    document.addEventListener('fullscreenchange', () => setTimeout(drawZones, 200));

    els.modalClose.addEventListener('click', closeModal);
    els.modal.addEventListener('click', e => { if (e.target === els.modal) closeModal(); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && els.modal.open) closeModal(); });

    window.addEventListener('resize', drawZones);
  }

  // ============ POLLING LOOP ============
  function startPolling() {
    fetchStats();
    fetchEvents();
    pollTimer = setInterval(() => { fetchStats(); fetchEvents(); }, 2000);
    clockTimer = setInterval(updateClock, 1000);
  }

  function stopPolling() {
    clearInterval(pollTimer);
    clearInterval(clockTimer);
  }

  // ============ INIT ============
  document.addEventListener('DOMContentLoaded', () => {
    initHandlers();
    updateClock();
    drawZones();
    startPolling();
    console.log('[EventLens] Dashboard initialized');
  });

  window.addEventListener('beforeunload', stopPolling);
})();