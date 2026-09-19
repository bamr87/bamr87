// The six-layer harness health — a pure TypeScript port of the bamr87 hub's `dash-gen harness`
// (specs/014-harness-parity, FR-1; reference: bamr87/bamr87@d58a26c
// .github/scripts/dash-gen/harness.py). The hub computes a SCORECARD (nine metrics, two of
// them judged against declared thresholds) and six TRIP WIRES (aggregate-drift alarms) from
// four committed fleet signals, offline and deterministically; GitFactory runs the same rules
// over the hub's committed files (the hub as fleet source) or over a live Fleet Ops scan
// (`signals.ts`). Every input is optional: a missing or malformed signal nulls its metrics
// and trips `stale-data`, never throws — the wire that watches for staleness is exactly how
// a missing input becomes visible. No I/O, no globals (golden rule #3). All parsed values
// are untrusted data: numbers are coerced and bounded, strings pass through as text.

// ── signal shapes (the fields the hub's generator reads) ───────────────────

export interface UsageWorkflow {
  repo?: string;
  workflow?: string;
  path?: string;
  avg_min?: number;
  runs?: number;
  success?: number;
  external?: boolean;
}

export interface ActionsUsage {
  generated_at?: string;
  totals?: {
    success_rate_pct?: number;
    effectiveness_pct?: number;
    total_min?: number;
    waste_min?: number;
    waste_hours?: number;
  };
  workflows?: UsageWorkflow[];
}

export interface FleetTriage {
  generated_at?: string;
  totals?: { failing_workflows?: number; repos_red?: number };
}

export interface IssuePipeline {
  generated_at?: string;
  totals?: { pipeline_prs?: number; stages?: Record<string, number> };
}

export interface RotationToken {
  name?: string;
  oldest_age_days?: number;
  max_age_days?: number;
}

export interface TokenRotation {
  generated_at?: string;
  tokens?: RotationToken[];
}

/** The four signals. `null`/`undefined` (or `{}`) means "missing" — the hub's `{}`. */
export interface HarnessSignals {
  actions_usage?: ActionsUsage | null;
  fleet_triage?: FleetTriage | null;
  issue_pipeline?: IssuePipeline | null;
  token_rotation?: TokenRotation | null;
}

export const SIGNAL_NAMES = [
  'actions_usage',
  'fleet_triage',
  'issue_pipeline',
  'token_rotation',
] as const;
export type SignalName = (typeof SIGNAL_NAMES)[number];

// ── configuration (the hub's `_data/fleet.yml` → `harness:` block) ─────────

export interface HarnessConfig {
  scorecard: { completion_rate_min_pct: number; effectiveness_min_pct: number };
  trip_wires: {
    stale_data_days: number;
    pass_rate_floor_pct: number;
    waste_ceiling_pct: number;
    cost_spike_multiplier: number;
    cost_spike_min_runs: number;
    cost_spike_min_avg_min: number;
    standing_failures_max: number;
    credential_grace_days: number;
  };
}

/** The hub's defaults (harness.py `DEFAULT_SCORECARD` / `DEFAULT_TRIP_WIRES`). */
export const DEFAULT_CONFIG: HarnessConfig = {
  scorecard: { completion_rate_min_pct: 80, effectiveness_min_pct: 70 },
  trip_wires: {
    stale_data_days: 3,
    pass_rate_floor_pct: 75,
    waste_ceiling_pct: 30,
    cost_spike_multiplier: 3.0,
    cost_spike_min_runs: 3,
    cost_spike_min_avg_min: 5.0,
    standing_failures_max: 30,
    credential_grace_days: 15,
  },
};

/** The weekly rotation ledger gets slack the daily signals do not (harness.py, literal 10). */
const ROTATION_STALE_DAYS = 10;

const isRecord = (v: unknown): v is Record<string, unknown> =>
  !!v && typeof v === 'object' && !Array.isArray(v);

/** A finite number, or null. Strings that are numbers are accepted (YAML round-trips them). */
export function num(v: unknown): number | null {
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  if (typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v))) return Number(v);
  return null;
}

