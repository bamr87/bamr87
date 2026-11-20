// The front door, told as a story: a status strip (how healthy, how far from
// budget, what waits on the maintainer, how current the signals are), the two
// budgets with their direction, the harnesses against the standard, how work
// flows, the hub's own scorecard, when the AI crons fire, the attention queue
// grouped by the lever that clears it, and one timeline of signal freshness.
// Every number links to the page that explains it; the caveats are a footnote.
import { useMemo, useState, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router';
import { Anchor, Badge, Button, Group, Paper, SegmentedControl, SimpleGrid, Skeleton, Stack, Text, Tooltip } from '@mantine/core';
import { useDecisionCounts, useJobs, useNodes, useStateDoc } from '../api/hooks';
import { STATIC } from '../api/backend';
import type { Attention, Dict, HarnessRepo, HistoryPoint, ScheduleEntry, ScoreMetric, StateDoc, Trend } from '../api/types';
import { HBars } from '../components/Charts';
import { DataTable } from '../components/DataTable';
import { Load, Meter, PageHeader, RepoLink, Section, Status, type Tone } from '../components/ui';
import { Bullet, Delta, FreshnessTimeline, HeatStrip, SegmentBar, Sparkline, type Segment } from '../components/Viz';
import { JobStatus } from '../jobs/JobStatus';
import { RunButton } from '../jobs/RunButton';
import { useRunner } from '../jobs/JobRunner';
import { age, cronDays, cronHours, fmt, usd } from '../lib/format';
import { SOURCE_HOME, to } from '../lib/links';
import u from '../styles/utils.module.css';

/** A finding's severity band: the number stays in a tooltip, the band is what a row shows. */
const band = (sev: number): Tone => (sev >= 80 ? 'crit' : sev >= 60 ? 'warn' : 'info');
const BAND_LABEL: Record<Tone, string> = { crit: 'critical', warn: 'warning', info: 'advisory', good: 'ok' };
/** A finding's identity across sorts and groups (the index in a row key is not one). */
const sig = (a: Attention) => `${a.kind}:${a.repo ?? 'fleet'}:${a.summary}`;

/** What acting on a finding means: an operation, or the page that owns the lever. */
export function leverFor(a: Attention): { op?: string; params?: Record<string, unknown>; page?: string; label: string } | null {
  if (a.kind === 'coverage-gap' && /oauth/i.test(a.summary)) return { op: 'secrets-plan', label: 'Plan rotation' };
  // A standard-gap finding is one lever's whole group: the kit upgrade is an
  // operation, every other lever is worked from the rebuild plan.
  if (a.kind === 'standard-gap') {
    return a.lever === 'kit-upgrade'
      ? { op: 'deploy-gaps', params: { upgrade: true }, label: 'Upgrade seeds (dry run)' }
      : { page: `${to.harnesses()}?lever=${a.lever ?? ''}`, label: 'Open the rebuild plan' };
  }
  switch (a.kind) {
    case 'coverage-gap': return { op: 'deploy-gaps', label: 'Deploy kit (dry run)' };
    case 'kit-drift':
    case 'auth-drift': return { op: 'deploy-gaps', params: { upgrade: true }, label: 'Upgrade seeds (dry run)' };
    case 'harness-failing': return { op: 'remediate', label: 'Build fix queue' };
    case 'budget-breach': return { page: to.config('harnesses'), label: 'Budget settings' };
    case 'cost-trend': return { page: to.costs(), label: 'Open costs' };
    case 'throughput-fleet':
    case 'throughput-repo':
    case 'schedule-collision': return { page: a.repo ? to.schedules(a.repo) : to.schedules(), label: 'Open schedules' };
    default: return null;
  }
}

/** One key per lever, so the findings one run (or one page) works sit together. */
export function leverKey(a: Attention): string {
  const l = leverFor(a);
  if (!l) return `hand:${a.kind}`;
  // Page levers group by what the button says (each row still opens its own plan); operations by what they run.
  return l.op ? `op:${l.op}:${JSON.stringify(l.params ?? {})}` : `page:${l.label}`;
}

export function AttentionTable({ rows, showRepo = true, dense = false }: { rows: Attention[]; showRepo?: boolean; dense?: boolean }) {
  const { runOp } = useRunner();
  const navigate = useNavigate();
  // The job a row's lever started, by finding, so its outcome shows in the row; the list is polled while one is tracked.
  const [started, setStarted] = useState<Record<string, string>>({});
  const jobs = useJobs(Object.keys(started).length > 0);
  const act = async (a: Attention) => {
    const l = leverFor(a);
    if (!l) return;
    if (!l.op) {
      if (l.page) navigate(l.page);
      return;
    }
    const job = await runOp(l.op, l.params ?? {});
    if (job) setStarted((m) => ({ ...m, [sig(a)]: job.id }));
  };
  return (
    <DataTable
      rows={rows}
      keys
      dense={dense}
      rowKey={(a, i) => `${a.kind}:${a.repo ?? 'fleet'}:${i}`}
      rowLabel={(a) => `${BAND_LABEL[band(a.severity)]} · ${a.kind} · ${a.repo ?? 'fleet'}: ${a.summary}`}
      tone={(a) => (a.severity >= 80 ? 'crit' : a.severity >= 60 ? 'warn' : undefined)}
      href={(a) => (a.repo ? to.project(a.repo) : leverFor(a)?.page)}
      initialSort={{ key: 'sev', desc: true }}
      empty={<Status tone="good">nothing needs attention</Status>}
      columns={[
        {
          key: 'sev', header: 'sev', sort: (a) => a.severity, width: 104, render: (a) => (
            <Tooltip label={`severity ${a.severity} of 100`}>
              <span className={u.inlineBlock}><Status tone={band(a.severity)}>{BAND_LABEL[band(a.severity)]}</Status></span>
            </Tooltip>
          ),
        },
        { key: 'kind', header: 'kind', sort: (a) => a.kind, render: (a) => <Text span ff="monospace" fz={12.5} className={u.nowrap}>{a.kind}</Text> },
        ...(showRepo ? [{ key: 'repo', header: 'repo', sort: (a: Attention) => a.repo ?? '', render: (a: Attention) => <RepoLink name={a.repo} /> }] : []),
        { key: 'summary', header: 'finding', render: (a) => <Text size="sm">{a.summary}</Text> },
        { key: 'lever', header: 'lever', render: (a) => <Text size="xs" c="dimmed">{a.action}</Text> },
        {
          key: 'act', header: '', render: (a) => {
            const l = leverFor(a);
            if (!l) return null;
            const id = started[sig(a)];
            const job = id ? jobs.data?.find((j) => j.id === id) : undefined;
            return (
              <Group gap={6} wrap="wrap" justify="flex-end">
                {id ? (
                  <Anchor component={Link} to={to.job(id)} underline="never" aria-label="the job this lever started">
                    <JobStatus status={job?.status ?? 'queued'} state={job?.state} />
                  </Anchor>
                ) : null}
                <Button size="compact-xs" variant="light" onClick={() => void act(a)}>{l.label}</Button>
              </Group>
            );
          },
        },
      ]}
    />
  );
}

/** The queue by lever: five rows that share one button become one group with the button once, strongest group first. */
function AttentionByLever({ rows }: { rows: Attention[] }) {
  const groups = useMemo(() => {
    const m = new Map<string, Attention[]>();
    for (const a of rows) m.set(leverKey(a), [...(m.get(leverKey(a)) ?? []), a]);
    return [...m.entries()]
      .map(([key, items]) => ({ key, items, top: Math.max(...items.map((a) => a.severity)), lever: leverFor(items[0]) }))
      .sort((x, y) => y.top - x.top || y.items.length - x.items.length);
  }, [rows]);
  if (!rows.length) return <Status tone="good">nothing needs attention</Status>;
  return (
    <Stack gap="sm">
      {groups.map((g) => (
        <Paper key={g.key} p="sm" data-lever-group>
          <Group gap="xs" wrap="wrap" mb={6}>
            <Status tone={band(g.top)}>{BAND_LABEL[band(g.top)]}</Status>
            <Text size="sm" fw={600}>{g.lever?.label ?? `By hand: ${g.items[0].kind}`}</Text>
            <Text size="xs" c="dimmed">
              {g.items.length === 1 ? '1 finding' : `${g.items.length} findings`}
              {g.lever?.op ? ' · one run works the whole group' : g.lever?.page ? ' · worked from one page' : " · a setting or a commit: the maintainer's"}
            </Text>
          </Group>
          <AttentionTable rows={g.items} dense />
        </Paper>
      ))}
    </Stack>
  );
}

function AttentionQueue({ rows }: { rows: Attention[] }) {
  const [view, setView] = useState<'lever' | 'flat'>('lever');
  return (
    <Section
      title="Attention queue"
      description="Every finding with the lever that clears it. By lever, the findings one run or one page works sit together; a row still opens its project, and a lever's job shows its outcome in the row."
      actions={<SegmentedControl size="xs" value={view} onChange={(v) => setView(v as 'lever' | 'flat')} data={[{ label: 'By lever', value: 'lever' }, { label: 'Flat', value: 'flat' }]} />}
    >
      {view === 'lever' ? <AttentionByLever rows={rows} /> : <AttentionTable rows={rows} />}
    </Section>
  );
}

const Big = ({ children }: { children: ReactNode }) => <Text fz={26} fw={600} lh={1.1}>{children}</Text>;
const Small = ({ children }: { children: ReactNode }) => <Text span size="xs" c="dimmed" fw={400}>{children}</Text>;

/** One cell of the status strip: its title is the link to the page that explains it (never the whole tile, whose body holds links of its own). */
function Cell({ title, href, anchor, pill, children }: { title: string; href?: string; anchor?: string; pill?: ReactNode; children: ReactNode }) {
  const label = href
    ? <Anchor component={Link} to={href} size="sm" fw={600}>{title}</Anchor>
    : anchor ? <Anchor href={anchor} size="sm" fw={600}>{title}</Anchor> : <Text size="sm" fw={600}>{title}</Text>;
  return (
    <Paper p="md" data-cell={title}>
      <Stack gap={6}>
        <Group justify="space-between" gap={6} wrap="wrap">{label}{pill}</Group>
        {children}
      </Stack>
    </Paper>
  );
}

function BudgetLine({ label, value, ceiling, pct, breach }: { label: string; value: string; ceiling: string; pct: number | null | undefined; breach: boolean }) {
  return (
    <Group gap={6} wrap="wrap" justify="space-between">
      <Text size="sm">
        <Text span fw={600} c={breach ? 'var(--critical)' : undefined}>{value}</Text>
        {' '}<Text span size="xs" c="dimmed">{label} · ceiling {ceiling}</Text>
      </Text>
      <Delta pct={pct} better="down" />
    </Group>
  );
}

const DECISION_KIND: Record<string, string> = { needs_amr: 'needs Amr', ratification: 'awaiting ratification', dependabot: 'Dependabot', ready_to_merge: 'ready to merge' };

/** What waits on the maintainer: the decision index's counts, read on a console; the published page never carries them. */
function Decisions() {
  const q = useDecisionCounts();
  const d = q.data;
  const stale = d ? d.status !== 'fresh' : false;
  const pill = STATIC ? <Status tone="info">console</Status>
    : q.isError ? <Status tone="warn">index unavailable</Status>
      : d ? <Status tone={d.total ? (stale ? 'warn' : 'info') : 'good'}>{d.status}</Status> : null;
  const read = d?.age_s == null ? 'index age unknown' : `index read ${d.age_s < 3600 ? `${Math.round(d.age_s / 60)} min` : `${(d.age_s / 3600).toFixed(1)} h`} ago`;
  return (
    <Cell title="Waiting on you" href={to.prs()} pill={pill}>
      {STATIC ? <Text size="sm" c="dimmed">The decision index is read on a console with the operator's token; the published page never carries it.</Text>
        : q.isError ? <Text size="sm" c="dimmed">{(q.error as Error).message}</Text>
          : !d ? <Skeleton h={30} />
            : d.status === 'unavailable' ? <Text size="sm" c="dimmed">No decision index on this console yet: <code>tools/dash decisions refresh</code> builds it from GitHub.</Text>
            : (
              <>
                <Big>{fmt(d.total, 0)} <Small>decisions across the fleet</Small></Big>
                <Group gap={4} wrap="wrap">
                  {Object.entries(d.counts).map(([k, v]) => <Badge key={k} variant="light" size="sm" color={v ? undefined : 'gray'}>{DECISION_KIND[k] ?? k} {v}</Badge>)}
                </Group>
                <Text size="xs" c="dimmed">{read}{d.warnings?.length ? ` · ${d.warnings.length} caveat(s)` : ''}</Text>
              </>
            )}
    </Cell>
  );
}

function StatusStrip({ s, points }: { s: StateDoc; points: HistoryPoint[] }) {
  const hr = s.harnesses ?? {};
  const t = hr.totals ?? {};
  const attention = hr.attention ?? [];
  const tri = s.triage.totals ?? {};
  const red = tri.repos_red ?? 0;
  const amber = tri.repos_amber ?? 0;
  const scanned = s.triage.repos_scanned ?? t.repos_scanned ?? red + amber;
  const green = Math.max(0, scanned - red - amber);
  // The generator keeps the strongest `attention_max` findings: a count at the cap is a floor, not a total.
  const cap = Number((s.contract.harnesses as Dict<unknown> | undefined)?.attention_max ?? 20) || 20;
  const total = t.attention ?? attention.length;
  const capped = total >= cap;
  const counts = { crit: 0, warn: 0, info: 0 };
  const levers = new Map<string, number>();
  for (const a of attention) {
    const b = band(a.severity);
    if (b !== 'good') counts[b] += 1;
    levers.set(leverKey(a), (levers.get(leverKey(a)) ?? 0) + 1);
  }
  const biggest = Math.max(0, ...[...levers.values()]);
  const newestFirst = [...points].reverse();
  const below = newestFirst.findIndex((p) => p.attention != null && p.attention < cap);
  const daysAtCap = capped ? (below === -1 ? newestFirst.length : below) : 0;
  const ai = hr.trends?.ai_cost_usd ?? {};
  const mins = hr.trends?.actions_minutes ?? {};
  const breaches = [ai, mins].filter((x) => x.status === 'breach').length;
  const sources = Object.entries(s.sources);
  const dated = sources.filter(([, v]) => v.present && v.age_days != null).sort((a, b) => (b[1].age_days ?? 0) - (a[1].age_days ?? 0));
  const oldest = dated[0];
  const missing = sources.filter(([, v]) => !v.present).map(([k]) => k);
  const oldestTone: Tone = missing.length ? 'crit' : !oldest ? 'info' : (oldest[1].age_days ?? 0) > 3 ? 'warn' : 'good';
  const healthTone: Tone = red ? 'crit' : amber ? 'warn' : 'good';
  const healthSegs: Segment[] = [
    { key: 'red', label: 'red', value: red, tone: 'crit', href: to.inbox() },
    { key: 'amber', label: 'amber', value: amber, tone: 'warn', href: to.projects() },
    { key: 'green', label: 'green', value: green, tone: 'good', href: to.projects() },
  ];
  const sevSegs: Segment[] = [
    { key: 'crit', label: 'critical', value: counts.crit, tone: 'crit' },
    { key: 'warn', label: 'warning', value: counts.warn, tone: 'warn' },
    { key: 'info', label: 'advisory', value: counts.info, tone: 'info' },
  ];
  const attentionPill = counts.crit ? <Status tone="crit">{counts.crit} critical</Status>
    : counts.warn ? <Status tone="warn">{counts.warn} warning</Status>
      : attention.length ? <Status tone="info">advisory only</Status> : <Status tone="good">clear</Status>;
  return (
    <SimpleGrid cols={{ base: 1, xs: 2, lg: 5 }} spacing="md" data-status-strip>
      <Cell title="Fleet health" href={to.projects()} pill={<Status tone={healthTone}>{red ? `${red} red` : amber ? `${amber} amber` : 'all green'}</Status>}>
        <Big>{fmt(green, 0)} <Small>of {fmt(scanned, 0)} repos green</Small></Big>
        <SegmentBar segments={healthSegs} label="repos by health" />
        <Text size="xs" c="dimmed">{fmt(tri.failing_workflows, 0)} standing failures · {fmt(tri.prs_ci_failing, 0)} PRs with CI red</Text>
      </Cell>
      <Cell title="Attention" anchor="#attention" pill={attentionPill}>
        <Big>{capped ? `${cap}+` : fmt(total, 0)} <Small>findings{capped ? ', the list stops there' : ''}</Small></Big>
        <SegmentBar segments={sevSegs} label="findings by severity" />
        <Text size="xs" c="dimmed">
          {levers.size} levers · the biggest clears {biggest}
          {capped && daysAtCap ? ` · at the cap ${daysAtCap === 1 ? 'for a day' : `for ${daysAtCap} days`}` : ''}
        </Text>
      </Cell>
      <Cell title="Budgets" href={to.costs()} pill={<Status tone={breaches ? 'crit' : 'good'}>{breaches ? `${breaches} breached` : 'within'}</Status>}>
        <BudgetLine label="Claude" value={usd(ai.projected_monthly)} ceiling={usd(ai.budget_monthly)} pct={ai.wow_delta_pct} breach={ai.status === 'breach'} />
        <BudgetLine label="Actions" value={`${fmt(mins.projected_monthly, 0)} min`} ceiling={`${fmt(mins.budget_monthly, 0)} min`} pct={mins.wow_delta_pct} breach={mins.status === 'breach'} />
        <Text size="xs" c="dimmed">the projected month against the ceilings in fleet.yml</Text>
      </Cell>
      <Decisions />
      <Cell title="Signals" anchor="#freshness" pill={<Status tone={oldestTone}>{missing.length ? `${missing.length} missing` : oldest ? `${age(oldest[1].age_days)} old` : 'no stamps'}</Status>}>
        <Big>{oldest ? age(oldest[1].age_days) : '—'} <Small>oldest input{oldest ? `: ${oldest[0]}` : ''}</Small></Big>
        <Text size="xs" c="dimmed">{dated.filter(([, v]) => (v.age_days ?? 0) <= 1).length} of {sources.length} refreshed within a day · snapshot {s.generated_at}</Text>
      </Cell>
    </SimpleGrid>
  );
}

/** Where hub workloads run, in one line (the Nodes page in full): each node's
 * state and the placement-drift count. The published page probes nothing, so
 * it says drift is read on a console; a console that could read no node's
 * containers says it is not read. Neither shows a zero it never measured. */
function NodesLine() {
  const q = useNodes();
  const d = q.data;
  if (!d) return null;
  const tone = d.problems.length ? 'crit' : d.drift == null ? 'info' : d.drift.length ? 'warn' : 'good';
  const drift = d.drift != null ? `${d.drift.length} service(s)` : d.probed ? 'not read' : 'read on a console';
  return (
    <Paper p="sm" mt="md">
      <Group justify="space-between" wrap="wrap" gap="xs">
        <Group gap="xs" wrap="wrap">
          <Anchor component={Link} to={to.nodes()} fw={600} size="sm">Nodes</Anchor>
          {d.nodes.map((n) => (
            <Text key={n.name} size="sm" c={n.status === 'unknown' ? 'var(--warning)' : n.status === 'up' ? undefined : 'dimmed'}>
              {n.name} <Text span size="xs" c="dimmed">{n.role} · {n.status === 'unprobed' ? 'not probed' : n.status}</Text>
            </Text>
          ))}
        </Group>
        <Status tone={tone}>placement drift: {drift}{d.problems.length ? ` · ${d.problems.length} problem(s)` : ''}</Status>
      </Group>
    </Paper>
  );
}

function BudgetCard({ title, trend, format, values, labels, sub }: {
  title: string; trend: Trend; format: (v: unknown) => string; values: number[]; labels: string[]; sub: string;
}) {
  const breach = trend.status === 'breach';
  return (
    <Paper p="md" data-budget={title}>
      <Stack gap={6}>
        <Group justify="space-between" gap={6} wrap="nowrap">
          <Anchor component={Link} to={to.costs()} size="sm" fw={600}>{title}</Anchor>
          <Status tone={breach ? 'crit' : 'good'}>{breach ? 'over ceiling' : 'within ceiling'}</Status>
        </Group>
        <Group gap={8} align="baseline" wrap="wrap">
          <Text fz={26} fw={600} lh={1.1} c={breach ? 'var(--critical)' : undefined}>{format(trend.projected_monthly)}</Text>
          <Text size="xs" c="dimmed">projected this month · ceiling {format(trend.budget_monthly)}</Text>
        </Group>
        <Meter value={trend.projected_monthly ?? 0} cap={trend.budget_monthly ?? 1} />
        <Group gap="sm" wrap="wrap">
          <Delta pct={trend.wow_delta_pct} better="down" />
          <Text size="xs" c="dimmed">last 7 days {format(trend.last7)} · the 7 before {format(trend.prior7)}</Text>
        </Group>
        <Sparkline values={values} labels={labels} label={`${title} by day`} format={(v) => format(v)} />
        <Text size="xs" c="dimmed">{sub}</Text>
      </Stack>
    </Paper>
  );
}

function Budgets({ s }: { s: StateDoc }) {
  const ai = s.harnesses?.trends?.ai_cost_usd ?? {};
  const mins = s.harnesses?.trends?.actions_minutes ?? {};
  const aiDays = s.usage.ai?.by_day ?? [];
  const acDays = s.usage.actions?.by_day ?? [];
  const minutes = (v: unknown) => (v == null || v === '' ? '—' : `${fmt(v, 0)} min`);
  const aiSub = ai.measured_total != null
    ? `measured ${usd(ai.measured_total)} · estimated ${usd(ai.estimated_total)} (${fmt(ai.estimated_share_pct)}% of the window) · API-equivalent (estimate)`
    : 'API-equivalent (estimate)';
  const mom = mins.mom_delta_pct == null ? '' : ` (${mins.mom_delta_pct > 0 ? '+' : ''}${fmt(mins.mom_delta_pct)}% month over month)`;
  const minsSub = mins.billed_this_month != null
    ? `billing meter: ${fmt(mins.billed_this_month, 0)} min this month · ${fmt(mins.billed_previous_month, 0)} last month${mom}`
    : `source: ${mins.source ?? 'runs'}`;
  return (
    <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
      <BudgetCard title="Claude spend" trend={ai} format={usd} values={aiDays.map((d) => Number(d.cost_usd) || 0)} labels={aiDays.map((d) => d.day)} sub={aiSub} />
      <BudgetCard title="Actions minutes" trend={mins} format={minutes} values={acDays.map((d) => Number(d.total_min) || 0)} labels={acDays.map((d) => d.date)} sub={minsSub} />
    </SimpleGrid>
  );
}

/** The controls graded harnesses miss, counted from the repos when the catalog has no index. */
function missingFromRepos(repos: HarnessRepo[] | undefined): Dict<number> {
  const out: Dict<number> = {};
  for (const r of repos ?? []) for (const h of r.harnesses ?? []) for (const m of h.standard?.missing ?? []) out[m] = (out[m] ?? 0) + 1;
  return out;
}

function Harnesses({ s, points }: { s: StateDoc; points: HistoryPoint[] }) {
  const hr = s.harnesses ?? {};
  const t = hr.totals ?? {};
  const cat = hr.catalog ?? {};
  const tp = hr.throughput ?? {};
  const graded = cat.graded ?? t.harnesses_graded ?? 0;
  const conformant = cat.conformant ?? t.harnesses_conformant ?? 0;
  const retired = cat.retired ?? t.harnesses_retired ?? 0;
  const dormant = cat.dormant ?? t.harnesses_dormant ?? 0;
  // The catalog counts live harnesses (dormant ones, in archived repos, are outside it); graded = live with a verdict.
  const ungraded = Math.max(0, (cat.harnesses ?? graded) - graded);
  const segs: Segment[] = [
    { key: 'ok', label: 'conformant', value: conformant, tone: 'good', href: to.harnesses() },
    { key: 'off', label: 'off the standard', value: Math.max(0, graded - conformant), tone: 'warn', href: to.harnesses('gaps') },
    { key: 'ungraded', label: 'not graded', value: ungraded, tone: 'muted', hint: 'live, but without a verdict against the standard' },
  ];
  const outside = `${fmt(retired, 0)} in retired projects (lever: retire), ${fmt(dormant, 0)} of them dormant: the repo is archived and they cannot run`;
  const missing = Object.entries(cat.missing_by_control ?? missingFromRepos(hr.repos))
    .filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1]).slice(0, 6).map(([control, n]) => ({ control, n }));
  const series = points.filter((p) => p.harnesses_conformant != null);
  const sched = tp.est_scheduled_ai_per_day ?? 0;
  const observed = tp.observed_ai_runs_per_day ?? 0;
  const cap = tp.cap_fleet ?? 0;
  const top = Math.max(sched, observed, cap) * 1.1 || 1;
  const baseTotal = (t.baseline_ok ?? 0) + (t.baseline_gaps ?? 0);
  const share = graded ? Math.round((100 * conformant) / graded) : null;
  return (
    <SimpleGrid cols={{ base: 1, md: 3 }} spacing="md">
      <Paper p="md">
        <Stack gap={6}>
          <Group justify="space-between" gap={6} wrap="nowrap">
            <Anchor component={Link} to={to.harnesses()} size="sm" fw={600}>Against the standard</Anchor>
            <Status tone={share == null ? 'info' : share === 100 ? 'good' : 'warn'}>{share == null ? 'none graded' : `${share}% conformant`}</Status>
          </Group>
          <Big>{fmt(conformant, 0)} <Small>of {fmt(graded, 0)} harnesses meet it</Small></Big>
          <SegmentBar segments={segs} label="harnesses against the standard" />
          {series.length >= 2
            ? <Sparkline values={series.map((p) => p.harnesses_conformant ?? 0)} labels={series.map((p) => p.at)} label="conformant harnesses by day" format={(v) => fmt(v, 0)} height={32} />
            : null}
          <Text size="xs" c="dimmed">baseline seeded in {fmt(t.baseline_ok, 0)} of {baseTotal} repos · {fmt(t.kit_upgradeable, 0)} machine seeds upgradeable · {outside}</Text>
        </Stack>
      </Paper>
      <Paper p="md">
        <Stack gap={6}>
          <Anchor component={Link} to={to.harnesses('gaps')} size="sm" fw={600}>Most-missed controls</Anchor>
          <HBars rows={missing} label="control" value="n" />
          <Text size="xs" c="dimmed">graded harnesses missing each control; one harness can miss several</Text>
        </Stack>
      </Paper>
      <Paper p="md">
        <Stack gap={6}>
          <Group justify="space-between" gap={6} wrap="nowrap">
            <Anchor component={Link} to={to.schedules()} size="sm" fw={600}>AI runs per day</Anchor>
            <Status tone={observed > cap ? 'warn' : 'good'}>{observed > cap ? 'observed over the cap' : 'under the cap'}</Status>
          </Group>
          <Bullet label="scheduled (estimate)" value={sched} max={top} threshold={cap} tone={sched > cap ? 'crit' : 'info'} format={(v) => fmt(v)} />
          <Bullet label="observed, all triggers" value={observed} max={top} threshold={cap} tone={observed > cap ? 'warn' : 'info'} format={(v) => fmt(v)} />
          <Text size="xs" c="dimmed">
            the tick is the fleet cap of {fmt(cap, 0)} a day · {(tp.hour_collisions ?? []).length} crowded UTC hour(s) ·
            {' '}{fmt(t.scheduled_agents, 0)} scheduled agents, {fmt(t.scheduled_switched, 0)} with a kill switch
          </Text>
        </Stack>
      </Paper>
    </SimpleGrid>
  );
}

