// The front door: how much needs attention, the fleet's vital signs, the
// ranked attention queue (each finding with its lever), and how fresh every
// signal is. Every tile, row and source is a link to the page that explains it.
import { Link, useNavigate } from 'react-router';
import { Anchor, Button, Group, Paper, SimpleGrid, Stack, Text } from '@mantine/core';
import { useStateDoc } from '../api/hooks';
import type { Attention, StateDoc } from '../api/types';
import { DataTable } from '../components/DataTable';
import { Load, Meter, PageHeader, RepoLink, Section, StatTile, Status } from '../components/ui';
import { RunButton } from '../jobs/RunButton';
import { useRunner } from '../jobs/JobRunner';
import { age, fmt, usd } from '../lib/format';
import { SOURCE_HOME, to } from '../lib/links';

/** What acting on a finding means: an operation, or the page that owns the lever. */
export function leverFor(a: Attention): { op?: string; params?: Record<string, unknown>; page?: string; label: string } | null {
  if (a.kind === 'coverage-gap' && /oauth/i.test(a.summary)) return { op: 'secrets-plan', label: 'Plan rotation' };
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

export function AttentionTable({ rows, showRepo = true }: { rows: Attention[]; showRepo?: boolean }) {
  const { runOp } = useRunner();
  const navigate = useNavigate();
  return (
    <DataTable
      rows={rows}
      keys
      rowKey={(a, i) => `${a.kind}:${a.repo}:${i}`}
      tone={(a) => (a.severity >= 80 ? 'crit' : a.severity >= 60 ? 'warn' : undefined)}
      href={(a) => (a.repo ? to.project(a.repo) : leverFor(a)?.page)}
      initialSort={{ key: 'sev', desc: true }}
      empty={<Status tone="good">nothing needs attention</Status>}
      columns={[
        { key: 'sev', header: 'sev', num: true, sort: (a) => a.severity, render: (a) => a.severity, width: 56 },
        { key: 'kind', header: 'kind', sort: (a) => a.kind, render: (a) => <Text span ff="monospace" fz={12.5} style={{ whiteSpace: 'nowrap' }}>{a.kind}</Text> },
        ...(showRepo ? [{ key: 'repo', header: 'repo', sort: (a: Attention) => a.repo ?? '', render: (a: Attention) => <RepoLink name={a.repo} /> }] : []),
        { key: 'summary', header: 'finding', render: (a) => <Text size="sm">{a.summary}</Text> },
        { key: 'lever', header: 'lever', render: (a) => <Text size="xs" c="dimmed">{a.action}</Text> },
        {
          key: 'act', header: '', render: (a) => {
            const l = leverFor(a);
            if (!l) return null;
            return (
              <Button size="compact-xs" variant="light" onClick={() => (l.op ? void runOp(l.op, l.params ?? {}) : l.page && navigate(l.page))}>
                {l.label}
              </Button>
            );
          },
        },
      ]}
    />
  );
}

function Tiles({ s }: { s: StateDoc }) {
  const hr = s.harnesses ?? {};
  const t = hr.totals ?? {};
  const tp = hr.throughput ?? {};
  const tr = hr.trends?.ai_cost_usd ?? {};
  const wires = s.health?.trip_wires ?? [];
  const tripped = wires.filter((w) => w.tripped).length;
  const tri = s.triage.totals ?? {};
  const pipe = (s.pipeline.totals ?? {}) as Record<string, unknown>;
  const baseTotal = (t.baseline_ok ?? 0) + (t.baseline_gaps ?? 0);
  return (
    <SimpleGrid cols={{ base: 1, xs: 2, md: 3, lg: 4 }} spacing="md">
      <StatTile href={to.harnesses()} label="AI workflows" value={fmt(t.ai_workflows)}
        sub={`in ${fmt(t.repos_with_ai)} / ${fmt(t.repos_scanned)} repos · scan ${hr.scan?.mode ?? 'none'}`} />
      <StatTile href={to.schedules()} label="Scheduled AI runs / day" value={fmt(tp.est_scheduled_ai_per_day)}
        meter={<Meter value={tp.est_scheduled_ai_per_day ?? 0} cap={tp.cap_fleet ?? 1} />}
        sub={`cap ${fmt(tp.cap_fleet)} · observed ${fmt(tp.observed_ai_runs_per_day)}/day, all triggers`} />
      <StatTile href={to.costs()} label="Projected monthly Claude spend" value={usd(tr.projected_monthly)}
        tone={tr.status === 'breach' ? 'crit' : undefined}
        meter={<Meter value={tr.projected_monthly ?? 0} cap={tr.budget_monthly ?? 1} />}
        sub={`ceiling ${usd(tr.budget_monthly)} · WoW ${tr.wow_delta_pct == null ? '—' : `${tr.wow_delta_pct}%`} · ${tr.status ?? ''}`} />
      <StatTile href={to.harnesses('gaps')} label="Repos at harness baseline" value={`${fmt(t.baseline_ok)} / ${baseTotal}`}
        meter={<Meter value={t.baseline_ok ?? 0} cap={baseTotal || 1} tone="good" />}
        sub={`${fmt(t.kit_upgradeable)} machine seeds upgradeable`} />
      <StatTile href={to.health()} label="Trip wires tripped" value={`${tripped} / ${wires.length}`} tone={tripped ? 'crit' : undefined}
        sub={`hub scorecard · ${s.health?.generated_at ?? 'no data'}`} />
      <StatTile href={to.inbox('workflow')} label="Standing failures" value={fmt(tri.failing_workflows)} tone={tri.failing_workflows ? 'crit' : undefined}
        sub={`${fmt(tri.repos_red)} repos red · ${fmt(tri.open_issues)} issues · ${fmt(tri.open_prs)} PRs open`} />
      <StatTile href={to.loop('issue_pipeline')} label="Issue pipeline — agent PRs open" value={fmt(pipe.pipeline_prs)}
        sub={Object.entries((pipe.stages ?? {}) as Record<string, number>).map(([k, v]) => `${k} ${v}`).join(' · ') || 'no stages'} />
      <StatTile href={to.projects()} label="Registry projects" value={fmt(s.registry.count)}
        sub={`${s.registry.projects.filter((p) => p.auto_evolve).length} opted into repo evolution`} />
    </SimpleGrid>
  );
}

function Freshness({ s }: { s: StateDoc }) {
  return (
    <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }} spacing="sm">
      {Object.entries(s.sources).map(([k, v]) => {
        const home = SOURCE_HOME[k];
        const tone = !v.present ? 'crit' : v.age_days == null ? 'info' : v.age_days > 3 ? 'warn' : 'good';
        return (
          <Paper key={k} p="sm">
            <Stack gap={4}>
              <Group justify="space-between" wrap="nowrap" gap={6}>
                {home ? <Anchor component={Link} to={home.page} ff="monospace" fz={12.5}>{k}</Anchor> : <Text ff="monospace" fz={12.5}>{k}</Text>}
                <Status tone={tone}>{v.present ? (v.age_days == null ? 'present' : `${age(v.age_days)} old`) : 'missing'}</Status>
              </Group>
              <Group justify="space-between" gap={6}>
                <Text size="xs" c="dimmed">{v.generated_at ?? 'no stamp'}</Text>
                {home?.op ? <RunButton op={home.op} variant="subtle" size="compact-xs">refresh</RunButton> : null}
              </Group>
            </Stack>
          </Paper>
        );
      })}
    </SimpleGrid>
  );
}

