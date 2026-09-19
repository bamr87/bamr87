// Live signals (specs/014-harness-parity, FR-3): the hub's four signal shapes, built from a
// Fleet Ops scan instead of the hub's committed files, so the same `harnessHealth()` runs
// over a live fleet. Only `actions_usage` and `fleet_triage` can be derived from a scan;
// `issue_pipeline` and `token_rotation` are the hub's own loops and report as missing —
// exactly what the hub's generator would say if those files were absent. Pure.

import type { FactoryRun } from '../github/types.js';
import type { MetricsRollup } from '../fleet/types.js';
import type { ActionsUsage, FleetTriage, HarnessSignals, UsageWorkflow } from './health.js';
import { stampUtc } from './health.js';

/** The slice of a Fleet Ops metrics row the adapter needs (`FleetWorkflowMetrics` fits). */
export interface LiveWorkflowMetrics {
  repo: string;
  displayPath: string;
  name: string;
  runs: number;
  avgMin: number;
  success: number;
}

/** The slice of a scanned repo the adapter needs (`RepoSnapshot` fits). */
export interface LiveRepo {
  slug: string;
  status: 'idle' | 'loading' | 'ready' | 'error';
  runs: FactoryRun[];
}

export interface LiveScan {
  /** Fleet-wide rollup (Fleet Ops' `fleetMetrics` rollup). */
  rollup: MetricsRollup | null;
  workflows: LiveWorkflowMetrics[];
  repos: LiveRepo[];
  /** When the scan finished; becomes every signal's `generated_at`. */
  scannedAt: Date;
}

const round1 = (x: number): number => Math.round(x * 10) / 10;

/** The hub's `actions_usage.yml` totals + per-workflow rows, from a live scan. */
export function liveActionsUsage(scan: LiveScan): ActionsUsage | null {
  if (!scan.rollup) return null;
  const r = scan.rollup;
  const workflows: UsageWorkflow[] = scan.workflows.map((w) => ({
    repo: w.repo.split('/').pop() ?? w.repo,
    workflow: w.name,
    path: w.displayPath,
    avg_min: round1(w.avgMin),
    runs: w.runs,
    success: w.success,
    external: false,
  }));
  return {
    generated_at: stampUtc(scan.scannedAt),
    totals: {
      success_rate_pct: round1(r.successRatePct),
      effectiveness_pct: round1(r.effectivenessPct),
      total_min: round1(r.totalMin),
      waste_min: round1(r.wasteMin),
      waste_hours: round1(r.wasteMin / 60),
    },
    workflows,
  };
}

/** Newest run per workflow path, per repo. */
function latestByPath(runs: FactoryRun[]): Map<string, FactoryRun> {
  const m = new Map<string, FactoryRun>();
  for (const run of runs) {
    const cur = m.get(run.path);
    if (!cur || run.createdAt > cur.createdAt) m.set(run.path, run);
  }
  return m;
}

/** The hub's `fleet_triage.yml` totals the scorecard reads: standing red workflows and red repos. */
export function liveFleetTriage(scan: LiveScan): FleetTriage | null {
  const ready = scan.repos.filter((r) => r.status === 'ready');
  if (!ready.length) return null;
  let failing = 0;
  let reposRed = 0;
  for (const repo of ready) {
    let red = 0;
    for (const run of latestByPath(repo.runs).values()) {
      if (run.status === 'completed' && run.conclusion === 'failure') red += 1;
    }
    failing += red;
    if (red > 0) reposRed += 1;
  }
  return {
    generated_at: stampUtc(scan.scannedAt),
    totals: { failing_workflows: failing, repos_red: reposRed },
  };
}

/** All four signals from a live scan; the hub-only loops are honestly absent. */
export function liveSignals(scan: LiveScan): HarnessSignals {
  return {
    actions_usage: liveActionsUsage(scan),
    fleet_triage: liveFleetTriage(scan),
    issue_pipeline: null,
    token_rotation: null,
  };
}
