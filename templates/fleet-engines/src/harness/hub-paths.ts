// What the hub commits and a console reads — the paths, the Pages URLs, and the snapshot
// shape a hub read produces. Pure constants and types; the store that persists a hub slug
// stays in each consumer (GitFactory keeps its zustand store, an editor keeps its settings).

import { parseRepo } from '../github/types.js';
import type { HarnessConfig, HarnessHealth, HarnessSignals, SignalName } from './health.js';
import type { FleetManifest } from './lanes.js';

export const DEFAULT_HUB = 'bamr87/bamr87';

/** What the hub commits and its consoles read. */
export const HUB_PATHS = {
  config: '_data/fleet.yml',
  health: '_data/harness_health.yml',
  manifest: 'fleet.manifest.yml',
  pulse: '.github/workflows/fleet-pulse.yml',
} as const;
export const signalPath = (name: SignalName): string => `_data/${name}.yml`;

/** The hub's five archify diagrams, as its /harness/ page lists them. */
export const HUB_DIAGRAMS: { file: string; title: string }[] = [
  { file: 'harness-layers.architecture', title: 'The six layers, mapped onto the hub' },
  { file: 'fleet-pulse.workflow', title: 'fleet-pulse.yml — the daily loop' },
  { file: 'fleet-signals.dataflow', title: 'Fleet signals — from GitHub to the alarm panel' },
  { file: 'issue-pipeline.lifecycle', title: 'issue-pipeline.yml — labels as state' },
  {
    file: 'repo-evolution.sequence',
    title: 'repo-evolution.yml — a draft PR into a submodule’s own upstream',
  },
];

/** The hub's Pages URL for a path (`/harness/` by default); a user site drops the repo segment. */
export function hubPagesUrl(slug: string, path = '/harness/'): string | null {
  const ref = parseRepo(slug);
  if (!ref) return null;
  const site = `${ref.owner.toLowerCase()}.github.io`;
  const base = ref.repo.toLowerCase() === site ? `https://${site}` : `https://${site}/${ref.repo}`;
  return `${base}${path.startsWith('/') ? path : `/${path}`}`;
}
export const hubDiagramUrl = (slug: string, file: string): string | null =>
  hubPagesUrl(slug, `/diagrams/${file}.html`);
export const hubFileUrl = (slug: string, path: string): string =>
  `https://github.com/${slug}/blob/main/${path}`;

/** Where a committed health file and an in-app recomputation disagree. */
export interface ParityDiff {
  where: string;
  committed: string;
  recomputed: string;
}

/** One hub read: what was committed, the same engine re-run over the committed signals, the diff. */
export interface HubSnapshot {
  slug: string;
  fetchedAt: string;
  /** The hub's `_data/fleet.yml` → `harness:` thresholds (its defaults when the file is absent). */
  config: HarnessConfig;
  /** The health file the hub committed, or null when it has not published one. */
  committed: HarnessHealth | null;
  /** The same engine run over the hub's committed signals, at the committed stamp. */
  recomputed: HarnessHealth;
  /** Where the committed file and the recomputation disagree (empty = parity). */
  parity: ParityDiff[];
  signals: HarnessSignals;
  /** Which hub files were found, by path. */
  found: Record<string, boolean>;
  manifest: FleetManifest | null;
  /** The fleet-pulse cron (the hub's daily loop), when its workflow file was readable. */
  pulseCron: string | null;
}
