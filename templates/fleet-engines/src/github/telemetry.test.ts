import { describe, expect, it } from 'vitest';
import { ledForRun, latestBySlug, statusBySlug, dashboardStats, statsByLine } from './telemetry.js';
import type { FactoryRun } from './types.js';

// ── fixtures ────────────────────────────────────────────────────────────
let seq = 100;
const nextId = (): number => ++seq;

/** Fixed base for building deterministic ISO durations. */
const BASE_MS = Date.parse('2026-07-01T00:00:00Z');
const at = (offsetSec: number): string => new Date(BASE_MS + offsetSec * 1000).toISOString();

/** Timestamps for a run that started at BASE and took `sec` seconds. */
const span = (sec: number): Pick<FactoryRun, 'createdAt' | 'runStartedAt' | 'updatedAt'> => ({
  createdAt: at(0),
  runStartedAt: at(0),
  updatedAt: at(sec),
});

/** Terse FactoryRun factory: completed/success by default, override what a case cares about. */
function mk(overrides: Partial<FactoryRun> & { slug: string }): FactoryRun {
  const runId = overrides.runId ?? nextId();
  return {
    path: `.github/workflows/factory--${overrides.slug}.yml`,
    runId,
    runNumber: runId,
    status: 'completed',
    conclusion: 'success',
    event: 'push',
    htmlUrl: `https://github.com/o/r/actions/runs/${runId}`,
    runAttempt: 1,
    createdAt: at(0),
    runStartedAt: at(0),
    updatedAt: at(60),
    ...overrides,
  };
}

describe('ledForRun', () => {
  it('maps run state + conclusion to a LED colour', () => {
    expect(ledForRun(undefined)).toBe('idle');
    expect(ledForRun(mk({ slug: 'a', status: 'completed', conclusion: 'success' }))).toBe('on');
    expect(ledForRun(mk({ slug: 'a', status: 'in_progress', conclusion: null }))).toBe('warn');
    expect(ledForRun(mk({ slug: 'a', status: 'queued', conclusion: null }))).toBe('warn');
    expect(ledForRun(mk({ slug: 'a', status: 'completed', conclusion: 'failure' }))).toBe('bad');
    expect(ledForRun(mk({ slug: 'a', status: 'completed', conclusion: 'timed_out' }))).toBe('bad');
    expect(ledForRun(mk({ slug: 'a', status: 'completed', conclusion: 'startup_failure' }))).toBe('bad');
    expect(ledForRun(mk({ slug: 'a', status: 'completed', conclusion: 'stale' }))).toBe('bad');
    expect(ledForRun(mk({ slug: 'a', status: 'completed', conclusion: 'cancelled' }))).toBe('idle');
    expect(ledForRun(mk({ slug: 'a', status: 'completed', conclusion: 'skipped' }))).toBe('idle');
    expect(ledForRun(mk({ slug: 'a', status: 'completed', conclusion: 'neutral' }))).toBe('idle');
    expect(ledForRun(mk({ slug: 'a', status: 'completed', conclusion: null }))).toBe('idle');
  });
});

describe('latestBySlug', () => {
  const runs: FactoryRun[] = [
    mk({ slug: 'triage', runId: 1, createdAt: at(0), conclusion: 'success' }),
    mk({ slug: 'triage', runId: 2, createdAt: at(300), conclusion: 'failure' }), // newest by date
    mk({ slug: 'triage', runId: 9, createdAt: at(100), conclusion: 'success' }),
    mk({ slug: 'gardener', runId: 3, createdAt: at(200), conclusion: 'failure' }),
    mk({ slug: 'gardener', runId: 7, createdAt: at(200), conclusion: 'success' }), // tie on date, larger runId wins
  ];

  it('picks the newest run per slug (max createdAt, tie-broken by runId)', () => {
    const latest = latestBySlug(runs);
    expect(latest.size).toBe(2);
    expect(latest.get('triage')!.runId).toBe(2);
    expect(latest.get('gardener')!.runId).toBe(7);
  });

  it('is unaffected by input order', () => {
    const shuffled = [runs[4], runs[0], runs[3], runs[1], runs[2]];
    const latest = latestBySlug(shuffled);
    expect(latest.get('triage')!.runId).toBe(2);
    expect(latest.get('gardener')!.runId).toBe(7);
  });

  it('statusBySlug lights each line by its latest run', () => {
    const status = statusBySlug(runs);
    expect(status.get('triage')).toBe('bad'); // latest triage failed
    expect(status.get('gardener')).toBe('on'); // latest gardener succeeded
  });
});

