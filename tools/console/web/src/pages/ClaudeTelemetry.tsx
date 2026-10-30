// Claude Code native OTel telemetry (/api/claude-telemetry, claude_telemetry.py):
// Prometheus claude_code_* counters + Elasticsearch api_request/tool_result events.
// Read-only. Cost is Claude Code's API-equivalent (estimate) — the subscription
// budget model lives in the Spend vs budget section, not here.
import { Badge, Group, Paper, SegmentedControl, SimpleGrid, Table, Text } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { api } from '../api/client';
import { Banner, Empty, Mono, Section, StatTile } from '../components/ui';

type Row = Record<string, any>;
const n = (v: unknown, d = 0) => (typeof v === 'number' ? v.toLocaleString(undefined, { maximumFractionDigits: d }) : '—');
const usd = (v: unknown) => (typeof v === 'number' ? `$${v.toFixed(2)}` : '—');
const rows = (v: unknown): Row[] => (Array.isArray(v) ? v : []);

export function ClaudeTelemetry() {
  const [win, setWin] = useState('24h');
  const q = useQuery({ queryKey: ['claude-telemetry', win], queryFn: () => api<Row>(`/api/claude-telemetry?window=${win}`), refetchInterval: 30_000 });
  const d = q.data ?? {};
  const m = (d.metrics ?? {}) as Row;
  const t = (m.totals ?? {}) as Row;
  const ev = (d.events ?? {}) as Row;
  const label = d.cost_label ?? 'API-equivalent (estimate)';
  return (
    <Section title="Claude Code telemetry (OTel)">
      <Group justify="space-between" mb="xs">
        <Text size="xs" c="dimmed">claude_code_* from Prometheus, events from Elasticsearch logs-fleet.claude-*</Text>
        <SegmentedControl size="xs" value={win} onChange={setWin} data={['1h', '24h', '7d']} />
      </Group>
      {q.error ? <Banner tone="warn">{(q.error as Error).message}</Banner> : null}
      {m.error ? <Banner tone="warn" title="Prometheus">{m.error}</Banner> : null}
      {ev.error ? <Banner tone="warn" title="Elasticsearch">{ev.error}</Banner> : null}
      <SimpleGrid cols={{ base: 2, md: 4 }} spacing="md">
        <StatTile label={`Sessions (${win})`} value={n(t.sessions)} sub={`active ${n(t.active_time_s)} s`} />
        <StatTile label={`Tokens (${win})`} value={n(t.tokens)} sub={rows(m.tokens).map((r) => `${r.type} ${n(r.value)}`).join(' · ') || '—'} />
        <StatTile label={`Cost — ${label}`} value={usd(t.cost_usd_api_equivalent)} sub="not the subscription bill" />
        <StatTile label="Code" value={`${n(t.lines_of_code)} lines`} sub={`${n(t.commits)} commits · ${n(t.pull_requests)} PRs · ${n(t.tool_decisions)} edit decisions`} />
      </SimpleGrid>
      {rows(m.tool_decisions).length ? (
        <Group gap="xs" mt="xs">{rows(m.tool_decisions).map((r) => <Badge key={`${r.tool_name}${r.decision}`} variant="light">{r.tool_name} {r.decision}: {n(r.value)}</Badge>)}</Group>
      ) : null}
      <Text size="sm" fw={600} mt="md">Sessions (api_request events)</Text>
      {rows(ev.sessions).length === 0 ? <Empty>No api_request events in this window.</Empty> : (
        <Paper p="xs"><Table verticalSpacing={4} striped>
          <Table.Thead><Table.Tr><Table.Th>Session</Table.Th><Table.Th>Last</Table.Th><Table.Th>Requests</Table.Th><Table.Th>Models</Table.Th><Table.Th>In / Out</Table.Th><Table.Th>Cache read / write</Table.Th><Table.Th>{label}</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>{rows(ev.sessions).map((s) => (
            <Table.Tr key={s.session}>
              <Table.Td><Mono>{s.session}</Mono></Table.Td><Table.Td>{(s.last ?? '').slice(0, 19).replace('T', ' ')}</Table.Td>
              <Table.Td data-num>{s.api_requests}</Table.Td><Table.Td>{(s.models ?? []).join(', ')}</Table.Td>
              <Table.Td data-num>{n(s.tokens?.input)} / {n(s.tokens?.output)}</Table.Td>
              <Table.Td data-num>{n(s.tokens?.cache_read)} / {n(s.tokens?.cache_creation)}</Table.Td>
              <Table.Td data-num>{usd(s.cost_usd_api_equivalent)}</Table.Td>
            </Table.Tr>))}</Table.Tbody>
        </Table></Paper>
      )}
      {ev.counts ? <Text size="xs" c="dimmed" mt="xs">events: {Object.entries(ev.counts as Row).map(([k, v]) => `${k} ${v}`).join(' · ')}</Text> : null}
    </Section>
  );
}
