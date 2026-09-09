// The fleet/v1 manifest as text: a `fleet.manifest.yml` document for a set of lanes, and the
// small deterministic YAML emitter behind it. Kept apart from lanes.ts so a reader that only
// parses does not carry the emitter.

import type { FleetLane } from './lanes.js';

export interface ManifestMeta {
  repo: string;
  summary: string;
  provenance?: 'declared' | 'derived';
  /** Comment lines (without `# `) written above the document. */
  header?: string[];
}

/** A `fleet.manifest.yml` document for a set of lanes (lanes + the token contract), as text. */
export function toFleetManifestYaml(lanes: FleetLane[], meta: ManifestMeta): string {
  const { repo } = meta;
  const tokens = [...new Set(lanes.flatMap((l) => l.uses_tokens))].sort();
  const doc = {
    spec_version: 'fleet/v1',
    repo,
    provenance: meta.provenance ?? 'derived',
    summary: meta.summary,
    lanes,
    tokens: tokens.map((name) => ({
      name,
      scope: 'fleet',
      required: name === 'CLAUDE_CODE_OAUTH_TOKEN',
      purpose: TOKEN_PURPOSE[name] ?? 'Declared by a machine on the floor.',
      used_by: lanes.filter((l) => l.uses_tokens.includes(name)).map((l) => l.id),
    })),
  };
  const header = meta.header ?? ["fleet.manifest.yml — this repository's AI fleet, in the shared 'fleet/v1' vocabulary."];
  return `${header.map((h) => `# ${h}\n`).join('')}${yamlDump(doc)}`;
}

const TOKEN_PURPOSE: Record<string, string> = {
  CLAUDE_CODE_OAUTH_TOKEN:
    'Preferred Claude auth (house convention: OAuth first). Produced by `claude setup-token`.',
  ANTHROPIC_API_KEY: 'Fallback Claude auth, used only when the OAuth token is absent.',
  FLEET_TOKEN: 'Fine-grained PAT for cross-repo writes.',
};

/** A small, deterministic YAML emitter for the manifest (block style, quoted where needed). */
export function yamlDump(value: unknown, indent = 0): string {
  const pad = '  '.repeat(indent);
  if (Array.isArray(value)) {
    if (!value.length) return `${pad}[]\n`;
    return value
      .map((item) => {
        if (item && typeof item === 'object') {
          const body = yamlDump(item, indent + 1).replace(/^\s*/, '');
          return `${pad}- ${body}`;
        }
        return `${pad}- ${scalar(item)}\n`;
      })
      .join('');
  }
  if (value && typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>)
      .map(([k, v]) => {
        if (v && typeof v === 'object') {
          if (Array.isArray(v) && !v.length) return `${pad}${k}: []\n`;
          return `${pad}${k}:\n${yamlDump(v, indent + 1)}`;
        }
        return `${pad}${k}: ${scalar(v)}\n`;
      })
      .join('');
  }
  return `${pad}${scalar(value)}\n`;
}

function scalar(v: unknown): string {
  if (v === null || v === undefined) return 'null';
  if (typeof v === 'boolean' || typeof v === 'number') return String(v);
  const s = String(v);
  return /^[A-Za-z0-9_./@-][A-Za-z0-9_./@ -]*$/.test(s) && !/^(true|false|null|yes|no)$/i.test(s)
    ? s
    : JSON.stringify(s);
}