/**
 * Read the `harness:` block out of a parsed `fleet.yml` (or the block itself), with the
 * hub's defaults for every absent key — an absent block degrades to sane behaviour.
 */
export function parseHarnessConfig(fleetYml: unknown): HarnessConfig {
  const root = isRecord(fleetYml) ? fleetYml : {};
  const block = isRecord(root.harness) ? root.harness : root;
  const sc = isRecord(block.scorecard) ? block.scorecard : {};
  const tw = isRecord(block.trip_wires) ? block.trip_wires : {};
  const pick = <T extends Record<string, number>>(src: Record<string, unknown>, defaults: T): T => {
    const out = { ...defaults } as Record<string, number>;
    for (const key of Object.keys(defaults)) {
      const v = num(src[key]);
      if (v !== null) out[key] = v;
    }
    return out as T;
  };
  return {
    scorecard: pick(sc, DEFAULT_CONFIG.scorecard),
    trip_wires: pick(tw, DEFAULT_CONFIG.trip_wires),
  };
}

// ── time ───────────────────────────────────────────────────────────────────

/** The generators stamp `%Y-%m-%d %H:%M UTC`; ISO and bare dates are tolerated (harness.py). */
export function parseGeneratedAt(value: unknown): Date | null {
  if (typeof value !== 'string') return null;
  let m = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}) UTC$/.exec(value);
  if (m) return new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]));
  m = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})$/.exec(value);
  if (m) {
    const t = Date.parse(value);
    return Number.isNaN(t) ? null : new Date(t);
  }
  m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (m) return new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  return null;
}

/** Python's round-half-even at one decimal, as the hub's `round(x, 1)` produces. */
const round1 = (x: number): number => roundHalfEven(x, 1);
const round2 = (x: number): number => roundHalfEven(x, 2);

function roundHalfEven(x: number, digits: number): number {
  const f = 10 ** digits;
  const y = x * f;
  const floor = Math.floor(y);
  const diff = y - floor;
  let r: number;
  if (Math.abs(diff - 0.5) < 1e-9) r = floor % 2 === 0 ? floor : floor + 1;
  else r = Math.round(y);
  return r / f;
}

export function sourceAgeDays(data: unknown, now: Date): number | null {
  const ts = parseGeneratedAt(isRecord(data) ? data.generated_at : undefined);
  if (!ts) return null;
  return round1((now.getTime() - ts.getTime()) / 86_400_000);
}

export function median(values: number[]): number | null {
  if (!values.length) return null;
  const ordered = [...values].sort((a, b) => a - b);
  const mid = Math.floor(ordered.length / 2);
  return ordered.length % 2 ? ordered[mid] : (ordered[mid - 1] + ordered[mid]) / 2;
}

// ── scorecard ──────────────────────────────────────────────────────────────

export type Direction = 'up' | 'down' | 'steady';
export type MetricStatus = 'ok' | 'warn' | 'unknown';

export interface Metric {
  value: number | null;
  direction: Direction;
  threshold?: number;
  status?: MetricStatus;
}

export const SCORECARD_KEYS = [
  'completion_rate_pct',
  'effectiveness_pct',
  'waste_hours',
  'cost_min_per_verified_run',
  'standing_failures',
  'repos_red',
  'escalations_open',
  'agent_prs_open',
  'oldest_credential_age_days',
] as const;
export type ScorecardKey = (typeof SCORECARD_KEYS)[number];
export type Scorecard = Record<ScorecardKey, Metric>;

const present = <T>(v: T | null | undefined): v is T => v !== null && v !== undefined;

