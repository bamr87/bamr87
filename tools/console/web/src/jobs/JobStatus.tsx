import { Badge, Group, Loader, Stack, Text, Tooltip } from '@mantine/core';
import { Status } from '../components/ui';
import type { JobDiagnostic } from '../api/types';

// `status` is what the job's process did; `state` (HUB-064) is what the console
// derives when it reads the job. They differ only where state says more: a
// running job whose log has gone quiet past its threshold reads `stalled`.
export function JobStatus({ status, state }: { status: string; state?: string | null }) {
  if (state === 'stalled' && status === 'running') {
    return <Status tone="warn" title="running, but its log has not grown past the operation's stall threshold">stalled</Status>;
  }
  if (status === 'succeeded') return <Status tone="good">succeeded</Status>;
  if (status === 'failed') return <Status tone="crit">failed</Status>;
  if (status === 'cancelled') return <Status tone="warn">cancelled</Status>;
  // The console restarted while this job ran; nothing finished it.
  if (status === 'interrupted') return <Status tone="warn" title="the console restarted while this job ran">interrupted</Status>;
  if (status === 'running') {
    // Status's info pill, with a spinner where the glyph goes.
    return <Badge variant="default" size="sm" leftSection={<Loader size={10} />}>running</Badge>;
  }
  return <Status tone="info">{status}</Status>;
}

/** Why a job may be slow (HUB-064): each diagnostic's code as a badge, its sentence beside it — or, compact, in a tooltip. */
export function JobDiagnostics({ items, compact = false }: { items?: JobDiagnostic[] | null; compact?: boolean }) {
  if (!items?.length) return null;
  if (compact) {
    return (
      <Group gap={4} wrap="wrap" data-testid="job-diagnostics">
        {items.map((d) => (
          <Tooltip key={d.code} label={d.detail} multiline maw={360}>
            <Badge size="xs" color="yellow" variant="light" miw="max-content">{d.code}</Badge>
          </Tooltip>
        ))}
      </Group>
    );
  }
  return (
    <Stack gap={4} data-testid="job-diagnostics">
      {items.map((d) => (
        <Group key={d.code} gap={8} wrap="nowrap" align="flex-start">
          <Badge size="xs" color="yellow" variant="light" miw="max-content">{d.code}</Badge>
          <Text size="xs" miw={0}>{d.detail}</Text>
        </Group>
      ))}
    </Stack>
  );
}
