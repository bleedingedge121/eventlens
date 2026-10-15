import React, { useState, useEffect, useRef, useCallback } from "react";

const CATEGORIES = [
  { key: "", label: "All" },
  { key: "tailgating", label: "Tailgating" },
  { key: "person_down", label: "Person Down" },
  { key: "fighting", label: "Fighting" },
  { key: "crowd_incident", label: "Crowd" },
  { key: "suspicious_activity", label: "Suspicious" },
];

const SEVERITY_MAP = {
  person_down: "critical",
  fighting: "critical",
  tailgating: "warning",
  crowd_incident: "warning",
  suspicious_activity: "notice",
};

const BADGE_CLASS = {
  tailgating: "badge-tailgating",
  person_down: "badge-person_down",
  crowd_incident: "badge-crowd_incident",
  suspicious_activity: "badge-suspicious_activity",
  fighting: "badge-fighting",
};

const CAMERAS = [
  { id: "cam1", name: "Camera 1 — Main Entrance Lobby" },
  { id: "cam2", name: "Camera 2 — Office Floor Corridor" },
];

const ZONES = {
  cam1: {
    doorZone: [[180, 240], [420, 240], [420, 480], [180, 480]],
    restrictedZones: [
      { name: "Server Corridor", poly: [[500, 100], [620, 100], [620, 350], [500, 350]] },
    ],
  },
  cam2: {
    doorZone: [[100, 200], [300, 200], [300, 450], [100, 450]],
    restrictedZones: [
      { name: "Emergency Stairwell", poly: [[450, 50], [580, 50], [580, 300], [450, 300]] },
    ],
  },
};

