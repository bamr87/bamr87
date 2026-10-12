// One repo, live from GitHub: open issues, pull requests, recent runs and
// workflows. Fleet repos the hub owns get the writes — issues (open, comment,
// close, reopen, labels), PR comments and labels, re-run / cancel a run,
// enable / disable a workflow — each one said, confirmed and logged through
// useGhAction. Anything else is read-only. Nothing here merges, deletes or pushes.
import { useState } from 'react';
import { useSearchParams } from 'react-router';
import {
  Anchor, Badge, Button, Drawer, Group, MultiSelect, Paper, Select, Stack, Tabs, Text, Textarea, TextInput,
} from '@mantine/core';
import { useGithubIssue, useGithubRepo, useGithubStatus } from '../api/hooks';
import type { GhIssue, GhRepoDetail } from '../api/types';
import { DataTable } from '../components/DataTable';
import { Banner, Conclusion, External, Load, Mono, Spinner, Status } from '../components/ui';
import { when } from '../lib/format';
import { gh } from '../lib/links';
import { useGhAction } from './useGhAction';

type Pull = GhRepoDetail['pulls'][number];
type Run = GhRepoDetail['runs'][number];
type Workflow = GhRepoDetail['workflows'][number];
const TABS = ['issues', 'pulls', 'runs', 'workflows'] as const;

const Labels = ({ names }: { names: string[] }) => (
  <Group gap={4} wrap="wrap">{names.map((l) => <Badge key={l} size="xs" variant="light" color="gray">{l}</Badge>)}</Group>
);

