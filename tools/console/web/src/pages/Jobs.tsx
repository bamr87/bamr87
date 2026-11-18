// Every job the console runtime holds — started from this page, the terminal
// dash, or an agent through the fleet MCP server: one runtime, one list.
//
// Two views of the same list. "Runs" is every job, newest first, filtered by
// status, group and text. "By operation" folds it to one row per operation —
// its latest result, how often it ran and how often it worked — which is the
// question once fifty operations have each run a few times. History survives
// a console restart (jobs.json beside the logs); "Clear finished" forgets
// finished jobs and deletes their logs, and never touches a running one.
//
// Each console job also carries what the console derives when it reads it
// (HUB-064, tools/console/docs/job-status.md): a state that turns `stalled`
// when a running job's log goes quiet past its threshold, its age, the time
// since its log last grew, and the reasons it may be slow.
import { hasConsole } from '../api/backend';
import { Link, useNavigate, useParams } from 'react-router';
import { useState } from 'react';
import { Anchor, Badge, Button, Code, Group, Paper, SegmentedControl, SimpleGrid, Stack, Text, TextInput } from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { useQueryClient } from '@tanstack/react-query';
import { IconPlayerStop, IconRepeat, IconSearch, IconTrash } from '@tabler/icons-react';
import { del, post } from '../api/client';
import { useJobs } from '../api/hooks';
import type { Job } from '../api/types';
import { DataTable } from '../components/DataTable';
import { Load, PageHeader, StatTile } from '../components/ui';
import { LogView, useJobTail } from '../jobs/JobLog';
import { useRunner } from '../jobs/JobRunner';
import { JobDiagnostics, JobStatus } from '../jobs/JobStatus';
import { LoopRunSummary } from '../jobs/LoopRunSummary';
import { AssistAnswer } from '../jobs/AssistAnswer';
import { duration, includesText, seconds, when } from '../lib/format';
import { to } from '../lib/links';
import u from '../styles/utils.module.css';

