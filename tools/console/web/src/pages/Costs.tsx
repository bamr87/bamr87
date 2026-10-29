// Claude spend and Actions minutes: window totals, week over week, projected
// month vs the ceiling (last-7-day average × 30.44), and the daily series.
import { Link } from 'react-router';
import { Anchor, Group, Paper, SimpleGrid, Stack, Table, Text , Box } from '@mantine/core';
import { useData, useStateDoc } from '../api/hooks';
import type { Dict, Trend } from '../api/types';
import { DataTable } from '../components/DataTable';
import { ColumnChart } from '../components/Charts';
import { Load, Meter, Mono, PageHeader, RepoLink, Section, Status } from '../components/ui';
import { RunButton } from '../jobs/RunButton';
import { fmt, repoName, usd } from '../lib/format';
import { gh, to } from '../lib/links';

type Row = Dict<any>;

/** Where the minutes and the dollars go: the per-workflow and per-repo cuts of
 * the two committed ledgers (actions_usage.yml, ai_usage.yml) — what the
 * retired /actions/ and /ai-usage/ boards showed. */
function Attribution() {
  const actions = useData<Row>('actions_usage');
  const ai = useData<Row>('ai_usage');
  return (
    <>
      <Section title="Actions minutes by workflow" description="The most expensive workflows in the window. Effectiveness is the share of minutes in runs that succeeded; waste is the minutes in runs that failed or were cancelled.">
        <Load q={actions}>
          {(a) => (
            <DataTable<Row> rows={(a?.workflows ?? []).filter((w: Row) => !w.external)} keys rowKey={(w) => `${w.repo}:${w.path}`} minWidth={900}
              href={(w) => to.project(repoName(w.repo))} open={(w) => gh.workflowRuns(w.repo, w.path)}
              initialSort={{ key: 'min', desc: true }} maxHeight={520}
              tone={(w) => (w.effectiveness_pct != null && w.effectiveness_pct < 50 && w.total_min > 30 ? 'warn' : undefined)}
              columns={[
                { key: 'r', header: 'repo', sort: (w) => w.repo, render: (w) => <RepoLink nwo={w.repo} /> },
                { key: 'w', header: 'workflow', sort: (w) => w.workflow, render: (w) => <Text size="sm">{w.workflow}</Text> },
                { key: 't', header: 'type', sort: (w) => w.type, render: (w) => <Mono dim>{w.type}</Mono> },
                { key: 'runs', header: 'runs', num: true, sort: (w) => w.runs, render: (w) => w.runs },
                { key: 'min', header: 'minutes', num: true, sort: (w) => w.total_min, render: (w) => fmt(w.total_min, 0) },
                { key: 'p95', header: 'p95', num: true, sort: (w) => w.p95_min, render: (w) => fmt(w.p95_min) },
                { key: 'waste', header: 'waste', num: true, sort: (w) => w.waste_min, render: (w) => fmt(w.waste_min, 0) },
                { key: 'eff', header: 'effective', num: true, sort: (w) => w.effectiveness_pct, render: (w) => (w.effectiveness_pct == null ? '—' : `${w.effectiveness_pct}%`) },
              ]} />
          )}
        </Load>
      </Section>
      <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="md">
        <Section title="Claude in CI by repo">
          <Load q={ai}>
            {(d) => (
              <DataTable<Row> rows={d?.by_repo ?? []} rowKey={(r) => r.repo} href={(r) => to.project(repoName(r.repo))} initialSort={{ key: 'usd', desc: true }} maxHeight={420}
                columns={[
                  { key: 'r', header: 'repo', sort: (r) => r.repo, render: (r) => <RepoLink nwo={r.repo} /> },
                  { key: 'runs', header: 'runs', num: true, sort: (r) => r.runs, render: (r) => r.runs },
                  { key: 'turns', header: 'turns', num: true, sort: (r) => r.turns, render: (r) => r.turns },
                  { key: 'usd', header: 'cost', num: true, sort: (r) => r.cost_usd, render: (r) => usd(r.cost_usd) },
                ]} />
            )}
          </Load>
        </Section>
        <Section title="Claude in CI by workflow">
          <Load q={ai}>
            {(d) => (
              <DataTable<Row> rows={d?.by_workflow ?? []} rowKey={(r) => r.workflow} initialSort={{ key: 'usd', desc: true }} maxHeight={420}
                columns={[
                  { key: 'w', header: 'workflow', sort: (r) => r.workflow, render: (r) => <Text size="sm">{r.workflow}</Text> },
                  { key: 'runs', header: 'runs', num: true, sort: (r) => r.runs, render: (r) => r.runs },
                  { key: 'min', header: 'minutes', num: true, sort: (r) => r.minutes, render: (r) => fmt(r.minutes, 0) },
                  { key: 'usd', header: 'cost', num: true, sort: (r) => r.cost_usd, render: (r) => usd(r.cost_usd) },
                ]} />
            )}
          </Load>
        </Section>
      </SimpleGrid>
    </>
  );
}

