/* EventLens Motion Layer.
 * Zero-dependency native Web Animations API implementation.
 * Safe for plain browsers without any bundler or importmap. */
(() => {
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduced) return;

  const EASE = 'cubic-bezier(0.22, 1, 0.36, 1)';

  // 1. Page-load sequence
  window.addEventListener('DOMContentLoaded', () => {
    const navbar = document.querySelector('.navbar');
    if (navbar) {
      navbar.animate([
        { opacity: 0, transform: 'translateY(-16px)' },
        { opacity: 1, transform: 'translateY(0)' }
      ], { duration: 550, easing: EASE, fill: 'forwards' });
    }

    const cards = document.querySelectorAll('.telemetry-card');
    cards.forEach((card, i) => {
      card.animate([
        { opacity: 0, transform: 'translateY(16px)' },
        { opacity: 1, transform: 'translateY(0)' }
      ], { duration: 600, delay: 120 + i * 70, easing: EASE, fill: 'forwards' });
    });

    const panels = document.querySelectorAll('.panel, .console-panel, .distribution-panel, .chat-sidebar');
    panels.forEach((p) => {
      p.animate([
        { opacity: 0 },
        { opacity: 1 }
      ], { duration: 700, delay: 250, easing: EASE, fill: 'forwards' });
    });
  });

  // 2. Incident feed animation
  const feed = document.getElementById('event-feed');
  if (feed) {
    const seen = new Set();
    let firstPaint = true;
    new MutationObserver(() => {
      const fresh = [...feed.querySelectorAll('.event-item')].filter(el => !seen.has(el.dataset.id));
      fresh.forEach(el => seen.add(el.dataset.id));
      const targets = firstPaint ? fresh.slice(0, 6) : fresh.slice(0, 3);
      firstPaint = false;
      targets.forEach((target, i) => {
        target.animate([
          { opacity: 0, transform: 'translateX(-12px)' },
          { opacity: 1, transform: 'translateX(0)' }
        ], { duration: 450, delay: i * 50, easing: EASE, fill: 'forwards' });
      });
    }).observe(feed, { childList: true });
  }

  // 3. Dialog entrance animation
  document.querySelectorAll('dialog').forEach(dlg => {
    new MutationObserver(() => {
      if (dlg.open) {
        const target = dlg.firstElementChild || dlg;
        target.animate([
          { opacity: 0, transform: 'scale(0.97) translateY(10px)' },
          { opacity: 1, transform: 'scale(1) translateY(0)' }
        ], { duration: 300, easing: EASE, fill: 'forwards' });
      }
    }).observe(dlg, { attributes: true, attributeFilter: ['open'] });
  });
})();
