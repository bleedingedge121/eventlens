// EventLens dashboard — talks only to the existing local API (/api/events, /api/stats, /api/health, /api/source, /api/chat, /stream/{cam}).
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
const CATS = {
  tailgating: ['Tailgating', '#F59E0B'], person_down: ['Person Down', '#EF4444'], fighting: ['Fighting', '#F97316'],
  crowd_incident: ['Crowd', '#818CF8'], suspicious_activity: ['Suspicious', '#22D3EE']
};
const cname = c => (CATS[c] || [String(c || 'Unknown').replace(/_/g, ' ')])[0];
const ccol = c => (CATS[c] || [0, '#94A3B8'])[1];
const LOW = 0.6;

// ---- event field helpers (tolerant of common naming variants) ----
const tms = e => { let t = e.timestamp ?? e.ts ?? e.created_at ?? e.time; if (typeof t === 'number') return t < 1e12 ? t * 1000 : t; const d = Date.parse(t); return isNaN(d) ? null : d; };
const conf = e => { let c = e.confidence; if (c == null || c === '') return null; c = +c; return isNaN(c) ? null : c > 1 ? c / 100 : c; };
const lat = e => { const v = e.latency_ms ?? e.vlm_latency_ms ?? e.latency; return v == null || isNaN(+v) ? null : +v; };
const cam = e => e.camera_id ?? e.camera ?? 'unknown';
const sum = e => e.summary ?? e.description ?? '';
const img = e => { const p = e.keyframe_url ?? e.keyframe_path ?? e.keyframe ?? e.image; return p ? (/^(https?:|\/|data:)/.test(p) ? p : '/' + p.replace(/\\/g, '/')) : null; };
const review = e => e.category === 'suspicious_activity' || (conf(e) != null && conf(e) < LOW);
const fT = ms => ms == null ? '—' : new Date(ms).toLocaleTimeString([], { hour12: false });
const fDT = ms => ms == null ? '—' : new Date(ms).toLocaleString([], { hour12: false });
const pct = c => c == null ? 'n/a' : Math.round(c * 100) + '%';
const camLbl = id => id.replace(/^cam(\d+)$/i, (_, n) => 'CAM ' + n.padStart(2, '0'));

const S = { events: [], cat: '', cam: '', q: '', range: 864e5, sel: null, audio: true, maxId: null, seq: 0, src: null };
function toast(msg, err) { const t = document.createElement('div'); t.className = 'toast' + (err ? ' err' : ''); t.textContent = msg; $('#toasts').append(t); setTimeout(() => t.remove(), 4000); }
async function api(path, opt) { const r = await fetch(path, opt); if (!r.ok) throw new Error(path + ' → ' + r.status); return r.json(); }
const list = d => Array.isArray(d) ? d : (d?.events ?? []);

// ---- system / stream status (reflects real state) ----
function sys(state, text) { const p = $('#sys-pill'); p.className = 'pill ' + state; $('#sys-text').textContent = text; }
function streamState(cls, text, fb) {
  const t = $('#stream-state'); t.className = 'tag ' + cls; t.textContent = text;
  $('#stream-fallback').classList.toggle('hide', !fb); if (fb) { $('#fallback-text').textContent = fb; $('#retry').hidden = cls !== 'err'; $('.offline .spinner').hidden = cls === 'err'; }
}
async function health() {
  try { const h = await api('/api/health'); sys(h.ok ? 'live' : 'warn', h.ok ? 'Local engine online' : 'Engine degraded'); }
  catch { sys('err', 'Backend offline'); }
}
function setStream() {
  const c = $('#camera-select').value; streamState('', 'Connecting', 'Waiting for first frame…');
  $('#stream').src = `/stream/${c}?t=${Date.now()}`; $('#hud-camera').textContent = camLbl(c);
}
$('#stream').addEventListener('load', () => streamState('live', S.src && S.src !== '0' && !/^rtsp/i.test(S.src) ? 'Processing recording' : 'Live', ''));
$('#stream').addEventListener('error', () => streamState('err', 'Disconnected', 'Stream unavailable — the camera has no active ingestion or the backend is unreachable.'));
$('#retry').onclick = setStream; $('#camera-select').onchange = setStream;
setInterval(() => $('#hud-time').textContent = new Date().toLocaleTimeString([], { hour12: false }), 1000);

