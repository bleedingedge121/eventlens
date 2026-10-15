// EventLens Dashboard Logic

let currentCategory = "";
let currentCamera = "cam1";
let pollInterval = null;

document.addEventListener("DOMContentLoaded", () => {
  initCameraSelector();
  initFilterButtons();
  initSourceControl();
  initModal();

  // Initial fetch and 2-second interval polling per AGENTS.md Section 6
  fetchStats();
  fetchEvents();
  pollInterval = setInterval(() => {
    fetchStats();
    fetchEvents();
  }, 2000);
});

function initCameraSelector() {
  const select = document.getElementById("camera-select");
  const streamImg = document.getElementById("live-stream");
  const hudCam = document.getElementById("hud-cam-id");

  select.addEventListener("change", (e) => {
    currentCamera = e.target.value;
    hudCam.textContent = `CAM: ${currentCamera}`;
    streamImg.src = `/stream/${currentCamera}?t=${Date.now()}`;
    fetchEvents();
  });
}

function initFilterButtons() {
  const buttons = document.querySelectorAll(".filter-btn");
  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      buttons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentCategory = btn.getAttribute("data-category");
      fetchEvents();
    });
  });
}

function initSourceControl() {
  const input = document.getElementById("source-input");
  const btn = document.getElementById("start-source-btn");

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
        setTimeout(() => { btn.textContent = "Start Feed"; btn.disabled = false; }, 2000);
      } else {
        alert("Failed to start camera source.");
        btn.textContent = "Start Feed";
        btn.disabled = false;
      }
    } catch (err) {
      console.error("Error starting camera source:", err);
      alert("Error starting camera stream.");
      btn.textContent = "Start Feed";
      btn.disabled = false;
    }
  });
}

async function fetchStats() {
  try {
    const res = await fetch("/api/stats");
    if (!res.ok) return;
    const stats = await res.json();

    document.getElementById("stat-today").textContent = stats.events_today ?? 0;
    document.getElementById("stat-total").textContent = stats.total_events ?? 0;
    document.getElementById("stat-latency").textContent = stats.avg_latency_ms ? `${stats.avg_latency_ms} ms` : "-- ms";
  } catch (err) {
    console.warn("Stats fetch failed:", err);
  }
}

async function fetchEvents() {
  try {
    let url = `/api/events?limit=30`;
    if (currentCategory) url += `&category=${encodeURIComponent(currentCategory)}`;

    const res = await fetch(url);
    if (!res.ok) return;
    const data = await res.json();
    renderEvents(data.events || []);
  } catch (err) {
    console.warn("Events fetch failed:", err);
  }
}

function renderEvents(events) {
  const container = document.getElementById("events-container");
  const countSpan = document.getElementById("feed-count");
  countSpan.textContent = `${events.length} item${events.length === 1 ? "" : "s"}`;

  if (!events || events.length === 0) {
    container.innerHTML = `
      <div style="padding: 32px; text-align: center; color: var(--text-dim); font-size: 0.9rem;">
        No events recorded for this selection.
      </div>
    `;
    return;
  }

  container.innerHTML = events.map((ev) => {
    const catClass = `badge-${ev.category}`;
    const formattedCat = ev.category.replace("_", " ");
    const tracksStr = ev.track_ids && ev.track_ids.length ? `Tracks: [${ev.track_ids.join(", ")}]` : "";

    return `
      <div class="event-item">
        <img class="event-thumb" src="${ev.keyframe_url}" alt="Keyframe"
             onclick="openModal('${ev.keyframe_url}', 'Event #${ev.id} - ${formattedCat}', '${encodeURIComponent(ev.summary)}')">
        <div class="event-body">
          <div class="event-meta">
            <span class="badge ${catClass}">${formattedCat}</span>
            <span class="event-time">${formatTimestamp(ev.timestamp)}</span>
            <span class="event-cam">${ev.camera_id}</span>
          </div>
          <div class="event-summary">${escapeHtml(ev.summary)}</div>
          <div class="event-footer">
            <span>Conf: ${(ev.confidence * 100).toFixed(0)}%</span>
            <span>Latency: ${ev.latency_ms || 0}ms</span>
            ${tracksStr ? `<span>${tracksStr}</span>` : ""}
          </div>
        </div>
      </div>
    `;
  }).join("");
}

function formatTimestamp(isoStr) {
  if (!isoStr) return "";
  try {
    const date = new Date(isoStr);
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
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

function initModal() {
  const modal = document.getElementById("keyframe-modal");
  const closeBtn = document.getElementById("modal-close-btn");
  closeBtn.addEventListener("click", () => {
    modal.style.display = "none";
  });
  modal.addEventListener("click", (e) => {
    if (e.target === modal) modal.style.display = "none";
  });
}

function openModal(imgUrl, title, summaryEnc) {
  const modal = document.getElementById("keyframe-modal");
  document.getElementById("modal-img").src = imgUrl;
  document.getElementById("modal-title").textContent = title;
  document.getElementById("modal-desc").textContent = decodeURIComponent(summaryEnc);
  modal.style.display = "flex";
}
window.openModal = openModal;