function Flow({ s }: { s: StateDoc }) {
  const pipe = (s.pipeline.totals ?? {}) as Record<string, unknown>;
  const stages = (pipe.stages ?? {}) as Record<string, number>;
  const order = ['intake', 'ready', 'in-pr', 'blocked', 'done'];
  const rows = [...order.filter((k) => k in stages), ...Object.keys(stages).filter((k) => !order.includes(k) && k !== 'hold')]
    .map((k) => ({ stage: k, n: stages[k] ?? 0 }));
  const tri = s.triage.totals ?? {};
  const prs = tri.open_prs ?? 0;
  const drafts = tri.draft_prs ?? 0;
  const prSegs: Segment[] = [
    { key: 'ready', label: 'ready for review', value: Math.max(0, prs - drafts), tone: 'info', href: to.prs() },
    { key: 'draft', label: 'drafts', value: drafts, tone: 'muted', href: to.prs() },
  ];
  const queued = ['intake', 'implement', 'complete'].map((k) => `${k} ${fmt(pipe[`queued_${k}`], 0)}`).join(' · ');
  return (
    <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
      <Paper p="md">
        <Stack gap={6}>
          <Group justify="space-between" gap={6} wrap="nowrap">
            <Anchor component={Link} to={to.loop('issue_pipeline')} size="sm" fw={600}>Issue pipeline</Anchor>
            <Text size="xs" c="dimmed">{fmt(pipe.pipeline_prs, 0)} agent PRs open</Text>
          </Group>
          {rows.length ? <HBars rows={rows} label="stage" value="n" /> : <Text size="sm" c="dimmed">no stages</Text>}
          <Text size="xs" c="dimmed">on hold {fmt(stages.hold, 0)} · queued for the next run: {queued}</Text>
        </Stack>
      </Paper>
      <Paper p="md">
        <Stack gap={6}>
          <Group justify="space-between" gap={6} wrap="nowrap">
            <Anchor component={Link} to={to.prs()} size="sm" fw={600}>Pull requests and issues</Anchor>
            <Status tone={tri.prs_ci_failing ? 'warn' : 'good'}>{fmt(tri.prs_ci_failing, 0)} with CI red</Status>
          </Group>
          <Big>{fmt(prs, 0)} <Small>pull requests open</Small></Big>
          <SegmentBar segments={prSegs} label="open pull requests" />
          <Text size="xs" c="dimmed">{fmt(tri.dependabot_prs, 0)} Dependabot · {fmt(tri.stale_prs, 0)} stale</Text>
          <Text size="sm" mt={4}>
            <Text span fw={600}>{fmt(tri.open_issues, 0)}</Text>
            {' '}<Text span size="xs" c="dimmed">issues open · {fmt(tri.open_bugs, 0)} bugs · {fmt(tri.stale_issues, 0)} stale ·</Text>
            {' '}<Anchor component={Link} to={to.inbox()} size="xs">inbox</Anchor>
          </Text>
        </Stack>
      </Paper>
    </SimpleGrid>
  );
}

