// Live bot activity: one page, refreshed every 5 s over SSE (api/live.ts →
// /api/live/stream, app.py + live.py). Claude Code sessions on this machine
// (host collector, tools/console/live_collector.py), live Claude usage from
// Prometheus (Claude Code OTel), running jobs with a live log tail, spend vs
// budget, the harness scorecard and deep-dive progress. Spec:
// tools/console/docs/realtime-bot-dashboard-spec.md.
import { Anchor, Badge, Group, Paper, Progress, SimpleGrid, Stack, Table, Text } from '@mantine/core';
import { useState } from 'react';
import { Link } from 'react-router';
import { useLive } from '../api/live';
import { LogView, useJobTail } from '../jobs/JobLog';
import { Banner, Empty, LocalOnly, Meter, Mono, PageHeader, Section, StatTile, Status, type Tone } from '../components/ui';
import { hasConsole } from '../api/backend';
import { ClaudeTelemetry } from './ClaudeTelemetry';

type Row = Record<string, any>;
const n = (v: unknown, d = 2) => (typeof v === 'number' ? v.toLocaleString(undefined, { maximumFractionDigits: d }) : '—');
const usd = (v: unknown) => (typeof v === 'number' ? `$${v.toFixed(2)}` : '—');
const age = (s: number) => (s >= 86400 ? `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h` : s >= 3600 ? `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m` : `${Math.floor(s / 60)}m`);
const err = (x: Row | undefined) => (x && typeof x.error === 'string' ? x.error : null);

function Budget({ title, t, money, href }: { title: string; t: Row; money: boolean; href: string }) {
  const f = (v: unknown) => (money ? usd(v) : n(v, 0));
  const set = t?.budget_set && typeof t.budget_monthly === 'number';
  return (
    <StatTile
      href={href}
      label={title}
      value={f(t?.projected_monthly)}
      tone={set && t.projected_monthly > t.budget_monthly ? 'crit' : undefined}
      meter={set ? <Meter value={t.projected_monthly ?? 0} cap={t.budget_monthly} /> : null}
      sub={<>projected month · {set ? `budget ${f(t.budget_monthly)}` : 'budget unset'} · last 7d {f(t?.last7)}{t?.billed_this_month != null ? ` · billed so far ${f(t.billed_this_month)}` : ''}</>}
    />
  );
}

function JobTail({ id }: { id: string }) {
  const { raw } = useJobTail(id);
  return <LogView raw={raw.split('\n').slice(-60).join('\n')} height={220} placeholder="waiting for output…" />;
}

