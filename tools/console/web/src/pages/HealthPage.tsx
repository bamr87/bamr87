// The hub's own six-layer harness health (_data/harness_health.yml, docs/HARNESS.md):
// trip wires first (tripped on top), then the scorecard with each metric's
// desired direction and threshold. Shown in the TUI's Harness tab too.
import { Link } from 'react-router';
import { Anchor, Group, Paper, SimpleGrid, Stack, Text } from '@mantine/core';
import { IconArrowDown, IconArrowUp, IconMinus } from '@tabler/icons-react';
import { useStateDoc } from '../api/hooks';
import { DataTable } from '../components/DataTable';
import { External, Load, PageHeader, Section, Status } from '../components/ui';
import { RunButton } from '../jobs/RunButton';
import { fmt } from '../lib/format';
import { gh, to } from '../lib/links';

const WIRE_PAGE: Record<string, string> = {
  'stale-data': '/', 'pass-rate-floor': '/inbox?kind=workflow', 'waste-ceiling': '/costs', 'budget': '/costs',
  'standing-failures': '/inbox?kind=workflow', 'credential-age': '/auth',
};

export function HealthPage() {
  const state = useStateDoc();
  return (
    <Load q={state}>
      {(s) => {
        const wires = [...(s.health?.trip_wires ?? [])].sort((a, b) => Number(b.tripped) - Number(a.tripped));
        const score = Object.entries(s.health?.scorecard ?? {});
        return (
          <>
            <PageHeader
              title="Harness health"
              description={<>The control plane's own scorecard and trip wires, computed offline from the committed fleet signals. Thresholds live in <Anchor component={Link} to={to.config('harness')}>fleet.yml harness:</Anchor>. See <External href={gh.hubFile('docs/HARNESS.md')}>docs/HARNESS.md</External>.</>}
              actions={<RunButton op="harness">Recompute scorecard</RunButton>}
            />
            <Section mt={0} title={`Trip wires (${wires.filter((w) => w.tripped).length} of ${wires.length} tripped)`}>
              <DataTable
                rows={wires}
                keys
                rowKey={(w) => w.id}
                href={(w) => WIRE_PAGE[w.id] ?? null}
                tone={(w) => (w.tripped ? 'crit' : undefined)}
                empty="no trip wires — the scorecard has not been generated"
                columns={[
                  { key: 'state', header: '', render: (w) => (w.tripped ? <Status tone="crit">tripped</Status> : <Status tone="good">ok</Status>), width: 100 },
                  { key: 'id', header: 'wire', render: (w) => <Text ff="monospace" size="sm">{w.id}</Text> },
                  { key: 'summary', header: 'reading', render: (w) => <Text size="sm">{w.summary}</Text> },
                ]}
              />
            </Section>
            <Section title="Scorecard" description={`Generated ${s.health?.generated_at ?? '—'}. Arrows show which way is better.`}>
              <SimpleGrid cols={{ base: 1, xs: 2, md: 3 }} spacing="sm">
                {score.map(([k, m]) => {
                  const Arrow = m.direction === 'up' ? IconArrowUp : m.direction === 'down' ? IconArrowDown : IconMinus;
                  return (
                    <Paper key={k} p="md">
                      <Stack gap={4}>
                        <Group justify="space-between" gap={6}>
                          <Text size="sm" c="dimmed">{k.replace(/_/g, ' ')}</Text>
                          {m.status === 'ok' ? <Status tone="good">ok</Status> : m.status === 'warn' ? <Status tone="warn">below target</Status> : null}
                        </Group>
                        <Group gap={6} align="baseline">
                          <Text fz={24} fw={600}>{fmt(m.value)}</Text>
                          <Arrow size={14} color="var(--ink-2)" aria-label={`better is ${m.direction}`} />
                        </Group>
                        {m.threshold != null ? <Text size="xs" c="dimmed">threshold {fmt(m.threshold)}</Text> : null}
                      </Stack>
                    </Paper>
                  );
                })}
              </SimpleGrid>
            </Section>
          </>
        );
      }}
    </Load>
  );
}
