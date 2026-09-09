// The `fleet/v1` lane — the fleet's interchange contract. Every fleet repo commits a
// `fleet.manifest.yml` in this vocabulary (bamr87/wtd's FLEET-SPEC; `wtd fleet adopt`
// derives it, the hub and its consoles read it), so a lane designed in one tool and
// inventoried in another is the same record. `parseFleetManifest` reads any repo's manifest
// tolerantly; the blueprint → lanes direction lives with GitFactory's compiler, not here.
// Pure; manifest text is untrusted data.

import { parse as parseYaml } from 'yaml';

export type LaneKind =
  | 'content'
  | 'triage'
  | 'review'
  | 'maintenance'
  | 'analysis'
  | 'orchestrator'
  | 'fanout'
  | 'mention'
  | 'other';
export const LANE_KINDS: LaneKind[] = [
  'content',
  'triage',
  'review',
  'maintenance',
  'analysis',
  'orchestrator',
  'fanout',
  'mention',
  'other',
];

export type LaneHarness = 'claude-code-action' | 'claude-cli' | 'wtd-fleet' | 'engine' | 'none';
export const LANE_HARNESSES: LaneHarness[] = ['claude-code-action', 'claude-cli', 'wtd-fleet', 'engine', 'none'];

export type LaneTrigger =
  | { kind: 'schedule'; cron: string }
  | { kind: 'dispatch' }
  | { kind: 'event'; events: string[] };

export interface LaneGuardrails {
  never_merges: boolean;
  opens_pull_requests?: boolean;
  writable_paths?: string[];
  max_writes_per_run?: number;
}

export interface FleetLane {
  id: string;
  kind: LaneKind;
  harness: LaneHarness;
  implementation: string;
  description: string;
  triggers: LaneTrigger[];
  /** The repo variable that switches the lane, or null. */
  switch: string | null;
  uses_tokens: string[];
  guardrails: LaneGuardrails;
  state_paths?: string[];
}

export interface FleetManifest {
  spec_version: string;
  repo: string;
  provenance: 'declared' | 'derived' | 'unknown';
  summary: string;
  lanes: FleetLane[];
  /** Lines the parser could not read as lanes (kept as counts, never as content). */
  skipped: number;
}

// ── manifest → lanes ────────────────────────────────────────────────────────

const isRecord = (v: unknown): v is Record<string, unknown> =>
  !!v && typeof v === 'object' && !Array.isArray(v);
const strList = (v: unknown): string[] =>
  Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [];

function laneFrom(v: unknown): FleetLane | null {
  if (!isRecord(v) || typeof v.id !== 'string' || !v.id.trim()) return null;
  const kind = LANE_KINDS.includes(v.kind as LaneKind) ? (v.kind as LaneKind) : 'other';
  const harness = LANE_HARNESSES.includes(v.harness as LaneHarness)
    ? (v.harness as LaneHarness)
    : 'none';
  const triggers: LaneTrigger[] = [];
  for (const t of Array.isArray(v.triggers) ? v.triggers : []) {
    if (!isRecord(t)) continue;
    if (t.kind === 'schedule' && typeof t.cron === 'string') triggers.push({ kind: 'schedule', cron: t.cron });
    else if (t.kind === 'dispatch') triggers.push({ kind: 'dispatch' });
    else if (t.kind === 'event') triggers.push({ kind: 'event', events: strList(t.events) });
  }
  const g = isRecord(v.guardrails) ? v.guardrails : {};
  const guardrails: LaneGuardrails = { never_merges: g.never_merges !== false };
  if (typeof g.opens_pull_requests === 'boolean') guardrails.opens_pull_requests = g.opens_pull_requests;
  if (Array.isArray(g.writable_paths)) guardrails.writable_paths = strList(g.writable_paths);
  if (typeof g.max_writes_per_run === 'number') guardrails.max_writes_per_run = g.max_writes_per_run;
  return {
    id: v.id.trim(),
    kind,
    harness,
    implementation: typeof v.implementation === 'string' ? v.implementation : '',
    description: typeof v.description === 'string' ? v.description : v.id.trim(),
    triggers,
    switch: typeof v.switch === 'string' && v.switch.trim() ? v.switch.trim() : null,
    uses_tokens: strList(v.uses_tokens).sort(),
    guardrails,
    ...(Array.isArray(v.state_paths) ? { state_paths: strList(v.state_paths) } : {}),
  };
}

/** Parse a `fleet.manifest.yml`. Never throws: junk yields an empty manifest with `skipped`. */
export function parseFleetManifest(text: string): FleetManifest {
  let doc: unknown = null;
  try {
    doc = parseYaml(text);
  } catch {
    doc = null;
  }
  const root = isRecord(doc) ? doc : {};
  const rawLanes = Array.isArray(root.lanes) ? root.lanes : [];
  const lanes = rawLanes.map(laneFrom).filter((l): l is FleetLane => !!l);
  const provenance =
    root.provenance === 'declared' || root.provenance === 'derived' ? root.provenance : 'unknown';
  return {
    spec_version: typeof root.spec_version === 'string' ? root.spec_version : '',
    repo: typeof root.repo === 'string' ? root.repo : '',
    provenance,
    summary: typeof root.summary === 'string' ? root.summary : '',
    lanes,
    skipped: rawLanes.length - lanes.length,
  };
}

/** The lane whose implementation is this workflow path, or whose id is its basename. */
export function laneForPath(manifest: FleetManifest | null, path: string): FleetLane | null {
  if (!manifest) return null;
  const base = path.split('/').pop()?.replace(/\.ya?ml$/i, '') ?? path;
  return (
    manifest.lanes.find((l) => l.implementation === path) ??
    manifest.lanes.find((l) => l.id === base) ??
    null
  );
}
