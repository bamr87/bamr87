// Run-metrics engine for Fleet Ops — a TypeScript port of the dash's
// actions_analytics.py aggregation (bamr87/bamr87 .github/scripts/dash-gen).
// Cost = wall-clock run minutes (runStartedAt → updatedAt), a shadow price for
// billable minutes; value = share of minutes ending in success; waste = minutes on
// failed/cancelled/timed-out/startup-failed runs. Two gitorio additions on top of
// the dash formulas: rework (runAttempt > 1) and queue latency (createdAt →
// runStartedAt). PURE and total: time arrives as an ISO-string parameter, malformed
// timestamps skip a run rather than throwing, and nothing here does I/O.

import type { FactoryRun } from '../github/types.js';
import type { DashType, MetricFlag, MetricsRollup, WorkflowMetrics } from './types.js';

/** Windowing options. `nowIso` is the analysis instant — callers own the clock. */
export interface MetricsOptions {
  nowIso: string;
  /** Lookback window in days (dash default: 14). */
  windowDays?: number;
}

const DEFAULT_WINDOW_DAYS = 14;

/** Non-success terminal conclusions whose minutes count as waste (dash WASTE_CONCLUSIONS). */
const WASTE_CONCLUSIONS: ReadonlySet<string> = new Set([
  'failure',
  'cancelled',
  'timed_out',
  'startup_failure',
]);

// Flag thresholds — mirrors of the dash's tunable constants, plus the rework
// addition (same 25% bar as cancel-heavy).
const SLOW_AVG_MIN = 12;
const LOW_EFFECTIVENESS = 55;
const CANCEL_HEAVY_PCT = 25;
const CRON_HEAVY_PCT = 60;
const MIN_WASTE_MIN = 4;
const REWORK_HEAVY_PCT = 25;

// ── numeric helpers (dash: round(x, 1) / round(x, 2) / pct / p95 / median) ──

/**
 * Round half to EVEN — Python 3's `round()`. The dash computes every rounded value
 * with Python `round()`, so an exact TS port must tie-break the same way (JS
 * `Math.round` ties toward +∞, which diverges on exact `.5` values, e.g. p95 index
 * `round(28.5)` = 28 in Python vs 29 in JS, and `round(6.25, 1)` = 6.2 vs 6.3).
 */
function bankersRound(x: number): number {
  const floor = Math.floor(x);
  const diff = x - floor;
  if (diff < 0.5) return floor;
  if (diff > 0.5) return floor + 1;
  return floor % 2 === 0 ? floor : floor + 1; // exact .5 → nearest even
}

function round1(x: number): number {
  return bankersRound(x * 10) / 10;
}

function round2(x: number): number {
  return bankersRound(x * 100) / 100;
}

/** Percentage of `part` in `whole`, one decimal; 0 when `whole` is 0 (dash pct()). */
function pct(part: number, whole: number): number {
  return whole ? round1((100 * part) / whole) : 0;
}