const SCORE: Record<string, { label: string; unit: string; max?: number }> = {
  completion_rate_pct: { label: 'completion rate', unit: '%', max: 100 },
  effectiveness_pct: { label: 'effectiveness', unit: '%', max: 100 },
  waste_hours: { label: 'wasted hours', unit: ' h' },
  cost_min_per_verified_run: { label: 'minutes per verified run', unit: ' min' },
  standing_failures: { label: 'standing failures', unit: '' },
  repos_red: { label: 'repos red', unit: '' },
  escalations_open: { label: 'escalations open', unit: '' },
  agent_prs_open: { label: 'agent PRs open', unit: '' },
  oldest_credential_age_days: { label: 'oldest credential', unit: ' d' },
};

function Health({ s }: { s: StateDoc }) {
  const wires = [...(s.health?.trip_wires ?? [])].sort((a, b) => Number(b.tripped) - Number(a.tripped));
  const tripped = wires.filter((w) => w.tripped).length;
  const score = Object.entries(s.health?.scorecard ?? {}) as [string, ScoreMetric][];
  return (
    <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
      <Paper p="md">
        <Stack gap={2}>
          <Group justify="space-between" gap={6} wrap="nowrap" mb={4}>
            <Anchor component={Link} to={to.health()} size="sm" fw={600}>Scorecard</Anchor>
            <Text size="xs" c="dimmed">{s.health?.generated_at ?? 'not generated'}</Text>
          </Group>
          {score.length ? score.map(([k, m]) => {
            const meta = SCORE[k] ?? { label: k.replace(/_/g, ' '), unit: '' };
            const v = m.value ?? 0;
            const max = meta.max ?? (m.threshold != null ? Math.max(v, m.threshold) * 1.25 : 0);
            const tone: Tone = m.status === 'ok' ? 'good' : m.status === 'warn' ? 'warn' : m.status ? 'crit' : 'info';
            const better = m.direction === 'up' || m.direction === 'down' || m.direction === 'steady' ? m.direction : undefined;
            const edge = m.direction === 'down' ? 'ceiling' : 'floor';
            return (
              <Bullet key={k} label={meta.label} value={v} max={max} threshold={m.threshold} tone={tone} better={better}
                format={(x) => `${fmt(x)}${meta.unit}`} sub={m.threshold != null ? `${edge} ${fmt(m.threshold)}${meta.unit}` : undefined} />
            );
          }) : <Text size="sm" c="dimmed">the scorecard has not been generated</Text>}
        </Stack>
      </Paper>
      <Paper p="md">
        <Stack gap={6}>
          <Group justify="space-between" gap={6} wrap="nowrap">
            <Anchor component={Link} to={to.health()} size="sm" fw={600}>Trip wires</Anchor>
            <Status tone={tripped ? 'crit' : 'good'}>{tripped} of {wires.length} tripped</Status>
          </Group>
          {wires.length ? wires.map((w) => (
            <Group key={w.id} gap={8} wrap="nowrap" align="flex-start">
              <Status tone={w.tripped ? 'crit' : 'good'}>{w.tripped ? 'tripped' : 'ok'}</Status>
              <div>
                <Text size="sm" ff="monospace" fz={12.5}>{w.id}</Text>
                <Text size="xs" c="dimmed">{w.summary}</Text>
              </div>
            </Group>
          )) : <Text size="sm" c="dimmed">no trip wires — the scorecard has not been generated</Text>}
        </Stack>
      </Paper>
    </SimpleGrid>
  );
}