// ---- ingestion ----
async function startSource(src) {
  src = src.trim(); if (!src) return toast('Enter a video path, RTSP URL or 0.', true);
  const cid = $('#camera-select').value, b = $('#start-source'); b.disabled = true;
  try { await api('/api/source', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ camera_id: cid, source: src }) });
    S.src = src; toast(`Ingestion started on ${camLbl(cid)}`); setStream(); }
  catch (e) { streamState('err', 'Ingestion failed', 'Could not start ingestion. Check the source path and backend logs.'); toast('Failed to start ingestion: ' + e.message, true); }
  b.disabled = false;
}
$('#start-source').onclick = () => startSource($('#source-input').value);
$$('.scenario-btn').forEach(b => b.onclick = () => { $('#source-input').value = b.dataset.src; startSource(b.dataset.src); });

// ---- viewport tools ----
const zonesBtn = $('#zones-toggle');
function toggleZones() { const on = zonesBtn.getAttribute('aria-pressed') !== 'true'; zonesBtn.setAttribute('aria-pressed', on); $('#zones-state').textContent = on ? 'On' : 'Off'; $('#zone-overlay').style.display = on ? '' : 'none'; }
zonesBtn.onclick = toggleZones;
$('#snapshot').onclick = () => { try { const i = $('#stream'), c = document.createElement('canvas'); c.width = i.naturalWidth; c.height = i.naturalHeight; c.getContext('2d').drawImage(i, 0, 0);
  const a = document.createElement('a'); a.href = c.toDataURL('image/png'); a.download = `eventlens_${$('#camera-select').value}_${Date.now()}.png`; a.click(); } catch { toast('Snapshot unavailable: no frame yet.', true); } };
const fs = () => document.fullscreenElement ? document.exitFullscreen() : $('#viewport').requestFullscreen?.();
$('#fullscreen').onclick = fs;
function toggleAudio() { S.audio = !S.audio; $('#audio-label').textContent = S.audio ? 'Audio On' : 'Audio Off'; }
$('#audio-toggle').onclick = toggleAudio;
function beep() { try { const a = new AudioContext(), o = a.createOscillator(), g = a.createGain(); o.frequency.value = 880; g.gain.value = .08; o.connect(g); g.connect(a.destination); o.start(); o.stop(a.currentTime + .15); } catch { } }
document.addEventListener('keydown', e => {
  const typing = /INPUT|TEXTAREA|SELECT/.test(e.target.tagName); if (e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.key === '/' && !typing) { e.preventDefault(); $('#event-search').focus(); }
  else if (!typing) { const k = e.key.toLowerCase(); if (k === 'm') toggleAudio(); else if (k === 'z') toggleZones(); else if (k === 'f') fs(); }
});

// ---- data load (stale responses discarded) ----
async function load() {
  const my = ++S.seq;
  try {
    const since = new Date(Date.now() - S.range).toISOString();
    const evs = list(await api(`/api/events?limit=1000&since=${encodeURIComponent(since)}`));
    if (my !== S.seq) return;
    const sorted = evs.filter(e => tms(e) != null && tms(e) >= Date.now() - S.range).sort((a, b) => tms(b) - tms(a));
    const top = sorted.reduce((m, e) => Math.max(m, +e.id || 0), 0);
    if (S.maxId != null && top > S.maxId && S.audio) beep();
    S.maxId = Math.max(S.maxId ?? 0, top); S.events = sorted; S.err = false;
    const cams = [...new Set(['cam1', 'cam2', ...sorted.map(cam)])], sel = $('#cam-filter'), cur = sel.value;
    sel.innerHTML = '<option value="">All cameras</option>' + cams.map(c => `<option value="${esc(c)}">${esc(camLbl(c))}</option>`).join(''); sel.value = cur;
  } catch (e) { if (my !== S.seq) return; S.err = true; S.events = []; }
  render();
}
const base = () => S.events.filter(e => (!S.cam || cam(e) === S.cam) && (!S.q || (sum(e) + cname(e.category) + cam(e)).toLowerCase().includes(S.q)));
const shown = () => base().filter(e => !S.cat || e.category === S.cat);

