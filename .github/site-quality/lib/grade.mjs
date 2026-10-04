// =============================================================================
// lib/grade.mjs — the ONE place site-quality decides pass / warn / fail
// -----------------------------------------------------------------------------
// Inputs are the raw collector outputs (axe, pa11y, LHCI) plus the resolved
// config. Every finding gets a level:
//   error  the caller's config made it gating (axe.fail_on, a contrast `max`,
//          a Lighthouse budget at level error, load_errors: error,
//          allowlist.on_expired: error)
//   warn   reported, never gating (the default for everything)
//   info   moderate/minor axe notes outside fail_on
// An allowlist entry that matches turns an error or warn into `allowed`
// (reported as a known issue, counted with the warnings). Status:
// fail = any error, warn = any warn/allowed, else pass.
// =============================================================================
import { entryMatches, expiredEntries } from './config.mjs';

const pathOf = (url, base) => {
  try {
    const u = new URL(url); const b = new URL(base.endsWith('/') ? base : `${base}/`);
    let p = u.pathname;
    if (b.pathname !== '/' && p.startsWith(b.pathname.replace(/\/$/, ''))) p = p.slice(b.pathname.replace(/\/$/, '').length) || '/';
    return p;
  } catch { return url; }
};

/** Normalise an LHCI assertion result into the allowlist's rule id. */
export const lhRule = (r) => r.auditProperty ? `${r.auditId}:${String(r.auditProperty).replace(/\./g, ':')}` : r.auditId;

