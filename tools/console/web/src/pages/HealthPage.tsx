// The hub's own six-layer harness health (_data/harness_health.yml, docs/HARNESS.md):
// trip wires first (tripped on top), then the scorecard with each metric's
// desired direction and threshold. Shown in the TUI's Harness tab too.
import { useState } from 'react';
import { Link } from 'react-router';
import { Anchor, Group, Paper, SegmentedControl, SimpleGrid, Stack, Text } from '@mantine/core';
import { IconArrowDown, IconArrowUp, IconMinus } from '@tabler/icons-react';
import { STATIC, asset } from '../api/backend';
import { useStateDoc } from '../api/hooks';
import { DataTable } from '../components/DataTable';
import { External, Load, PageHeader, Section, Status } from '../components/ui';
import { RunButton } from '../jobs/RunButton';
import { fmt } from '../lib/format';
import { gh, to } from '../lib/links';

const WIRE_PAGE: Record<string, string> = {
  'stale-data': '/overview', 'pass-rate-floor': '/inbox?kind=workflow', 'waste-ceiling': '/costs', 'budget': '/costs',
  'standing-failures': '/inbox?kind=workflow', 'credential-age': '/auth',
};

/** The archify diagrams in diagrams/ (tools/render-diagrams.sh), in reading order. */
export const DIAGRAMS: [string, string][] = [
  ['harness-layers.architecture', 'The six layers, mapped onto the hub'],
  ['fleet-pulse.workflow', 'fleet-pulse.yml — the daily loop'],
  ['fleet-signals.dataflow', 'Fleet signals — from GitHub to the alarm panel'],
  ['issue-pipeline.lifecycle', 'issue-pipeline.yml — labels as state'],
  ['repo-evolution.sequence', "repo-evolution.yml — a draft PR into a submodule's own upstream"],
];

/** The published copy on Pages (build-pages.sh copies them), the console's /diagrams route otherwise. */
const diagramUrl = (name: string) => (STATIC ? asset(`diagrams/${name}.html`) : `/diagrams/${name}.html`);

function Diagrams() {
  const [pick, setPick] = useState(DIAGRAMS[0][0]);
  const title = DIAGRAMS.find(([n]) => n === pick)?.[1] ?? pick;
  return (
    <Section title="How the loops run" description={<>Interactive diagrams authored as typed JSON in <External href={gh.hubFile('diagrams')}>diagrams/</External> and compiled by the vendored archify skill (<code>tools/render-diagrams.sh</code>). Each opens standalone with search, focus, route tracing, theme and export.</>}
      actions={<External href={diagramUrl(pick)} size="sm">open standalone</External>}>
      <SegmentedControl size="xs" mb="sm" value={pick} onChange={setPick} data={DIAGRAMS.map(([value, label]) => ({ value, label: label.split(' — ')[0] }))} style={{ maxWidth: '100%', overflowX: 'auto' }} />
      {/* Sandboxed without allow-same-origin: the diagram runs its own inline
          script, and this origin may hold a console or GitHub token. */}
      <iframe key={pick} src={diagramUrl(pick)} title={title} loading="lazy" sandbox="allow-scripts allow-popups allow-downloads"
        style={{ width: '100%', height: 760, border: '1px solid var(--grid)', borderRadius: 8, background: 'var(--surface)' }} />
    </Section>
  );
}

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
            <Diagrams />
          </>
        );
      }}
    </Load>
  );
}