function render() {
  const b = base(), v = shown();
  const lats = v.map(lat).filter(x => x != null);
  $('#k-total').textContent = S.err ? '—' : v.length;
  $('#k-review').textContent = S.err ? '—' : v.filter(review).length;
  $('#k-lat').textContent = lats.length ? Math.round(lats.reduce((a, c) => a + c, 0) / lats.length) + ' ms' : '—';
  $('#k-last').textContent = v[0] ? fT(tms(v[0])) : '—';
  $('#k-last-s').textContent = v[0] ? `${cname(v[0].category)} · ${camLbl(cam(v[0]))}` : S.err ? 'Could not load events' : 'No events in period';
  $('#feed-count').textContent = v.length;
  $('#count-all').textContent = b.length; Object.keys(CATS).forEach(c => { const el = $('#count-' + c); if (el) el.textContent = b.filter(e => e.category === c).length; });
  $('#event-feed').innerHTML = S.err ? '<div class="empty">Could not load events from <code>/api/events</code>. This is a connection error, not zero events.</div>'
    : v.length ? v.map(e => `<button class="ev ${S.sel == e.id ? 'sel' : ''}" role="listitem" data-id="${esc(e.id)}" style="--c:${ccol(e.category)}">
      <div class="th">${img(e) ? `<img src="${esc(img(e))}" alt="" loading="lazy" onerror="this.remove()">` : 'No image'}</div>
      <div><div class="ev-t"><span class="badge" style="--c:${ccol(e.category)}">${esc(cname(e.category))}</span><span class="ev-m">${fT(tms(e))} · ${esc(camLbl(cam(e)))}${conf(e) != null ? ` · <span class="${conf(e) < LOW ? 'lowc' : ''}">${pct(conf(e))}</span>` : ''}</span></div><p>${esc(sum(e))}</p></div></button>`).join('')
    : '<div class="empty">No events match the current period and filters.</div>';
  timeline(v); bars('#bars-cat', v, e => e.category, cname, ccol); bars('#bars-cam', v, cam, camLbl, () => '#22D3EE');
}
function bars(sel, v, key, lab, col) {
  const m = {}; v.forEach(e => m[key(e)] = (m[key(e)] || 0) + 1); const k = Object.keys(m).sort((a, b) => m[b] - m[a]), mx = Math.max(1, ...Object.values(m));
  $(sel).innerHTML = k.length ? k.map(x => `<div class="bar"><span>${esc(lab(x))}</span><i style="--c:${col(x)};width:${m[x] / mx * 100}%"></i><span>${m[x]}</span></div>`).join('') : '<div class="muted-s">No data for the current filters.</div>';
}