/** Every AI cron's cells, weekday × UTC hour: a cron contributes one to each cell it can fire in (hourly crons to every hour). */
function heatCells(entries: ScheduleEntry[]): number[][] {
  const cells = Array.from({ length: 7 }, () => Array.from({ length: 24 }, () => 0));
  for (const e of entries) {
    if (e.ai === false) continue;
    for (const d of cronDays(e.cron)) for (const h of cronHours(e.cron)) cells[d][h] += 1;
  }
  return cells;
}

function Crons({ s }: { s: StateDoc }) {
  const schedule = s.harnesses?.schedule;
  const collisions = s.harnesses?.throughput?.hour_collisions;
  const cells = useMemo(() => heatCells(schedule ?? []), [schedule]);
  const crowded = useMemo(() => {
    const set = new Set<string>();
    for (const c of collisions ?? []) for (const d of c.days ?? []) set.add(`${d}:${parseInt(c.utc_hour, 10)}`);
    return set;
  }, [collisions]);
  return <HeatStrip cells={cells} crowded={crowded} cap={s.harnesses?.throughput?.cap_per_utc_hour} />;
}

function Freshness({ s }: { s: StateDoc }) {
  const rows = Object.entries(s.sources).map(([k, v]) => {
    const home = SOURCE_HOME[k];
    const tone: Tone = !v.present ? 'crit' : v.age_days == null ? 'info' : v.age_days > 3 ? 'warn' : 'good';
    return {
      key: k,
      label: home ? <Anchor component={Link} to={home.page} ff="monospace" fz={12.5}>{k}</Anchor> : <Text ff="monospace" fz={12.5}>{k}</Text>,
      present: v.present,
      age_days: v.age_days,
      stamp: v.generated_at,
      tone,
      action: home?.op ? <RunButton op={home.op} variant="subtle" size="compact-xs">refresh</RunButton> : null,
    };
  });
  return <FreshnessTimeline rows={rows} />;
}

