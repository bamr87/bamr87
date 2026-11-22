#!/usr/bin/env node
/**
 * layout_compare.mjs — turn layout captures into differences (ux-audit kit).
 *
 * Change      --base DIR --head DIR   the same targets captured twice (before/after a change):
 *             per capture the score delta, rules fixed and introduced, a structural diff
 *             (boxes resized/moved sideways, added, removed, or only pushed down), anchor
 *             deltas, and a pixel diff when pngjs + pixelmatch are installed.
 * Consistency --consistency DIR       one run: captures sharing a role (section, home, …)
 *             across sites, compared by their pattern anchors (breadcrumb, section nav,
 *             h1, lead, first card) against the first site, so differences in layout
 *             separate from differences in content.
 *
 * Writes <out>/compare.{json,md} or consistency.{json,md}, diff/<key>.svg overlays and a board.svg.
 * Exit 0 · 1 when --fail-on regression and a capture got worse · 2 usage.
 *
 * Why geometry and not pixels: a pixel diff counts every pixel that content pushed down,
 * and two sites never share content, so pixels can neither name what changed nor say
 * whether two sites lay a page out the same way. Boxes can.
 */
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { join, resolve } from 'node:path';

function usage(msg) {
  if (msg) console.error(`layout_compare: ${msg}`);
  console.error('usage: layout_compare.mjs --base DIR --head DIR [--out DIR] [--fail-on none|regression]\n       layout_compare.mjs --consistency DIR [--out DIR]');
  process.exit(2);
}

function parseArgs(argv) {
  const a = { failOn: 'none' };
  for (let i = 0; i < argv.length; i++) {
    const v = () => { if (i + 1 >= argv.length) usage(`${argv[i]} needs a value`); return argv[++i]; };
    switch (argv[i]) {
      case '--base': a.base = v(); break;
      case '--head': a.head = v(); break;
      case '--consistency': a.consistency = v(); break;
      case '--out': a.out = v(); break;
      case '--fail-on': a.failOn = v(); break;
      case '-h': case '--help': usage();
      default: usage(`unknown argument ${argv[i]}`);
    }
  }
  if (!a.consistency && !(a.base && a.head)) usage('pass --base and --head, or --consistency');
  if (!['none', 'regression'].includes(a.failOn)) usage('--fail-on must be none or regression');
  a.out = resolve(a.out || a.head || a.consistency);
  return a;
}