// ---- timeline (SVG): x = time, y = model confidence ----
function timeline(v) {
  const W = 1000, H = 230, L = 44, R = 16, T = 14, B = 30, t1 = Date.now(), t0 = t1 - S.range, x = t => L + (t - t0) / (t1 - t0) * (W - L - R), y = c => T + (1 - c) * (H - T - B);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Event timeline. ${v.length} events.">`;
  [0, .5, 1].forEach(c => s += `<line x1="${L}" x2="${W - R}" y1="${y(c)}" y2="${y(c)}" stroke="#29364A" stroke-dasharray="${c ? '3 4' : ''}"/><text x="${L - 8}" y="${y(c) + 4}" text-anchor="end">${c * 100}%</text>`);
  for (let i = 0; i <= 5; i++) { const t = t0 + (t1 - t0) * i / 5; s += `<text x="${x(t)}" y="${H - 8}" text-anchor="${i == 0 ? 'start' : i == 5 ? 'end' : 'middle'}">${S.range > 864e5 ? new Date(t).toLocaleDateString([], { month: 'short', day: 'numeric' }) : fT(t).slice(0, 5)}</text>`; }
  s += `<line x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}" stroke="#22C55E" stroke-width="2"/>`;
  if (!v.length) s += `<text x="${W / 2}" y="${H / 2}" text-anchor="middle">${S.err ? 'Event data unavailable' : 'No events detected in this period'}</text>`;
  v.forEach(e => { const c = conf(e), low = c != null && c < LOW, col = low ? '#F59E0B' : '#EF4444', t = tms(e);
    s += `<g class="mk" tabindex="0" role="button" data-id="${esc(e.id)}" aria-label="${esc(cname(e.category))} at ${fT(t)} on ${esc(cam(e))}"><line x1="${x(t)}" x2="${x(t)}" y1="${y(0)}" y2="${y(c ?? 0)}" stroke="${col}" stroke-opacity=".35"/>
      <circle cx="${x(t)}" cy="${y(c ?? 0)}" r="${S.sel == e.id ? 9 : 6}" fill="${c == null ? 'none' : col}" stroke="${S.sel == e.id ? '#22D3EE' : col}" stroke-width="2"/></g>`; });
  $('#timeline').innerHTML = s + '</svg>';
}
const tip = $('#tip');
$('#timeline').addEventListener('mouseover', e => { const g = e.target.closest('.mk'); if (g) showTip(g, e); });
$('#timeline').addEventListener('mousemove', e => { if (!tip.hidden) place(e.clientX, e.clientY); });
$('#timeline').addEventListener('mouseout', () => tip.hidden = true);
$('#timeline').addEventListener('focusin', e => { const g = e.target.closest('.mk'); if (g) { const r = g.getBoundingClientRect(); showTip(g); place(r.right, r.top); } });
$('#timeline').addEventListener('focusout', () => tip.hidden = true);
function showTip(g) { const ev = S.events.find(x => x.id == g.dataset.id); if (!ev) return;
  tip.innerHTML = `<b>${fDT(tms(ev))} | ${esc(camLbl(cam(ev)))}</b><div>Event: ${esc(cname(ev.category))}</div><div>Confidence: ${pct(conf(ev))}</div><div>${esc(sum(ev)).slice(0, 140)}</div>`; tip.hidden = false; }
function place(px, py) { const r = tip.getBoundingClientRect(); tip.style.left = Math.min(px + 14, innerWidth - r.width - 8) + 'px'; tip.style.top = Math.max(8, Math.min(py + 14, innerHeight - r.height - 8)) + 'px'; }
$('#timeline').addEventListener('click', e => { const g = e.target.closest('.mk'); if (g) pick(g.dataset.id, true); });
$('#timeline').addEventListener('keydown', e => { const g = e.target.closest('.mk'); if (g && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); pick(g.dataset.id, true); } });
$('#event-feed').addEventListener('click', e => { const b = e.target.closest('.ev'); if (b) pick(b.dataset.id, true); });

// ---- selection + modal (feed and timeline stay in sync) ----
function pick(id, open) {
  S.sel = id; render(); document.querySelector(`.ev[data-id="${CSS.escape(String(id))}"]`)?.scrollIntoView({ block: 'nearest' });
  if (open) modal(S.events.find(e => e.id == id));
}
function modal(e) {
  if (!e) return; const c = conf(e), l = lat(e), m = $('#event-modal');
  const b = $('#modal-category-badge'); b.textContent = cname(e.category); b.style.setProperty('--c', ccol(e.category));
  $('#modal-title').textContent = `Event #${e.id}`; $('#modal-summary').textContent = sum(e) || 'No summary recorded.';
  $('#modal-camera').textContent = camLbl(cam(e)); $('#modal-timestamp').textContent = fDT(tms(e)); $('#modal-confidence').textContent = pct(c); $('#modal-latency').textContent = l == null ? 'n/a' : Math.round(l) + ' ms';
  const mi = $('#modal-image'), u = img(e); mi.style.display = u ? '' : 'none'; mi.src = u || '';
  const tr = e.track_ids ?? e.tracks ?? []; $('#modal-tracks').innerHTML = (Array.isArray(tr) ? tr : String(tr).split(',')).filter(x => x !== '').map(t => `<span>#${esc(t)}</span>`).join('') || '<span class="muted-s">None recorded</span>';
  $('#copy-event').onclick = () => navigator.clipboard.writeText(JSON.stringify(e, null, 2)).then(() => toast('Event JSON copied'), () => toast('Copy failed', true));
  $('#query-link').href = 'chat.html?q=' + encodeURIComponent(`Tell me about event ${e.id} (${cname(e.category)} on ${cam(e)})`);
  m.showModal();
}
$('#modal-close').onclick = () => $('#event-modal').close();
$$('dialog').forEach(d => d.addEventListener('click', e => { if (e.target === d) d.close(); }));