export function grade({ cfg, theme = { kind: 'none' }, axeRaw = null, contrastRaw = null, lighthouse = null, meta = {}, asOf }) {
  const entries = cfg.allowlist.entries;
  const used = new Set();
  const findings = [];
  const add = (f) => {
    if (f.level === 'error' || f.level === 'warn') {
      const hit = entries.find((e) => entryMatches(e, f));
      if (hit) { used.add(hit.index); f.allowed = { index: hit.index, issue: hit.issue, until: hit.until, reason: hit.reason, was: f.level }; f.level = 'allowed'; }
    }
    findings.push(f);
  };

  // ---- axe: one finding per violating node, so a selector-scoped allowlist
  // entry covers exactly its nodes and a NEW node under the same rule still counts.
  if (axeRaw) {
    const fo = cfg.axe.fail_on;
    for (const p of axeRaw.pages) {
      if (p.error) { add({ check: 'axe', rule: 'page-load', page: p.page, viewport: p.viewport, level: cfg.load_errors, message: p.error }); continue; }
      for (const v of p.violations) {
        const gating = fo && v.tags.some((t) => fo.tags.includes(t)) && fo.impacts.includes(v.impact);
        const level = gating ? 'error' : ['critical', 'serious'].includes(v.impact) ? 'warn' : 'info';
        for (const n of v.nodes) {
          add({ check: 'axe', rule: v.rule, page: p.page, viewport: p.viewport, impact: v.impact, level, message: v.help, help: v.helpUrl,
            nodes: [`${n.target} ${n.html}`], target: n.target, matched: n.matched || [] });
        }
      }
    }
  }

  // ---- contrast: allowlisted nodes don't count toward a page's `max`.
  const contrastRows = [];
  if (contrastRaw) {
    for (const p of contrastRaw.pages) {
      if (p.error) { add({ check: 'contrast', rule: 'page-load', page: p.path, level: cfg.load_errors, message: p.error }); contrastRows.push({ path: p.path, error: p.error, max: p.max }); continue; }
      const counted = [];
      for (const i of p.issues) {
        const hit = entries.find((e) => entryMatches(e, { rule: 'contrast', page: p.path, nodes: [`${i.selector} ${i.context}`] }));
        if (hit) { used.add(hit.index); findings.push({ check: 'contrast', rule: 'contrast', page: p.path, level: 'allowed', message: `contrast ${i.shape}`, target: i.selector,
          allowed: { index: hit.index, issue: hit.issue, until: hit.until, reason: hit.reason, was: typeof p.max === 'number' ? 'error' : 'warn' } }); }
        else counted.push(i);
      }
      const shapes = {};
      for (const i of counted) shapes[i.shape] = (shapes[i.shape] || 0) + 1;
      const top = Object.entries(shapes).sort((x, y) => y[1] - x[1]).slice(0, 5);
      const over = typeof p.max === 'number' && counted.length > p.max;
      contrastRows.push({ path: p.path, count: counted.length, max: p.max, over, top });
      if (counted.length) findings.push({ check: 'contrast', rule: 'contrast', page: p.path, level: over ? 'error' : 'warn',
        message: `${counted.length} contrast failure(s)${typeof p.max === 'number' ? ` (max ${p.max})` : ' (report-only)'}; most common: ${top[0]?.[0] || ''}`, count: counted.length });
    }
  }

  // ---- Lighthouse: failed assertions at the level the caller set.
  if (lighthouse) {
    if (!lighthouse.collected) add({ check: 'lighthouse', rule: 'page-load', page: '*', level: cfg.load_errors, message: 'Lighthouse collection failed (see the job log)' });
    for (const r of lighthouse.assertions || []) {
      if (r.passed) continue;
      add({ check: 'lighthouse', rule: lhRule(r), page: pathOf(r.url, meta.base || ''), level: r.level === 'error' ? 'error' : 'warn',
        message: `${lhRule(r)}: expected ${r.operator} ${r.expected}, median ${typeof r.actual === 'number' ? +r.actual.toFixed(3) : r.actual}` });
    }
  }

  // ---- allowlist hygiene
  const expired = expiredEntries({ allowlist: { entries } }, asOf);
  for (const e of expired) {
    findings.push({ check: 'config', rule: 'allowlist-expired', page: e.page || '*', level: cfg.allowlist.on_expired,
      message: `allowlist entry #${e.index + 1} (${e.rule}${e.selector ? ` ${e.selector}` : ''}) expired on ${e.until}; renew it with a reason or fix ${e.issue}` });
  }
  const ran = new Set([axeRaw && 'axe', contrastRaw && 'contrast', lighthouse && 'lighthouse'].filter(Boolean));
  const stale = ran.size ? entries.filter((e) => !used.has(e.index)) : [];

  const count = (lvl) => findings.filter((f) => f.level === lvl).length;
  const counts = { error: count('error'), warn: count('warn'), allowed: count('allowed'), info: count('info') };
  const status = counts.error ? 'fail' : counts.warn || counts.allowed ? 'warn' : 'pass';
  return {
    schema: 'site-quality-report/v1',
    status, counts,
    mode: cfg.mode, base_url: meta.base || '', pages: cfg.pages,
    theme, hub: meta.hub || {}, config: meta.configPath || '', generated_at: meta.now || new Date().toISOString(),
    checks: {
      lighthouse: lighthouse ? { ran: true, collected: lighthouse.collected, scores: lighthouse.scores || [], public_links: lighthouse.links || {} } : { ran: false },
      axe: axeRaw ? { ran: true, version: axeRaw.axe, tags: axeRaw.tags, viewports: cfg.viewports.map((v) => v.name), pages: cfg.axe.pages } : { ran: false },
      contrast: contrastRaw ? { ran: true, rows: contrastRows, hide_elements: contrastRaw.hide_elements } : { ran: false },
    },
    allowlist: { on_expired: cfg.allowlist.on_expired, entries: entries.length, expired: expired.map((e) => e.index), stale: stale.map((e) => ({ index: e.index, rule: e.rule, page: e.page, selector: e.selector })) },
    findings,
  };
}

// ---------------------------------------------------------------------------
// Markdown summary (job summary + issue body)
// ---------------------------------------------------------------------------
const ICON = { pass: '✅ PASS', warn: '⚠️ WARN', fail: '❌ FAIL' };
const esc = (s) => String(s ?? '').replace(/\|/g, '\\|').replace(/\r?\n/g, ' ');

function groupRows(list) {
  const groups = new Map();
  for (const f of list) {
    const k = [f.check, f.rule, f.page, f.viewport || '', f.message, f.allowed?.index ?? ''].join('\u0000');
    const g = groups.get(k) || { ...f, n: 0, examples: [] };
    g.n += f.count && f.check === 'contrast' ? f.count : 1;
    if (f.target && g.examples.length < 2) g.examples.push(f.target);
    groups.set(k, g);
  }
  return [...groups.values()];
}

