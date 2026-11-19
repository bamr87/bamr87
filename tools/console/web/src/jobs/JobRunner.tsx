// Running an operation, from anywhere in the console.
//
// runOp() is the one entry point every button, palette pick and form uses:
// it says in plain words what a GitHub-writing operation is about to do and
// asks first (the server refuses a write without confirm=true anyway), warns
// when gh is not signed in for an operation that needs it, submits the job,
// and opens the job drawer on its live log — the page you were on stays put.
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router';
import { Anchor, Badge, Box, Button, Code, Drawer, Group, Stack, Text } from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { useQueryClient } from '@tanstack/react-query';
import { githubToken, hasConsole } from '../api/backend';
import { post } from '../api/client';
import { useCaps, useOps } from '../api/hooks';
import type { Job, Op } from '../api/types';
import { to } from '../lib/links';
import { JobDiagnostics, JobStatus } from './JobStatus';
import { LogView, expectJob, useJobTail } from './JobLog';
import u from '../styles/utils.module.css';

type Params = Record<string, unknown>;

/** How a caller wants a run handled. The gate is not optional: neither field skips a confirm. */
export interface RunOptions {
  /** No "Started" toast and no job drawer, and a failure to start is thrown to the caller (the docked assistant shows its own thread). */
  quiet?: boolean;
  /** One more line for the confirm dialog: what this particular run adds to the operation's standing description. */
  detail?: string;
}

interface Runner {
  runOp: (op: string, params?: Params, opts?: RunOptions) => Promise<Job | null>;
  openJob: (id: string) => void;
  isRemote: (op: string, params?: Params) => boolean;
}

const RunnerContext = createContext<Runner | null>(null);

export function useRunner(): Runner {
  const r = useContext(RunnerContext);
  if (!r) throw new Error('useRunner outside <JobRunner>');
  return r;
}

/** Same rule as the server: a remote op writes only with apply, except the always-writing ones;
 * an op whose confirm guards SPEND (loop-run) asks unless it is a $0 rehearsal. */
export function remoteWrite(op: Op | undefined, params: Params = {}): boolean {
  if (!op?.remote_write) return false;
  if (op.id === 'prs-agent') return params.apply === true; // without apply it only re-checks the plan, $0
  if (op.confirm === 'spend') return params.rehearse !== true;
  return params.apply === true || op.id === 'dispatch' || op.id === 'observe-reset';
}