// ---- filters ----
$('#event-search').oninput = e => { S.q = e.target.value.trim().toLowerCase(); render(); };
$('#cam-filter').onchange = e => { S.cam = e.target.value; render(); };
$('#range').onchange = e => { S.range = +e.target.value; load(); };
$$('.filter-btn').forEach(b => b.onclick = () => { S.cat = b.dataset.category; $$('.filter-btn').forEach(x => { const on = x === b; x.classList.toggle('on', on); x.setAttribute('aria-pressed', on); }); render(); });

// ================= REPORT GENERATION =================
const SECS = { stats: 'Operational statistics', register: 'Incident register', patterns: 'Trends & patterns', limits: 'Confidence & limitations', perf: 'Technical performance', ai: 'AI interpretation & recommendations' };
function checks(sel, items, name) { $(sel).innerHTML = items.map(([v, l]) => `<label><input type="checkbox" name="${name}" value="${esc(v)}" checked> ${esc(l)}</label>`).join(''); }
$('#open-report').onclick = () => {
  const cams = [...new Set(['cam1', 'cam2', ...S.events.map(cam)])];
  checks('#rp-cams', cams.map(c => [c, camLbl(c)]), 'cam'); checks('#rp-cats', Object.keys(CATS).map(c => [c, cname(c)]), 'cat'); checks('#rp-secs', Object.entries(SECS), 'sec');
  $('#rep-form').hidden = false; $('#rep-view').hidden = true; $('#report-modal').showModal();
};
$('#rep-close').onclick = () => $('#report-modal').close();
$('#rp-period').onchange = e => $('#rp-custom').hidden = e.target.value !== 'custom';
const vals = n => $$(`input[name=${n}]:checked`).map(i => i.value);

$('#rep-form').onsubmit = async ev => {
  ev.preventDefault(); const go = $('#rp-go'), p = $('#rp-period').value; let from, to = Date.now();
  if (p === 'today') { from = new Date().setHours(0, 0, 0, 0); } else if (p === 'custom') { from = Date.parse($('#rp-from').value); to = Date.parse($('#rp-to').value); } else from = to - +p;
  if (isNaN(from) || isNaN(to) || from >= to) return toast('Choose a valid reporting period.', true);
  const cams = vals('cam'), cats = vals('cat'), secs = vals('sec'); if (!cams.length || !cats.length) return toast('Select at least one camera and category.', true);
  go.disabled = true; go.textContent = 'Retrieving events…';
  try {
    const all = list(await api(`/api/events?limit=5000&since=${encodeURIComponent(new Date(from).toISOString())}`));
    const evs = all.filter(e => { const t = tms(e); return t != null && t >= from && t <= to && cams.includes(cam(e)) && cats.includes(e.category); }).sort((a, b) => tms(a) - tms(b));
    go.textContent = 'Building report…';
    const cfg = { from, to, cams, cats, secs, detail: $('#rp-detail').value, notes: $('#rp-notes').value.trim() };
    const rep = await buildReport(evs, cfg); showReport(rep, evs, cfg);
  } catch (e) { toast('Report failed: ' + e.message + ' Your selections were kept.', true); }
  go.disabled = false; go.textContent = 'Generate Report';
};
const tally = (evs, f) => evs.reduce((m, e) => (m[f(e)] = (m[f(e)] || 0) + 1, m), {});
const tbl = (m, lab) => `<table><tr><th>${lab}</th><th>Events</th></tr>${Object.entries(m).sort((a, b) => b[1] - a[1]).map(([k, n]) => `<tr><td>${esc(lab === 'Category' ? cname(k) : camLbl(k))}</td><td class="m">${n}</td></tr>`).join('')}</table>`;

