import { describe, expect, it } from 'vitest';
import { assignFlags, computeWorkflowMetrics, rollup, rollupByType } from './metrics.js';
import type { DashType, WorkflowMetrics } from './types.js';
import type { FactoryRun } from '../github/types.js';

// ── fixtures ────────────────────────────────────────────────────────────

/** The analysis instant every test folds against (default window: 14 days back). */
const NOW = '2026-07-15T00:00:00Z';
const OPTS = { nowIso: NOW };

/** Fixed base inside the window for building deterministic ISO timestamps. */
const BASE_MS = Date.parse('2026-07-10T00:00:00Z');
const at = (offsetSec: number): string => new Date(BASE_MS + offsetSec * 1000).toISOString();

/** Timestamps for a run that started at BASE and ran for `min` wall-clock minutes. */
const dur = (min: number): Pick<FactoryRun, 'createdAt' | 'runStartedAt' | 'updatedAt'> => ({
  createdAt: at(0),
  runStartedAt: at(0),
  updatedAt: at(min * 60),
});

const PATH_A = '.github/workflows/factory--alpha.yml';
const LABELS = new Map<string, { name: string; dashType: DashType }>([
  [PATH_A, { name: 'Alpha Line', dashType: 'ai' }],
]);

let seq = 100;
const nextId = (): number => ++seq;

/** Terse FactoryRun factory: a completed 1-minute success on PATH_A by default. */
function mk(overrides: Partial<FactoryRun> = {}): FactoryRun {
  const runId = overrides.runId ?? nextId();
  return {
    path: PATH_A,
    slug: 'alpha',
    runId,
    runNumber: runId,
    status: 'completed',
    conclusion: 'success',
    event: 'push',
    htmlUrl: `https://github.com/o/r/actions/runs/${runId}`,
    runAttempt: 1,
    ...dur(1),
    ...overrides,
  };
}

/** Terse WorkflowMetrics factory: a healthy workflow that trips no flag by default. */
function mkWm(overrides: Partial<WorkflowMetrics> & { path: string }): WorkflowMetrics {
  return {
    name: overrides.path,
    dashType: 'other',
    runs: 4,
    totalMin: 0,
    avgMin: 0,
    p95Min: 0,
    wasteMin: 0,
    runsPerWeek: 0,
    success: 4,
    failure: 0,
    cancelled: 0,
    other: 0,
    successRatePct: 100,
    effectivenessPct: 100,
    schedPct: 0,
    reworkRuns: 0,
    reworkPct: 0,
    queueP50Sec: null,
    events: {},
    flags: [],
    priority: 0,
    ...overrides,
  };
}

// ── computeWorkflowMetrics ──────────────────────────────────────────────

describe('computeWorkflowMetrics — windowing and totality', () => {
  it('includes a run created exactly at the cutoff, excludes one created just before', () => {
    const cutMs = Date.parse(NOW) - 14 * 86_400_000;
    const cutIso = new Date(cutMs).toISOString();
    const runs = [
      mk({ createdAt: cutIso, runStartedAt: cutIso, updatedAt: new Date(cutMs + 60_000).toISOString() }),
      mk({ createdAt: new Date(cutMs - 1000).toISOString() }),
    ];
    const [wm] = computeWorkflowMetrics(runs, LABELS, OPTS);
    expect(wm.runs).toBe(1);
  });

  it('folds only completed runs; queued/in-progress count in nothing', () => {
    const runs = [
      mk({ conclusion: 'success', ...dur(2) }),
      mk({ status: 'in_progress', conclusion: null }),
      mk({ status: 'queued', conclusion: null }),
    ];
    const [wm] = computeWorkflowMetrics(runs, LABELS, OPTS);
    expect(wm.runs).toBe(1);
    expect(wm.totalMin).toBe(2);
  });

  it('never throws on malformed timestamps — bad runs are skipped, bad nowIso yields []', () => {
    const runs = [mk({ updatedAt: 'not-a-date' }), mk({ createdAt: 'bogus' }), mk({ ...dur(3) })];
    const [wm] = computeWorkflowMetrics(runs, LABELS, OPTS);
    expect(wm.runs).toBe(1);
    expect(wm.totalMin).toBe(3);
    expect(computeWorkflowMetrics(runs, LABELS, { nowIso: 'nonsense' })).toEqual([]);
  });

  it('returns [] for empty input', () => {
    expect(computeWorkflowMetrics([], LABELS, OPTS)).toEqual([]);
  });
});

