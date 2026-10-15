// EventLens Security Operations Console Logic (UI/UX Pro Max)

let currentCategory = "";
let currentCamera = "cam1";
let pollInterval = null;
let lastSeenEventId = 0;
let audioAlertsEnabled = true;
let zonesVisible = true;
let currentEvents = [];
let searchQuery = "";

// Camera Zone Definitions (loaded dynamically or preset)
const CAMERA_ZONES = {
  cam1: {
    doorZone: [[180, 240], [420, 240], [420, 480], [180, 480]],
    restrictedZones: [
      { name: "Server Corridor", poly: [[500, 100], [620, 100], [620, 350], [500, 350]] }
    ]
  },
  cam2: {
    doorZone: [[100, 200], [300, 200], [300, 450], [100, 450]],
    restrictedZones: [
      { name: "Emergency Stairwell", poly: [[450, 50], [580, 50], [580, 300], [450, 300]] }
    ]
  }
};

document.addEventListener("DOMContentLoaded", () => {
  initClock();
  initCameraSelector();
  initFilterButtons();
  initSearch();
  initSourceControl();
  initAudioToggle();
  initZoneOverlay();
  initViewportActions();
  initModal();

  // Initial fetch and 2-second polling per AGENTS.md Section 6
  fetchStats();
  fetchEvents();
  pollInterval = setInterval(() => {
    fetchStats();
    fetchEvents();
  }, 2000);
});

// Real-time HUD Clock
function initClock() {
  const clockEl = document.getElementById("hud-clock");
  setInterval(() => {
    const now = new Date();
    if (clockEl) {
      clockEl.textContent = now.toTimeString().split(" ")[0];
    }
  }, 1000);
}

// Camera Switcher
function initCameraSelector() {
  const select = document.getElementById("camera-select");
  const streamImg = document.getElementById("live-stream");
  const hudCam = document.getElementById("hud-cam-id");

  select.addEventListener("change", (e) => {
    currentCamera = e.target.value;
    hudCam.textContent = `CAM: ${currentCamera}`;
    streamImg.src = `/stream/${currentCamera}?t=${Date.now()}`;
    drawZoneOverlay();
    fetchEvents();
  });
}

// Category Filter Pills
function initFilterButtons() {
  const buttons = document.querySelectorAll(".filter-btn");
  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      buttons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentCategory = btn.getAttribute("data-category");
      renderFilteredEvents();
    });
  });
}

// Search Filter
function initSearch() {
  const searchInput = document.getElementById("event-search");
  searchInput.addEventListener("input", (e) => {
    searchQuery = e.target.value.toLowerCase().trim();
    renderFilteredEvents();
  });
}

// Ingestion Source Controller
function initSourceControl() {
  const input = document.getElementById("source-input");
  const btn = document.getElementById("start-source-btn");
  const scenarioBtns = document.querySelectorAll(".scenario-btn");

  scenarioBtns.forEach((sBtn) => {
    sBtn.addEventListener("click", () => {
      input.value = sBtn.getAttribute("data-src");
      btn.click();
    });
  });

  btn.addEventListener("click", async () => {
    const src = input.value.trim() || "0";
    btn.disabled = true;
    btn.textContent = "Connecting...";

    try {
      const resp = await fetch("/api/source", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ camera_id: currentCamera, source: src }),
      });
      const data = await resp.json();
      if (data.success) {
        document.getElementById("live-stream").src = `/stream/${currentCamera}?t=${Date.now()}`;
        btn.textContent = "Active";
        setTimeout(() => { btn.textContent = "Start Ingestion"; btn.disabled = false; }, 2000);
      } else {
        alert("Failed to start camera source.");
        btn.textContent = "Start Ingestion";
        btn.disabled = false;
      }
    } catch (err) {
      console.error("Error starting camera source:", err);
      alert("Error starting camera stream.");
      btn.textContent = "Start Ingestion";
      btn.disabled = false;
    }
  });
}

