// @vitest-environment node
// Harness health parity (specs/014-harness-parity, AC-1 / AC-2).
//
// Two proofs. The golden one: the hub's committed inputs at bamr87/bamr87@d58a26c (reduced to
// the fields the generator reads — see fixtures/hub/SOURCE.md) run through the TypeScript
// port at the committed `generated_at` and reproduce the committed `harness_health.yml`
// exactly. The invariants: every case in the hub's own `test_harness.py`, ported.

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parse } from 'yaml';
import { describe, expect, it } from 'vitest';
import {
  buildScorecard,
  DEFAULT_CONFIG,
  evaluateTripWires,
  harnessHealth,
  parseGeneratedAt,
  parseHarnessConfig,
  toActionsUsage,
  toFleetTriage,
  toIssuePipeline,
  toTokenRotation,
  type ActionsUsage,
  type FleetTriage,
  type HarnessConfig,
  type IssuePipeline,
  type TokenRotation,
  type TripWire,
  type UsageWorkflow,
} from './health.js';

const FIX = fileURLToPath(new URL('./fixtures/hub/', import.meta.url));
const load = (name: string): unknown => parse(readFileSync(join(FIX, name), 'utf8'));

describe('golden parity with the hub (AC-1)', () => {
  const cfg = parseHarnessConfig(load('fleet-harness.yml'));
  const expected = load('harness_health.yml') as ReturnType<typeof harnessHealth>;
  const now = parseGeneratedAt(expected.generated_at)!;
  const actual = harnessHealth(
    {
      actions_usage: toActionsUsage(load('actions_usage.yml')),
      fleet_triage: toFleetTriage(load('fleet_triage.yml')),
      issue_pipeline: toIssuePipeline(load('issue_pipeline.yml')),
      token_rotation: toTokenRotation(load('token_rotation.yml')),
    },
    cfg,
    now,
  );

  it('reads the hub’s thresholds', () => {
    expect(cfg.scorecard).toEqual({ completion_rate_min_pct: 80, effectiveness_min_pct: 70 });
    expect(cfg.trip_wires.cost_spike_multiplier).toBe(3.0);
    expect(cfg.trip_wires.standing_failures_max).toBe(30);
  });

  it('reproduces the committed scorecard exactly', () => {
    expect(actual.scorecard).toEqual(expected.scorecard);
  });

  it('reproduces every committed trip wire, its summary, and its detail rows', () => {
    expect(actual.trip_wires).toEqual(expected.trip_wires);
    expect(actual.tripped_count).toBe(expected.tripped_count);
  });

  it('reproduces the source freshness line and the stamp', () => {
    expect(actual.sources).toEqual(expected.sources);
    expect(actual.generated_at).toBe(expected.generated_at);
    expect(actual.note).toBe(expected.note);
  });
});

// ── the hub's test_harness.py, ported ───────────────────────────────────────

const NOW = new Date(Date.UTC(2026, 7, 27, 12, 0));
const CFG: HarnessConfig = DEFAULT_CONFIG;

const wf = (
  opts: { repo?: string; avg?: number; runs?: number; success?: number; external?: boolean; workflow?: string } = {},
): UsageWorkflow => ({
  repo: opts.repo ?? 'hub',
  workflow: opts.workflow ?? 'ci',
  path: '.github/workflows/ci.yml',
  avg_min: opts.avg ?? 2.0,
  runs: opts.runs ?? 5,
  success: opts.success ?? 5,
  external: opts.external ?? false,
});

const usage = (
  workflows?: UsageWorkflow[],
  totals: Partial<NonNullable<ActionsUsage['totals']>> = {},
): ActionsUsage => ({
  generated_at: '2026-08-27 09:00 UTC',
  totals: {
    success_rate_pct: 90.0,
    effectiveness_pct: 82.0,
    total_min: 100.0,
    waste_min: 10.0,
    waste_hours: 0.2,
    ...totals,
  },
  workflows: workflows ?? [wf()],
});

const triage = (failing = 5): FleetTriage => ({
  generated_at: '2026-08-27 09:00 UTC',
  totals: { failing_workflows: failing, repos_red: 2 },
});

const pipeline = (): IssuePipeline => ({
  generated_at: '2026-08-27 09:00 UTC',
  totals: { pipeline_prs: 3, stages: { blocked: 4, hold: 1 } },
});

const rotation = (age = 10, maxAge = 45): TokenRotation => ({
  generated_at: '2026-08-24 22:00 UTC',
  tokens: [{ name: 'CLAUDE_CODE_OAUTH_TOKEN', oldest_age_days: age, max_age_days: maxAge }],
});

const byId = (wires: TripWire[]) => Object.fromEntries(wires.map((w) => [w.id, w]));