const readSummary = (dir) => {
  const f = join(dir, 'summary.json');
  if (!existsSync(f)) usage(`${f} not found (run layout_capture.mjs first)`);
  return JSON.parse(readFileSync(f, 'utf8'));
};
const readGeometry = (dir, key) => JSON.parse(readFileSync(join(dir, `${key}.json`), 'utf8'));
const esc = (t) => String(t).replace(/[&<>"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[ch]);

const keyed = (g) => {
  const m = new Map(), n = {};
  for (const it of g.items) {
    const base = `${it.tag}|${it.cls}|${it.txt.slice(0, 40)}`;
    n[base] = (n[base] || 0) + 1;
    m.set(`${base}#${n[base]}`, it);
  }
  return m;
};

export function structural(a, b) {
  const A = keyed(a), B = keyed(b);
  const r = { unchanged: 0, shifted: 0, resized: 0, added: 0, removed: 0, changed: [] };
  for (const [k, x] of A) {
    const y = B.get(k);
    if (!y) { r.removed++; r.changed.push({ t: 'removed', k, x }); continue; }
    if (Math.abs(x.w - y.w) > 2 || Math.abs(x.h - y.h) > 2 || Math.abs(x.x - y.x) > 2) { r.resized++; r.changed.push({ t: 'resized', k, x, y }); }
    else if (Math.abs(x.y - y.y) > 2) r.shifted++;
    else r.unchanged++;
  }
  for (const [k, y] of B) if (!A.has(k)) { r.added++; r.changed.push({ t: 'added', k, y }); }
  return r;
}

const ruleKey = (r) => `${r.id}|${r.at?.txt ?? ''}`;
export function ruleDelta(a, b) {
  const A = new Set(a.rules.map(ruleKey)), B = new Set(b.rules.map(ruleKey));
  return { fixed: a.rules.filter((r) => !B.has(ruleKey(r))), introduced: b.rules.filter((r) => !A.has(ruleKey(r))) };
}

export function anchorDelta(a, b) {
  return Object.fromEntries(Object.keys({ ...a.anchors, ...b.anchors }).map((k) => {
    const x = a.anchors[k], y = b.anchors[k];
    if (!x || !y) return [k, x || y ? 'only one side has it' : null];
    return [k, { dx: y.x - x.x, dy: y.y - x.y, dw: y.w - x.w, dfs: +(y.fs - x.fs).toFixed(1), dlines: (y.lines ?? 0) - (x.lines ?? 0) }];
  }));
}

async function pixelDiff(pa, pb) {
  if (!existsSync(pa) || !existsSync(pb)) return null;
  let PNG, pixelmatch;
  try {
    ({ PNG } = await import('pngjs'));
    ({ default: pixelmatch } = await import('pixelmatch'));
  } catch {
    return null;
  }
  const A = PNG.sync.read(readFileSync(pa)), B = PNG.sync.read(readFileSync(pb));
  const w = Math.min(A.width, B.width), h = Math.min(A.height, B.height);
  const crop = (P) => { const o = new PNG({ width: w, height: h }); PNG.bitblt(P, o, 0, 0, w, h, 0, 0); return o; };
  const n = pixelmatch(crop(A).data, crop(B).data, null, w, h, { threshold: 0.1 });
  return +((100 * n) / (w * h)).toFixed(1);
}

function diffSvg(a, b, s) {
  const W = Math.max(a.summary.vw, b.summary.vw), H = Math.max(...[...a.items, ...b.items].map((it) => it.y + it.h), 100);
  const p = [`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}"><rect width="${W}" height="${H}" fill="#fff"/>`];
  for (const it of a.items) p.push(`<rect x="${it.x}" y="${it.y}" width="${it.w}" height="${it.h}" fill="none" stroke="#e2e8f0"/>`);
  for (const c of s.changed) {
    if ((c.x || c.y).k === 'landmark') continue;
    if (c.x) p.push(`<rect x="${c.x.x}" y="${c.x.y}" width="${c.x.w}" height="${c.x.h}" fill="#dc2626" fill-opacity="0.08" stroke="#dc2626" stroke-dasharray="3 2"/>`);
    if (c.y) p.push(`<rect x="${c.y.x}" y="${c.y.y}" width="${c.y.w}" height="${c.y.h}" fill="#16a34a" fill-opacity="0.08" stroke="#16a34a"/>`);
  }
  p.push('</svg>');
  return p.join('\n');
}

// A board: rows of panels, each panel one wireframe (an SVG string) with a title and up to 7 note lines.
function board(title, rows, crop = 1250) {
  const PW = Math.max(...rows.flat().map((pn) => pn.width)), GAP = 28, HEAD = 56, FOOT = 140, TOP = 48;
  const cols = Math.max(...rows.map((r) => r.length));
  const W = GAP + cols * (PW + GAP), RH = HEAD + crop + FOOT, H = TOP + rows.length * RH;
  const out = [`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" font-family="system-ui,-apple-system,sans-serif">`, `<rect width="${W}" height="${H}" fill="#f1f5f9"/>`, `<text x="${GAP}" y="30" font-size="18" font-weight="700" fill="#0f172a">${esc(title)}</text>`];
  rows.forEach((row, ri) => row.forEach((pn, ci) => {
    const x = GAP + ci * (PW + GAP), y = TOP + ri * RH;
    out.push(`<text x="${x}" y="${y + 20}" font-size="14" font-weight="600" fill="#0f172a">${esc(pn.title.slice(0, 52))}</text>`);
    out.push(`<text x="${x}" y="${y + 40}" font-size="12.5" fill="${pn.tone || '#334155'}">${esc(pn.subtitle.slice(0, 60))}</text>`);
    out.push(`<rect x="${x - 1}" y="${y + HEAD - 1}" width="${pn.width + 2}" height="${crop + 2}" fill="none" stroke="#cbd5e1"/>`);
    out.push(pn.svg.replace(/^<svg [^>]*>/, `<svg x="${x}" y="${y + HEAD}" width="${pn.width}" height="${crop}" viewBox="0 0 ${pn.width} ${crop}" overflow="hidden">`));
    (pn.notes || []).slice(0, 7).forEach((n, j) => out.push(`<text x="${x}" y="${y + HEAD + crop + 20 + j * 17}" font-size="11.5" fill="${n.tone || '#334155'}">${esc(n.text.slice(0, 62))}</text>`));
  }));
  out.push('</svg>');
  return out.join('\n');
}

const ruleNotes = (rules) => (rules.length ? rules.map((r) => ({ text: `${r.id.split('-')[0]} ${r.msg}`, tone: r.severity === 'error' ? '#b91c1c' : '#a16207' })) : [{ text: 'no layout findings', tone: '#15803d' }]);
const scoreTone = (s) => (s < 80 ? '#b91c1c' : '#15803d');
const smallestViewportFirst = (a, b) => a.vw - b.vw;

async function change(a) {
  const base = readSummary(a.base), head = readSummary(a.head);
  const headKeys = new Map(head.captures.map((c) => [c.key, c]));
  const rows = [], md = ['# Layout change', '', `\`${a.base}\` → \`${a.head}\``, '', '| capture | score | fixed | introduced | resized · added · removed · shifted | pixels |', '| --- | --- | --- | --- | --- | --- |'];
  mkdirSync(join(a.out, 'diff'), { recursive: true });
  let regressions = 0;
  const panels = [];
  for (const bc of [...base.captures].sort(smallestViewportFirst)) {
    const hc = headKeys.get(bc.key);
    if (!hc) { rows.push({ key: bc.key, missing: 'head' }); md.push(`| ${bc.key} | ${bc.score} → — | | | not in head | |`); continue; }
    const ga = readGeometry(a.base, bc.key), gb = readGeometry(a.head, bc.key);
    const s = structural(ga, gb), r = ruleDelta(ga, gb);
    const px = await pixelDiff(join(a.base, `${bc.key}.png`), join(a.head, `${bc.key}.png`));
    const worse = r.introduced.length > 0 || hc.score < bc.score;
    if (worse) regressions++;
    const changed = s.resized + s.added + s.removed > 0 || r.fixed.length || r.introduced.length;
    rows.push({ key: bc.key, score: [bc.score, hc.score], fixed: r.fixed.map((x) => x.id), introduced: r.introduced.map((x) => x.id), structural: { ...s, changed: undefined }, anchors: anchorDelta(ga, gb), pixels_pct: px, regression: worse });
    md.push(`| ${bc.key} | ${bc.score} → ${hc.score} | ${r.fixed.map((x) => x.id.split('-')[0]).join(' ') || '—'} | ${r.introduced.map((x) => x.id.split('-')[0]).join(' ') || '—'} | ${s.resized} · ${s.added} · ${s.removed} · ${s.shifted} | ${px == null ? 'n/a' : `${px}%`} |`);
    if (changed) {
      const d = diffSvg(ga, gb, s);
      writeFileSync(join(a.out, 'diff', `${bc.key}.svg`), d);
      if (panels.length < 4) panels.push([
        { title: `${bc.key} — base`, subtitle: `score ${bc.score} · ${bc.errors} errors · ${bc.warnings} warnings`, tone: scoreTone(bc.score), svg: readFileSync(join(a.base, `${bc.key}.svg`), 'utf8'), width: ga.summary.vw, notes: ruleNotes(ga.rules) },
        { title: `${bc.key} — head`, subtitle: `score ${hc.score} · ${hc.errors} errors · ${hc.warnings} warnings`, tone: scoreTone(hc.score), svg: readFileSync(join(a.head, `${bc.key}.svg`), 'utf8'), width: gb.summary.vw, notes: ruleNotes(gb.rules) },
        { title: 'structural diff', subtitle: `${s.resized} resized · ${s.added} added · ${s.removed} removed · ${s.shifted} shifted${px == null ? '' : ` · pixels ${px}%`}`, svg: d, width: Math.max(ga.summary.vw, gb.summary.vw), notes: [{ text: 'red dashed = box before · green = box after' }, { text: 'grey = unchanged or only pushed down' }] },
      ]);
    }
  }
  for (const hc of head.captures) if (!base.captures.some((c) => c.key === hc.key)) { rows.push({ key: hc.key, missing: 'base' }); md.push(`| ${hc.key} | — → ${hc.score} | | | not in base | |`); }
  md.push('', `${regressions} capture(s) got worse (a rule introduced or a lower score).`);
  writeFileSync(join(a.out, 'compare.json'), JSON.stringify({ schema: 'ux-layout-compare/v1', base: a.base, head: a.head, regressions, captures: rows }, null, 1));
  writeFileSync(join(a.out, 'compare.md'), `${md.join('\n')}\n`);
  if (panels.length) writeFileSync(join(a.out, 'board.svg'), board('Layout change: base → head', panels));
  console.log(md.join('\n'));
  if (a.failOn === 'regression' && regressions) process.exit(1);
}

function consistency(a) {
  const run = readSummary(a.consistency);
  const groups = new Map();
  for (const c of run.captures) {
    if (!c.role) continue;
    const k = `${c.role}--${c.viewport}`;
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(c);
  }
  const report = [], md = ['# Layout consistency', '', 'Captures that share a role, compared by pattern anchors against the first site in each group. Δ is in CSS pixels; a layout difference moves x, w or font size, a content difference moves y and line counts.', ''];
  const rows = [];
  for (const [k, caps] of [...groups].sort()) {
    if (caps.length < 2) continue;
    const ref = readGeometry(a.consistency, caps[0].key);
    md.push(`## ${k}`, '', `reference: ${caps[0].key}`, '', '| capture | score | anchor | Δx | Δw | Δfont | Δy | Δlines |', '| --- | --- | --- | --- | --- | --- | --- | --- |');
    const entry = { group: k, reference: caps[0].key, sites: [] };
    for (const c of caps.slice(1)) {
      const g = readGeometry(a.consistency, c.key), d = anchorDelta(ref, g);
      const layoutDrift = Object.values(d).filter((v) => v && typeof v === 'object').reduce((m, v) => Math.max(m, Math.abs(v.dx), Math.abs(v.dw), Math.abs(v.dfs) * 4), 0);
      entry.sites.push({ key: c.key, score: c.score, anchors: d, layout_drift_px: layoutDrift });
      for (const [name, v] of Object.entries(d)) md.push(v && typeof v === 'object' ? `| ${c.key} | ${c.score} | ${name} | ${v.dx} | ${v.dw} | ${v.dfs} | ${v.dy} | ${v.dlines} |` : `| ${c.key} | ${c.score} | ${name} | ${v ?? 'absent on both'} | | | | |`);
    }
    md.push('');
    report.push(entry);
    if (caps[0].viewport === 'phone' && rows.length < 3) rows.push(caps.slice(0, 4).map((c) => {
      const g = readGeometry(a.consistency, c.key);
      return { title: c.key, subtitle: `score ${c.score} · ${c.errors} errors · ${c.warnings} warnings`, tone: scoreTone(c.score), svg: readFileSync(join(a.consistency, `${c.key}.svg`), 'utf8'), width: g.summary.vw, notes: ruleNotes(g.rules) };
    }));
  }
  if (!report.length) md.push('No role is shared by two or more captures, so there is nothing to compare.');
  mkdirSync(a.out, { recursive: true });
  writeFileSync(join(a.out, 'consistency.json'), JSON.stringify({ schema: 'ux-layout-consistency/v1', run: a.consistency, groups: report }, null, 1));
  writeFileSync(join(a.out, 'consistency.md'), `${md.join('\n')}\n`);
  if (rows.length) writeFileSync(join(a.out, 'board-consistency.svg'), board('Layout consistency: one role across sites', rows));
  console.log(md.join('\n'));
}

if (process.argv[1]?.endsWith('layout_compare.mjs')) {
  const a = parseArgs(process.argv.slice(2));
  (a.consistency ? Promise.resolve(consistency(a)) : change(a)).catch((err) => { console.error(err); process.exit(2); });
}