// Audio Alerts (Web Audio API Synthesizer)
function initAudioToggle() {
  const btn = document.getElementById("audio-toggle-btn");
  const statusEl = document.getElementById("audio-status");
  const iconEl = document.getElementById("audio-icon");

  btn.addEventListener("click", () => {
    audioAlertsEnabled = !audioAlertsEnabled;
    statusEl.textContent = audioAlertsEnabled ? "ON" : "OFF";
    iconEl.textContent = audioAlertsEnabled ? "🔔" : "🔕";
    btn.style.borderColor = audioAlertsEnabled ? "var(--border-dim)" : "var(--accent-rose)";
  });
}

function playSecurityChime() {
  if (!audioAlertsEnabled) return;
  try {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) return;
    const ctx = new AudioContext();

    // Dual-tone futuristic notification chime
    const playTone = (freq, start, duration) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(freq, ctx.currentTime + start);
      gain.gain.setValueAtTime(0.08, ctx.currentTime + start);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + start + duration);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(ctx.currentTime + start);
      osc.stop(ctx.currentTime + start + duration);
    };

    playTone(880, 0, 0.15);    // A5
    playTone(1320, 0.12, 0.25); // E6
  } catch (e) {
    // Audio context may be restricted before user interaction
  }
}

// Canvas Trigger Zone Overlay
function initZoneOverlay() {
  const toggleBtn = document.getElementById("toggle-zones-btn");
  const statusEl = document.getElementById("zones-status");

  toggleBtn.addEventListener("click", () => {
    zonesVisible = !zonesVisible;
    statusEl.textContent = zonesVisible ? "VISIBLE" : "HIDDEN";
    drawZoneOverlay();
  });

  window.addEventListener("resize", drawZoneOverlay);
  setTimeout(drawZoneOverlay, 500);
}

