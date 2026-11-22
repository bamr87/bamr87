/**
 * layout_probe.mjs — the in-page half of the ux-audit layout capture (L1–L6).
 *
 * `probe` runs INSIDE the page (Playwright `page.evaluate(probe, opts)`), so it
 * must stay self-contained: no imports, no closures over module scope. It reads
 * the rendered box of every visible landmark, heading, text block, link,
 * control and image, applies the layout rules, and draws a wireframe SVG from
 * that geometry. Everything else (targets, files, exit codes) lives in
 * layout_capture.mjs; comparisons live in layout_compare.mjs.
 *
 * The rules judge rendered layout, which neither axe (WCAG) nor a page-level
 * overflow check sees: a nav strip that clips its own current item passes both.
 */

export const SCHEMA = 'ux-layout/v1';

export const VIEWPORTS = {
  phone: { width: 375, height: 812 },
  tablet: { width: 768, height: 1024 },
  desktop: { width: 1280, height: 800 },
};

// One row per rule; `phone` rules only run at widths <= 480px.
export const RULES = [
  { id: 'L1-page-overflow', severity: 'error', phone: false, what: 'The page pans sideways: content is wider than the viewport and the root does not clip it (overflow behind overflow-x: hidden or clip on <html>/<body> does not count, since nobody can reach it).' },
  { id: 'L2-current-clipped', severity: 'error', phone: false, what: 'The current item (aria-current or .active) is cut off by its container or the viewport.' },
  { id: 'L3-squeezed-label', severity: 'warn', phone: true, what: 'A short label (32 characters or fewer: breadcrumb, nav item, badge, button) wraps inside a box narrower than 55% of the screen.' },
  { id: 'L4-indented-column', severity: 'warn', phone: true, what: 'A text block of 3+ lines starts more than 32px right of the content edge, outside any card, article or list item.' },
  { id: 'L5-long-lead', severity: 'warn', phone: true, what: 'A text block set at 18px or larger runs more than 5 lines.' },
  { id: 'L6-hidden-scroller', severity: 'warn', phone: false, what: 'Controls sit off-screen in a scrolling strip whose scrollbar is hidden, with no sign the strip scrolls.' },
];

// Provisional: a transparent number for trends, not a gate.
export const scoreOf = (errors, warnings) => Math.max(0, 100 - 15 * errors - 5 * warnings);