function TrendCard({ title, t, money }: { title: string; t: Trend; money: boolean }) {
  const f = (v: number | null | undefined) => (money ? usd(v) : `${fmt(v, 0)} min`);
  const st = t.status === 'breach' ? <Status tone="crit">over ceiling</Status> : t.status === 'growing' ? <Status tone="warn">growing</Status>
    : t.status === 'ok' ? <Status tone="good">ok</Status> : <Status tone="info">{t.status ?? 'no data'}</Status>;
  return (
    <Paper p="md">
      <Group justify="space-between" mb="xs"><Text fw={600}>{title}</Text>{st}</Group>
      <Table verticalSpacing={4}>
        <Table.Tbody>
          <Table.Tr><Table.Td>Window total</Table.Td><Table.Td data-num>{f(t.window_total)}</Table.Td></Table.Tr>
          <Table.Tr><Table.Td>Last 7 days / prior 7</Table.Td><Table.Td data-num>{f(t.last7)} / {f(t.prior7)}</Table.Td></Table.Tr>
          <Table.Tr><Table.Td>Week over week</Table.Td><Table.Td data-num>{t.wow_delta_pct == null ? '—' : `${t.wow_delta_pct}%`}</Table.Td></Table.Tr>
          <Table.Tr><Table.Td fw={600}>Projected month</Table.Td><Table.Td data-num fw={600}>{f(t.projected_monthly)} <Text span c="dimmed" size="xs">vs {f(t.budget_monthly)}</Text></Table.Td></Table.Tr>
        </Table.Tbody>
      </Table>
      <Box mt={8}><Meter value={t.projected_monthly ?? 0} cap={t.budget_monthly ?? 1} /></Box>
    </Paper>
  );
}

export function Costs() {
  const state = useStateDoc();
  return (
    <Load q={state}>
      {(s) => {
        const tr = s.harnesses?.trends ?? {};
        const ai = s.usage.ai ?? {};
        const ac = s.usage.actions ?? {};
        return (
          <>
            <PageHeader
              title="Costs"
              description={<>From the committed ledgers. Ceilings and the growth threshold are <Anchor component={Link} to={to.config('harnesses')}>harnesses.budget</Anchor>. Per-run agent cost is on <Anchor component={Link} to={to.activity()}>Agent activity</Anchor>; attribution by workflow and repo is below.</>}
              actions={
                <>
                  <RunButton op="ai-usage">Refresh Claude ledger</RunButton>
                  <RunButton op="actions">Refresh Actions analytics</RunButton>
                  <RunButton op="harnesses-offline">Recompute trends</RunButton>
                </>
              }
            />
            <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
              <TrendCard title="Claude CI spend" t={tr.ai_cost_usd ?? {}} money />
              <TrendCard title="Actions minutes" t={tr.actions_minutes ?? {}} money={false} />
            </SimpleGrid>
            <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md" mt="md">
              <Section mt={0} title={`Claude spend by day (${fmt(ai.window_days)}-day window)`}>
                <Paper p="md">
                  <Stack gap={0}>
                    <ColumnChart rows={(ai.by_day ?? []) as Record<string, unknown>[]} label="day" series={[{ key: 'cost_usd', label: 'USD' }]} fmtLabel={(x) => String(x).slice(5)} />
                  </Stack>
                </Paper>
              </Section>
              <Section mt={0} title={`Actions minutes by day (${fmt(ac.window_days)}-day window)`}>
                <Paper p="md">
                  <ColumnChart rows={(ac.by_day ?? []) as Record<string, unknown>[]} label="date" series={[{ key: 'total_min', label: 'minutes' }]} fmtLabel={(x) => String(x).slice(5)} />
                </Paper>
              </Section>
            </SimpleGrid>
            <Attribution />
          </>
        );
      }}
    </Load>
  );
}