function confirmText(op: Op, p: Params): string {
  const fields = JSON.stringify(p.fields ?? {});
  switch (op.id) {
    case 'dispatch': return `Dispatch ${String(p.workflow)}.yml in GitHub Actions with ${fields}.`;
    case 'prs-act': return `Apply PR queue plan ${String(p.plan_id)}: the action and pull requests you just reviewed. It is planned again from GitHub first and refused if any pull request moved since; then each op runs once and its result is recorded.`;
    case 'prs-agent': return `Apply PR queue plan ${String(p.plan_id)}: one capped local Claude Code session per pull request you reviewed (pr_queue.agent's model, turns and dollars; API-equivalent, an estimate). Each edit is pushed as one commit to the pull request's branch, never forced, and the pull request is labelled needs-amr.`;
    case 'loop-run': return `Run ${String(p.loop)}${p.step ? `/${String(p.step)}` : ''} locally on ${p.target && p.target !== 'all' ? String(p.target) : "today's sample"}: one capped attempt per item through headless Claude Code in the sandbox, then a dry-run preview under .fleet/runs/ — nothing is filed. This spends Claude budget (API-equivalent, an estimate), held to budget.loops.`;
    case 'assist': return `Ask the assistant: "${String(p.question ?? '').slice(0, 160)}" — one headless Claude Code session with the fleet MCP server attached${p.page ? ' and the page you have open' : ''}. This spends Claude budget (API-equivalent, an estimate), capped by assistant.budget_usd; it holds no write tool and cannot reach the network${p.page ? ', and on the page it can do only what the dock\'s mode allows — never answer a confirming dialog' : ''}.`;
    case 'voices-pr': return `File the staged edit of the voice model (plan ${String(p.plan_id)}) as ONE draft pull request in the hub that changes only _data/voices/voices.yml. The publish token is probed with gh api user first, and the plan is re-checked against a fresh main; it is refused while another voices PR is open.`;
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

// Assistant conversations the person confirmed in this tab. The spend gate asks once per conversation: its
// dialog states the whole envelope (how many messages, the cap of each), and a later message that continues
// THAT conversation is sent under the same yes. A new conversation, another tab or a reload asks again, and
// the server caps a conversation's length whatever the page remembers (core._assist).
const confirmedConversations = new Set<string>();

/** Where an operation can run from this page: anywhere with a console; on the
 * public page, only a workflow dispatch, and only with a GitHub token. */
export function runnableHere(opId: string): boolean {
  return hasConsole() || (opId === 'dispatch' && Boolean(githubToken()));
}

export function JobRunner({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const ops = useOps();
  const caps = useCaps();
  const qc = useQueryClient();
  const [jobId, setJobId] = useState<string | null>(null);

  const isRemote = useCallback((id: string, params: Params = {}) => remoteWrite(ops.data?.find((o) => o.id === id), params), [ops.data]);

  const runOp = useCallback(
    async (id: string, params: Params = {}, opts: RunOptions = {}) => {
      const op = ops.data?.find((o) => o.id === id);
      if (!op) {
        notifications.show({ color: 'red', title: 'Unknown operation', message: id });
        return null;
      }
      if (!runnableHere(id)) {
        const go = await confirm(id === 'dispatch' ? 'Connect GitHub to dispatch' : 'This runs on a console', (
          <Text size="sm">{id === 'dispatch'
            ? 'This page dispatches control-plane workflows from your browser, with a GitHub token you give it on the Connect page.'
            : `“${op.title}” runs the hub's own tools in a working tree, so it needs a running console. Connect one (it can be the console on your own machine) and this page runs it with a live log.`}</Text>
        ), 'Open Connect', false);
        if (go) navigate(to.connect());
        return null;
      }
      const remote = remoteWrite(op, params);
      const continues = id === 'assist' && typeof params.conversation === 'string' && confirmedConversations.has(params.conversation);
      if (remote && !continues) {
        const spend = op.confirm === 'spend';
        const ok = await confirm(spend ? 'This spends Claude budget' : 'This writes to GitHub', (
          <Stack gap="xs">
            <Text size="sm">{confirmText(op, params)}</Text>
            {opts.detail ? <Text size="sm">{opts.detail}</Text> : null}
            <Text size="xs" c="dimmed">{id === 'assist'
              ? 'One confirmed job runs at a time, so an operation that writes or spends waits until the answer is in. The console never commits, merges or files.'
              : spend
              ? 'One confirmed job runs at a time, and one run per loop. Tick "rehearse" for a $0 pass that stops before the model call. The console never commits, merges or files.'
              : 'Only one GitHub-writing job runs at a time. The console never commits or merges.'}</Text>
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
        if (id === 'assist' && typeof job.params?.conversation === 'string') confirmedConversations.add(job.params.conversation);
        void qc.invalidateQueries({ queryKey: ['jobs'] });
        if (opts.quiet) return job;
        notifications.show({ title: 'Started', message: job.title, color: 'cyan' });
        expectJob(job.id);
        setJobId(job.id);
        return job;
      } catch (e) {
        if (opts.quiet) throw e;
        notifications.show({ color: 'red', title: 'Could not start', message: (e as Error).message, autoClose: 9000 });
        return null;
      }
    },
    [ops.data, caps.data, qc, navigate],
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
            <JobStatus status={job.status} state={job.state} />
            {job.remote_write ? <Badge color="yellow" variant="light">writes to GitHub</Badge> : null}
            <Anchor component={Link} to={to.job(job.id)} size="sm" onClick={onClose}>Open the job page</Anchor>
            <Anchor component={Link} to={to.op(job.op)} size="sm" onClick={onClose}>About {job.op}</Anchor>
          </Group>
          <Code block className={u.preWrap}>{job.argv.map((a) => a.replace(/^.*\/tools\//, 'tools/')).join(' ')}</Code>
          <JobDiagnostics items={job.diagnostics} />
        </Stack>
      ) : null}
      {error ? <Text c="red" size="sm" mt="sm">{error}</Text> : null}
      <Box mt={12}>
        <LogView raw={raw} height="calc(100vh - 220px)" />
      </Box>
      <Group justify="flex-end" mt="sm">
        <Button variant="default" onClick={onClose}>Close</Button>
      </Group>
    </Drawer>
  );
}