export function probe({ maxHeight = 2400, rules }) {
  const VW = innerWidth, VH = innerHeight, doc = document.documentElement;
  const MAXH = maxHeight > 0 ? maxHeight : Infinity;
  const cls = (el) => (typeof el.className === 'string' ? el.className : '');
  const cat = (el) => {
    const t = el.tagName.toLowerCase(), r = el.getAttribute('role') || '', c = cls(el);
    if (['header', 'nav', 'main', 'aside', 'footer'].includes(t) || ['navigation', 'banner', 'contentinfo', 'complementary', 'main'].includes(r)) return 'landmark';
    if (/^h[1-6]$/.test(t)) return 'heading';
    if (['img', 'picture', 'video', 'canvas'].includes(t) || (t === 'i' && /\bbi-/.test(c))) return 'media';
    if (['button', 'input', 'select', 'textarea'].includes(t) || /\b(btn|nav-link|badge|dropdown-item|page-link)\b/.test(c)) return 'control';
    if (t === 'a') return 'link';
    if (['p', 'li', 'figcaption', 'blockquote', 'dd', 'dt', 'label', 'td', 'th'].includes(t)) return 'text';
    return null;
  };
  const lineCount = (el, fs) => {
    const rg = document.createRange();
    rg.selectNodeContents(el);
    const tops = [...rg.getClientRects()]
      .filter((r) => r.width > 1 && r.height > 4 && r.height < fs * 2.2)
      .map((r) => Math.round(r.top))
      .sort((a, b) => a - b);
    let n = 0, last = -1e9;
    for (const t of tops) if (t - last > 4) { n++; last = t; }
    return n;
  };
  const scrollParent = (el) => {
    for (let e = el.parentElement; e && e !== document.body && e !== doc; e = e.parentElement) {
      if (getComputedStyle(e).overflowX !== 'visible') return e;
    }
    return null;
  };

  // L1 asks what a user gets: can they pan sideways? scrollWidth alone also counts overflow
  // the viewport clips, which nobody can reach. The viewport takes <html>'s overflow-x, or
  // <body>'s when <html> is visible; hidden or clip there means no panning. (Not scrollTo:
  // under `scroll-behavior: smooth` it animates, and an immediate read of scrollX says 0.)
  const rootOx = getComputedStyle(doc).overflowX;
  const viewportOx = rootOx === 'visible' ? getComputedStyle(document.body).overflowX : rootOx;
  const sideways = !['hidden', 'clip'].includes(viewportOx) && doc.scrollWidth > doc.clientWidth + 1;

  const els = [], items = [];
  for (const el of document.querySelectorAll('body *')) {
    const k = cat(el);
    if (!k) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) continue;
    const y = r.top + scrollY;
    if (y > MAXH || y + r.height < 0) continue;
    const c = cls(el);
    const txt = (el.innerText || el.getAttribute('aria-label') || el.getAttribute('alt') || '').trim().replace(/\s+/g, ' ');
    const fs = parseFloat(cs.fontSize);
    const it = {
      k, tag: el.tagName.toLowerCase(), cls: c.split(/\s+/).filter(Boolean).slice(0, 4).join('.'),
      x: Math.round(r.left + scrollX), y: Math.round(y), w: Math.round(r.width), h: Math.round(r.height),
      fs: Math.round(fs * 10) / 10, txt: txt.slice(0, 60),
    };
    if (cs.position === 'fixed' || cs.position === 'sticky') it.fixed = true;
    if (el.getAttribute('aria-current') || /\bactive\b/.test(c)) it.current = true;
    if (['heading', 'text', 'link', 'control'].includes(k) && txt) it.lines = lineCount(el, fs);
    const sp = scrollParent(el);
    if (sp) {
      const pr = sp.getBoundingClientRect();
      if (r.left < pr.left - 1 || r.right > pr.right + 1) {
        it.clipped = true;
        it.hiddenBar = getComputedStyle(sp).scrollbarWidth === 'none';
      }
    }
    if (r.right > VW + 1 || r.left < -1) it.offscreen = true;
    els.push(el);
    items.push(it);
  }
  const TEXTY = ['heading', 'text', 'link', 'control'];
  const leaf = items.map((it, i) => !els.some((o, j) => j !== i && TEXTY.includes(items[j].k) && els[i].contains(o)));

  // ---- rules ---------------------------------------------------------------
  const sev = Object.fromEntries(rules.map((r) => [r.id, r.severity]));
  const found = [];
  const add = (id, i, msg) => {
    found.push({ id, severity: sev[id], msg, at: i == null ? null : { tag: items[i].tag, cls: items[i].cls, txt: items[i].txt, x: items[i].x, y: items[i].y, w: items[i].w, h: items[i].h } });
    if (i != null) items[i].flag = (items[i].flag ? `${items[i].flag},` : '') + id;
  };
  const phone = VW <= 480;
  if (sideways) add('L1-page-overflow', null, `the page pans sideways: ${doc.scrollWidth}px of content in a ${doc.clientWidth}px viewport`);
  const wide = items.filter((it) => ['heading', 'text', 'media'].includes(it.k) && it.w > 0.5 * VW && !it.fixed);
  const contentEdge = wide.length ? Math.min(...wide.map((it) => it.x)) : 0;
  const seen = new Set();
  items.forEach((it, i) => {
    if (it.k !== 'landmark' && it.current && (it.clipped || it.offscreen)) add('L2-current-clipped', i, `the current item "${it.txt}" is cut off by its container`);
    if (!phone) return;
    if (leaf[i] && TEXTY.includes(it.k) && it.lines >= 2 && it.w < 0.55 * VW && it.txt.length >= 3 && it.txt.length <= 32 && !seen.has(it.txt)) {
      seen.add(it.txt);
      add('L3-squeezed-label', i, `"${it.txt}" wraps to ${it.lines} lines in a ${it.w}px box`);
    }
    if (['heading', 'text'].includes(it.k) && it.txt.length >= 60 && it.lines >= 3 && it.x - contentEdge > 32 && !els[i].closest('.card, article, li')) {
      add('L4-indented-column', i, `a ${it.lines}-line text block starts ${it.x - contentEdge}px right of the content edge`);
    }
    if (it.k === 'text' && it.fs >= 18 && it.lines > 5) add('L5-long-lead', i, `${it.lines} lines of ${it.fs}px text`);
  });
  const hidden = items.filter((it) => it.k === 'control' && it.clipped && it.hiddenBar && !it.current).length;
  if (hidden) add('L6-hidden-scroller', null, `${hidden} control(s) sit off-screen in a strip whose scrollbar is hidden`);

  // ---- anchors: a page pattern's key regions, for cross-site comparison ----
  const visible = (sel) => [...document.querySelectorAll(sel)].find((e) => e.getBoundingClientRect().height > 0);
  const box = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect(), i = els.indexOf(el);
    return { x: Math.round(r.left + scrollX), y: Math.round(r.top + scrollY), w: Math.round(r.width), h: Math.round(r.height), fs: parseFloat(getComputedStyle(el).fontSize), lines: i >= 0 ? items[i].lines : undefined };
  };
  const h1 = visible('h1');
  const strip = [...document.querySelectorAll('nav, ul, div')].find((e) => ['auto', 'scroll'].includes(getComputedStyle(e).overflowX) && e.querySelectorAll('a').length >= 3 && e.getBoundingClientRect().height > 0) || visible('nav.nav-pills, nav.nav-tabs');
  const anchors = {
    breadcrumb: box(visible('ol.breadcrumb, nav[aria-label*="readcrumb"] ol')),
    sectionNav: box(strip),
    h1: box(h1),
    lead: box(h1 && (h1.parentElement.querySelector('p.lead') || h1.nextElementSibling)),
    firstCard: box([...document.querySelectorAll('main article, main .card')].find((e) => e.getBoundingClientRect().height > 40)),
  };
  const errors = found.filter((r) => r.severity === 'error').length;
  const warnings = found.length - errors;
  const summary = {
    url: location.href, vw: VW, vh: VH, docW: doc.scrollWidth, docH: doc.scrollHeight, items: items.length,
    contentEdge, h1AtPctOfFold: anchors.h1 ? Math.round((100 * anchors.h1.y) / VH) : null,
    errors, warnings, score: Math.max(0, 100 - 15 * errors - 5 * warnings),
  };

  // ---- wireframe SVG, drawn from the geometry (violations in red) ----------
  const H = Math.round(Math.min(MAXH, doc.scrollHeight));
  const C = { landmark: '#94a3b8', heading: '#2563eb', text: '#64748b', link: '#0d9488', control: '#7c3aed', media: '#d97706' };
  const esc = (s) => String(s).replace(/[&<>"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[ch]);
  const p = [`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${VW} ${H}" width="${VW}" height="${H}" font-family="ui-monospace,Menlo,monospace">`, `<rect width="${VW}" height="${H}" fill="#ffffff"/>`];
  for (const k of ['landmark', 'media', 'control', 'link', 'text', 'heading']) {
    items.forEach((it, i) => {
      if (it.k !== k || it.y > H) return;
      const bad = !!it.flag, col = bad ? '#dc2626' : C[k];
      if (k === 'landmark') { p.push(`<rect x="${it.x}" y="${it.y}" width="${it.w}" height="${it.h}" fill="none" stroke="${col}" stroke-dasharray="4 3"/>`); return; }
      if (k === 'media') { p.push(`<rect x="${it.x}" y="${it.y}" width="${it.w}" height="${it.h}" fill="${col}" fill-opacity="0.15" stroke="${col}"/>`); return; }
      if (['text', 'heading', 'link'].includes(k) && leaf[i] && it.lines) {
        const lh = it.h / it.lines, bh = Math.max(2, Math.min(lh * 0.55, it.fs * 0.6));
        for (let l = 0; l < it.lines; l++) {
          const bw = l === it.lines - 1 && it.lines > 1 ? it.w * 0.6 : it.w;
          p.push(`<rect x="${it.x}" y="${(it.y + l * lh + (lh - bh) / 2).toFixed(1)}" width="${bw.toFixed(1)}" height="${bh.toFixed(1)}" rx="1" fill="${col}" fill-opacity="${k === 'heading' ? 0.8 : 0.35}"/>`);
        }
        if (bad) p.push(`<rect x="${it.x - 1}" y="${it.y - 1}" width="${it.w + 2}" height="${it.h + 2}" fill="none" stroke="#dc2626" stroke-width="2"/>`);
      } else if (k !== 'text' || bad) {
        p.push(`<rect x="${it.x}" y="${it.y}" width="${it.w}" height="${it.h}" rx="3" fill="none" stroke="${col}" stroke-width="${bad ? 2 : 1}"/>`);
        if (it.txt && k === 'control') p.push(`<text x="${it.x + 3}" y="${it.y + Math.min(it.h - 3, 11)}" font-size="9" fill="${col}">${esc(it.txt.slice(0, Math.max(3, Math.floor(it.w / 5.5))))}</text>`);
      }
      if (bad) p.push(`<text x="${Math.max(2, Math.min(it.x + it.w + 2, VW - 30))}" y="${it.y + 9}" font-size="9" font-weight="700" fill="#dc2626">${esc(it.flag.replace(/-[a-z-]+/g, ''))}</text>`);
    });
  }
  p.push(`<line x1="0" y1="${VH}" x2="${VW}" y2="${VH}" stroke="#f59e0b" stroke-dasharray="6 4"/><text x="4" y="${VH - 4}" font-size="9" fill="#b45309">fold · ${VW}×${VH}</text></svg>`);
  return { geometry: { summary, anchors, rules: found, items }, svg: p.join('\n') };
}