describe('computeWorkflowMetrics — durations and conclusion folding', () => {
  it('clamps a negative duration to 0 (and 0 total minutes reads as 100% effective)', () => {
    const runs = [mk({ createdAt: at(0), runStartedAt: at(600), updatedAt: at(0) })];
    const [wm] = computeWorkflowMetrics(runs, LABELS, OPTS);
    expect(wm.totalMin).toBe(0);
    expect(wm.avgMin).toBe(0);
    expect(wm.effectivenessPct).toBe(100);
  });

  it('falls back to createdAt when runStartedAt is null', () => {
    const runs = [mk({ createdAt: at(0), runStartedAt: null, updatedAt: at(120) })];
    const [wm] = computeWorkflowMetrics(runs, LABELS, OPTS);
    expect(wm.totalMin).toBe(2);
  });

  it('rounds percentages half-to-even like Python (pct(1,16)=6.25 → 6.2, not 6.3)', () => {
    // 1 success + 15 failures → successRatePct = pct(1,16) = 6.25, banker's-rounded to 6.2.
    const runs = [mk({ conclusion: 'success' }), ...Array.from({ length: 15 }, () => mk({ conclusion: 'failure' }))];
    const [wm] = computeWorkflowMetrics(runs, LABELS, OPTS);
    expect(wm.successRatePct).toBe(6.2);
  });

  it('folds success into successMin, waste conclusions into wasteMin, skipped into other', () => {
    const runs = [
      mk({ conclusion: 'success', ...dur(10) }),
      mk({ conclusion: 'failure', ...dur(5) }),
      mk({ conclusion: 'cancelled', ...dur(3) }),
      mk({ conclusion: 'timed_out', ...dur(2) }),
      mk({ conclusion: 'skipped', ...dur(4) }),
    ];
    const [wm] = computeWorkflowMetrics(runs, LABELS, OPTS);
    expect(wm.runs).toBe(5);
    expect(wm.totalMin).toBe(24);
    expect(wm.success).toBe(1);
    expect(wm.failure).toBe(2); // failure + timed_out
    expect(wm.cancelled).toBe(1);
    expect(wm.other).toBe(1); // skipped: minutes in totalMin only
    expect(wm.wasteMin).toBe(10);
    expect(wm.successRatePct).toBe(25); // 1 of 4 — `other` is not in the denominator
    expect(wm.effectivenessPct).toBe(41.7); // pct(10, 24) — need not sum to 100 with waste
  });

  it('takes p95 as nearest-rank, not interpolated (10-value case → the max, not 9.55)', () => {
    const runs = Array.from({ length: 10 }, (_, i) => mk({ ...dur(i + 1) }));
    const [wm] = computeWorkflowMetrics(runs, LABELS, OPTS);
    expect(wm.p95Min).toBe(10); // idx = min(9, round(0.95·9)) = 9 → sorted[9]
    expect(wm.totalMin).toBe(55);
    expect(wm.avgMin).toBe(5.5);
    expect(wm.runsPerWeek).toBe(5); // 10 runs / 2 weeks
  });

  it('p95 index ties round half-to-even like Python (n=31 → idx 28, not 29)', () => {
    // 0.95·30 = 28.5 exactly. Python int(round(28.5)) = 28 (even); JS Math.round → 29.
    // durations 1..31 → sorted[28] = 29 (banker's) vs sorted[29] = 30 (half-up).
    const runs = Array.from({ length: 31 }, (_, i) => mk({ ...dur(i + 1) }));
    const [wm] = computeWorkflowMetrics(runs, LABELS, OPTS);
    expect(wm.p95Min).toBe(29);
  });

  it('scales runsPerWeek by windowDays', () => {
    const runs = [mk(), mk(), mk()];
    const [wm] = computeWorkflowMetrics(runs, LABELS, { nowIso: NOW, windowDays: 7 });
    expect(wm.runsPerWeek).toBe(3);
  });
});