export function Live() {
  const { doc, transport, error, ticks } = useLive(5);
  const [jobSel, setJobSel] = useState<string | null>(null);
  if (!hasConsole()) return <LocalOnly what="Live activity" />;
  const tone: Tone = transport === 'sse' ? 'good' : transport === 'polling' ? 'warn' : 'info';
  const s = (doc?.sessions ?? {}) as Row;
  const cl = (doc?.claude_live ?? {}) as Row;
  const jobs = (doc?.jobs ?? {}) as Row;
  const spend = (doc?.spend ?? {}) as Row;
  const sc = ((doc?.health ?? {}) as Row).scorecard ?? {};
  const dd = ((doc?.deep_dive ?? {}) as Row).summary ?? {};
  const obs = (doc?.observability ?? {}) as Row;
  const running: Row[] = jobs.running ?? [];
  const shownJob = jobSel ?? running[0]?.id ?? (jobs.recent ?? [])[0]?.id ?? null;

  return (
    <>
      <PageHeader
        title="Live activity"
        description="Fleet bot activity, pushed every 5 s. Sessions come from the host collector (tools/console/live_collector.py), live Claude usage from Prometheus (Claude Code OTel), spend and health from the ledgers."
        actions={<Group gap="xs"><Status tone={tone}>{transport}</Status><Text size="xs" c="dimmed">updated {doc?.generated_at?.slice(11, 19) ?? '—'} UTC · #{ticks}</Text></Group>}
      />
      {error ? <Banner tone="warn" title="Feed error">{error}</Banner> : null}

      <SimpleGrid cols={{ base: 2, md: 4 }} spacing="md">
        <StatTile label="Claude sessions" value={`${s.counts?.active ?? 0} active / ${s.counts?.total ?? 0}`} sub={`collector ${s.collector ?? '—'}${s.age_s != null ? ` · ${n(s.age_s, 0)}s old` : ''}`} tone={s.collector === 'ok' ? undefined : 'crit'} />
        <StatTile label="Claude cost (24h, OTel)" value={usd(cl.cost_usd_24h)} sub={`1h ${usd(cl.cost_usd_1h)} · ${n(cl.tokens_1h, 0)} tokens/1h · ${n(cl.sessions_24h, 0)} sessions/24h`} href="/observe/metrics" />
        <StatTile label="Running jobs" value={running.length} sub={`${(jobs.recent ?? []).length} recent`} href="/jobs" />
        <StatTile label="Deep dive" value={`${dd.processed ?? 0}/${dd.total ?? '—'}`} meter={<Progress value={100 * (dd.progress ?? 0)} />} sub={`cycle ${dd.cycle ?? '—'} · day ${dd.day ?? '—'}/${dd.cycle_days ?? '—'} · today ${dd.today?.repo ?? '—'}`} href="/deep-dive" />
      </SimpleGrid>

      <Section title="Claude Code sessions (this Mac)">
        {err(s) ? <Banner tone="crit">{err(s)}</Banner> : null}
        {s.collector === 'missing' || s.collector === 'stale' ? <Banner tone="warn" title={`Collector ${s.collector}`}>Run <Mono>python3 tools/console/live_collector.py</Mono> on the host.</Banner> : null}
        {(s.sessions ?? []).length === 0 ? <Empty>No Claude processes.</Empty> : (
          <Paper p="xs"><Table verticalSpacing={4} striped>
            <Table.Thead><Table.Tr><Table.Th>State</Table.Th><Table.Th>Origin</Table.Th><Table.Th>PID</Table.Th><Table.Th>CPU %</Table.Th><Table.Th>RSS MB</Table.Th><Table.Th>Age</Table.Th><Table.Th>cwd</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>{(s.sessions as Row[]).map((x) => (
              <Table.Tr key={x.pid}>
                <Table.Td><Status tone={x.state === 'active' ? 'good' : 'info'}>{x.state}</Status></Table.Td>
                <Table.Td><Badge variant="light">{x.origin}</Badge></Table.Td>
                <Table.Td data-num>{x.pid}</Table.Td><Table.Td data-num>{n(x.cpu, 1)}</Table.Td><Table.Td data-num>{n(x.rss_mb, 0)}</Table.Td>
                <Table.Td>{age(x.age_s)}</Table.Td><Table.Td><Mono dim>{x.cwd ?? '—'}</Mono></Table.Td>
              </Table.Tr>))}</Table.Tbody>
          </Table></Paper>
        )}
      </Section>

      <ClaudeTelemetry />

      <Section title="Spend vs budget">
        <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
          <Budget title="Claude CI spend (dash ai)" t={spend.ai_cost_usd} money href="/costs" />
          <Budget title="GitHub Actions minutes" t={spend.actions_minutes} money={false} href="/costs" />
        </SimpleGrid>
        {err(spend) ? <Banner tone="crit">{err(spend)}</Banner> : null}
      </Section>

      <Section title="Jobs">
        {(jobs.recent ?? []).length === 0 ? <Empty>No jobs.</Empty> : (
          <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
            <Paper p="xs"><Stack gap={4}>{(jobs.recent as Row[]).map((j) => (
              <Group key={j.id} justify="space-between" wrap="nowrap" style={{ cursor: 'pointer', fontWeight: j.id === shownJob ? 600 : undefined }} onClick={() => setJobSel(j.id)}>
                <Text size="sm" truncate="end">{j.label ?? j.op}</Text>
                <Group gap={6} wrap="nowrap"><Status tone={j.status === 'running' ? 'info' : j.status === 'succeeded' ? 'good' : j.status === 'failed' ? 'crit' : 'warn'}>{j.status}</Status><Anchor component={Link} to={`/jobs/${j.id}`} size="xs">open</Anchor></Group>
              </Group>))}</Stack></Paper>
            {shownJob ? <JobTail key={shownJob} id={shownJob} /> : null}
          </SimpleGrid>
        )}
      </Section>

      <Section title="Harness scorecard">
        <SimpleGrid cols={{ base: 2, md: 4 }} spacing="md">
          {Object.entries(sc as Row).map(([k, v]: [string, any]) => (
            <StatTile key={k} href="/harnesses/health" label={k.replace(/_/g, ' ')} value={n(v?.value)} tone={v?.status && v.status !== 'ok' ? 'crit' : undefined}
              sub={`${v?.direction === 'up' ? 'higher is better' : 'lower is better'}${v?.threshold != null ? ` · threshold ${v.threshold}` : ''}${v?.status ? ` · ${v.status}` : ''}`} />
          ))}
        </SimpleGrid>
      </Section>

      <Section title="Observability planes">
        <Group gap="xs">{Object.entries(obs).filter(([k]) => k !== 'error').map(([k, v]: [string, any]) => (
          <Status key={k} tone={v?.reachable ? 'good' : 'crit'}>{k}</Status>))}
          <Anchor component={Link} to="/observe/traces" size="sm">traces</Anchor><Anchor component={Link} to="/activity" size="sm">agent activity</Anchor>
        </Group>
      </Section>
    </>
  );
}
