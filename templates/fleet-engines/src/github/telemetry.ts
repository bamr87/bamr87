// Pure telemetry mapping + stats (seed 04).
// NO network I/O: this consumes already-fetched FactoryRun[] (from the transport client's
// listFactoryRuns) and derives LED states + dashboard/per-line statistics. Keeping it pure
// keeps it deterministic and trivially testable — same rules as the compiler and the deploy
// planner (CLAUDE.md golden rule #3).
//
// Everything here parses fixed ISO strings only; no Date.now()/new Date() (argless) so the
// same input always yields the same output.

import type { FactoryRun, LedState, RunConclusion } from './types.js';

/** Conclusions that light a machine/line LED red (ARCHITECTURE §6): a run that failed to succeed. */
const BAD_CONCLUSIONS: ReadonlySet<RunConclusion> = new Set<RunConclusion>([
  'failure',
  'timed_out',
  'startup_failure',
  'stale',
]);

/**
 * Conclusions counted as a hard failure in aggregate stats. Narrower than {@link BAD_CONCLUSIONS}:
 * `stale` glows red on a LED but is not a run-the-numbers failure (it never really executed).
 */
const FAILURE_CONCLUSIONS: ReadonlySet<RunConclusion> = new Set<RunConclusion>([
  'failure',
  'timed_out',
  'startup_failure',
]);

/**
 * Map a single run (or its absence) to a LED colour.
 * - no run yet → `idle`
 * - still queued/in progress → `warn`
 * - completed successfully → `on`
 * - completed with a failing conclusion → `bad`
 * - completed but cancelled/skipped/neutral/action_required/unknown → `idle`
 */
export function ledForRun(run: FactoryRun | undefined): LedState {
  if (!run) return 'idle';
  if (run.status !== 'completed') return 'warn';
  if (run.conclusion === 'success') return 'on';
  if (BAD_CONCLUSIONS.has(run.conclusion)) return 'bad';
  return 'idle';
}

/** True when `a` is newer than `b`: later createdAt, tie-broken by larger runId. */
function isNewer(a: FactoryRun, b: FactoryRun): boolean {
  if (a.createdAt !== b.createdAt) return a.createdAt > b.createdAt;
  return a.runId > b.runId;
}

/**
 * The newest run per assembly-line slug. "Newest" = max ISO `createdAt` (lexical compare is
 * correct for well-formed UTC timestamps), tie-broken by the larger `runId`. Deterministic.
 */
export function latestBySlug(runs: FactoryRun[]): Map<string, FactoryRun> {
  const latest = new Map<string, FactoryRun>();
  for (const run of runs) {
    const current = latest.get(run.slug);
    if (!current || isNewer(run, current)) latest.set(run.slug, run);
  }
  return latest;
}

/** The LED colour for each line's latest run. */
export function statusBySlug(runs: FactoryRun[]): Map<string, LedState> {
  const statuses = new Map<string, LedState>();
  for (const [slug, run] of latestBySlug(runs)) statuses.set(slug, ledForRun(run));
  return statuses;
}

/**
 * Wall-clock seconds a run took: `updatedAt - (runStartedAt ?? createdAt)`, clamped to `>= 0`
 * (a run whose start stamp lands after its update stamp reports 0 rather than a negative). Parses
 * fixed ISO strings only.
 */
function durationSec(run: FactoryRun): number {
  const start = Date.parse(run.runStartedAt ?? run.createdAt);
  const end = Date.parse(run.updatedAt);
  return Math.max(0, (end - start) / 1000);
}

/** The p50 (median) of a set of numbers, or null if empty. Even counts average the two middles. */
function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 1 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

/** Success rate (0..1, or null with no completed runs) + p50 duration over a run group's completed runs. */
function rateAndP50(runs: FactoryRun[]): { successRate: number | null; p50DurationSec: number | null } {
  const completed = runs.filter((r) => r.status === 'completed');
  const success = completed.filter((r) => r.conclusion === 'success').length;
  return {
    successRate: completed.length ? success / completed.length : null,
    p50DurationSec: median(completed.map(durationSec)),
  };
}

/** Top-of-dashboard rollup across every polled run. */
export interface DashboardStats {
  total: number;
  completed: number;
  success: number;
  failure: number;
  inProgress: number;
  /** success / completed, in 0..1, or null when nothing has completed yet. */
  successRate: number | null;
  /** Median completed-run duration in seconds, or null when nothing has completed. */
  p50DurationSec: number | null;
}

/** Aggregate stats across all runs. Pure; counts derive from the run `status`/`conclusion` fields. */
export function dashboardStats(runs: FactoryRun[]): DashboardStats {
  const completedRuns = runs.filter((r) => r.status === 'completed');
  const success = completedRuns.filter((r) => r.conclusion === 'success').length;
  const failure = completedRuns.filter((r) => FAILURE_CONCLUSIONS.has(r.conclusion)).length;
  const inProgress = runs.filter((r) => r.status !== 'completed').length;
  const { successRate, p50DurationSec } = rateAndP50(runs);
  return {
    total: runs.length,
    completed: completedRuns.length,
    success,
    failure,
    inProgress,
    successRate,
    p50DurationSec,
  };
}

/** Per-assembly-line rollup row. */
export interface LineStat {
  slug: string;
  total: number;
  successRate: number | null;
  p50DurationSec: number | null;
}

/** One {@link LineStat} per slug, sorted by slug ascending. Pure and deterministic. */
export function statsByLine(runs: FactoryRun[]): LineStat[] {
  const groups = new Map<string, FactoryRun[]>();
  for (const run of runs) {
    const group = groups.get(run.slug);
    if (group) group.push(run);
    else groups.set(run.slug, [run]);
  }

  const rows: LineStat[] = [];
  for (const [slug, groupRuns] of groups) {
    const { successRate, p50DurationSec } = rateAndP50(groupRuns);
    rows.push({ slug, total: groupRuns.length, successRate, p50DurationSec });
  }
  rows.sort((a, b) => (a.slug < b.slug ? -1 : a.slug > b.slug ? 1 : 0));
  return rows;
}