describe('trip wires — the hub’s invariants (AC-2)', () => {
  it('reports every wire even when quiet', () => {
    const wires = evaluateTripWires(CFG, usage(), triage(), pipeline(), rotation(), NOW);
    expect(new Set(wires.map((w) => w.id))).toEqual(
      new Set(['stale-data', 'pass-rate-floor', 'waste-ceiling', 'cost-spike', 'standing-failures', 'credential-overdue']),
    );
    expect(wires.some((w) => w.tripped)).toBe(false);
  });

  it('a missing input trips stale-data and never crashes', () => {
    const w = byId(evaluateTripWires(CFG, null, null, null, null, NOW))['stale-data'];
    expect(w.tripped).toBe(true);
    expect(new Set(w.detail!.map((d) => d.source))).toEqual(
      new Set(['actions_usage', 'fleet_triage', 'issue_pipeline', 'token_rotation']),
    );
  });

  it('an old snapshot trips stale-data', () => {
    const old = usage();
    old.generated_at = '2026-08-20 09:00 UTC'; // 7 days before NOW, limit 3
    const w = byId(evaluateTripWires(CFG, old, triage(), pipeline(), rotation(), NOW))['stale-data'];
    expect(w.tripped).toBe(true);
    expect(w.detail!.map((d) => d.source)).toEqual(['actions_usage']);
  });

  it('the rotation ledger gets weekly slack', () => {
    const w = byId(evaluateTripWires(CFG, usage(), triage(), pipeline(), rotation(), NOW))['stale-data'];
    expect(w.tripped).toBe(false);
  });

  it('cost-spike uses the median, not the mean', () => {
    const flock = Array.from({ length: 9 }, (_, i) => wf({ avg: 2.0, workflow: `w${i}` }));
    const spike = wf({ repo: 'big', avg: 60.0, workflow: 'runaway' });
    const second = wf({ repo: 'mid', avg: 20.0, workflow: 'creeper' });
    const w = byId(
      evaluateTripWires(CFG, usage([...flock, spike, second]), triage(), pipeline(), rotation(), NOW),
    )['cost-spike'];
    expect(w.tripped).toBe(true);
    expect(new Set(w.detail!.map((d) => d.workflow))).toEqual(new Set(['runaway', 'creeper']));
  });

  it('the absolute floor quiets tiny fleets', () => {
    const flock = Array.from({ length: 9 }, (_, i) => wf({ avg: 1.0, workflow: `w${i}` }));
    const outlier = wf({ avg: 4.0, workflow: 'chunky' });
    const w = byId(evaluateTripWires(CFG, usage([...flock, outlier]), triage(), pipeline(), rotation(), NOW))['cost-spike'];
    expect(w.tripped).toBe(false);
  });

  it('cost-spike ignores external mirrors and low-run workflows', () => {
    const flock = Array.from({ length: 5 }, (_, i) => wf({ avg: 2.0, workflow: `w${i}` }));
    const ext = wf({ repo: 'skills', avg: 90.0, workflow: 'mirror', external: true });
    const rare = wf({ avg: 90.0, workflow: 'once', runs: 1 });
    const w = byId(evaluateTripWires(CFG, usage([...flock, ext, rare]), triage(), pipeline(), rotation(), NOW))['cost-spike'];
    expect(w.tripped).toBe(false);
  });

  it('pass-rate floor and waste ceiling', () => {
    const bad = usage(undefined, { success_rate_pct: 60.0, waste_min: 40.0, total_min: 100.0 });
    const wires = byId(evaluateTripWires(CFG, bad, triage(), pipeline(), rotation(), NOW));
    expect(wires['pass-rate-floor'].tripped).toBe(true);
    expect(wires['waste-ceiling'].tripped).toBe(true);
  });

  it('standing failures at the boundary', () => {
    expect(byId(evaluateTripWires(CFG, usage(), triage(31), pipeline(), rotation(), NOW))['standing-failures'].tripped).toBe(true);
    expect(byId(evaluateTripWires(CFG, usage(), triage(30), pipeline(), rotation(), NOW))['standing-failures'].tripped).toBe(false);
  });

  it('credential-overdue uses the ledger policy plus grace', () => {
    // 61 days vs max_age 45 + grace 15 = 60 → tripped; 60 exactly → not.
    expect(byId(evaluateTripWires(CFG, usage(), triage(), pipeline(), rotation(61), NOW))['credential-overdue'].tripped).toBe(true);
    expect(byId(evaluateTripWires(CFG, usage(), triage(), pipeline(), rotation(60), NOW))['credential-overdue'].tripped).toBe(false);
  });
});

describe('scorecard — the hub’s invariants (AC-2)', () => {
  it('thresholds and cost per verified run', () => {
    const sc = buildScorecard(CFG, usage(), triage(), pipeline(), rotation());
    expect(sc.completion_rate_pct.status).toBe('ok');
    expect(sc.effectiveness_pct.status).toBe('ok');
    expect(sc.cost_min_per_verified_run.value).toBe(20.0); // 100 min / 5 verified runs
    expect(sc.escalations_open.value).toBe(5); // blocked 4 + hold 1
    expect(sc.agent_prs_open.value).toBe(3);
    expect(sc.oldest_credential_age_days.value).toBe(10);
    expect(sc.waste_hours.status).toBeUndefined(); // informational: no threshold, no status
  });

  it('missing inputs null the metrics and mark judged ones unknown', () => {
    const sc = buildScorecard(CFG, null, null, null, null);
    expect(sc.completion_rate_pct).toEqual({ value: null, direction: 'up', threshold: 80, status: 'unknown' });
    expect(sc.standing_failures.value).toBeNull();
    expect(sc.escalations_open.value).toBeNull();
  });

  it('an absent config block degrades to the hub’s defaults', () => {
    expect(parseHarnessConfig({})).toEqual(DEFAULT_CONFIG);
    expect(parseHarnessConfig({ harness: { trip_wires: { standing_failures_max: '12' } } }).trip_wires.standing_failures_max).toBe(12);
    expect(parseHarnessConfig({ harness: { scorecard: { completion_rate_min_pct: 'junk' } } }).scorecard.completion_rate_min_pct).toBe(80);
  });
});