function Dashboard({ apiBase }) {
  const [stats, setStats] = useState({ events_today: 0, total_events: 0, avg_latency_ms: "--", categories: {} });
  const [events, setEvents] = useState([]);
  const [currentCamera, setCurrentCamera] = useState("cam1");
  const [currentCategory, setCurrentCategory] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [sourceInput, setSourceInput] = useState("");
  const [ingesting, setIngesting] = useState(false);
  const [zonesVisible, setZonesVisible] = useState(true);
  const [audioEnabled, setAudioEnabled] = useState(true);
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [lastEventId, setLastEventId] = useState(0);

  const canvasRef = useRef(null);
  const viewportRef = useRef(null);
  const streamImgRef = useRef(null);
  const pollTimerRef = useRef(null);
  const audioCtxRef = useRef(null);

  // Audio chime
  const playChime = useCallback(() => {
    if (!audioEnabled) return;
    try {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return;
      const ctx = new AC();
      const play = (freq, start, dur) => {
        const o = ctx.createOscillator(); const g = ctx.createGain();
        o.type = "sine"; o.frequency.setValueAtTime(freq, ctx.currentTime + start);
        g.gain.setValueAtTime(0.06, ctx.currentTime + start);
        g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + start + dur);
        o.connect(g); g.connect(ctx.destination);
        o.start(ctx.currentTime + start); o.stop(ctx.currentTime + start + dur);
      };
      play(880, 0, 0.15); play(1320, 0.12, 0.25);
    } catch {}
  }, [audioEnabled]);

  // Draw zone overlay
  const drawZones = useCallback(() => {
    const canvas = canvasRef.current;
    const container = viewportRef.current;
    if (!canvas || !container || !zonesVisible) return;
    const rect = container.getBoundingClientRect();
    canvas.width = rect.width;
    canvas.height = rect.height;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const cam = ZONES[currentCamera];
    if (!cam) return;
    const sx = canvas.width / 640;
    const sy = canvas.height / 480;

    // Door zone
    if (cam.doorZone) {
      ctx.beginPath();
      cam.doorZone.forEach((pt, i) => {
        const x = pt[0] * sx, y = pt[1] * sy;
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      });
      ctx.closePath();
      ctx.fillStyle = "rgba(56, 189, 248, 0.1)";
      ctx.fill();
      ctx.strokeStyle = "rgba(56, 189, 248, 0.7)";
      ctx.lineWidth = 2; ctx.setLineDash([4, 4]); ctx.stroke(); ctx.setLineDash([]);
      const f = cam.doorZone[0];
      ctx.fillStyle = "rgba(56, 189, 248, 0.9)";
      ctx.font = "11px IBM Plex Mono, monospace";
      ctx.fillText("DOOR ZONE", f[0] * sx + 6, f[1] * sy + 14);
    }

    // Restricted zones
    cam.restrictedZones?.forEach((rz) => {
      ctx.beginPath();
      rz.poly.forEach((pt, i) => {
        const x = pt[0] * sx, y = pt[1] * sy;
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      });
      ctx.closePath();
      ctx.fillStyle = "rgba(244, 63, 94, 0.12)";
      ctx.fill();
      ctx.strokeStyle = "rgba(244, 63, 94, 0.75)";
      ctx.lineWidth = 2; ctx.setLineDash([4, 4]); ctx.stroke(); ctx.setLineDash([]);
      const f = rz.poly[0];
      ctx.fillStyle = "rgba(244, 63, 94, 0.9)";
      ctx.font = "11px IBM Plex Mono, monospace";
      ctx.fillText(rz.name.toUpperCase(), f[0] * sx + 6, f[1] * sy + 14);
    });
  }, [currentCamera, zonesVisible]);

  useEffect(() => {
    window.addEventListener("resize", drawZones);
    drawZones();
    return () => window.removeEventListener("resize", drawZones);
  }, [drawZones]);

  // Fetch stats
  const fetchStats = useCallback(async () => {
    try {
      const r = await fetch(`${apiBase}/api/stats`);
      if (r.ok) setStats(await r.json());
    } catch {}
  }, [apiBase]);

  // Fetch events
  const fetchEvents = useCallback(async () => {
    try {
      const r = await fetch(`${apiBase}/api/events?limit=50`);
      if (!r.ok) return;
      const data = await r.json();
      const evs = data.events || [];
      // New event chime
      if (evs.length > 0) {
        const maxId = Math.max(...evs.map(e => e.id));
        if (lastEventId !== 0 && maxId > lastEventId) playChime();
        setLastEventId(maxId);
      }
      setEvents(evs);
    } catch {}
  }, [apiBase, lastEventId, playChime]);

  // Polling
  useEffect(() => {
    fetchStats(); fetchEvents();
    pollTimerRef.current = setInterval(() => { fetchStats(); fetchEvents(); }, 2000);
    return () => clearInterval(pollTimerRef.current);
  }, [fetchStats, fetchEvents]);

  // Start ingestion
  const handleStartSource = async () => {
    const src = sourceInput.trim() || "0";
    setIngesting(true);
    try {
      const r = await fetch(`${apiBase}/api/source`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ camera_id: currentCamera, source: src }),
      });
      const data = await r.json();
      if (data.success && streamImgRef.current) {
        streamImgRef.current.src = `${apiBase}/stream/${currentCamera}?t=${Date.now()}`;
      }
    } catch {}
    setIngesting(false);
  };

  // Camera switch
  const handleCameraChange = (camId) => {
    setCurrentCamera(camId);
    if (streamImgRef.current) {
      streamImgRef.current.src = `${apiBase}/stream/${camId}?t=${Date.now()}`;
    }
    setTimeout(drawZones, 100);
  };

  // Filtered events
  const filtered = events.filter(e => {
    if (currentCategory && e.category !== currentCategory) return false;
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      return e.summary.toLowerCase().includes(q) ||
        e.camera_id.toLowerCase().includes(q) ||
        e.category.toLowerCase().includes(q) ||
        String(e.id).includes(q);
    }
    return true;
  });

  // Open modal
  const openModal = (ev) => setSelectedEvent(ev);
  const closeModal = () => setSelectedEvent(null);

  // Format time
  const fmtTime = (iso) => {
    try { return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }); }
    catch { return iso; }
  };

  return (
    <>
      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-header">
            <span className="stat-label">Events Today</span>
            <span className="stat-icon" aria-hidden="true">📅</span>
          </div>
          <span className="stat-val">{stats.events_today ?? 0}</span>
          <span className="stat-detail">Logged in SQLite</span>
        </div>
        <div className="stat-card">
          <div className="stat-header">
            <span className="stat-label">Avg VLM Latency</span>
            <span className="stat-icon" aria-hidden="true">⚡</span>
          </div>
          <span className="stat-val">{stats.avg_latency_ms ? `${stats.avg_latency_ms} ms` : "-- ms"}</span>
          <span className="stat-detail">Trigger → Audit Summary</span>
        </div>
        <div className="stat-card">
          <div className="stat-header">
            <span className="stat-label">Total Verified</span>
            <span className="stat-icon" aria-hidden="true">🛡️</span>
          </div>
          <span className="stat-val">{stats.total_events ?? 0}</span>
          <span className="stat-detail">Filtered & Stored Incidents</span>
        </div>
        <div className="stat-card" style={{ borderColor: "rgba(88,196,255,0.3)", background: "linear-gradient(180deg, var(--panel) 0%, rgba(2,132,199,0.06) 100%)" }}>
          <div className="stat-header">
            <span className="stat-label">Inference Stack</span>
            <span className="stat-icon" aria-hidden="true">💻</span>
          </div>
          <span className="stat-val" style={{ color: "var(--accent)" }}>RTX 5070 Ti</span>
          <span className="stat-detail">YOLOv11 · ByteTrack · Ollama</span>
        </div>
      </div>

      <div className="console-grid">
        {/* Video Panel */}
        <section className="card video-card">
          <div className="card-header">
            <div className="card-title">
              <span className="live-indicator" aria-hidden="true">●</span>
              Live Camera Feed
            </div>
            <div className="controls-group">
              <button
                className="btn btn-ghost"
                onClick={() => setZonesVisible(v => !v)}
                aria-pressed={zonesVisible}
              >
                Zones: <strong>{zonesVisible ? "Visible" : "Hidden"}</strong>
              </button>
              <select className="select" value={currentCamera} onChange={e => handleCameraChange(e.target.value)}>
                {CAMERAS.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
          </div>

          <div className="video-viewport" ref={viewportRef}>
            <img
              ref={streamImgRef}
              id="live-stream"
              src={`${apiBase}/stream/${currentCamera}`}
              alt={`Camera ${currentCamera} stream`}
              onError={(e) => {
                e.target.onerror = null;
                e.target.src = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='640' height='360'><rect width='100%' height='100%' fill='%23090c12'/><text x='50%' y='50%' fill='%235b6674' font-family='monospace' font-size='14' text-anchor='middle'>STANDBY — START STREAM BELOW</text></svg>";
              }}
            />
            <canvas ref={canvasRef} className="zone-canvas" aria-hidden="true" />

            <div className="hud-overlay">
              <span className="hud-pill rec"><span className="rec-dot" aria-hidden="true"></span>REC</span>
              <span className="hud-pill" id="hud-cam">CAM: {currentCamera}</span>
              <span className="hud-pill" id="hud-fps">4 FPS</span>
              <span className="hud-pill" id="hud-clock">
                {new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
              </span>
            </div>

            <div className="viewport-actions">
              <button className="icon-btn" title="Snapshot" onClick={() => {
                if (streamImgRef.current) {
                  const a = document.createElement("a");
                  a.download = `eventlens_${currentCamera}_${Date.now()}.jpg`;
                  a.href = streamImgRef.current.src; a.click();
                }
              }}>📸</button>
              <button className="icon-btn" title="Fullscreen" onClick={() => {
                const v = viewportRef.current;
                if (!document.fullscreenElement) v.requestFullscreen().catch(()=>{});
                else document.exitFullscreen();
              }}>⛶</button>
            </div>
          </div>

          <div className="controls-bar">
            <div className="controls-group">
              <input
                className="input"
                type="text"
                value={sourceInput}
                onChange={e => setSourceInput(e.target.value)}
                placeholder="Video path, RTSP URL, or '0' for webcam"
              />
              <button className="btn btn-primary" onClick={handleStartSource} disabled={ingesting}>
                {ingesting ? "Connecting…" : "Start Ingestion"}
              </button>
            </div>
            <div className="controls-group compact">
              <button className="btn btn-ghost" onClick={() => { setSourceInput("data/videos/test_tailgating.mp4"); handleStartSource(); }}>Tailgating</button>
              <button className="btn btn-ghost" onClick={() => { setSourceInput("data/videos/test_person_down.mp4"); handleStartSource(); }}>Person Down</button>
              <button className="btn btn-ghost" onClick={() => { setSourceInput("data/videos/test_crowd.mp4"); handleStartSource(); }}>Crowd</button>
              <button className="btn btn-ghost" onClick={() => { setSourceInput("data/videos/test_suspicious.mp4"); handleStartSource(); }}>Suspicious</button>
              <button className="btn btn-ghost" onClick={() => { setSourceInput("0"); handleStartSource(); }}>Webcam</button>
            </div>
          </div>
        </section>

        {/* Events Panel */}
        <section className="card feed-card">
          <div className="card-header">
            <div className="card-title">
              Classified Incidents
              <span className="counter-badge">{filtered.length}</span>
            </div>
            <input
              className="input"
              type="text"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              placeholder="Filter incidents…"
              style={{ width: "220px", minWidth: 0 }}
            />
          </div>

          <div className="filter-bar">
            {CATEGORIES.map(c => (
              <button
                key={c.key}
                className={`filter-btn ${currentCategory === c.key ? "active" : ""}`}
                onClick={() => setCurrentCategory(c.key)}
              >
                {c.label}
                <span className="pill-count">{stats.categories?.[c.key] ?? 0}</span>
              </button>
            ))}
          </div>

          <div className="events-list">
            {filtered.length === 0 ? (
              <div className="empty-state">
                <span>No incidents matching active filters.</span>
              </div>
            ) : (
              filtered.map(ev => (
                <div
                  key={ev.id}
                  className={`event-item ${SEVERITY_MAP[ev.category] || "notice"}`}
                  onClick={() => openModal(ev)}
                >
                  <img
                    className="event-thumb"
                    src={ev.keyframe_url}
                    alt={`Keyframe for event ${ev.id}`}
                    onError={e => { e.target.onerror = null; e.target.src = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='88' height='52'><rect width='100%' height='100%' fill='%230a0e12'/></svg>"; }}
                  />
                  <div className="event-body">
                    <div className="event-meta">
                      <span className={`badge ${BADGE_CLASS[ev.category]}`}>{ev.category.replace("_", " ")}</span>
                      <span className="event-time">{fmtTime(ev.timestamp)}</span>
                      <span className="event-cam">{ev.camera_id}</span>
                    </div>
                    <div className="event-summary">{ev.summary}</div>
                    <div className="event-footer">
                      <span>Conf: {(ev.confidence * 100).toFixed(0)}%</span>
                      <span>Latency: {ev.latency_ms || 0}ms</span>
                      {ev.track_ids?.length && (
                        <span>Tracks: {ev.track_ids.map(id => <span key={id} className="track-chip">#{id}</span>)}</span>
                      )}
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </section>
      </div>

      {/* Modal */}
      {selectedEvent && (
        <div className="modal-overlay open" onClick={closeModal}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <div className="modal-header-title">
                <span className={`badge ${BADGE_CLASS[selectedEvent.category]}`}>{selectedEvent.category.replace("_", " ")}</span>
                <h3>Incident #{selectedEvent.id}</h3>
              </div>
              <button className="btn btn-ghost btn-close" onClick={closeModal}>✕</button>
            </div>
            <div className="modal-body">
              <div className="modal-img-wrap">
                <img src={selectedEvent.keyframe_url} alt={`Keyframe ${selectedEvent.id}`} />
              </div>
              <div className="modal-details">
                <div className="modal-row">
                  <span className="detail-label">Summary</span>
                  <p className="detail-value" style={{ background: "var(--bg)", padding: "10px 14px", borderRadius: "6px", borderLeft: "3px solid var(--accent)" }}>{selectedEvent.summary}</p>
                </div>
                <div className="meta-grid">
                  <div className="meta-box"><span className="meta-label">Camera</span><span className="meta-val mono">{selectedEvent.camera_id}</span></div>
                  <div className="meta-box"><span className="meta-label">Timestamp</span><span className="meta-val mono">{selectedEvent.timestamp}</span></div>
                  <div className="meta-box"><span className="meta-label">Confidence</span><span className="meta-val mono">{(selectedEvent.confidence * 100).toFixed(1)}%</span></div>
                  <div className="meta-box"><span className="meta-label">Latency</span><span className="meta-val mono">{selectedEvent.latency_ms || 0} ms</span></div>
                </div>
                <div className="modal-row">
                  <span className="detail-label">Track IDs</span>
                  <div className="tracks-container">
                    {selectedEvent.track_ids?.length ? (
                      selectedEvent.track_ids.map(id => <span key={id} className="track-chip">Track #{id}</span>)
                    ) : <span style={{ color: "var(--muted-2)" }}>None</span>}
                  </div>
                </div>
                <div className="modal-actions">
                  <button className="btn" onClick={() => {
                    navigator.clipboard.writeText(JSON.stringify(selectedEvent, null, 2));
                  }}>Copy Event JSON</button>
                  <a className="btn btn-primary" href={`/chat.html?q=${encodeURIComponent(`Tell me about incident #${selectedEvent.id} on ${selectedEvent.camera_id}`)}`}>Query AI about this Event</a>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export default Dashboard;