async function aiNarrative(evs, cfg) {
  const rec = evs.slice(-60).map(e => ({ id: e.id, time: new Date(tms(e)).toISOString(), camera: cam(e), category: e.category, confidence: conf(e), summary: sum(e) }));
  const q = `Using ONLY the event records below, write a ${cfg.detail === 'full' ? 'detailed' : 'concise'} analysis with: executive summary, notable patterns, and prioritised follow-up actions. Do not invent events or identify individuals. State uncertainty. ${cfg.notes ? 'Operator request: ' + cfg.notes + '. ' : ''}Records (${rec.length} of ${evs.length}): ${JSON.stringify(rec)}`;
  const r = await api('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: q }) });
  if (!r.answer) throw new Error('empty answer'); return r.answer;
}
async function buildReport(evs, cfg) {
  const n = evs.length, lats = evs.map(lat).filter(x => x != null), lows = evs.filter(e => conf(e) != null && conf(e) < LOW), noc = evs.filter(e => conf(e) == null);
  const byC = tally(evs, e => e.category), byCam = tally(evs, cam), has = k => cfg.secs.includes(k), full = cfg.detail === 'full', ov = cfg.detail === 'overview';
  let ai = null, aiErr = null; if (has('ai') && n) { try { ai = await aiNarrative(evs, cfg); } catch (e) { aiErr = e.message; } }
  const hours = tally(evs, e => new Date(tms(e)).getHours()), peak = Object.entries(hours).sort((a, b) => b[1] - a[1])[0];
  const sec = [];
  sec.push(['overview', 'Report Overview', `<div class="fact"><p>Period: ${fDT(cfg.from)} → ${fDT(cfg.to)}<br>Cameras: ${cfg.cams.map(camLbl).join(', ')}<br>Categories: ${cfg.cats.map(cname).join(', ')}<br>Generated: ${fDT(Date.now())}<br>Events analysed: <b>${n}</b></p></div>${cfg.notes ? `<p class="muted-s">Operator instructions: ${esc(cfg.notes)}</p>` : ''}`]);
  sec.push(['summary', 'Executive Summary', n ? `<div class="fact"><p>${n} event${n > 1 ? 's' : ''} recorded; most frequent category: ${esc(cname(Object.entries(byC).sort((a, b) => b[1] - a[1])[0][0]))}. ${evs.filter(review).length} require human review (suspicious activity or confidence below ${LOW * 100}%).</p></div>${ai && ov ? `<div class="ai"><div class="ai-t">Model-generated interpretation</div>${esc(ai)}</div>` : ''}` : '<p>No events matched the selected scope. This means no detections were stored for these filters; it does not confirm that no incident occurred.</p>']);
  if (!ov && has('stats') && n) sec.push(['stats', 'Operational Statistics', `<div class="row2"><div>${tbl(byC, 'Category')}</div><div>${tbl(byCam, 'Camera')}</div></div><p class="muted-s">Normal-vs-anomalous ratios are not reported: the system stores detections only, not a count of normal observations.</p>`]);
  if (!ov && has('register') && n) sec.push(['register', 'Chronological Incident Register', `<table><tr><th>Time</th><th>Cam</th><th>Category</th><th>Conf.</th><th>Summary</th><th>ID / Evidence</th></tr>${evs.map(e => `<tr><td class="m">${fDT(tms(e))}</td><td class="m">${esc(camLbl(cam(e)))}</td><td>${esc(cname(e.category))}</td><td class="m">${pct(conf(e))}</td><td>${esc(sum(e))}</td><td class="m">#${esc(e.id)}${img(e) ? ` <a href="${esc(img(e))}" target="_blank" rel="noopener">keyframe</a>` : ''}</td></tr>`).join('')}</table>`]);
  if (!ov && has('patterns') && n) sec.push(['patterns', 'Trends and Patterns', `<div class="fact"><p>Observed from stored records: busiest hour of day ${peak ? String(peak[0]).padStart(2, '0') + ':00 (' + peak[1] + ' events)' : 'n/a'}; busiest camera ${esc(camLbl(Object.entries(byCam).sort((a, b) => b[1] - a[1])[0][0]))}. These are counts, not evidence of a common cause.</p></div>`]);
  if (has('limits')) sec.push(['limits', 'Confidence and Limitations', `<ul><li>${lows.length} event(s) below ${LOW * 100}% confidence; ${noc.length} without a recorded confidence.</li><li>Classifications and summaries are produced by local models and may be wrong; they are not verified incidents.</li><li>Footage gaps and stream interruptions are not recorded in the event store, so completeness cannot be confirmed.</li></ul>`]);
  if (has('perf') && lats.length) { const s = [...lats].sort((a, b) => a - b); sec.push(['perf', 'Technical Performance', `<p class="mono">Latency (trigger → saved) from ${lats.length} records — mean ${Math.round(lats.reduce((a, c) => a + c, 0) / lats.length)} ms, median ${Math.round(s[s.length >> 1])} ms, max ${Math.round(s[s.length - 1])} ms.</p>`]); }
  if (!ov && ai) sec.push(['ai', 'AI Interpretation and Recommended Follow-up', `<div class="ai"><div class="ai-t">Model-generated — verify against footage</div>${esc(ai)}</div>${n > 60 ? '<p class="note">The model received the 60 most recent events only.</p>' : ''}`]);
  else if (has('ai') && aiErr) sec.push(['ai', 'AI Interpretation', `<p class="note">AI narrative unavailable (${esc(aiErr)}). All other sections are computed directly from stored records.</p>`]);
  if (full && n) sec.push(['appx', 'Appendix', `<p class="mono">Event IDs: ${evs.map(e => '#' + e.id).join(', ')}</p><p class="muted-s">Method: events retrieved from /api/events and filtered client-side by period, camera and category. Statistics are counts of those records.</p>`]);
  return sec;
}
function showReport(sec, evs, cfg) {
  const rv = $('#rep-view'); rv.hidden = false; $('#rep-form').hidden = true;
  rv.innerHTML = `<div><h2 class="t">EventLens Intelligence Report</h2><div class="meta-h"><span>${fDT(cfg.from)} → ${fDT(cfg.to)}</span><span>${evs.length} events</span><span>${esc(cfg.detail)}</span></div></div>
  <nav class="toc" aria-label="Contents">${sec.map(([id, t]) => `<a href="#r-${id}">${esc(t)}</a>`).join('')}</nav>
  ${sec.map(([id, t, h]) => `<section id="r-${id}"><h3>${esc(t)}</h3>${h}</section>`).join('')}
  <div class="actions rep-actions"><button class="btn" id="r-copy">Copy text</button><button class="btn" id="r-csv">Export CSV</button><button class="btn" id="r-json">Export JSON</button><button class="btn" id="r-pdf">Print / Save PDF</button><button class="btn btn-primary" id="r-again">Revise parameters</button><button class="btn" id="r-back">Back to dashboard</button></div>`;
  rv.querySelectorAll('.toc a').forEach(a => a.onclick = e => { e.preventDefault(); rv.querySelector(a.getAttribute('href')).scrollIntoView(); });
  const dl = (name, type, data) => { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([data], { type })); a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000); };
  $('#r-copy').onclick = () => navigator.clipboard.writeText(rv.innerText).then(() => toast('Report copied'), () => toast('Copy failed', true));
  $('#r-json').onclick = () => dl('eventlens_events.json', 'application/json', JSON.stringify(evs, null, 2));
  $('#r-csv').onclick = () => { const q = v => '"' + String(v ?? '').replace(/"/g, '""') + '"'; dl('eventlens_events.csv', 'text/csv', 'id,timestamp,camera,category,confidence,latency_ms,summary\n' + evs.map(e => [e.id, new Date(tms(e)).toISOString(), cam(e), e.category, conf(e), lat(e), sum(e)].map(q).join(',')).join('\n')); };
  $('#r-pdf').onclick = () => print();
  $('#r-again').onclick = () => { rv.hidden = true; $('#rep-form').hidden = false; };
  $('#r-back').onclick = () => $('#report-modal').close();
  rv.scrollTop = 0; $('#report-modal').scrollTo(0, 0);
}

// ---- boot ----
setStream(); health(); load();
setInterval(health, 10000); setInterval(load, 5000);