function table(list, { allowed = false, limit = 40 } = {}) {
  if (!list.length) return '_none_';
  const rows = groupRows(list);
  const head = allowed
    ? ['| Check | Rule | Page | Viewport | Count | Tracked by | Until |', '|---|---|---|---|---|---|---|']
    : ['| Check | Rule | Page | Viewport | Count | Detail |', '|---|---|---|---|---|---|'];
  const body = rows.slice(0, limit).map((g) => allowed
    ? `| ${g.check} | \`${esc(g.rule)}\` | ${esc(g.page)} | ${esc(g.viewport || '—')} | ${g.n} | ${esc(g.allowed.issue)} | ${esc(g.allowed.until)} |`
    : `| ${g.check} | \`${esc(g.rule)}\`${g.impact ? ` (${g.impact})` : ''} | ${esc(g.page)} | ${esc(g.viewport || '—')} | ${g.n} | ${esc(g.message)}${g.examples.length ? `<br>e.g. \`${esc(g.examples[0]).slice(0, 120)}\`` : ''} |`);
  if (rows.length > limit) body.push(`| … | ${rows.length - limit} more row(s) in report.json | | | | |`);
  return [...head, ...body].join('\n');
}

export function themeLabel(t) {
  if (t?.kind === 'live') return 'not built here (url mode scans the deployed site)';
  if (!t || t.kind === 'none') return 'none (the site ships its own layouts)';
  if (t.kind === 'gem') return `gem \`${t.gem}\`${t.version ? ` ${t.version}` : ''} (resolved fresh by bundler)`;
  const sha = t.sha ? `[\`${t.sha.slice(0, 12)}\`](https://github.com/${t.repo}/commit/${t.sha})` : '**unresolved**';
  return `\`${t.repo}@${t.ref}\` → ${sha}${t.cache ? ` (${t.cache})` : ''}`;
}

export function renderSummary(r, { artifact = 'site-quality-report' } = {}) {
  const by = (lvl) => r.findings.filter((f) => f.level === lvl);
  const lines = [
    `## 🚦 site-quality — ${ICON[r.status]}`,
    '',
    `**${r.counts.error} error(s)** · ${r.counts.warn} warning(s) · ${r.counts.allowed} allowlisted · ${r.counts.info} note(s)`,
    '',
    `| | |`, `|---|---|`,
    `| Mode | \`${r.mode}\` |`,
    `| Base | ${r.mode === 'url' ? r.base_url : `local \`_site\` served at ${r.base_url}`} |`,
    `| Theme | ${themeLabel(r.theme)} |`,
    `| Config | \`${r.config}\` (allowlist: ${r.allowlist.entries} entr${r.allowlist.entries === 1 ? 'y' : 'ies'}, expired → ${r.allowlist.on_expired}) |`,
    `| Hub | ${r.hub.repo ? `\`${r.hub.repo}@${(r.hub.sha || '').slice(0, 12)}\`` : '—'} |`,
    '',
    '### ❌ Errors (gating)', table(by('error')), '',
    '### ⚠️ Warnings', table(by('warn')), '',
    '### 🟡 Allowlisted known issues', table(by('allowed'), { allowed: true }), '',
  ];
  if (by('info').length) lines.push('<details><summary>ℹ️ Moderate/minor axe notes (never gating)</summary>', '', table(by('info')), '', '</details>', '');
  if (r.allowlist.stale.length) {
    lines.push('### 🧹 Allowlist entries that matched nothing (delete them once the fix has landed)', ...r.allowlist.stale.map((e) => `- #${e.index + 1} \`${e.rule}\`${e.page ? ` on ${e.page}` : ''}${e.selector ? ` (\`${e.selector}\`)` : ''}`), '');
  }
  const lh = r.checks.lighthouse;
  if (lh.ran && lh.scores.length) {
    lines.push('### Lighthouse (median run per page)', '', '| Page | Perf | A11y | BP | SEO | LCP | CLS | TBT | Total KiB |', '|---|---|---|---|---|---|---|---|---|',
      ...lh.scores.map((s) => `| ${s.page}${lh.public_links[s.url] ? ` [report](${lh.public_links[s.url]})` : ''} | ${s.performance} | ${s.accessibility} | ${s['best-practices']} | ${s.seo} | ${s.lcp} | ${s.cls} | ${s.tbt} | ${s.total_kib} |`), '');
  }
  const c = r.checks.contrast;
  if (c.ran && c.rows.length) {
    lines.push('### pa11y contrast (WCAG 1.4.3)', '', '| Page | Failures | Gate |', '|---|---|---|',
      ...c.rows.map((x) => `| ${x.path} | ${x.error ? 'error' : x.count} | ${x.error ? `❌ ${esc(x.error)}` : typeof x.max === 'number' ? (x.over ? `❌ > ${x.max}` : `✅ ≤ ${x.max}`) : 'report-only'} |`), '');
  }
  lines.push(`Full reports (Lighthouse HTML/JSON, axe, pa11y, \`report.json\`): the \`${artifact}\` artifact.`, '');
  return lines.join('\n');
}
