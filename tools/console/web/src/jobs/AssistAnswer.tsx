// An assist job's structured view (core.assist_job_fields): the question, the
// page it was asked from, and the answer once the session ended — rendered as
// Markdown through the same sanitizer the site's posts go through — with the
// spend labelled as the estimate it is.
import { Group, Paper, Stack, Text } from '@mantine/core';
import type { AssistJob } from '../api/types';
import { Markdown } from '../components/Markdown';
import { Mono, Status, type Tone } from '../components/ui';

const tone = (o: string | null): Tone => (o === 'ok' ? 'good' : o == null ? 'info' : o === 'usage_limit' ? 'warn' : 'crit');

export function AssistAnswer({ a, done }: { a: AssistJob; done: boolean }) {
  return (
    <Paper p="sm" mb="md" data-testid="assist-answer">
      <Stack gap={6}>
        <Text size="xs" c="dimmed">Asked{a.context ? <> from <Mono>{a.context}</Mono></> : null}</Text>
        <Text size="sm" fw={600}>{a.question}</Text>
        {a.answer ? <Markdown source={a.answer} /> : <Text size="sm" c="dimmed">{done ? 'No answer was recorded — the log says why.' : 'Reading the fleet…'}</Text>}
        <Group gap="sm" wrap="wrap">
          {a.outcome ? <Status tone={tone(a.outcome)}>{a.outcome}</Status> : null}
          {a.cost_usd != null ? <Text size="xs" c="dimmed">${a.cost_usd.toFixed(4)} ({a.cost_label}{a.cost_source ? `, ${a.cost_source}` : ''})</Text> : null}
          {a.turns != null ? <Text size="xs" c="dimmed">{a.turns} turns</Text> : null}
          {a.models.length ? <Text size="xs" c="dimmed">{a.models.join(', ')}</Text> : null}
        </Group>
      </Stack>
    </Paper>
  );
}