function drawZoneOverlay() {
  const canvas = document.getElementById("zone-overlay-canvas");
  const container = document.getElementById("viewport-container");
  if (!canvas || !container) return;

  const rect = container.getBoundingClientRect();
  canvas.width = rect.width;
  canvas.height = rect.height;

  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  if (!zonesVisible) return;

  const camConfig = CAMERA_ZONES[currentCamera];
  if (!camConfig) return;

  // Scale from native 640x480 coordinate space
  const scaleX = canvas.width / 640;
  const scaleY = canvas.height / 480;

  // Draw Door Zone
  if (camConfig.doorZone) {
    ctx.beginPath();
    camConfig.doorZone.forEach((pt, i) => {
      const x = pt[0] * scaleX;
      const y = pt[1] * scaleY;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.closePath();
    ctx.fillStyle = "rgba(56, 189, 248, 0.12)";
    ctx.fill();
    ctx.strokeStyle = "rgba(56, 189, 248, 0.75)";
    ctx.lineWidth = 2;
    ctx.setLineDash([4, 4]);
    ctx.stroke();
    ctx.setLineDash([]);

    // Label
    const first = camConfig.doorZone[0];
    ctx.fillStyle = "rgba(56, 189, 248, 0.9)";
    ctx.font = "11px monospace";
    ctx.fillText("DOOR ZONE", first[0] * scaleX + 6, first[1] * scaleY + 14);
  }

  // Draw Restricted Zones
  if (camConfig.restrictedZones) {
    camConfig.restrictedZones.forEach((rz) => {
      ctx.beginPath();
      rz.poly.forEach((pt, i) => {
        const x = pt[0] * scaleX;
        const y = pt[1] * scaleY;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.closePath();
      ctx.fillStyle = "rgba(244, 63, 94, 0.14)";
      ctx.fill();
      ctx.strokeStyle = "rgba(244, 63, 94, 0.8)";
      ctx.lineWidth = 2;
      ctx.setLineDash([4, 4]);
      ctx.stroke();
      ctx.setLineDash([]);

      const first = rz.poly[0];
      ctx.fillStyle = "rgba(244, 63, 94, 0.95)";
      ctx.font = "11px monospace";
      ctx.fillText(rz.name.toUpperCase(), first[0] * scaleX + 6, first[1] * scaleY + 14);
    });
  }
}

// Viewport Actions: Snapshot & Fullscreen
function initViewportActions() {
  const snapshotBtn = document.getElementById("snapshot-btn");
  const fullscreenBtn = document.getElementById("fullscreen-btn");
  const viewport = document.getElementById("viewport-container");

  snapshotBtn.addEventListener("click", () => {
    const streamImg = document.getElementById("live-stream");
    const link = document.createElement("a");
    link.download = `eventlens_${currentCamera}_${Date.now()}.jpg`;
    link.href = streamImg.src;
    link.click();
  });

  fullscreenBtn.addEventListener("click", () => {
    if (!document.fullscreenElement) {
      viewport.requestFullscreen().catch((err) => console.warn(err));
    } else {
      document.exitFullscreen();
    }
  });

  document.addEventListener("fullscreenchange", () => {
    setTimeout(drawZoneOverlay, 200);
  });
}

// Fetch Stats & Update Telemetry Cards
async function fetchStats() {
  try {
    const res = await fetch("/api/stats");
    if (!res.ok) return;
    const stats = await res.json();

    document.getElementById("stat-today").textContent = stats.events_today ?? 0;
    document.getElementById("stat-total").textContent = stats.total_events ?? 0;
    document.getElementById("stat-latency").textContent = stats.avg_latency_ms ? `${stats.avg_latency_ms} ms` : "-- ms";

    // Update filter badge counts
    if (stats.categories) {
      let total = 0;
      for (const [cat, cnt] of Object.entries(stats.categories)) {
        const el = document.getElementById(`count-${cat}`);
        if (el) el.textContent = cnt;
        total += cnt;
      }
      const allEl = document.getElementById("count-all");
      if (allEl) allEl.textContent = total;
    }
  } catch (err) {
    console.warn("Stats fetch failed:", err);
  }
}

// Fetch Events & Trigger Alerts
async function fetchEvents() {
  try {
    const res = await fetch("/api/events?limit=50");
    if (!res.ok) return;
    const data = await res.json();
    const events = data.events || [];

    // Detect new incoming events and chime
    if (events.length > 0) {
      const highestId = Math.max(...events.map(e => e.id));
      if (lastSeenEventId !== 0 && highestId > lastSeenEventId) {
        playSecurityChime();
      }
      lastSeenEventId = highestId;
    }

    currentEvents = events;
    renderFilteredEvents();
  } catch (err) {
    console.warn("Events fetch failed:", err);
  }
}

// Render Events matching current category & search query
function renderFilteredEvents() {
  const container = document.getElementById("events-container");
  const countSpan = document.getElementById("feed-count");

  let filtered = currentEvents;

  if (currentCategory) {
    filtered = filtered.filter(e => e.category === currentCategory);
  }

  if (searchQuery) {
    filtered = filtered.filter(e =>
      e.summary.toLowerCase().includes(searchQuery) ||
      e.camera_id.toLowerCase().includes(searchQuery) ||
      e.category.toLowerCase().includes(searchQuery) ||
      String(e.id).includes(searchQuery)
    );
  }

  countSpan.textContent = `${filtered.length}`;

  if (!filtered || filtered.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <span>No incidents matching active filters.</span>
      </div>
    `;
    return;
  }

  container.innerHTML = filtered.map((ev) => {
    const catClass = `badge-${ev.category}`;
    const formattedCat = ev.category.replace(/_/g, " ");
    const tracksHtml = ev.track_ids && ev.track_ids.length 
      ? ev.track_ids.map(id => `<span class="track-chip">#${id}</span>`).join(" ") 
      : "";

    let severityClass = "severity-notice";
    if (ev.category === "person_down" || ev.category === "fighting") {
      severityClass = "severity-critical";
    } else if (ev.category === "tailgating" || ev.category === "crowd_incident") {
      severityClass = "severity-warning";
    }

    return `
      <div class="event-item ${severityClass}" onclick="openModalById(${ev.id})">
        <div class="event-thumb-wrap">
          <img class="event-thumb" src="${ev.keyframe_url}" alt="Keyframe"
               onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'96\\' height=\\'58\\'><rect width=\\'100%\\' height=\\'100%\\' fill=\\'%23121a2d\\'/></svg>';">
        </div>
        <div class="event-body">
          <div class="event-meta">
            <span class="badge ${catClass}">${formattedCat}</span>
            <span class="event-time">${formatTime(ev.timestamp)}</span>
            <span class="event-cam">${ev.camera_id}</span>
          </div>
          <div class="event-summary">${escapeHtml(ev.summary)}</div>
          <div class="event-footer">
            <span>Confidence: ${(ev.confidence * 100).toFixed(0)}%</span>
            <span>Latency: ${ev.latency_ms || 0}ms</span>
            ${tracksHtml ? `<div style="display:inline-flex; gap:4px; align-items:center;">Tracks: ${tracksHtml}</div>` : ""}
          </div>
        </div>
      </div>
    `;
  }).join("");
}

function formatTime(isoStr) {
  if (!isoStr) return "";
  try {
    const d = new Date(isoStr);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return isoStr;
  }
}

function escapeHtml(str) {
  if (!str) return "";
  return str.replace(/[&<>'"]/g, 
    tag => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[tag] || tag)
  );
}

// Modal Inspector
let selectedEvent = null;

function initModal() {
  const modal = document.getElementById("keyframe-modal");
  const closeBtn = document.getElementById("modal-close-btn");
  const copyBtn = document.getElementById("copy-json-btn");

  closeBtn.addEventListener("click", () => {
    modal.style.display = "none";
  });
  modal.addEventListener("click", (e) => {
    if (e.target === modal) modal.style.display = "none";
  });

  copyBtn.addEventListener("click", () => {
    if (selectedEvent) {
      navigator.clipboard.writeText(JSON.stringify(selectedEvent, null, 2));
      copyBtn.textContent = "✓ Copied!";
      setTimeout(() => { copyBtn.textContent = "📋 Copy Event JSON"; }, 1500);
    }
  });
}

function openModalById(eventId) {
  const ev = currentEvents.find(e => e.id === eventId);
  if (!ev) return;
  selectedEvent = ev;

  const modal = document.getElementById("keyframe-modal");
  document.getElementById("modal-img").src = ev.keyframe_url;
  document.getElementById("modal-title").textContent = `Incident #${ev.id}`;
  document.getElementById("modal-summary").textContent = ev.summary;
  document.getElementById("modal-cam").textContent = ev.camera_id;
  document.getElementById("modal-time").textContent = ev.timestamp;
  document.getElementById("modal-conf").textContent = `${(ev.confidence * 100).toFixed(1)}%`;
  document.getElementById("modal-lat").textContent = `${ev.latency_ms || 0} ms`;

  const catBadge = document.getElementById("modal-category-badge");
  catBadge.className = `badge badge-${ev.category}`;
  catBadge.textContent = ev.category.replace(/_/g, " ");

  const tracksContainer = document.getElementById("modal-tracks");
  if (ev.track_ids && ev.track_ids.length) {
    tracksContainer.innerHTML = ev.track_ids.map(id => `<span class="track-chip">Track ID #${id}</span>`).join(" ");
  } else {
    tracksContainer.innerHTML = "<span style='color:var(--text-dim)'>None</span>";
  }

  // Pre-fill query link for Conversational Query interface
  const queryLink = document.getElementById("query-event-link");
  queryLink.href = `chat.html?q=${encodeURIComponent(`Tell me about incident #${ev.id} on ${ev.camera_id}`)}`;

  modal.style.display = "flex";
}
window.openModalById = openModalById;
