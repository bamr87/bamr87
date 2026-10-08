// Running an operation, from anywhere in the console.
//
// runOp() is the one entry point every button, palette pick and form uses:
// it says in plain words what a GitHub-writing operation is about to do and
// asks first (the server refuses a write without confirm=true anyway), warns
// when gh is not signed in for an operation that needs it, submits the job,
// and opens the job drawer on its live log — the page you were on stays put.
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import { Link } from 'react-router';
import { Anchor, Badge, Button, Code, Drawer, Group, Stack, Text } from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { useQueryClient } from '@tanstack/react-query';
import { post } from '../api/client';
import { useCaps, useOps } from '../api/hooks';
import type { Job, Op } from '../api/types';
import { to } from '../lib/links';
import { JobStatus } from './JobStatus';
import { LogView, useJobTail } from './JobLog';

type Params = Record<string, unknown>;

interface Runner {
  runOp: (op: string, params?: Params) => Promise<Job | null>;
  openJob: (id: string) => void;
  isRemote: (op: string, params?: Params) => boolean;
}

const RunnerContext = createContext<Runner | null>(null);

export function useRunner(): Runner {
  const r = useContext(RunnerContext);
  if (!r) throw new Error('useRunner outside <JobRunner>');
  return r;
}

/** Same rule as the server: a remote op writes only with apply, except the always-writing ones. */
export function remoteWrite(op: Op | undefined, params: Params = {}): boolean {
  if (!op?.remote_write) return false;
  return params.apply === true || op.id === 'dispatch' || op.id === 'observe-reset';
}

function confirmText(op: Op, p: Params): string {
  const fields = JSON.stringify(p.fields ?? {});
  switch (op.id) {
    case 'dispatch': return `Dispatch ${String(p.workflow)}.yml in GitHub Actions with ${fields}.`;
    case 'content-file': return `${op.title} for ${String(p.target)}. With apply, this opens issues in that site's GitHub repo.`;
    case 'keys-rotate': return `Write each workspace's new Anthropic API key from .env to the repos it serves (hub first), then DISABLE the key each one replaces in the Console.${p.allow_long_lived ? ' Keys that outlive the lifetime policy are allowed.' : ''}`;
    case 'ai-auth-sync': return `Set CLAUDE_AUTH_ORDER on ${String(p.target || 'every fleet repo')} from ai_auth: in _data/fleet.yml. This changes which Claude credential those repos' AI steps use first.`;
    case 'secrets-push': return `Push ${String(p.secret || 'every contract secret in .env')} from .env to GitHub — the HUB first${p.hub_only ? ' and nowhere else' : ', then every fleet repo for fleet-scoped secrets'}. This OVERWRITES the current values.`;
    case 'observe-reset': return `${op.title}. This DELETES every indexed log line and the elk volumes. Actions logs can be re-shipped from the lake; container logs cannot.`;
    default: return `${op.title}. With apply, this opens pull requests or writes secrets/variables in fleet repos.`;
  }
}

function confirm(title: string, body: ReactNode, label: string, danger: boolean): Promise<boolean> {
  return new Promise((resolve) => {
    modals.openConfirmModal({
      title,
      children: body,
      labels: { confirm: label, cancel: 'Cancel' },
      confirmProps: { color: danger ? 'red' : undefined },
      onConfirm: () => resolve(true),
      onCancel: () => resolve(false),
      onClose: () => resolve(false),
    });
  });
}

export function JobRunner({ children }: { children: ReactNode }) {
  const ops = useOps();
  const caps = useCaps();
  const qc = useQueryClient();
  const [jobId, setJobId] = useState<string | null>(null);

  const isRemote = useCallback((id: string, params: Params = {}) => remoteWrite(ops.data?.find((o) => o.id === id), params), [ops.data]);

  const runOp = useCallback(
    async (id: string, params: Params = {}) => {
      const op = ops.data?.find((o) => o.id === id);
      if (!op) {
        notifications.show({ color: 'red', title: 'Unknown operation', message: id });
        return null;
      }
      const remote = remoteWrite(op, params);
      if (remote) {
        const ok = await confirm('This writes to GitHub', (
          <Stack gap="xs">
            <Text size="sm">{confirmText(op, params)}</Text>
            <Text size="xs" c="dimmed">Only one GitHub-writing job runs at a time. The console never commits or merges.</Text>
          </Stack>
        ), 'Run it', true);
        if (!ok) return null;
      }
      if (op.needs_token && caps.data?.gh_authenticated === false) {
        const ok = await confirm('gh is not signed in', (
          <Text size="sm">This operation reads GitHub, and the console's environment has no working gh login, so it will probably degrade or fail. Sign in on the Credentials page, or run it anyway.</Text>
        ), 'Run anyway', false);
        if (!ok) return null;
      }
      try {
        const job = await post<Job>('/api/jobs', { op: id, params, confirm: remote });
        notifications.show({ title: 'Started', message: job.title, color: 'cyan' });
        void qc.invalidateQueries({ queryKey: ['jobs'] });
        setJobId(job.id);
        return job;
      } catch (e) {
        notifications.show({ color: 'red', title: 'Could not start', message: (e as Error).message, autoClose: 9000 });
        return null;
      }
    },
    [ops.data, caps.data, qc],
  );

  const value = useMemo(() => ({ runOp, openJob: setJobId, isRemote }), [runOp, isRemote]);

  return (
    <RunnerContext.Provider value={value}>
      {children}
      <JobDrawer jobId={jobId} onClose={() => setJobId(null)} />
    </RunnerContext.Provider>
  );
}

function JobDrawer({ jobId, onClose }: { jobId: string | null; onClose: () => void }) {
  const { raw, tail, error } = useJobTail(jobId);
  const job = tail?.job;
  return (
    <Drawer opened={Boolean(jobId)} onClose={onClose} position="right" size="xl" title={job ? job.title : 'Job'} keepMounted={false}>
      {job ? (
        <Stack gap="sm">
          <Group gap="xs" wrap="wrap">
            <JobStatus status={job.status} />
            {job.remote_write ? <Badge color="yellow" variant="light">writes to GitHub</Badge> : null}
            <Anchor component={Link} to={to.job(job.id)} size="sm" onClick={onClose}>Open the job page</Anchor>
            <Anchor component={Link} to={to.op(job.op)} size="sm" onClick={onClose}>About {job.op}</Anchor>
          </Group>
          <Code block style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{job.argv.map((a) => a.replace(/^.*\/tools\//, 'tools/')).join(' ')}</Code>
        </Stack>
      ) : null}
      {error ? <Text c="red" size="sm" mt="sm">{error}</Text> : null}
      <div style={{ marginTop: 12 }}>
        <LogView raw={raw} height="calc(100vh - 220px)" />
      </div>
      <Group justify="flex-end" mt="sm">
        <Button variant="default" onClick={onClose}>Close</Button>
      </Group>
    </Drawer>
  );
}