/** One issue or PR conversation, with the writes a fleet repo allows. */
function Thread({ nwo, n, d, can, onClose }: { nwo: string; n: number | null; d: GhRepoDetail; can: boolean; onClose: () => void }) {
  const q = useGithubIssue(nwo, n);
  const act = useGhAction(nwo);
  const [comment, setComment] = useState('');
  const [labels, setLabels] = useState<string[] | null>(null);
  const [reason, setReason] = useState<string>('completed');
  return (
    <Drawer opened={n != null} onClose={onClose} position="right" size="xl" title={<Mono>{nwo}#{n}</Mono>}>
      <Load q={q} rows={6}>
        {({ issue, comments }) => {
          const kind = issue.is_pr ? 'pull request' : 'issue';
          const current = labels ?? issue.labels;
          const add = current.filter((l) => !issue.labels.includes(l));
          const remove = issue.labels.filter((l) => !current.includes(l));
          return (
            <Stack gap="sm">
              <Group gap={6} wrap="wrap">
                <Text fw={600}>{issue.title}</Text>
                <Status tone={issue.state === 'open' ? 'good' : 'info'}>{issue.state}{issue.state_reason ? ` · ${issue.state_reason}` : ''}</Status>
                <External href={issue.html_url} size="xs">GitHub</External>
              </Group>
              <Text size="xs" c="dimmed">{issue.user} · opened {when(issue.created_at)} · updated {when(issue.updated_at)}</Text>
              <pre className="log" style={{ maxHeight: 260, whiteSpace: 'pre-wrap' }}>{issue.body || '(no description)'}</pre>
              {comments.map((c) => (
                <Paper key={c.id} p="xs" withBorder>
                  <Text size="xs" c="dimmed">{c.user} · <External href={c.html_url} size="xs">{when(c.created_at)}</External></Text>
                  <Text size="sm" style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{c.body}</Text>
                </Paper>
              ))}
              {can ? (
                <>
                  <Textarea placeholder={`Comment on this ${kind}…`} autosize minRows={3} value={comment} onChange={(e) => setComment(e.currentTarget.value)} />
                  <Group gap="xs" wrap="wrap">
                    <Button size="xs" disabled={!comment.trim()} onClick={async () => {
                      if (await act('issue.comment', { number: issue.number, body: comment }, { title: 'Post a comment', what: `Post this comment on ${kind} #${issue.number} as the connected account.`, label: 'Post' })) setComment('');
                    }}>Comment</Button>
                    {!issue.is_pr && issue.state === 'open' ? (
                      <>
                        <Select size="xs" w={150} value={reason} onChange={(v) => setReason(v ?? 'completed')} data={[{ value: 'completed', label: 'completed' }, { value: 'not_planned', label: 'not planned' }]} aria-label="close reason" />
                        <Button size="xs" variant="light" color="red" onClick={() => void act('issue.close', { number: issue.number, reason }, { title: 'Close issue', what: `Close issue #${issue.number} as ${reason.replace('_', ' ')}.`, label: 'Close', danger: true })}>Close</Button>
                      </>
                    ) : null}
                    {!issue.is_pr && issue.state === 'closed' ? (
                      <Button size="xs" variant="light" onClick={() => void act('issue.reopen', { number: issue.number }, { title: 'Reopen issue', what: `Reopen issue #${issue.number}.`, label: 'Reopen' })}>Reopen</Button>
                    ) : null}
                  </Group>
                  <Group gap="xs" align="flex-end" wrap="wrap">
                    <MultiSelect size="xs" w={380} label="Labels" data={Array.from(new Set([...d.labels.map((l) => l.name), ...issue.labels]))} value={current} onChange={setLabels} searchable clearable />
                    <Button size="xs" variant="light" disabled={!add.length && !remove.length} onClick={async () => {
                      const what = [add.length ? `add ${add.join(', ')}` : '', remove.length ? `remove ${remove.join(', ')}` : ''].filter(Boolean).join('; ');
                      if (await act('issue.labels', { number: issue.number, add, remove }, { title: 'Change labels', what: `On #${issue.number}: ${what}.`, label: 'Apply' })) setLabels(null);
                    }}>Apply labels</Button>
                  </Group>
                </>
              ) : <Text size="xs" c="dimmed">Read-only: not a fleet repo the hub owns, or GitHub writes are off.</Text>}
            </Stack>
          );
        }}
      </Load>
    </Drawer>
  );
}

function NewIssue({ nwo, d }: { nwo: string; d: GhRepoDetail }) {
  const act = useGhAction(nwo);
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [labels, setLabels] = useState<string[]>([]);
  if (!open) return <Button size="xs" variant="light" onClick={() => setOpen(true)} mb="sm">New issue</Button>;
  return (
    <Paper p="sm" mb="sm" withBorder>
      <Stack gap="xs">
        <TextInput size="xs" placeholder="Title" value={title} onChange={(e) => setTitle(e.currentTarget.value)} maxLength={256} />
        <Textarea size="xs" placeholder="Description (markdown)" autosize minRows={3} value={body} onChange={(e) => setBody(e.currentTarget.value)} />
        <MultiSelect size="xs" placeholder="Labels" data={d.labels.map((l) => l.name)} value={labels} onChange={setLabels} searchable clearable />
        <Group gap="xs">
          <Button size="xs" disabled={!title.trim()} onClick={async () => {
            if (await act('issue.create', { title, body, labels }, { title: 'Open an issue', what: `Open “${title.trim()}” in ${nwo} as the connected account.`, label: 'Open issue' })) {
              setTitle(''); setBody(''); setLabels([]); setOpen(false);
            }
          }}>Open issue</Button>
          <Button size="xs" variant="subtle" color="gray" onClick={() => setOpen(false)}>Cancel</Button>
        </Group>
      </Stack>
    </Paper>
  );
}

export function RepoManager({ nwo }: { nwo: string }) {
  const status = useGithubStatus();
  const connected = Boolean(status.data?.connected);
  const repo = useGithubRepo(nwo, connected);
  const act = useGhAction(nwo);
  const [params] = useSearchParams();
  const initial = params.get('tab');
  const [tab, setTab] = useState<string>(TABS.includes(initial as (typeof TABS)[number]) ? (initial as string) : 'issues');
  const [thread, setThread] = useState<number | null>(null);

  if (status.data === undefined) return status.isError ? <Banner tone="crit">{(status.error as Error).message}</Banner> : <Spinner />;
  if (!connected) return <Banner tone="info" title="GitHub is not connected">Connect the console on the GitHub page to see this repo's issues, pull requests, runs and workflows live.</Banner>;

  return (
    <Load q={repo} rows={6}>
      {(d) => {
        const can = d.writable && Boolean(status.data?.writes_enabled);
        const r = d.repo;
        return (
          <>
            <Group gap="xs" mb="sm" wrap="wrap">
              {d.writable ? <Status tone="good" title="Writes allowed: a fleet repo the hub owns">managed</Status> : <Status tone="info" title="Not a fleet repo the hub owns">read-only</Status>}
              {r.private ? <Text size="xs" c="dimmed">private</Text> : null}
              {r.archived ? <Status tone="warn">archived</Status> : null}
              {r.language ? <Text size="xs" c="dimmed">{String(r.language)}</Text> : null}
              <Text size="xs" c="dimmed">default branch <Mono>{String(r.default_branch ?? '')}</Mono> · pushed {when(r.pushed_at as string | null)}</Text>
              <External href={(r.html_url as string) || gh.repo(nwo)} size="xs">GitHub</External>
            </Group>
            {r.description ? <Text size="sm" c="dimmed" mb="sm">{String(r.description)}</Text> : null}
            {d.writable && !status.data?.writes_enabled ? <Banner tone="info">GitHub writes are switched off (DASH_CONSOLE_GITHUB_WRITES / DASH_CONSOLE_AUTH).</Banner> : null}
            {Object.keys(d.errors).length ? (
              <Banner tone="warn" title="Some of this repo could not be read">
                {Object.entries(d.errors).map(([k, v]) => <div key={k}><Mono>{k}</Mono>: {v}</div>)}
              </Banner>
            ) : null}

            <Tabs value={tab} onChange={(v) => setTab(v ?? 'issues')} keepMounted={false}>
              <Tabs.List mb="sm">
                <Tabs.Tab value="issues">Issues ({d.issues.length})</Tabs.Tab>
                <Tabs.Tab value="pulls">Pull requests ({d.pulls.length})</Tabs.Tab>
                <Tabs.Tab value="runs">Runs ({d.runs.length})</Tabs.Tab>
                <Tabs.Tab value="workflows">Workflows ({d.workflows.length})</Tabs.Tab>
              </Tabs.List>

              <Tabs.Panel value="issues">
                {can && d.repo.has_issues !== false ? <NewIssue nwo={nwo} d={d} /> : null}
                <DataTable<GhIssue>
                  rows={d.issues} keys rowKey={(i) => String(i.number)} onActivate={(i) => setThread(i.number)}
                  open={(i) => i.html_url} copy={(i) => i.html_url} empty="No open issues."
                  columns={[
                    { key: 'n', header: '#', num: true, sort: (i) => i.number, render: (i) => <Anchor size="sm" onClick={() => setThread(i.number)}>#{i.number}</Anchor>, width: 70 },
                    { key: 't', header: 'title', sort: (i) => i.title, render: (i) => <div><Text size="sm">{i.title}</Text><Labels names={i.labels} /></div> },
                    { key: 'u', header: 'author', sort: (i) => i.user ?? '', render: (i) => <Text size="sm">{i.user ?? ''}</Text> },
                    { key: 'c', header: 'comments', num: true, sort: (i) => i.comments, render: (i) => i.comments },
                    { key: 'd', header: 'updated', sort: (i) => i.updated_at, render: (i) => <Text size="xs" c="dimmed">{when(i.updated_at)}</Text> },
                  ]}
                />
              </Tabs.Panel>

              <Tabs.Panel value="pulls">
                <Text size="xs" c="dimmed" mb="xs">Comment and label from the conversation. The console never merges.</Text>
                <DataTable<Pull>
                  rows={d.pulls} keys rowKey={(p) => String(p.number)} onActivate={(p) => setThread(p.number)}
                  open={(p) => p.html_url} copy={(p) => p.html_url} empty="No open pull requests."
                  columns={[
                    { key: 'n', header: '#', num: true, sort: (p) => p.number, render: (p) => <Anchor size="sm" onClick={() => setThread(p.number)}>#{p.number}</Anchor>, width: 70 },
                    { key: 't', header: 'title', sort: (p) => p.title, render: (p) => <div><Group gap={6}><Text size="sm">{p.title}</Text>{p.draft ? <Text size="xs" c="dimmed">draft</Text> : null}</Group><Labels names={p.labels} /></div> },
                    { key: 'b', header: 'branch', render: (p) => <Mono dim>{p.head} → {p.base}</Mono> },
                    { key: 'u', header: 'author', sort: (p) => p.user ?? '', render: (p) => <Text size="sm">{p.user ?? ''}</Text> },
                    { key: 'd', header: 'updated', sort: (p) => p.updated_at, render: (p) => <Text size="xs" c="dimmed">{when(p.updated_at)}</Text> },
                  ]}
                />
              </Tabs.Panel>

              <Tabs.Panel value="runs">
                <DataTable<Run>
                  rows={d.runs} keys rowKey={(x) => String(x.id)} open={(x) => x.html_url} copy={(x) => x.html_url}
                  onActivate={(x) => window.open(x.html_url, '_blank', 'noopener')}
                  tone={(x) => (x.conclusion === 'failure' ? 'crit' : undefined)} empty="No recent runs."
                  columns={[
                    { key: 'w', header: 'workflow', sort: (x) => x.name, render: (x) => <div><Text size="sm">{x.name}</Text><Text size="xs" c="dimmed" lineClamp={1}>{x.display_title}</Text></div> },
                    { key: 'e', header: 'event', sort: (x) => x.event, render: (x) => <Text size="xs">{x.event}</Text> },
                    { key: 'b', header: 'branch', render: (x) => <Mono dim>{x.branch}</Mono> },
                    { key: 's', header: 'result', sort: (x) => x.conclusion ?? x.status, render: (x) => (x.status === 'completed' ? <Conclusion value={x.conclusion} /> : <Status tone="info">{x.status}</Status>) },
                    { key: 'a', header: 'started', sort: (x) => x.created_at, render: (x) => <Text size="xs" c="dimmed">{when(x.created_at)}{x.run_attempt > 1 ? ` · attempt ${x.run_attempt}` : ''}</Text> },
                    {
                      key: 'x', header: '', render: (x) => (can ? (
                        <Group gap={4} wrap="nowrap">
                          {x.status === 'completed' && x.conclusion !== 'success' && x.conclusion !== 'skipped' ? (
                            <Button size="compact-xs" variant="light" onClick={(e) => { e.stopPropagation(); void act('run.rerun_failed', { run_id: x.id }, { title: 'Re-run failed jobs', what: `Re-run the failed jobs of “${x.name}” run ${x.id}. This spends Actions minutes.`, label: 'Re-run' }); }}>Re-run failed</Button>
                          ) : null}
                          {x.status !== 'completed' ? (
                            <Button size="compact-xs" variant="light" color="red" onClick={(e) => { e.stopPropagation(); void act('run.cancel', { run_id: x.id }, { title: 'Cancel run', what: `Cancel “${x.name}” run ${x.id}.`, label: 'Cancel run', danger: true }); }}>Cancel</Button>
                          ) : null}
                        </Group>
                      ) : null),
                    },
                  ]}
                />
              </Tabs.Panel>

              <Tabs.Panel value="workflows">
                <DataTable<Workflow>
                  rows={d.workflows} keys rowKey={(w) => String(w.id)} open={(w) => w.html_url} copy={(w) => w.html_url}
                  onActivate={(w) => window.open(gh.workflowRuns(nwo, w.path), '_blank', 'noopener')}
                  tone={(w) => (w.state !== 'active' ? 'muted' : undefined)} empty="No workflows."
                  columns={[
                    { key: 'n', header: 'workflow', sort: (w) => w.name, render: (w) => <Text size="sm">{w.name}</Text> },
                    { key: 'p', header: 'file', sort: (w) => w.path, render: (w) => <External href={gh.workflow(nwo, w.path)} size="sm"><Mono>{w.path}</Mono></External> },
                    { key: 's', header: 'state', sort: (w) => w.state, render: (w) => (w.state === 'active' ? <Status tone="good">active</Status> : <Status tone="warn">{w.state.replace(/_/g, ' ')}</Status>) },
                    {
                      key: 'x', header: '', render: (w) => {
                        if (!can || w.path.startsWith('dynamic/')) return null;
                        const on = w.state === 'active';
                        return (
                          <Button size="compact-xs" variant="light" color={on ? 'red' : undefined} onClick={(e) => {
                            e.stopPropagation();
                            void act(on ? 'workflow.disable' : 'workflow.enable', { workflow_id: w.id }, {
                              title: `${on ? 'Disable' : 'Enable'} workflow`,
                              what: on ? `Disable “${w.name}” (${w.path}): it stops running on every trigger until re-enabled.` : `Enable “${w.name}” (${w.path}).`,
                              label: on ? 'Disable' : 'Enable', danger: on,
                            });
                          }}>{on ? 'Disable' : 'Enable'}</Button>
                        );
                      },
                    },
                  ]}
                />
              </Tabs.Panel>
            </Tabs>
            {thread != null ? <Thread key={thread} nwo={nwo} n={thread} d={d} can={can} onClose={() => setThread(null)} /> : null}
          </>
        );
      }}
    </Load>
  );
}