export function Overview() {
  const state = useStateDoc();
  return (
    <Load q={state} rows={8}>
      {(s) => {
        const attention = s.harnesses?.attention ?? [];
        const points = s.history?.points ?? [];
        const history = s.history?.source === 'git' ? `${s.history.days ?? points.length} day(s) of it here` : 'none here';
        return (
          <>
            <PageHeader
              title="Overview"
              description="The fleet in one screen: how healthy, how far from budget, what waits on you, and how current the signals are. Every number links to the page that explains it."
              actions={<RunButton op="harnesses-offline">Recompute harness analytics</RunButton>}
            />
            <StatusStrip s={s} points={points} />
            <NodesLine />
            <Section title="Budget direction" description="The projected month against each ceiling, the week-over-week turn, and the last fifteen days.">
              <Budgets s={s} />
            </Section>
            <Section title="Harnesses" description="Every AI workflow graded against the harness standard, the controls they most often lack, and how often the scheduled agents run.">
              <Harnesses s={s} points={points} />
            </Section>
            <Section title="Flow" description="Where open work sits in the issue pipeline, and the open pull requests and issues across the fleet.">
              <Flow s={s} />
            </Section>
            <Section title="Health" description="The hub's own scorecard against its thresholds, and the trip wires.">
              <Health s={s} />
            </Section>
            <Section title="When the AI crons fire" description="Every scheduled AI workflow by weekday and UTC hour. The Claude loops share one OAuth account's rate limit, so a crowded hour is a real risk, not a cosmetic one.">
              <Crons s={s} />
            </Section>
            <div id="attention">
              <AttentionQueue rows={attention} />
            </div>
            <div id="freshness">
              <Section title="Signal freshness" description="Each committed signal on one timeline (log scale: now, a day, a week, a month, a year), the page that renders it, and the operation that regenerates it.">
                <Freshness s={s} />
              </Section>
            </div>
            <Text size="xs" c="dimmed" mt="xl" maw={900}>
              Computed offline from the committed fleet signals, ranked strongest first from <code>_data/harness_registry.yml</code>; the trends are that file's own git history ({history}).
              Snapshot {s.generated_at}. Nothing here writes to a fleet repo by itself: deploys are dry runs unless you confirm apply, and the console never commits — review generated data in git and commit it yourself.
            </Text>
          </>
        );
      }}
    </Load>
  );
}