describe('computeWorkflowMetrics — labels, events, rework, queue latency', () => {
  it('uses the label name/type when present, basename slug + other when not', () => {
    const runs = [mk(), mk({ path: '.github/workflows/nightly-audit.yml', slug: 'nightly-audit' })];
    const byPath = new Map(computeWorkflowMetrics(runs, LABELS, OPTS).map((w) => [w.path, w]));
    expect(byPath.get(PATH_A)?.name).toBe('Alpha Line');
    expect(byPath.get(PATH_A)?.dashType).toBe('ai');
    const un = byPath.get('.github/workflows/nightly-audit.yml');
    expect(un?.name).toBe('nightly-audit');
    expect(un?.dashType).toBe('other');
  });

  it('counts events and derives schedPct from the schedule share', () => {
    const runs = [
      mk({ event: 'schedule' }),
      mk({ event: 'schedule' }),
      mk({ event: 'schedule' }),
      mk({ event: 'push' }),
    ];
    const [wm] = computeWorkflowMetrics(runs, LABELS, OPTS);
    expect(wm.events).toEqual({ schedule: 3, push: 1 });
    expect(wm.schedPct).toBe(75);
  });

  it('counts runAttempt > 1 as rework over the completed count', () => {
    const runs = [mk(), mk(), mk({ runAttempt: 2 }), mk({ runAttempt: 3 })];
    const [wm] = computeWorkflowMetrics(runs, LABELS, OPTS);
    expect(wm.reworkRuns).toBe(2);
    expect(wm.reworkPct).toBe(50);
  });

  it('reworkPct denominator excludes "other" (skipped) runs — not diluted by them', () => {
    // 4 outcome-bearing runs (2 re-runs) + 6 skipped: rework rate is 2/4 = 50%, NOT 2/10.
    const runs = [
      mk(),
      mk(),
      mk({ runAttempt: 2 }),
      mk({ runAttempt: 2 }),
      ...Array.from({ length: 6 }, () => mk({ conclusion: 'skipped' })),
    ];
    const [wm] = computeWorkflowMetrics(runs, LABELS, OPTS);
    expect(wm.runs).toBe(10);
    expect(wm.other).toBe(6);
    expect(wm.reworkRuns).toBe(2);
    expect(wm.reworkPct).toBe(50); // pct(2, 4 outcome-bearing), not pct(2, 10)
    // and the rework-heavy flag (completed ≥ 4 && rework > 25%) fires, not suppressed
    expect(assignFlags([wm])[0].flags).toContain('rework-heavy');
  });

  it('a re-attempt of a skipped run is not counted as rework (numerator is outcome-bearing too)', () => {
    const runs = [mk(), mk(), mk(), mk(), mk({ conclusion: 'skipped', runAttempt: 2 })];
    const [wm] = computeWorkflowMetrics(runs, LABELS, OPTS);
    expect(wm.reworkRuns).toBe(0);
    expect(wm.reworkPct).toBe(0);
  });

  it('takes queueP50Sec as the median created→started delay (even count = mean of middles)', () => {
    const q = (sec: number): Partial<FactoryRun> => ({
      createdAt: at(0),
      runStartedAt: at(sec),
      updatedAt: at(sec + 60),
    });
    const runs = [
      mk(q(10)),
      mk(q(30)),
      mk(q(50)),
      mk(q(90)),
      mk({ createdAt: at(0), runStartedAt: null, updatedAt: at(60) }), // folds, but no queue sample
    ];
    const [wm] = computeWorkflowMetrics(runs, LABELS, OPTS);
    expect(wm.runs).toBe(5);
    expect(wm.queueP50Sec).toBe(40); // median of [10, 30, 50, 90]
  });

  it('reports queueP50Sec null when no folded run has runStartedAt', () => {
    const runs = [mk({ createdAt: at(0), runStartedAt: null, updatedAt: at(60) })];
    const [wm] = computeWorkflowMetrics(runs, LABELS, OPTS);
    expect(wm.queueP50Sec).toBeNull();
  });
});

// ── assignFlags ─────────────────────────────────────────────────────────