export function Overview() {
  const state = useStateDoc();
  return (
    <Load q={state} rows={8}>
      {(s) => {
        const attention = s.harnesses?.attention ?? [];
        return (
          <>
            <PageHeader
              title="Overview"
              description="Every finding names its lever. Nothing here writes to a fleet repo by itself: deploys are dry runs unless you confirm apply, and the console never commits — review generated data in git and commit it yourself."
              actions={<RunButton op="harnesses-offline">Recompute harness analytics</RunButton>}
            />
            <Paper p="lg" mb="lg">
              <Group gap="xl" wrap="wrap" align="center">
                <div>
                  <Text fz={48} fw={600} lh={1} c={attention.length ? 'var(--warning)' : 'var(--good)'}>{fmt(s.harnesses?.totals?.attention ?? attention.length)}</Text>
                  <Text c="dimmed" size="sm">attention items across the fleet's AI harnesses</Text>
                </div>
                <Text size="sm" c="dimmed" maw={620}>
                  Ranked strongest first from <code>_data/harness_registry.yml</code>. Click a row for its project; the button runs or opens its lever.
                  Snapshot {s.generated_at}.
                </Text>
              </Group>
            </Paper>
            <Tiles s={s} />
            <Section title="Attention queue">
              <AttentionTable rows={attention} />
            </Section>
            <Section title="Signal freshness" description="Each committed signal, how old it is, the page that renders it, and the operation that regenerates it.">
              <Freshness s={s} />
            </Section>
          </>
        );
      }}
    </Load>
  );
}
