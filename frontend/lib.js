/* EventLens shared runtime: typed API errors, safe polling, connection status, shortcuts help. */
(() => {
  class ApiError extends Error {
    constructor(message, { status = 0, url = '', cause } = {}) {
      super(message, { cause });
      this.name = 'ApiError';
      this.status = status;
      this.url = url;
    }
  }

  const REQUEST_TIMEOUT_MS = 8000;
  const MAX_BACKOFF_MS = 30000;
  const FAILURES_BEFORE_BANNER = 3;

  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

  /** fetch JSON with timeout + caller abort; throws ApiError, never returns a half-parsed body. */
  async function getJson(url, { signal, timeout = REQUEST_TIMEOUT_MS, ...init } = {}) {
    const timer = AbortSignal.timeout(timeout);
    const combined = signal ? AbortSignal.any([signal, timer]) : timer;
    let res;
    try {
      res = await fetch(url, { cache: 'no-store', ...init, signal: combined });
    } catch (cause) {
      if (signal?.aborted) throw cause; // caller cancelled: let AbortError propagate untouched
      const why = timer.aborted ? 'timed out' : 'network unreachable';
      throw new ApiError(`${url} ${why}`, { url, cause });
    }
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new ApiError(body.detail || `${url} returned HTTP ${res.status}`, { status: res.status, url });
    }
    try { return await res.json(); }
    catch (cause) { throw new ApiError(`${url} returned invalid JSON`, { status: res.status, url, cause }); }
  }

  // ---- connection banner -------------------------------------------------
  const failing = new Set();
  let banner;
  function ensureBanner() {
    if (banner) return banner;
    banner = Object.assign(document.createElement('div'), { className: 'link-banner', hidden: true });
    banner.setAttribute('role', 'status');
    banner.innerHTML = '<span class="link-banner__dot"></span><span>Connection to the EventLens engine lost. Retrying automatically…</span>';
    document.body.prepend(banner);
    return banner;
  }
  function setLink(name, ok) {
    ok ? failing.delete(name) : failing.add(name);
    const down = failing.size > 0;
    ensureBanner().hidden = !down;
    document.documentElement.dataset.link = down ? 'down' : 'ok';
  }

  /** Sequential poller: never overlaps, cancels in-flight work on stop, backs off on failure, sleeps when tab hidden. */
  function createPoller({ name, interval, task }) {
    let stopped = false, timer = 0, ctrl = null, failures = 0;

    const schedule = (ms) => { if (!stopped) timer = setTimeout(tick, ms); };
    async function tick() {
      if (stopped) return;
      if (document.hidden) return; // visibilitychange restarts us
      ctrl = new AbortController();
      try {
        await task(ctrl.signal);
        failures = 0;
        setLink(name, true);
      } catch (err) {
        if (err?.name === 'AbortError') return;
        failures += 1;
        console.warn(`[EventLens] poll "${name}" failed (${failures}x):`, err);
        if (failures >= FAILURES_BEFORE_BANNER) setLink(name, false);
      }
      schedule(Math.min(interval * 2 ** Math.max(0, failures - 1), MAX_BACKOFF_MS));
    }
    const onVisibility = () => {
      if (document.hidden) { clearTimeout(timer); ctrl?.abort(); }
      else { clearTimeout(timer); tick(); }
    };
    document.addEventListener('visibilitychange', onVisibility);
    tick();

    return {
      stop() {
        stopped = true; clearTimeout(timer); ctrl?.abort();
        document.removeEventListener('visibilitychange', onVisibility);
        setLink(name, true);
      },
    };
  }

  const report = (err) => { if (err?.name !== 'AbortError') console.warn('[EventLens]', err); };

  // ---- keyboard shortcut help (?) ----------------------------------------
  const SHORTCUTS = [
    ['/', 'Focus search / query box'], ['1 · 2', 'Switch camera'],
    ['M', 'Mute alert audio'], ['F', 'Fullscreen viewport'], ['Esc', 'Close dialog'], ['?', 'This help'],
  ];
  function toggleHelp() {
    let dlg = document.getElementById('shortcut-help');
    if (!dlg) {
      dlg = document.createElement('dialog');
      dlg.id = 'shortcut-help'; dlg.className = 'modal shortcut-help';
      dlg.setAttribute('aria-label', 'Keyboard shortcuts');
      dlg.innerHTML = `<div class="modal-content"><header class="modal-header"><h2>Keyboard shortcuts</h2></header>
        <dl class="shortcut-list">${SHORTCUTS.map(([k, d]) => `<dt><kbd>${esc(k)}</kbd></dt><dd>${esc(d)}</dd>`).join('')}</dl></div>`;
      dlg.addEventListener('click', (e) => { if (e.target === dlg) dlg.close(); });
      document.body.append(dlg);
    }
    dlg.open ? dlg.close() : dlg.showModal();
  }
  document.addEventListener('keydown', (e) => {
    if (e.key !== '?' || e.ctrlKey || e.metaKey || e.altKey) return;
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;
    e.preventDefault();
    toggleHelp();
  });

  window.EL = Object.freeze({ ApiError, esc, getJson, createPoller, report });
})();