/** The playbook's health scorecard, from the signals the fleet already keeps. */
export function buildScorecard(
  cfg: HarnessConfig,
  usage: ActionsUsage | null | undefined,
  triage: FleetTriage | null | undefined,
  pipeline: IssuePipeline | null | undefined,
  rotation: TokenRotation | null | undefined,
): Scorecard {
  const uTot = usage?.totals ?? {};
  const tTot = triage?.totals ?? {};
  const pTot = pipeline?.totals ?? {};
  const stages = pTot.stages ?? {};

  let verifiedRuns: number | null = null;
  const workflows = Array.isArray(usage?.workflows) ? usage!.workflows! : null;
  if (workflows && workflows.length) {
    verifiedRuns = workflows.reduce((sum, w) => sum + Math.trunc(num(w.success) ?? 0), 0);
  }
  let costPerVerified: number | null = null;
  const totalMin = num(uTot.total_min);
  if (verifiedRuns && totalMin) costPerVerified = round2(totalMin / verifiedRuns);

  let oldestCredential: number | null = null;
  for (const token of rotation?.tokens ?? []) {
    const age = isRecord(token) ? num(token.oldest_age_days) : null;
    if (age !== null) oldestCredential = Math.max(oldestCredential ?? 0, age);
  }

  const sc = cfg.scorecard;
  const metric = (
    value: number | null,
    direction: Direction,
    threshold?: number,
    ok?: boolean,
  ): Metric => {
    const entry: Metric = { value, direction };
    if (threshold !== undefined) {
      entry.threshold = threshold;
      entry.status = value === null ? 'unknown' : ok ? 'ok' : 'warn';
    }
    return entry;
  };

  const completion = num(uTot.success_rate_pct);
  const effectiveness = num(uTot.effectiveness_pct);
  let escalations: number | null = null;
  if (Object.keys(stages).length) {
    escalations = Math.trunc(num(stages.blocked) ?? 0) + Math.trunc(num(stages.hold) ?? 0);
  }

  return {
    completion_rate_pct: metric(
      completion,
      'up',
      sc.completion_rate_min_pct,
      present(completion) && completion >= sc.completion_rate_min_pct,
    ),
    effectiveness_pct: metric(
      effectiveness,
      'up',
      sc.effectiveness_min_pct,
      present(effectiveness) && effectiveness >= sc.effectiveness_min_pct,
    ),
    waste_hours: metric(num(uTot.waste_hours), 'down'),
    cost_min_per_verified_run: metric(costPerVerified, 'down'),
    standing_failures: metric(num(tTot.failing_workflows), 'down'),
    repos_red: metric(num(tTot.repos_red), 'down'),
    escalations_open: metric(escalations, 'down'),
    agent_prs_open: metric(num(pTot.pipeline_prs), 'steady'),
    oldest_credential_age_days: metric(oldestCredential, 'down'),
  };
}

// ── trip wires ─────────────────────────────────────────────────────────────

export type WireId =
  | 'stale-data'
  | 'pass-rate-floor'
  | 'waste-ceiling'
  | 'cost-spike'
  | 'standing-failures'
  | 'credential-overdue';

export const WIRE_IDS: WireId[] = [
  'stale-data',
  'pass-rate-floor',
  'waste-ceiling',
  'cost-spike',
  'standing-failures',
  'credential-overdue',
];

export interface TripWire {
  id: WireId;
  tripped: boolean;
  summary: string;
  detail?: Record<string, unknown>[];
}

