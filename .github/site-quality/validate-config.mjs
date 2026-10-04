#!/usr/bin/env node
// =============================================================================
// validate-config.mjs — validate the caller's config against the JSON Schema,
// resolve every default, and hand the build/serve settings to the workflow.
// -----------------------------------------------------------------------------
// Usage: node validate-config.mjs --config <file> --schema <file> --out <json>
//          [--mode build|url] [--base-url URL] [--source DIR]
//          [--build-command CMD] [--expired-level warn|error]
// Exit 1 on a missing/invalid config (the one failure a default run can have:
// a config the workflow cannot read is a caller bug, not a site finding).
// Expired allowlist entries are annotated here and graded by report.mjs.
// =============================================================================
import { existsSync, readFileSync, writeFileSync, appendFileSync } from 'node:fs';
import { parseArgs } from 'node:util';
import { parseConfig, loadSchema, validate, resolve, expiredEntries } from './lib/config.mjs';

const { values: a } = parseArgs({
  options: {
    config: { type: 'string' }, schema: { type: 'string' }, out: { type: 'string' },
    mode: { type: 'string', default: 'build' }, 'base-url': { type: 'string', default: '' },
    source: { type: 'string', default: '' }, 'build-command': { type: 'string' },
    'expired-level': { type: 'string', default: '' },
  },
});

const fail = (msg) => { console.log(`::error title=site-quality config::${msg.replace(/\r?\n/g, '%0A')}`); process.exit(1); };

if (!['build', 'url'].includes(a.mode)) fail(`mode must be build or url (got "${a.mode}")`);
if (a['expired-level'] && !['warn', 'error'].includes(a['expired-level'])) fail(`expired-allowlist-level must be warn or error (got "${a['expired-level']}")`);
if (!a.config || !existsSync(a.config)) fail(`config not found: ${a.config} — copy templates/site-quality/site-quality.template.yml from bamr87/bamr87 to .github/site-quality.yml`);

let raw;
try { raw = parseConfig(readFileSync(a.config, 'utf8')); } catch (e) { fail(`${a.config} is not valid YAML: ${e.message}`); }
const errors = validate(raw, loadSchema(a.schema));
if (errors.length) fail(`${a.config} does not match site-quality.schema.json:\n- ${errors.join('\n- ')}`);

const cfg = resolve(raw, {
  mode: a.mode,
  baseUrl: a['base-url'],
  source: a.source,
  buildCommand: a['build-command'] || undefined,
  expiredLevel: a['expired-level'],
});
if (cfg.mode === 'url' && !/^https?:\/\//.test(cfg.site.base_url)) fail('url mode needs a base URL: set site.base_url in the config or pass the `base-url` input');

const expired = expiredEntries(raw);
for (const e of expired) {
  const lvl = cfg.allowlist.on_expired === 'error' ? 'error' : 'warning';
  console.log(`::${lvl} title=site-quality allowlist expired::allowlist entry #${e.index + 1} (${e.rule}${e.page ? ` on ${e.page}` : ''}) expired on ${e.until} — ${e.issue}`);
}

writeFileSync(a.out, JSON.stringify(cfg, null, 2));
console.log(`config OK: ${a.config} (${cfg.schema}, mode ${cfg.mode}, ${cfg.pages.length} page(s), ${cfg.allowlist.entries.length} allowlist entr${cfg.allowlist.entries.length === 1 ? 'y' : 'ies'}, ${expired.length} expired)`);

if (process.env.GITHUB_OUTPUT) {
  const eof = `EOF_${Math.random().toString(36).slice(2)}`;
  appendFileSync(process.env.GITHUB_OUTPUT, [
    `source=${cfg.site.source}`,
    `site_dir=${cfg.site.site_dir}`,
    `base_url=${cfg.site.base_url}`,
    `build_command<<${eof}`, cfg.site.build_command, eof,
    `lighthouse=${cfg.lighthouse.enabled}`,
    `axe=${cfg.axe.enabled}`,
    `contrast=${cfg.contrast.enabled}`,
    `public_upload=${cfg.lighthouse.public_upload}`,
    '',
  ].join('\n'));
}
