// The hub reader: eight tolerant reads through an injected GithubClient, the committed
// harness_health.yml read back, the same engine re-run over the committed signals, and a
// parity diff. I/O only through the client; no globals, no clock.

import { parse as parseYaml } from 'yaml';
import { repoSlug, type GithubClient, type RepoRef } from '../github/types.js';
import { HUB_PATHS, signalPath, type HubSnapshot, type ParityDiff } from './hub-paths.js';
import {
  DEFAULT_CONFIG,
  harnessHealth,
  parseGeneratedAt,
  parseHarnessConfig,
  SCORECARD_KEYS,
  SIGNAL_NAMES,
  toActionsUsage,
  toFleetTriage,
  toHarnessHealth,
  toIssuePipeline,
  toTokenRotation,
  type HarnessHealth,
  type HarnessSignals,
} from './health.js';
import { parseFleetManifest } from './lanes.js';

/** Where a committed health file and an in-app recomputation disagree. */
export function compareHealth(committed: HarnessHealth, recomputed: HarnessHealth): ParityDiff[] {
  const diffs: ParityDiff[] = [];
  const show = (v: unknown): string => (v === null || v === undefined ? 'None' : String(v));
  for (const k of SCORECARD_KEYS) {
    const a = committed.scorecard[k];
    const b = recomputed.scorecard[k];
    if (show(a.value) !== show(b.value)) {
      diffs.push({ where: `scorecard.${k}.value`, committed: show(a.value), recomputed: show(b.value) });
    }
    if ((a.status ?? 'unknown') !== (b.status ?? 'unknown')) {
      diffs.push({
        where: `scorecard.${k}.status`,
        committed: a.status ?? 'unknown',
        recomputed: b.status ?? 'unknown',
      });
    }
  }
  for (const w of recomputed.trip_wires) {
    const c = committed.trip_wires.find((x) => x.id === w.id);
    if (!c) {
      diffs.push({ where: `trip_wires.${w.id}`, committed: 'absent', recomputed: w.tripped ? 'tripped' : 'armed' });
    } else if (c.tripped !== w.tripped) {
      diffs.push({ where: `trip_wires.${w.id}.tripped`, committed: String(c.tripped), recomputed: String(w.tripped) });
    } else if (c.summary !== w.summary) {
      diffs.push({ where: `trip_wires.${w.id}.summary`, committed: c.summary, recomputed: w.summary });
    }
  }
  return diffs;
}

const CRON_RE = /cron:\s*(?:'([^']*)'|"([^"]*)"|([^#\n]+))/;

/** Read a hub through a client: every file tolerant (missing or unreadable → absent), never throws for a file. */
export async function readHub(
  client: GithubClient,
  ref: RepoRef,
  now: Date = new Date(),
): Promise<HubSnapshot> {
  const read = async (path: string): Promise<string | null> => {
    try {
      const f = await client.getFile(ref, path);
      return f ? f.content : null;
    } catch {
      return null;
    }
  };
  const doc = (text: string | null): unknown => {
    if (text === null) return null;
    try {
      return parseYaml(text);
    } catch {
      return null;
    }
  };
  const paths = [
    HUB_PATHS.config,
    HUB_PATHS.health,
    HUB_PATHS.manifest,
    HUB_PATHS.pulse,
    ...SIGNAL_NAMES.map(signalPath),
  ];
  const texts = await Promise.all(paths.map(read));
  const byPath = new Map(paths.map((p, i) => [p, texts[i]] as const));
  const text = (p: string): string | null => byPath.get(p) ?? null;
  const found = Object.fromEntries(paths.map((p) => [p, text(p) !== null]));

  const configDoc = doc(text(HUB_PATHS.config));
  const config = configDoc ? parseHarnessConfig(configDoc) : DEFAULT_CONFIG;
  const signals: HarnessSignals = {
    actions_usage: toActionsUsage(doc(text(signalPath('actions_usage')))),
    fleet_triage: toFleetTriage(doc(text(signalPath('fleet_triage')))),
    issue_pipeline: toIssuePipeline(doc(text(signalPath('issue_pipeline')))),
    token_rotation: toTokenRotation(doc(text(signalPath('token_rotation')))),
  };
  const committed = toHarnessHealth(doc(text(HUB_PATHS.health)));
  const stamp = committed ? parseGeneratedAt(committed.generated_at) : null;
  const recomputed = harnessHealth(signals, config, stamp ?? now);
  const manifestText = text(HUB_PATHS.manifest);
  const manifest = manifestText ? parseFleetManifest(manifestText) : null;
  const pulse = text(HUB_PATHS.pulse);
  const cron = pulse ? CRON_RE.exec(pulse) : null;
  return {
    slug: repoSlug(ref),
    fetchedAt: now.toISOString(),
    config,
    committed,
    recomputed,
    parity: committed ? compareHealth(committed, recomputed) : [],
    signals,
    found,
    manifest,
    pulseCron: cron ? (cron[1] ?? cron[2] ?? cron[3] ?? '').trim() || null : null,
  };
}