/** Statistical median: mean of the two middles for an even count; 0 for empty. */
function median(values: readonly number[]): number {
  if (values.length === 0) return 0;
  const s = [...values].sort((a, b) => a - b);
  const mid = s.length >> 1;
  return s.length % 2 === 1 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

/** Nearest-rank p95 (NOT interpolated): sorted[min(n−1, round(0.95·(n−1)))], two decimals. */
function p95(values: readonly number[]): number {
  if (values.length === 0) return 0;
  const s = [...values].sort((a, b) => a - b);
  const idx = Math.min(s.length - 1, bankersRound(0.95 * (s.length - 1)));
  return round2(s[idx]);
}

/** Basename of a path with a trailing `.yml`/`.yaml` stripped — the unlabeled-name fallback. */
function baseNoExt(path: string): string {
  const base = path.split('/').pop() ?? path;
  return base.replace(/\.ya?ml$/i, '');
}

// ── fold state (dash new_bucket()/fold(), extended with rework + queue) ──────

interface Bucket {
  runs: number;
  totalMin: number;
  successMin: number;
  wasteMin: number;
  success: number;
  failure: number;
  cancelled: number;
  other: number;
  durations: number[];
  /** Queue latencies (createdAt → runStartedAt) for runs that actually started. */
  queueSecs: number[];
  reworkRuns: number;
  events: Map<string, number>;
}

function newBucket(): Bucket {
  return {
    runs: 0,
    totalMin: 0,
    successMin: 0,
    wasteMin: 0,
    success: 0,
    failure: 0,
    cancelled: 0,
    other: 0,
    durations: [],
    queueSecs: [],
    reworkRuns: 0,
    events: new Map(),
  };
}

// ── public API ───────────────────────────────────────────────────────────────

/**
 * Fold a window of runs into per-workflow {@link WorkflowMetrics}, keyed by path.
 * Only `status === 'completed'` runs created inside the window fold; a run whose
 * timestamps don't parse is skipped (the dash skips runs without a computable
 * duration). A path absent from `labels` still gets metrics under its basename
 * slug with dashType 'other'. `flags`/`priority` come back zeroed — scope-aware
 * flagging is {@link assignFlags}'s job. Never throws.
 */
export function computeWorkflowMetrics(
  runs: FactoryRun[],
  labels: ReadonlyMap<string, { name: string; dashType: DashType }>,
  opts: MetricsOptions,
): WorkflowMetrics[] {
  const windowDays = opts.windowDays ?? DEFAULT_WINDOW_DAYS;
  const cutoffMs = Date.parse(opts.nowIso) - windowDays * 86_400_000;
  const weeks = Math.max(windowDays / 7, 1 / 7);

  const buckets = new Map<string, Bucket>();
  for (const run of runs) {
    const createdMs = Date.parse(run.createdAt);
    // Negated comparison so a NaN cutoff or createdAt excludes rather than throws.
    if (!(createdMs >= cutoffMs)) continue;
    if (run.status !== 'completed') continue;

    const startMs = run.runStartedAt !== null ? Date.parse(run.runStartedAt) : createdMs;
    const rawMin = (Date.parse(run.updatedAt) - startMs) / 60_000;
    if (!Number.isFinite(rawMin)) continue;
    const m = Math.max(0, rawMin);

    let b = buckets.get(run.path);
    if (!b) {
      b = newBucket();
      buckets.set(run.path, b);
    }

    b.runs += 1;
    b.totalMin += m;
    b.durations.push(m);
    b.events.set(run.event, (b.events.get(run.event) ?? 0) + 1);
    const c = run.conclusion;
    // Rework counts re-run attempts among OUTCOME-BEARING runs only (success/failure/
    // cancelled) — the same `completed` denominator the rework-heavy flag and
    // successRatePct use — so reworkPct is a fraction of the same base, never >100%.
    let outcomeBearing = false;
    if (c === 'success') {
      b.successMin += m;
      b.success += 1;
      outcomeBearing = true;
    } else if (c !== null && WASTE_CONCLUSIONS.has(c)) {
      b.wasteMin += m;
      if (c === 'cancelled') b.cancelled += 1;
      else b.failure += 1;
      outcomeBearing = true;
    } else {
      b.other += 1;
    }

    if (run.runStartedAt !== null && Number.isFinite(startMs - createdMs)) {
      b.queueSecs.push(Math.max(0, (startMs - createdMs) / 1000));
    }
    if (outcomeBearing && run.runAttempt > 1) b.reworkRuns += 1;
  }

  const out: WorkflowMetrics[] = [];
  for (const [path, b] of buckets) {
    const label = labels.get(path);
    out.push({
      path,
      name: label?.name ?? baseNoExt(path),
      dashType: label?.dashType ?? 'other',
      runs: b.runs,
      totalMin: round1(b.totalMin),
      avgMin: b.runs ? round2(b.totalMin / b.runs) : 0,
      p95Min: p95(b.durations),
      wasteMin: round1(b.wasteMin),
      runsPerWeek: round1(b.runs / weeks),
      success: b.success,
      failure: b.failure,
      cancelled: b.cancelled,
      other: b.other,
      successRatePct: pct(b.success, b.success + b.failure + b.cancelled),
      // "Other" minutes (skipped/neutral/…) live in totalMin only, so
      // effectiveness + waste share need not sum to 100.
      effectivenessPct: b.totalMin > 0 ? pct(b.successMin, b.totalMin) : 100,
      schedPct: pct(b.events.get('schedule') ?? 0, b.runs),
      reworkRuns: b.reworkRuns,
      // Denominator is the outcome-bearing count (matches the rework-heavy flag +
      // successRatePct), NOT `runs` — `runs` also includes skipped/neutral ('other')
      // runs, which would dilute the rate and wrongly suppress the flag.
      reworkPct: pct(b.reworkRuns, b.success + b.failure + b.cancelled),
      queueP50Sec: b.queueSecs.length > 0 ? round1(median(b.queueSecs)) : null,
      events: Object.fromEntries(b.events),
      flags: [],
      priority: 0,
    });
  }
  return out;
}

/**
 * Fill `flags` + `priority` across a workflow group and rank it for triage. The
 * high-cost median is taken over the *given* group — the caller chooses the scope
 * (one repo, one type, the whole fleet). Returns a NEW array (inputs untouched)
 * sorted by (priority desc, totalMin desc). Thresholds are the dash's; `failing`
 * and `flaky` are mutually exclusive by construction; `rework-heavy` is the
 * gitorio addition.
 */
export function assignFlags(workflows: WorkflowMetrics[]): WorkflowMetrics[] {
  const medianMin = median(workflows.map((w) => w.totalMin));

  const out = workflows.map((w): WorkflowMetrics => {
    const flags: MetricFlag[] = [];
    const completed = w.success + w.failure + w.cancelled;
    if (
      w.totalMin >= medianMin &&
      w.effectivenessPct < LOW_EFFECTIVENESS &&
      w.wasteMin >= MIN_WASTE_MIN
    ) {
      flags.push('high-cost-low-value');
    }
    if (completed >= 3 && w.successRatePct < 50) {
      flags.push('failing');
    } else if (completed >= 4 && w.successRatePct >= 50 && w.successRatePct < 85) {
      flags.push('flaky');
    }
    if (w.avgMin > SLOW_AVG_MIN) flags.push('slow');
    if (completed >= 4 && pct(w.cancelled, completed) > CANCEL_HEAVY_PCT) {
      flags.push('cancel-heavy');
    }
    if (w.runs >= 5 && w.schedPct > CRON_HEAVY_PCT) flags.push('cron-heavy');
    if (completed >= 4 && w.reworkPct > REWORK_HEAVY_PCT) flags.push('rework-heavy');

    // Priority: minutes wasted, then raw consumption — the "high running, low
    // effective" triage rank.
    const priority = round1(w.wasteMin + w.totalMin * (1 - w.effectivenessPct / 100));
    return { ...w, flags, priority };
  });

  out.sort((a, b) => b.priority - a.priority || b.totalMin - a.totalMin);
  return out;
}

/**
 * Aggregate a group of workflows into one {@link MetricsRollup}. WorkflowMetrics
 * does not retain successMin, so group effectiveness is reconstructed as
 * pct(Σ totalMin·effectivenessPct/100, Σ totalMin) — exact up to the per-workflow
 * pct rounding already baked into effectivenessPct. The rework denominator is
 * Σ runs, which is the completed-run count (only completed runs ever fold).
 */
export function rollup(workflows: WorkflowMetrics[]): MetricsRollup {
  let runs = 0;
  let totalMin = 0;
  let wasteMin = 0;
  let successMin = 0;
  let success = 0;
  let completed = 0;
  let reworkRuns = 0;
  for (const w of workflows) {
    runs += w.runs;
    totalMin += w.totalMin;
    wasteMin += w.wasteMin;
    successMin += (w.totalMin * w.effectivenessPct) / 100;
    success += w.success;
    completed += w.success + w.failure + w.cancelled;
    reworkRuns += w.reworkRuns;
  }
  return {
    runs,
    totalMin: round1(totalMin),
    wasteMin: round1(wasteMin),
    // Mirror the per-workflow + dash guard: an all-zero-minute group scores 100, not 0.
    effectivenessPct: totalMin > 0 ? pct(successMin, totalMin) : 100,
    successRatePct: pct(success, completed),
    // Same outcome-bearing denominator as the per-workflow reworkPct, not `runs`.
    reworkPct: pct(reworkRuns, completed),
  };
}

/**
 * Roll workflows up by dashType: one row per type present, each a {@link rollup}
 * plus its sharePct of the grand total minutes (0-guarded), sorted totalMin desc.
 */
export function rollupByType(
  workflows: WorkflowMetrics[],
): ({ type: DashType; sharePct: number } & MetricsRollup)[] {
  const groups = new Map<DashType, WorkflowMetrics[]>();
  for (const w of workflows) {
    const group = groups.get(w.dashType);
    if (group) group.push(w);
    else groups.set(w.dashType, [w]);
  }

  const rows = [...groups.entries()].map(([type, group]) => ({
    type,
    sharePct: 0,
    ...rollup(group),
  }));
  const grandMin = rows.reduce((sum, r) => sum + r.totalMin, 0);
  for (const r of rows) r.sharePct = grandMin ? round1((100 * r.totalMin) / grandMin) : 0;

  rows.sort((a, b) => b.totalMin - a.totalMin);
  return rows;
}