describe('assignFlags — failing / flaky', () => {
  it('flags failing at exactly 3 completed with rate < 50, not at 2 completed', () => {
    const [three] = assignFlags([
      mkWm({ path: 'a', success: 1, failure: 2, successRatePct: 33.3 }),
    ]);
    expect(three.flags).toContain('failing');
    const [two] = assignFlags([mkWm({ path: 'a', success: 0, failure: 2, successRatePct: 0 })]);
    expect(two.flags).not.toContain('failing');
  });

  it('flags flaky at 4 completed with 50 ≤ rate < 85, but not at rate 85', () => {
    const [flaky] = assignFlags([
      mkWm({ path: 'a', success: 3, failure: 1, successRatePct: 75 }),
    ]);
    expect(flaky.flags).toContain('flaky');
    expect(flaky.flags).not.toContain('failing');
    const [steady] = assignFlags([
      mkWm({ path: 'a', success: 17, failure: 3, successRatePct: 85 }),
    ]);
    expect(steady.flags).not.toContain('flaky');
  });

  it('keeps failing and flaky mutually exclusive (a bad-enough workflow is only failing)', () => {
    const [wm] = assignFlags([mkWm({ path: 'a', success: 1, failure: 3, successRatePct: 25 })]);
    expect(wm.flags).toContain('failing');
    expect(wm.flags).not.toContain('flaky');
  });
});

describe('assignFlags — slow / cancel-heavy / cron-heavy / rework-heavy', () => {
  it('flags slow strictly above 12 avg minutes', () => {
    expect(assignFlags([mkWm({ path: 'a', avgMin: 12 })])[0].flags).not.toContain('slow');
    expect(assignFlags([mkWm({ path: 'a', avgMin: 12.1 })])[0].flags).toContain('slow');
  });

  it('flags cancel-heavy strictly above a 25% cancelled share of ≥4 completed', () => {
    const heavy = mkWm({ path: 'a', success: 2, cancelled: 2, successRatePct: 50 });
    expect(assignFlags([heavy])[0].flags).toContain('cancel-heavy');
    const edge = mkWm({ path: 'a', success: 3, cancelled: 1, successRatePct: 75 });
    expect(assignFlags([edge])[0].flags).not.toContain('cancel-heavy'); // exactly 25
  });

  it('flags cron-heavy only with ≥5 runs and schedule share > 60', () => {
    expect(assignFlags([mkWm({ path: 'a', runs: 5, schedPct: 61 })])[0].flags).toContain('cron-heavy');
    expect(assignFlags([mkWm({ path: 'a', runs: 5, schedPct: 60 })])[0].flags).not.toContain('cron-heavy');
    expect(assignFlags([mkWm({ path: 'a', runs: 4, schedPct: 100 })])[0].flags).not.toContain('cron-heavy');
  });

  it('flags rework-heavy strictly above 25% rework of ≥4 completed', () => {
    expect(assignFlags([mkWm({ path: 'a', reworkRuns: 2, reworkPct: 50 })])[0].flags).toContain('rework-heavy');
    expect(assignFlags([mkWm({ path: 'a', reworkRuns: 1, reworkPct: 25 })])[0].flags).not.toContain('rework-heavy');
    const few = mkWm({ path: 'a', success: 3, reworkRuns: 3, reworkPct: 100 });
    expect(assignFlags([few])[0].flags).not.toContain('rework-heavy'); // only 3 completed
  });
});

