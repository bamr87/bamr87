// Observe-mode I/O: fetch a repo's .github/workflows/*.yml and reverse-import them into a
// read-only Fleet. Pairs with the pure parsers in parse.ts/facts.ts. Never writes to the repo.
// Since specs/014 the same pass reads the repo's committed `fleet.manifest.yml` — the hub's
// `fleet/v1` interchange contract — and pins each recorded lane to its workflow.

import type { GithubClient, RepoRef } from '../github/types.js';
import { parseFleetManifest, type FleetManifest } from '../harness/lanes.js';
import { extractFacts } from './facts.js';
import { buildFleet, parseWorkflow } from './parse.js';
import type { Fleet, ImportedWorkflow, WorkflowFacts } from './types.js';

const WORKFLOW_DIR = '.github/workflows';
export const MANIFEST_PATH = 'fleet.manifest.yml';

/** Fetch each workflow file once; returns `{path, text}` pairs (missing files skipped). */
async function fetchWorkflowTexts(
  client: GithubClient,
  repo: RepoRef,
): Promise<{ path: string; text: string }[]> {
  const entries = await client.listDir(repo, WORKFLOW_DIR);
  const files = entries.filter((e) => e.type === 'file' && /\.ya?ml$/.test(e.name));
  const fetched = await Promise.all(
    files.map(async (e) => {
      const file = await client.getFile(repo, e.path);
      return file ? { path: e.path, text: file.content } : null;
    }),
  );
  return fetched.filter((f): f is { path: string; text: string } => f !== null);
}

/** The repo's committed manifest, or null — a missing or unreadable file never fails an import. */
export async function fetchFleetManifest(
  client: GithubClient,
  repo: RepoRef,
): Promise<FleetManifest | null> {
  try {
    const file = await client.getFile(repo, MANIFEST_PATH);
    if (!file) return null;
    const manifest = parseFleetManifest(file.content);
    return manifest.lanes.length > 0 || manifest.spec_version ? manifest : null;
  } catch {
    return null;
  }
}

/** Pin each recorded lane to its workflow (by implementation path, else by id = basename). */
export function attachLanes(fleet: Fleet, manifest: FleetManifest | null): Fleet {
  fleet.manifest = manifest;
  if (!manifest) return fleet;
  for (const w of fleet.workflows) {
    const lane =
      manifest.lanes.find((l) => l.implementation === w.path) ??
      manifest.lanes.find((l) => l.id === w.slug) ??
      null;
    if (lane) w.lane = lane;
  }
  return fleet;
}

export async function importFleet(client: GithubClient, repo: RepoRef): Promise<Fleet> {
  const [texts, manifest] = await Promise.all([
    fetchWorkflowTexts(client, repo),
    fetchFleetManifest(client, repo),
  ]);
  const parsed: ImportedWorkflow[] = texts.map((f) => parseWorkflow(f.path, f.text));
  const fleet = attachLanes(buildFleet(repo, parsed), manifest);
  if (texts.length === 0) {
    fleet.warnings.push('No workflows found under .github/workflows/ — nothing to observe.');
  }
  return fleet;
}

/**
 * Fleet Ops import: one fetch pass, both parsers — the observe graph (Fleet) plus the
 * deep per-workflow facts the audit/metrics engines consume. Each file is read once.
 */
export async function importFleetDeep(
  client: GithubClient,
  repo: RepoRef,
): Promise<{ fleet: Fleet; facts: WorkflowFacts[] }> {
  const [texts, manifest] = await Promise.all([
    fetchWorkflowTexts(client, repo),
    fetchFleetManifest(client, repo),
  ]);
  const parsed: ImportedWorkflow[] = texts.map((f) => parseWorkflow(f.path, f.text));
  const fleet = attachLanes(buildFleet(repo, parsed), manifest);
  if (texts.length === 0) {
    fleet.warnings.push('No workflows found under .github/workflows/ — nothing to observe.');
  }
  return { fleet, facts: texts.map((f) => extractFacts(f.path, f.text)) };
}