const shortArgv = (j: Job) => j.argv.map((a) => a.replace(/^.*\/tools\//, 'tools/')).join(' ');
const stamp = (j: Job) => j.started ?? j.created ?? j.finished ?? '';
const took = (j: Job) => (j.started && j.finished ? duration(Date.parse(j.finished) - Date.parse(j.started)) : '');
// The console sends age_s; a workflow run on the published page has only its timestamp.
const ageOf = (j: Job) => j.age_s ?? (j.created ? Math.max(0, (Date.now() - Date.parse(j.created)) / 1000) : null);
const LIVE = new Set(['running', 'queued']);
const FINISHED = new Set(['succeeded', 'failed', 'cancelled', 'interrupted']);

type StatusFilter = 'all' | 'live' | 'stalled' | 'failed' | 'succeeded';
const STATUS_FILTERS: { label: string; value: StatusFilter }[] = [
  { label: 'All', value: 'all' }, { label: 'Running', value: 'live' }, { label: 'Stalled', value: 'stalled' },
  { label: 'Failed', value: 'failed' }, { label: 'Succeeded', value: 'succeeded' },
];
const statusMatches = (j: Job, f: StatusFilter) =>
  f === 'all' || (f === 'live' ? LIVE.has(j.status) : f === 'stalled' ? j.state === 'stalled'
    : f === 'failed' ? ['failed', 'cancelled', 'interrupted'].includes(j.status) : j.status === f);

async function cancel(id: string) {
  try {
    await post(`/api/jobs/${id}/cancel`, {});
    notifications.show({ message: 'cancel requested' });
  } catch (e) {
    notifications.show({ color: 'red', message: (e as Error).message });
  }
}

interface OpRow {
  op: string;
  title: string;
  group: string;
  latest: Job;
  runs: number;
  ok: number;
  failed: number;
}

function byOperation(list: Job[]): OpRow[] {
  const rows = new Map<string, OpRow>();
  for (const j of list) {   // newest first, so the first seen is the latest
    const r = rows.get(j.op);
    if (!r) rows.set(j.op, { op: j.op, title: j.title, group: j.group ?? '', latest: j, runs: 1, ok: j.status === 'succeeded' ? 1 : 0, failed: j.status === 'failed' ? 1 : 0 });
    else {
      r.runs += 1;
      if (j.status === 'succeeded') r.ok += 1;
      if (j.status === 'failed') r.failed += 1;
    }
  }
  return [...rows.values()];
}

function useClear() {
  const qc = useQueryClient();
  return (status: 'finished' | 'failed,cancelled,interrupted', count: number) => modals.openConfirmModal({
    title: status === 'finished' ? 'Clear finished jobs' : 'Clear failed jobs',
    children: (
      <Text size="sm">
        Forget {count} {status === 'finished' ? 'finished' : 'failed, cancelled or interrupted'} job(s) and delete their logs.
        Running jobs are never cleared, and nothing here touches GitHub.
      </Text>
    ),
    labels: { confirm: 'Clear', cancel: 'Keep' },
    confirmProps: { color: 'red' },
    onConfirm: async () => {
      try {
        const r = await del<{ removed: number }>(`/api/jobs?status=${encodeURIComponent(status)}`);
        notifications.show({ message: `cleared ${r.removed} job(s)` });
        await qc.invalidateQueries({ queryKey: ['jobs'] });
      } catch (e) {
        notifications.show({ color: 'red', message: (e as Error).message });
      }
    },
  });
}

export function Jobs() {
  const jobs = useJobs();
  const { runOp } = useRunner();
  const navigate = useNavigate();
  const clear = useClear();
  const [view, setView] = useState<'runs' | 'ops'>('runs');
  const [status, setStatus] = useState<StatusFilter>('all');
  const [group, setGroup] = useState('all');
  const [q, setQ] = useState('');
  const onConsole = hasConsole();
  return (
    <>
      <PageHeader
        title="Jobs"
        description={onConsole
          ? 'Every job this console has run, whichever surface started it — this page, the terminal dash, or an agent through the fleet MCP server. History and logs survive a console restart until cleared.'
          : 'On the published page, a job is a control-plane workflow dispatched in the hub: its recent workflow_dispatch runs, read from GitHub with your token, each with its steps as the log.'}
        actions={<Button component={Link} to={to.ops()} size="xs">Run an operation</Button>}
      />
      <Load q={jobs}>
        {(raw) => {
          // Newest first, whichever backend answered — both happen to send
          // that order today, but the page should not depend on it.
          const list = [...raw].sort((a, b) => stamp(b).localeCompare(stamp(a)));
          const count = (s: string) => list.filter((j) => j.status === s).length;
          const finished = list.filter((j) => FINISHED.has(j.status)).length;
          const failedish = list.filter((j) => ['failed', 'cancelled', 'interrupted'].includes(j.status)).length;
          const groups = [...new Set(list.map((j) => j.group).filter(Boolean) as string[])].sort();
          const stalled = list.filter((j) => j.state === 'stalled').length;
          const shown = list.filter((j) => statusMatches(j, status) && (group === 'all' || j.group === group)
            && includesText([j.title, j.op, j.group, shortArgv(j), JSON.stringify(j.params ?? {}),
              ...(j.diagnostics ?? []).map((d) => d.code)], q));
          return (
            <>
              <SimpleGrid cols={{ base: 2, md: 6 }} spacing="md" mb="md">
                <StatTile label="Running" value={count('running') + count('queued')} />
                <StatTile label="Stalled" value={stalled} tone={stalled ? 'warn' : undefined}
                  sub="running, log quiet past its threshold" />
                <StatTile label="Succeeded" value={count('succeeded')} />
                <StatTile label="Failed" value={count('failed')} tone={count('failed') ? 'crit' : undefined} />
                <StatTile label="Cancelled / interrupted" value={count('cancelled') + count('interrupted')} />
                <StatTile label="Wrote to GitHub" value={list.filter((j) => j.remote_write).length} />
              </SimpleGrid>
              <Paper p="sm" mb="md">
                <Group gap="sm" wrap="wrap" justify="space-between">
                  <Group gap="sm" wrap="wrap">
                    <SegmentedControl size="xs" value={view} onChange={(v) => setView(v as 'runs' | 'ops')}
                      data={[{ label: `Runs (${list.length})`, value: 'runs' }, { label: 'By operation', value: 'ops' }]} />
                    <SegmentedControl size="xs" value={status} onChange={(v) => setStatus(v as StatusFilter)} data={STATUS_FILTERS} />
                    {groups.length > 1 ? (
                      <SegmentedControl size="xs" value={group} onChange={setGroup}
                        data={[{ label: 'every group', value: 'all' }, ...groups.map((g) => ({ label: g, value: g }))]} />
                    ) : null}
                    <TextInput size="xs" placeholder="filter by name, argv, params" leftSection={<IconSearch size={14} />}
                      value={q} onChange={(e) => setQ(e.currentTarget.value)} w={220} aria-label="filter jobs" />
                  </Group>
                  {onConsole ? (
                    <Group gap="xs">
                      <Button size="xs" variant="default" leftSection={<IconTrash size={14} />} disabled={!failedish}
                        onClick={() => clear('failed,cancelled,interrupted', failedish)}>Clear failed</Button>
                      <Button size="xs" variant="light" color="red" leftSection={<IconTrash size={14} />} disabled={!finished}
                        onClick={() => clear('finished', finished)}>Clear finished ({finished})</Button>
                    </Group>
                  ) : null}
                </Group>
              </Paper>
              {view === 'runs' ? (
                <DataTable<Job>
                  rows={shown}
                  keys
                  rowKey={(j) => j.id}
                  href={(j) => to.job(j.id)}
                  tone={(j) => (j.status === 'failed' ? 'crit' : j.status === 'cancelled' || j.status === 'interrupted' || j.state === 'stalled' ? 'warn' : undefined)}
                  empty={list.length ? 'No job matches these filters.' : 'No jobs yet. Every Run button in the console starts one.'}
                  minWidth={980}
                  columns={[
                    // the reasons a live job may be slow sit under its state, where the eye already is
                    { key: 'status', header: 'status', sort: (j) => j.state ?? j.status, render: (j) => <Stack gap={4} align="flex-start"><JobStatus status={j.status} state={j.state} /><JobDiagnostics items={j.diagnostics} compact /></Stack> },
                    { key: 'op', header: 'operation', sort: (j) => j.title, render: (j) => <div><Text size="sm" fw={600}>{j.title}{j.remote_write ? <Badge ml={6} size="xs" color="yellow" variant="light">remote</Badge> : null}</Text><Code fz={11} className={u.anywhere}>{shortArgv(j)}</Code></div> },
                    { key: 'group', header: 'group', sort: (j) => j.group ?? '', render: (j) => (j.group ? <Badge size="xs" variant="outline">{j.group}</Badge> : null) },
                    { key: 'started', header: 'started', sort: stamp, render: (j) => <Text size="xs" c="dimmed">{when(j.started ?? j.created)}</Text> },
                    { key: 'age', header: 'age', num: true, sort: (j) => ageOf(j) ?? 0, render: (j) => <Text span size="xs" title="since it was sent">{seconds(ageOf(j))}</Text> },
                    { key: 'idle', header: 'idle', num: true, sort: (j) => j.idle_s ?? -1, render: (j) => (j.idle_s == null ? '' : <Text span size="xs" c={j.state === 'stalled' ? 'var(--warning)' : undefined} title={`since its log last grew; stalled past ${seconds(j.stall_s)}`}>{seconds(j.idle_s)}</Text>) },
                    { key: 'dur', header: 'took', num: true, render: took },
                    { key: 'exit', header: 'exit', num: true, render: (j) => j.exit_code ?? '' },
                    { key: 'x', header: '', render: (j) => (j.status === 'running' ? <Button size="compact-xs" color="red" variant="light" leftSection={<IconPlayerStop size={12} />} onClick={(e) => { e.stopPropagation(); void cancel(j.id); }}>Cancel</Button> : null) },
                  ]}
                />
              ) : (
                <DataTable<OpRow>
                  rows={byOperation(shown)}
                  keys
                  rowKey={(r) => r.op}
                  href={(r) => to.job(r.latest.id)}
                  tone={(r) => (r.latest.status === 'failed' ? 'crit' : undefined)}
                  empty="No job matches these filters."
                  minWidth={860}
                  initialSort={{ key: 'last', desc: true }}
                  columns={[
                    { key: 'status', header: 'latest', sort: (r) => r.latest.status, render: (r) => <JobStatus status={r.latest.status} state={r.latest.state} /> },
                    { key: 'op', header: 'operation', sort: (r) => r.title, render: (r) => <div><Text size="sm" fw={600}>{r.title}</Text><Anchor component={Link} to={to.op(r.op)} size="xs" onClick={(e) => e.stopPropagation()}>{r.op}</Anchor></div> },
                    { key: 'group', header: 'group', sort: (r) => r.group, render: (r) => (r.group ? <Badge size="xs" variant="outline">{r.group}</Badge> : null) },
                    { key: 'last', header: 'last run', sort: (r) => stamp(r.latest), render: (r) => <Text size="xs" c="dimmed">{when(r.latest.started ?? r.latest.created)}</Text> },
                    { key: 'runs', header: 'runs', num: true, sort: (r) => r.runs, render: (r) => r.runs },
                    { key: 'rate', header: 'succeeded', num: true, sort: (r) => r.ok / r.runs, render: (r) => `${r.ok}/${r.runs}` },
                    { key: 'dur', header: 'took', num: true, render: (r) => took(r.latest) },
                    {
                      key: 'x', header: '', render: (r) => (FINISHED.has(r.latest.status) && onConsole && !r.latest.remote_write ? (
                        <Button size="compact-xs" variant="default" leftSection={<IconRepeat size={12} />}
                          onClick={async (e) => { e.stopPropagation(); const n = await runOp(r.op, r.latest.params ?? {}); if (n) navigate(to.job(n.id)); }}>
                          Run again
                        </Button>
                      ) : null),
                    },
                  ]}
                />
              )}
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
        badges={j ? <><JobStatus status={j.status} state={j.state} />{j.remote_write ? <Badge color="yellow" variant="light">{j.confirm === 'spend' ? 'spends Claude budget' : 'writes to GitHub'}</Badge> : null}</> : null}
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
            <Code block className={u.preWrap}>{shortArgv(j)}</Code>
            <Group gap="lg">
              <Text size="xs" c="dimmed">started {when(j.started)}</Text>
              {j.finished ? <Text size="xs" c="dimmed">finished {when(j.finished)}</Text> : null}
              {j.exit_code != null ? <Text size="xs" c="dimmed">exit {j.exit_code}</Text> : null}
              {j.age_s != null ? <Text size="xs" c="dimmed">sent {seconds(j.age_s)} ago</Text> : null}
              {j.idle_s != null && j.state === 'queued' ? (
                <Text size="xs" c="dimmed" data-testid="job-idle">waiting {seconds(j.idle_s)} to start</Text>
              ) : j.idle_s != null ? (
                <Text size="xs" c={j.state === 'stalled' ? 'var(--warning)' : 'dimmed'} data-testid="job-idle">
                  last output {seconds(j.idle_s)} ago (stalled past {seconds(j.stall_s)})
                </Text>
              ) : null}
              {j.params && Object.keys(j.params).length ? <Text size="xs" c="dimmed" miw={0}>params <Code className={u.anywhere}>{JSON.stringify(j.params)}</Code></Text> : null}
            </Group>
            <JobDiagnostics items={j.diagnostics} />
          </Stack>
        </Paper>
      ) : null}
      {tail?.loop ? <LoopRunSummary f={tail.loop} done={Boolean(tail.done)} /> : null}
      {tail?.assist ? <AssistAnswer a={tail.assist} done={Boolean(tail.done)} /> : null}
      <LogView raw={raw} height="calc(100vh - 300px)" />
    </>
  );
}