describe('assignFlags — high-cost-low-value, priority, ordering', () => {
  it('measures high-cost against the group median (even count = mean of middles)', () => {
    // totalMin [10, 14, 18, 30] → median 16: only ≥16 with eff < 55 and waste ≥ 4 qualifies.
    const group = [
      mkWm({ path: 'a', totalMin: 10 }),
      mkWm({ path: 'b', totalMin: 14, effectivenessPct: 50, wasteMin: 4 }),
      mkWm({ path: 'c', totalMin: 18, effectivenessPct: 50, wasteMin: 4 }),
      mkWm({ path: 'd', totalMin: 30, effectivenessPct: 55, wasteMin: 10 }),
    ];
    const byPath = new Map(assignFlags(group).map((w) => [w.path, w]));
    expect(byPath.get('c')?.flags).toContain('high-cost-low-value'); // waste boundary is ≥
    expect(byPath.get('b')?.flags).not.toContain('high-cost-low-value'); // below median
    expect(byPath.get('d')?.flags).not.toContain('high-cost-low-value'); // eff 55 not < 55
  });

  it('computes priority = round1(wasteMin + totalMin·(1 − eff/100))', () => {
    const [wm] = assignFlags([
      mkWm({ path: 'a', wasteMin: 5, totalMin: 20, effectivenessPct: 40 }),
    ]);
    expect(wm.priority).toBe(17); // 5 + 20 × 0.6
  });

  it('sorts by priority desc, then totalMin desc, without mutating the input', () => {
    const x = mkWm({ path: 'x', totalMin: 50 }); // priority 0
    const y = mkWm({ path: 'y', totalMin: 10, wasteMin: 10 }); // priority 10
    const z = mkWm({ path: 'z', totalMin: 30, wasteMin: 10 }); // priority 10, more minutes
    const input = [x, y, z];
    const out = assignFlags(input);
    expect(out.map((w) => w.path)).toEqual(['z', 'y', 'x']);
    expect(input.map((w) => w.path)).toEqual(['x', 'y', 'z']);
    expect(x.priority).toBe(0);
    expect(x.flags).toEqual([]);
  });

  it('returns [] for an empty group', () => {
    expect(assignFlags([])).toEqual([]);
  });
});

// ── rollup / rollupByType ───────────────────────────────────────────────

describe('rollup', () => {
  const w1 = mkWm({
    path: 'a',
    runs: 4,
    totalMin: 30,
    wasteMin: 10,
    effectivenessPct: 60,
    success: 2,
    failure: 1,
    cancelled: 1,
    successRatePct: 50,
    reworkRuns: 1,
    reworkPct: 25,
  });
  const w2 = mkWm({
    path: 'b',
    runs: 6,
    totalMin: 10,
    success: 6,
  });

  it('sums the group and reconstructs effectiveness from totalMin × eff share', () => {
    const r = rollup([w1, w2]);
    expect(r.runs).toBe(10);
    expect(r.totalMin).toBe(40);
    expect(r.wasteMin).toBe(10);
    expect(r.effectivenessPct).toBe(70); // pct(30×0.6 + 10×1.0, 40)
    expect(r.successRatePct).toBe(80); // pct(8, 10)
    expect(r.reworkPct).toBe(10); // pct(1, 10 completed runs)
  });

  it('rolls an empty group up to zeros, effectiveness 100 (no minutes → none wasted, matches the dash)', () => {
    expect(rollup([])).toEqual({
      runs: 0,
      totalMin: 0,
      wasteMin: 0,
      effectivenessPct: 100,
      successRatePct: 0,
      reworkPct: 0,
    });
  });

  it('a non-empty all-zero-minute group scores 100 effectiveness, not 0 (dash totalMin-else-100 fallback)', () => {
    const r = rollup([
      mkWm({ path: 'a', totalMin: 0, effectivenessPct: 100, success: 3 }),
      mkWm({ path: 'b', totalMin: 0, effectivenessPct: 100, success: 2 }),
    ]);
    expect(r.totalMin).toBe(0);
    expect(r.effectivenessPct).toBe(100);
  });
});

describe('rollupByType', () => {
  it('groups by dashType with shares of grand minutes summing to ~100, sorted totalMin desc', () => {
    const rows = rollupByType([
      mkWm({ path: 'a', dashType: 'ai', totalMin: 30 }),
      mkWm({ path: 'b', dashType: 'ci', totalMin: 10 }),
      mkWm({ path: 'c', dashType: 'ai', totalMin: 20 }),
    ]);
    expect(rows.map((r) => r.type)).toEqual(['ai', 'ci']);
    expect(rows[0].totalMin).toBe(50);
    expect(rows[0].sharePct).toBe(83.3);
    expect(rows[1].sharePct).toBe(16.7);
    expect(rows[0].sharePct + rows[1].sharePct).toBeCloseTo(100, 1);
  });

  it('returns [] for no workflows and guards a zero grand total', () => {
    expect(rollupByType([])).toEqual([]);
    const rows = rollupByType([mkWm({ path: 'a', dashType: 'ci', totalMin: 0 })]);
    expect(rows).toHaveLength(1);
    expect(rows[0].sharePct).toBe(0);
  });
});