/** Every wire is reported, tripped or not — a quiet panel and a lost panel must not look the same. */
export function evaluateTripWires(
  cfg: HarnessConfig,
  usage: ActionsUsage | null | undefined,
  triage: FleetTriage | null | undefined,
  pipeline: IssuePipeline | null | undefined,
  rotation: TokenRotation | null | undefined,
  now: Date,
): TripWire[] {
  const tw = cfg.trip_wires;
  const wires: TripWire[] = [];
  const wire = (id: WireId, tripped: boolean, summary: string, detail?: Record<string, unknown>[]) => {
    const entry: TripWire = { id, tripped: !!tripped, summary };
    if (detail && detail.length) entry.detail = detail;
    wires.push(entry);
  };
  const has = (data: unknown): boolean => isRecord(data) && Object.keys(data).length > 0;

  // 1. stale-data — the observability layer watching itself.
  const sources: [SignalName, unknown][] = [
    ['actions_usage', usage],
    ['fleet_triage', triage],
    ['issue_pipeline', pipeline],
    ['token_rotation', rotation],
  ];
  const stale: Record<string, unknown>[] = [];
  for (const [name, data] of sources) {
    const limit = name === 'token_rotation' ? ROTATION_STALE_DAYS : tw.stale_data_days;
    const age = sourceAgeDays(data, now);
    if (!has(data)) stale.push({ source: name, age_days: null, why: 'missing' });
    else if (age === null) stale.push({ source: name, age_days: null, why: 'no generated_at' });
    else if (age > limit) stale.push({ source: name, age_days: age, why: `older than ${limit}d` });
  }
  wire(
    'stale-data',
    stale.length > 0,
    stale.length ? 'a committed fleet signal stopped refreshing' : 'all fleet signals fresh',
    stale,
  );

  const uTot = usage?.totals ?? {};

  // 2. pass-rate-floor — fleet-wide quality regression.
  const rate = num(uTot.success_rate_pct);
  wire(
    'pass-rate-floor',
    rate !== null && rate < tw.pass_rate_floor_pct,
    `fleet workflow success rate ${fmtFloat(rate)}% vs floor ${fmt(tw.pass_rate_floor_pct)}%`,
  );

  // 3. waste-ceiling — minutes ending in non-success, as a share of all minutes.
  let wastePct: number | null = null;
  const totalMin = num(uTot.total_min);
  if (totalMin) wastePct = round1((100 * (num(uTot.waste_min) ?? 0)) / totalMin);
  wire(
    'waste-ceiling',
    wastePct !== null && wastePct > tw.waste_ceiling_pct,
    `wasted minutes ${fmtFloat(wastePct)}% of total vs ceiling ${fmt(tw.waste_ceiling_pct)}%`,
  );

  // 4. cost-spike — a workflow whose average run dwarfs the fleet MEDIAN (never the mean:
  // one runaway must not raise the baseline that would have flagged it).
  const eligible = (Array.isArray(usage?.workflows) ? usage!.workflows! : []).filter(
    (w) =>
      isRecord(w) &&
      !w.external &&
      Math.trunc(num(w.runs) ?? 0) >= tw.cost_spike_min_runs &&
      num(w.avg_min) !== null,
  );
  const med = median(eligible.map((w) => num(w.avg_min)!));
  let spikes: UsageWorkflow[] = [];
  if (med) {
    // The absolute floor keeps a fleet of tiny workflows honest.
    const threshold = Math.max(med * tw.cost_spike_multiplier, tw.cost_spike_min_avg_min);
    spikes = eligible
      .filter((w) => num(w.avg_min)! >= threshold)
      .sort((a, b) => num(b.avg_min)! - num(a.avg_min)!)
      .slice(0, 5);
  }
  wire(
    'cost-spike',
    spikes.length > 0,
    med
      ? `workflows averaging ≥${fmtFloat(tw.cost_spike_multiplier)}× the fleet median (${fmtFloat(med)} min)`
      : 'no usable per-workflow cost data',
    spikes.map((w) => ({
      repo: w.repo ?? null,
      workflow: w.workflow ?? null,
      path: w.path ?? null,
      avg_min: w.avg_min ?? null,
      runs: w.runs ?? null,
    })),
  );

  // 5. standing-failures — the backlog the doctor drains is growing past its caps.
  const failing = num(triage?.totals?.failing_workflows);
  wire(
    'standing-failures',
    failing !== null && failing > tw.standing_failures_max,
    `${fmt(failing)} standing red workflows vs max ${fmt(tw.standing_failures_max)}`,
  );

  // 6. credential-overdue — a credential aged past its own rotation policy plus grace.
  const overdue: Record<string, unknown>[] = [];
  for (const token of rotation?.tokens ?? []) {
    if (!isRecord(token)) continue;
    const age = num(token.oldest_age_days);
    const maxAge = num(token.max_age_days);
    if (age !== null && maxAge !== null && age > maxAge + tw.credential_grace_days) {
      overdue.push({ name: token.name ?? null, oldest_age_days: age, max_age_days: maxAge });
    }
  }
  wire(
    'credential-overdue',
    overdue.length > 0,
    overdue.length
      ? 'a fleet credential is past its rotation policy plus grace'
      : 'credential ages within policy',
    overdue,
  );

  return wires;
}

