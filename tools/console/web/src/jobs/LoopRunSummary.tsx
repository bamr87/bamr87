// A loop-run job's structured view — the fields tools/fleetcore/loopjob.py
// parsed from the engine's run record (or its status lines while it runs):
// status, spend labelled as the estimate it is, the tier, one row per item.
// The terminal dash writes the same fields as text under its log.
import { Group, Paper, Stack, Text } from '@mantine/core';
import type { LoopJob, LoopJobItem } from '../api/types';
import { DataTable } from '../components/DataTable';
import { Mono, Status, type Tone } from '../components/ui';

const TONES: Record<string, Tone> = {
  completed: 'good', validated: 'good', rehearsed: 'good', published: 'good', reused: 'good',
  skipped: 'info', blocked: 'warn', attention: 'warn', usage: 'warn', 'publish-skipped': 'warn',
  failed: 'crit', interrupted: 'crit', refused: 'crit', 'publish-refused': 'crit', 'publish-failed': 'crit',
};
const tone = (s: string | null | undefined): Tone => (s ? TONES[s] ?? 'info' : 'info');
const usd = (n: number | null | undefined) => (n == null ? '—' : `$${n.toFixed(2)}`);

export function LoopRunSummary({ f, done }: { f: LoopJob; done: boolean }) {
  if (!f.run_id && !f.status && !f.notes.length) return null;
  return (
    <Paper p="sm" mb="md" data-testid="loop-run-summary">
      <Stack gap={6}>
        <Group gap="sm" wrap="wrap">
          <Status tone={done ? tone(f.status) : 'info'}>{f.status ?? (done ? 'no run record' : 'running')}</Status>
          {f.loop ? <Text size="sm" fw={600}><Mono>{f.loop}/{f.step}</Mono>{f.target ? <Text span size="xs" c="dimmed"> on {f.target}</Text> : null}</Text> : null}
          {f.mode ? <Text size="xs" c="dimmed">{f.mode}</Text> : null}
          {f.spent_usd != null ? <Text size="sm">{usd(f.spent_usd)} spent <Text span size="xs" c="dimmed">({f.cost_label}{f.estimated_usd ? `, ${usd(f.estimated_usd)} of it estimated` : ''})</Text></Text> : null}
          {f.model ? <Text size="xs" c="dimmed">{f.model} · {f.max_turns} turns · {usd(f.cap_usd)} cap per attempt</Text> : null}
          {f.attempts != null ? <Text size="xs" c="dimmed">{f.attempts} attempt(s) · {f.published ?? 0} published</Text> : null}
          {f.usage_limited ? <Status tone="warn">usage window spent — queue stopped</Status> : null}
          {f.run_id ? <Text size="xs" c="dimmed">run <Mono>{f.run_id}</Mono></Text> : null}
        </Group>
        {f.items.length ? (
          <DataTable
            rows={f.items}
            rowKey={(i: LoopJobItem) => i.key}
            minWidth={640}
            columns={[
              { key: 'status', header: 'status', render: (i: LoopJobItem) => <Status tone={tone(i.status)}>{i.status}</Status> },
              { key: 'key', header: 'item', render: (i: LoopJobItem) => <Mono>{i.key}</Mono> },
              { key: 'outcome', header: 'outcome', render: (i: LoopJobItem) => <Text size="xs">{i.outcome ?? i.decision ?? '—'}</Text> },
              { key: 'cost', header: 'cost', num: true, render: (i: LoopJobItem) => <Text size="xs">{i.cost_usd == null ? '—' : `${usd(i.cost_usd)}${i.cost_source === 'estimated' ? ' est.' : ''}`}</Text> },
              { key: 'turns', header: 'turns', num: true, render: (i: LoopJobItem) => <Text size="xs">{i.turns ?? '—'}</Text> },
              { key: 'reason', header: 'reason', render: (i: LoopJobItem) => <Text size="xs" c="dimmed">{[i.reason, ...i.flags, i.context ?? ''].filter(Boolean).join(' · ') || '—'}</Text> },
            ]}
          />
        ) : null}
        {f.notes.length && !f.items.length ? <Text size="xs" c="dimmed">{f.notes.join(' · ')}</Text> : null}
      </Stack>
    </Paper>
  );
}