describe('dashboardStats', () => {
  it('counts totals and computes successRate as success/completed', () => {
    const runs: FactoryRun[] = [
      mk({ slug: 'a', status: 'completed', conclusion: 'success' }),
      mk({ slug: 'a', status: 'completed', conclusion: 'success' }),
      mk({ slug: 'a', status: 'completed', conclusion: 'failure' }),
      mk({ slug: 'a', status: 'in_progress', conclusion: null }),
    ];
    const s = dashboardStats(runs);
    expect(s.total).toBe(4);
    expect(s.completed).toBe(3);
    expect(s.success).toBe(2);
    expect(s.failure).toBe(1);
    expect(s.inProgress).toBe(1);
    expect(s.successRate).toBeCloseTo(2 / 3, 5); // 2 of 3 completed → ~0.667
  });

  it('counts timed_out and startup_failure as failures but not stale', () => {
    const runs: FactoryRun[] = [
      mk({ slug: 'a', status: 'completed', conclusion: 'timed_out' }),
      mk({ slug: 'a', status: 'completed', conclusion: 'startup_failure' }),
      mk({ slug: 'a', status: 'completed', conclusion: 'stale' }),
    ];
    const s = dashboardStats(runs);
    expect(s.failure).toBe(2);
  });

  it('takes p50DurationSec as the median completed-run duration', () => {
    const runs: FactoryRun[] = [
      mk({ slug: 'a', status: 'completed', conclusion: 'success', ...span(10) }),
      mk({ slug: 'a', status: 'completed', conclusion: 'success', ...span(30) }),
      mk({ slug: 'a', status: 'completed', conclusion: 'success', ...span(20) }),
    ];
    expect(dashboardStats(runs).p50DurationSec).toBe(20);
  });

  it('falls back to createdAt when runStartedAt is null and clamps negatives to 0', () => {
    const runs: FactoryRun[] = [
      // runStartedAt null → duration measured from createdAt (0s → 40s = 40)
      mk({ slug: 'a', status: 'completed', conclusion: 'success', createdAt: at(0), runStartedAt: null, updatedAt: at(40) }),
      // updatedAt before start → clamped to 0
      mk({ slug: 'a', status: 'completed', conclusion: 'success', createdAt: at(0), runStartedAt: at(50), updatedAt: at(10) }),
    ];
    // durations [40, 0] → median (0 + 40) / 2 = 20
    expect(dashboardStats(runs).p50DurationSec).toBe(20);
  });

  it('returns null rate/p50 when nothing has completed', () => {
    expect(dashboardStats([]).successRate).toBeNull();
    expect(dashboardStats([]).p50DurationSec).toBeNull();
    const inFlight = dashboardStats([mk({ slug: 'a', status: 'in_progress', conclusion: null })]);
    expect(inFlight.successRate).toBeNull();
    expect(inFlight.p50DurationSec).toBeNull();
  });
});

describe('statsByLine', () => {
  it('returns one row per slug, sorted ascending, with per-line rate + p50', () => {
    const runs: FactoryRun[] = [
      mk({ slug: 'zeta', status: 'completed', conclusion: 'success', ...span(10) }),
      mk({ slug: 'alpha', status: 'completed', conclusion: 'failure', ...span(40) }),
      mk({ slug: 'alpha', status: 'completed', conclusion: 'success', ...span(20) }),
    ];
    const rows = statsByLine(runs);
    expect(rows.map((r) => r.slug)).toEqual(['alpha', 'zeta']);

    const [alpha, zeta] = rows;
    expect(alpha.total).toBe(2);
    expect(alpha.successRate).toBe(0.5); // 1 of 2
    expect(alpha.p50DurationSec).toBe(30); // median of 40, 20

    expect(zeta.total).toBe(1);
    expect(zeta.successRate).toBe(1);
    expect(zeta.p50DurationSec).toBe(10);
  });

  it('reports null rate/p50 for a line with no completed runs', () => {
    const rows = statsByLine([mk({ slug: 'a', status: 'in_progress', conclusion: null })]);
    expect(rows).toHaveLength(1);
    expect(rows[0].total).toBe(1);
    expect(rows[0].successRate).toBeNull();
    expect(rows[0].p50DurationSec).toBeNull();
  });
});
