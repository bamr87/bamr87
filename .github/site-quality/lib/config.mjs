// =============================================================================
// lib/config.mjs — load, validate and resolve a site-quality config
// -----------------------------------------------------------------------------
// The caller's .github/site-quality.yml is parsed as YAML 1.1 on purpose: an
// unquoted `until: 2026-12-31` then becomes a timestamp, not a string, and the
// schema rejects it, so dates are always quoted (the sdlc.yml convention).
// Validation uses the JSON Schema in templates/site-quality/ (2020-12, ajv).
// resolve() fills every default, and the defaults only REPORT: nothing here
// can turn a run red unless the caller's config asks for it (#314 bump rules).
// =============================================================================
import { readFileSync } from 'node:fs';
import { parse } from 'yaml';
import Ajv2020 from 'ajv/dist/2020.js';
import addFormats from 'ajv-formats';

export const DEFAULT_VIEWPORTS = [
  { name: 'mobile-390', width: 390, height: 844, mobile: true },
  { name: 'desktop-1366', width: 1366, height: 768, mobile: false },
];
/** The one config format id this runtime reads (the schema's `schema` const). */
export const CONFIG_SCHEMA = 'site-quality/v1';
export const DEFAULT_AXE_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22a', 'wcag22aa'];

/** Parse YAML text with the 1.1 schema (timestamps stay timestamps). Throws on syntax errors. */
export function parseConfig(text) {
  const doc = parse(text, { version: '1.1', prettyErrors: true });
  // yaml 1.1 parses `2026-12-31` into a Date — the schema's `type: string`
  // rejects it, which is the point. JSON-ify nothing else.
  return doc ?? {};
}

export function loadSchema(path) {
  return JSON.parse(readFileSync(path, 'utf8'));
}

/** Validate a parsed config. Returns a list of human-readable errors (empty = valid). */
export function validate(config, schema) {
  // A pre-release draft used `version: 1`; say exactly what replaces it.
  if (config && typeof config === 'object' && 'version' in config && !('schema' in config)) {
    return [`(root): \`version\` is not a key; the first line is \`schema: ${CONFIG_SCHEMA}\` (the .github/sdlc.yml convention)`];
  }
  const ajv = new Ajv2020({ allErrors: true, strict: false });
  addFormats(ajv);
  const check = ajv.compile(schema);
  if (check(config)) return [];
  return (check.errors || []).map((e) => {
    const where = e.instancePath || '(root)';
    let msg = `${where}: ${e.message}`;
    if (e.params?.allowedValues) msg += ` (${e.params.allowedValues.join(', ')})`;
    if (e.params?.additionalProperty) msg += ` (\`${e.params.additionalProperty}\`)`;
    if (e.keyword === 'type' && e.params?.type === 'string' && /\/until$/.test(where)) {
      msg += ' — quote the date: until: "YYYY-MM-DD"';
    }
    return msg;
  });
}

const today = () => new Date().toISOString().slice(0, 10);

/** Allowlist entries whose `until` is before `asOf` (YYYY-MM-DD, default today UTC). */
export function expiredEntries(config, asOf = today()) {
  const entries = config?.allowlist?.entries || [];
  return entries
    .map((e, index) => ({ ...e, index }))
    .filter((e) => typeof e.until === 'string' && e.until < asOf);
}

/**
 * Fill every default. `overrides` carries the workflow inputs that win over the
 * file: { mode, baseUrl, source, buildCommand, expiredLevel }.
 */
export function resolve(config, overrides = {}) {
  const site = config.site || {};
  const pages = config.pages;
  const lh = config.lighthouse || {};
  const axe = config.axe || {};
  const contrast = config.contrast || {};
  const allow = config.allowlist || {};
  const expiredLevel = overrides.expiredLevel || allow.on_expired || 'warn';
  return {
    schema: config.schema,
    mode: overrides.mode || 'build',
    site: {
      source: overrides.source || site.source || '.',
      build_command: overrides.buildCommand ?? site.build_command ?? '',
      site_dir: site.site_dir || '_site',
      base_url: (overrides.baseUrl || site.base_url || '').replace(/\/+$/, ''),
    },
    pages,
    viewports: (config.viewports || DEFAULT_VIEWPORTS).map((v) => ({ mobile: false, ...v })),
    load_errors: config.load_errors || 'warn',
    lighthouse: {
      enabled: lh.enabled !== false,
      pages: lh.pages?.length ? lh.pages : pages.slice(0, 3),
      runs: lh.runs || 1,
      form_factor: lh.form_factor || 'mobile',
      skip_audits: lh.skip_audits || [],
      public_upload: lh.public_upload === true,
      categories: lh.categories || {},
      metrics: lh.metrics || {},
      audits: lh.audits || {},
      sizes: lh.sizes || {},
      overrides: lh.overrides || [],
    },
    axe: {
      enabled: axe.enabled !== false,
      pages: axe.pages?.length ? axe.pages : pages,
      tags: axe.tags || DEFAULT_AXE_TAGS,
      fail_on: axe.fail_on || null,
    },
    contrast: {
      enabled: contrast.enabled !== false,
      pages: contrast.pages?.length ? contrast.pages : [{ path: pages[0] }],
      hide_elements: contrast.hide_elements || '',
      viewport: contrast.viewport || { width: 1366, height: 768 },
    },
    allowlist: {
      on_expired: expiredLevel,
      entries: (allow.entries || []).map((e, index) => ({ ...e, index })),
    },
  };
}

/** Is `page` a pattern covering many pages (`*` or a prefix ending in `*`)? */
export const isWildcardPage = (page) => typeof page === 'string' && page.endsWith('*');

/**
 * Does allowlist entry `e` cover finding `f` ({rule, page, viewport?, matched?: [selector])?
 * `selector` is a CSS selector matched IN THE BROWSER: the collectors (axe-check,
 * contrast-check) record, per node, which allowlist selectors match it or one of
 * its ancestors (`matched`). There is no text or HTML substring fallback.
 * A `*` or prefix page needs a selector (the schema enforces it; this refuses
 * such an entry too, so a hand-built config cannot blanket-allow a rule).
 */
export function entryMatches(e, f) {
  if (e.rule !== f.rule) return false;
  if (isWildcardPage(e.page) && !e.selector) return false;
  if (e.page && e.page !== '*') {
    if (e.page.endsWith('*')) {
      if (!f.page?.startsWith(e.page.slice(0, -1))) return false;
    } else if (e.page !== f.page) return false;
  }
  if (e.viewport && f.viewport && e.viewport !== f.viewport) return false;
  if (e.selector && !(f.matched || []).includes(e.selector)) return false;
  return true;
}
