// Every job the console runtime holds — started from this page, the terminal
// dash, or an agent through the fleet MCP server: one runtime, one list.
import { Link, useNavigate, useParams } from 'react-router';
import { Anchor, Badge, Button, Code, Group, Paper, SimpleGrid, Stack, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconPlayerStop, IconRepeat } from '@tabler/icons-react';
import { post } from '../api/client';
import { useJobs } from '../api/hooks';
import type { Job } from '../api/types';
import { DataTable } from '../components/DataTable';
import { Load, PageHeader, StatTile } from '../components/ui';
import { LogView, useJobTail } from '../jobs/JobLog';
import { useRunner } from '../jobs/JobRunner';
import { JobStatus } from '../jobs/JobStatus';
import { duration, when } from '../lib/format';
import { to } from '../lib/links';

const shortArgv = (j: Job) => j.argv.map((a) => a.replace(/^.*\/tools\//, 'tools/')).join(' ');

async function cancel(id: string) {
  try {
    await post(`/api/jobs/${id}/cancel`, {});
    notifications.show({ message: 'cancel requested' });
  } catch (e) {
    notifications.show({ color: 'red', message: (e as Error).message });
  }
}

export function Jobs() {
  const jobs = useJobs();
  return (
    <>
      <PageHeader
        title="Jobs"
        description="Every job this console process holds, whichever surface started it — this page, the terminal dash, or an agent through the fleet MCP server. Logs are kept for the life of the process."
        actions={<Button component={Link} to={to.ops()} size="xs">Run an operation</Button>}
      />
      <Load q={jobs}>
        {(list) => {
          const count = (s: string) => list.filter((j) => j.status === s).length;
          return (
            <>
              <SimpleGrid cols={{ base: 2, md: 4 }} spacing="md" mb="md">
                <StatTile label="Running" value={count('running') + count('queued')} />
                <StatTile label="Succeeded" value={count('succeeded')} />
                <StatTile label="Failed" value={count('failed')} tone={count('failed') ? 'crit' : undefined} />
                <StatTile label="Wrote to GitHub" value={list.filter((j) => j.remote_write).length} />
              </SimpleGrid>
              <DataTable<Job>
                rows={[...list].reverse()}
                keys
                rowKey={(j) => j.id}
                href={(j) => to.job(j.id)}
                tone={(j) => (j.status === 'failed' ? 'crit' : j.status === 'cancelled' ? 'warn' : undefined)}
                empty="No jobs yet. Every Run button in the console starts one."
                minWidth={860}
                columns={[
                  { key: 'status', header: 'status', sort: (j) => j.status, render: (j) => <JobStatus status={j.status} /> },
                  { key: 'op', header: 'operation', sort: (j) => j.title, render: (j) => <div><Text size="sm" fw={600}>{j.title}{j.remote_write ? <Badge ml={6} size="xs" color="yellow" variant="light">remote</Badge> : null}</Text><Code style={{ fontSize: 11, overflowWrap: 'anywhere' }}>{shortArgv(j)}</Code></div> },
                  { key: 'started', header: 'started', sort: (j) => j.started ?? '', render: (j) => <Text size="xs" c="dimmed">{when(j.started)}</Text> },
                  { key: 'dur', header: 'took', num: true, render: (j) => (j.started && j.finished ? duration(Date.parse(j.finished) - Date.parse(j.started)) : '') },
                  { key: 'exit', header: 'exit', num: true, render: (j) => j.exit_code ?? '' },
                  { key: 'x', header: '', render: (j) => (j.status === 'running' ? <Button size="compact-xs" color="red" variant="light" leftSection={<IconPlayerStop size={12} />} onClick={() => void cancel(j.id)}>Cancel</Button> : null) },
                ]}
              />
            </>
          );
        }}
      </Load>
    </>
  );
}

export function JobPage() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const { runOp } = useRunner();
  const { raw, tail, error } = useJobTail(id);
  const j = tail?.job;
  return (
    <>
      <PageHeader
        crumbs={[{ label: 'Jobs', to: to.jobs() }, { label: j?.title ?? id }]}
        title={j?.title ?? 'Job'}
        badges={j ? <><JobStatus status={j.status} />{j.remote_write ? <Badge color="yellow" variant="light">writes to GitHub</Badge> : null}</> : null}
        actions={j ? (
          <>
            <Anchor component={Link} to={to.op(j.op)} size="sm">About {j.op}</Anchor>
            {j.status === 'running' ? <Button size="xs" color="red" variant="light" leftSection={<IconPlayerStop size={14} />} onClick={() => void cancel(j.id)}>Cancel</Button> : null}
            {tail?.done ? (
              <Button size="xs" variant="default" leftSection={<IconRepeat size={14} />} onClick={async () => { const n = await runOp(j.op, j.params ?? {}); if (n) navigate(to.job(n.id)); }}>
                Run again
              </Button>
            ) : null}
          </>
        ) : null}
      />
      {error ? <Text c="red" size="sm" mb="sm">{error}</Text> : null}
      {j ? (
        <Paper p="sm" mb="md">
          <Stack gap={4}>
            <Code block style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{shortArgv(j)}</Code>
            <Group gap="lg">
              <Text size="xs" c="dimmed">started {when(j.started)}</Text>
              {j.finished ? <Text size="xs" c="dimmed">finished {when(j.finished)}</Text> : null}
              {j.exit_code != null ? <Text size="xs" c="dimmed">exit {j.exit_code}</Text> : null}
              {j.params && Object.keys(j.params).length ? <Text size="xs" c="dimmed">params <Code>{JSON.stringify(j.params)}</Code></Text> : null}
            </Group>
          </Stack>
        </Paper>
      ) : null}
      <LogView raw={raw} height="calc(100vh - 300px)" />
    </>
  );
}