/** Python's str() for an int-typed value the summaries interpolate (`None` when absent). */
export function fmt(v: number | null): string {
  return v === null ? 'None' : String(v);
}

/**
 * Python's str() for a float-typed value: an integral float prints with `.0` (`3.0`, `90.0`).
 * The hub's rates, percentages, medians, and the multiplier/floor thresholds are floats there
 * (`round(x, 1)` results and `3.0` / `5.0` in fleet.yml), so their summaries carry the decimal.
 */
export function fmtFloat(v: number | null): string {
  if (v === null) return 'None';
  return Number.isInteger(v) ? v.toFixed(1) : String(v);
}

// ── entry point ────────────────────────────────────────────────────────────

export interface HarnessHealth {
  generated_at: string;
  sources: Record<SignalName, { present: boolean; age_days: number | null }>;
  scorecard: Scorecard;
  trip_wires: TripWire[];
  tripped_count: number;
  note: string;
}

export const HARNESS_NOTE =
  'Six-layer harness health: scorecard + trip wires computed offline from the committed fleet signals (docs/HARNESS.md). Thresholds live in _data/fleet.yml `harness:`. A tripped wire is an attention item; the doctor and issue-pipeline loops own the fixes.';

/** `%Y-%m-%d %H:%M UTC`, the hub's stamp. */
export function stampUtc(now: Date): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${now.getUTCFullYear()}-${p(now.getUTCMonth() + 1)}-${p(now.getUTCDate())} ${p(now.getUTCHours())}:${p(now.getUTCMinutes())} UTC`;
}

/** The hub's `run()`: the committed `harness_health.yml`, as data. */
export function harnessHealth(
  signals: HarnessSignals,
  cfg: HarnessConfig = DEFAULT_CONFIG,
  now: Date = new Date(),
): HarnessHealth {
  const usage = signals.actions_usage ?? null;
  const triage = signals.fleet_triage ?? null;
  const pipeline = signals.issue_pipeline ?? null;
  const rotation = signals.token_rotation ?? null;
  const scorecard = buildScorecard(cfg, usage, triage, pipeline, rotation);
  const wires = evaluateTripWires(cfg, usage, triage, pipeline, rotation, now);
  const has = (d: unknown) => isRecord(d) && Object.keys(d).length > 0;
  const sources = Object.fromEntries(
    ([
      ['actions_usage', usage],
      ['fleet_triage', triage],
      ['issue_pipeline', pipeline],
      ['token_rotation', rotation],
    ] as [SignalName, unknown][]).map(([name, data]) => [
      name,
      { present: has(data), age_days: sourceAgeDays(data, now) },
    ]),
  ) as HarnessHealth['sources'];
  return {
    generated_at: stampUtc(now),
    sources,
    scorecard,
    trip_wires: wires,
    tripped_count: wires.filter((w) => w.tripped).length,
    note: HARNESS_NOTE,
  };
}

// ── tolerant readers for the committed files ───────────────────────────────

/** Keep only the fields the engine reads (untrusted YAML never travels further). */
export function toActionsUsage(v: unknown): ActionsUsage | null {
  if (!isRecord(v)) return null;
  const totals = isRecord(v.totals) ? v.totals : {};
  const workflows = Array.isArray(v.workflows)
    ? v.workflows.filter(isRecord).map((w) => ({
        repo: typeof w.repo === 'string' ? w.repo : undefined,
        workflow: typeof w.workflow === 'string' ? w.workflow : undefined,
        path: typeof w.path === 'string' ? w.path : undefined,
        avg_min: num(w.avg_min) ?? undefined,
        runs: num(w.runs) ?? undefined,
        success: num(w.success) ?? undefined,
        external: w.external === true,
      }))
    : undefined;
  return {
    generated_at: typeof v.generated_at === 'string' ? v.generated_at : undefined,
    totals: {
      success_rate_pct: num(totals.success_rate_pct) ?? undefined,
      effectiveness_pct: num(totals.effectiveness_pct) ?? undefined,
      total_min: num(totals.total_min) ?? undefined,
      waste_min: num(totals.waste_min) ?? undefined,
      waste_hours: num(totals.waste_hours) ?? undefined,
    },
    ...(workflows ? { workflows } : {}),
  };
}

export function toFleetTriage(v: unknown): FleetTriage | null {
  if (!isRecord(v)) return null;
  const totals = isRecord(v.totals) ? v.totals : {};
  return {
    generated_at: typeof v.generated_at === 'string' ? v.generated_at : undefined,
    totals: {
      failing_workflows: num(totals.failing_workflows) ?? undefined,
      repos_red: num(totals.repos_red) ?? undefined,
    },
  };
}

export function toIssuePipeline(v: unknown): IssuePipeline | null {
  if (!isRecord(v)) return null;
  const totals = isRecord(v.totals) ? v.totals : {};
  const stages: Record<string, number> = {};
  if (isRecord(totals.stages)) {
    for (const [k, s] of Object.entries(totals.stages)) {
      const n = num(s);
      if (n !== null) stages[k] = n;
    }
  }
  return {
    generated_at: typeof v.generated_at === 'string' ? v.generated_at : undefined,
    totals: {
      pipeline_prs: num(totals.pipeline_prs) ?? undefined,
      ...(isRecord(totals.stages) ? { stages } : {}),
    },
  };
}

export function toTokenRotation(v: unknown): TokenRotation | null {
  if (!isRecord(v)) return null;
  const tokens = Array.isArray(v.tokens)
    ? v.tokens.filter(isRecord).map((t) => ({
        name: typeof t.name === 'string' ? t.name : undefined,
        oldest_age_days: num(t.oldest_age_days) ?? undefined,
        max_age_days: num(t.max_age_days) ?? undefined,
      }))
    : undefined;
  return {
    generated_at: typeof v.generated_at === 'string' ? v.generated_at : undefined,
    ...(tokens ? { tokens } : {}),
  };
}

// ── the committed harness_health.yml, read back ─────────────────────────────

/** The hub's committed `harness_health.yml` as data, or null when the document is not one. */
export function toHarnessHealth(v: unknown): HarnessHealth | null {
  if (!isRecord(v) || !isRecord(v.scorecard) || !Array.isArray(v.trip_wires)) return null;
  const sc = v.scorecard;
  const scorecard = Object.fromEntries(
    SCORECARD_KEYS.map((k) => {
      const m = isRecord(sc[k]) ? sc[k] : {};
      const metric: Metric = {
        value: num(m.value),
        direction: m.direction === 'up' || m.direction === 'down' ? m.direction : 'steady',
      };
      const threshold = num(m.threshold);
      if (threshold !== null) metric.threshold = threshold;
      if (m.status === 'ok' || m.status === 'warn' || m.status === 'unknown') metric.status = m.status;
      return [k, metric];
    }),
  ) as Scorecard;
  const wires: TripWire[] = v.trip_wires.filter(isRecord).flatMap((w) => {
    const id = WIRE_IDS.find((x) => x === w.id);
    if (!id) return [];
    const wire: TripWire = {
      id,
      tripped: w.tripped === true,
      summary: typeof w.summary === 'string' ? w.summary : '',
    };
    if (Array.isArray(w.detail)) wire.detail = w.detail.filter(isRecord);
    return [wire];
  });
  const src = isRecord(v.sources) ? v.sources : {};
  const sources = Object.fromEntries(
    SIGNAL_NAMES.map((name) => {
      const s = isRecord(src[name]) ? src[name] : {};
      return [name, { present: s.present === true, age_days: num(s.age_days) }];
    }),
  ) as HarnessHealth['sources'];
  return {
    generated_at: typeof v.generated_at === 'string' ? v.generated_at : String(v.generated_at ?? ''),
    sources,
    scorecard,
    trip_wires: wires,
    tripped_count: num(v.tripped_count) ?? wires.filter((w) => w.tripped).length,
    note: typeof v.note === 'string' ? v.note : '',
  };
}
