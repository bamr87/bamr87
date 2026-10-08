// Claude spend and Actions minutes: window totals, week over week, projected
// month vs the ceiling (last-7-day average × 30.44), and the daily series.
import { Link } from 'react-router';
import { Anchor, Group, Paper, SimpleGrid, Stack, Table, Text } from '@mantine/core';
import { useStateDoc } from '../api/hooks';
import type { Trend } from '../api/types';
import { ColumnChart } from '../components/Charts';
import { External, Load, Meter, PageHeader, Section, Status } from '../components/ui';
import { RunButton } from '../jobs/RunButton';
import { fmt, usd } from '../lib/format';
import { to } from '../lib/links';

function TrendCard({ title, t, money }: { title: string; t: Trend; money: boolean }) {
  const f = (v: number | null | undefined) => (money ? usd(v) : `${fmt(v, 0)} min`);
  const st = t.status === 'breach' ? <Status tone="crit">over ceiling</Status> : t.status === 'growing' ? <Status tone="warn">growing</Status>
    : t.status === 'ok' ? <Status tone="good">ok</Status> : <Status tone="info">{t.status ?? 'no data'}</Status>;
  return (
    <Paper p="md">
      <Group justify="space-between" mb="xs"><Text fw={600}>{title}</Text>{st}</Group>
      <Table className="dt" verticalSpacing={4}>
        <Table.Tbody>
          <Table.Tr><Table.Td>Window total</Table.Td><Table.Td className="num">{f(t.window_total)}</Table.Td></Table.Tr>
          <Table.Tr><Table.Td>Last 7 days / prior 7</Table.Td><Table.Td className="num">{f(t.last7)} / {f(t.prior7)}</Table.Td></Table.Tr>
          <Table.Tr><Table.Td>Week over week</Table.Td><Table.Td className="num">{t.wow_delta_pct == null ? '—' : `${t.wow_delta_pct}%`}</Table.Td></Table.Tr>
          <Table.Tr><Table.Td fw={600}>Projected month</Table.Td><Table.Td className="num" fw={600}>{f(t.projected_monthly)} <Text span c="dimmed" size="xs">vs {f(t.budget_monthly)}</Text></Table.Td></Table.Tr>
        </Table.Tbody>
      </Table>
      <div style={{ marginTop: 8 }}><Meter value={t.projected_monthly ?? 0} cap={t.budget_monthly ?? 1} /></div>
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
              description={<>From the committed ledgers. Ceilings and the growth threshold are <Anchor component={Link} to={to.config('harnesses')}>harnesses.budget</Anchor>. Per-run agent cost is on <Anchor component={Link} to={to.activity()}>Agent activity</Anchor>; deeper attribution on the Pages boards <External href="https://bamr87.github.io/bamr87/ai-usage/">/ai-usage/</External> and <External href="https://bamr87.github.io/bamr87/actions/">/actions/</External>.</>}
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
          </>
        );
      }}
    </Load>
  );
}
