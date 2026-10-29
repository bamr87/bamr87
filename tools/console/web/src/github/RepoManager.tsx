// One repo, live from GitHub, with the writes the console allows on a fleet
// repo: open / comment / close / reopen / label an issue (a PR's conversation
// too), re-run a run's failed jobs, cancel a run, enable or disable a workflow.
// No merges, deletes, pushes or settings — the console's standing line.
import { useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import {
  Anchor, Badge, Button, Drawer, Group, Loader, MultiSelect, Paper, SegmentedControl, Stack, Switch, Tabs, Text, TextInput, Textarea,
} from '@mantine/core';
import { IconPlus, IconRefresh } from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import { useGithubIssue, useGithubRepo, useGithubStatus } from '../api/hooks';
import type { GhIssue, GhRepoDetail } from '../api/types';
import { DataTable } from '../components/DataTable';
import { Banner, Conclusion, External, Load, Mono, Status } from '../components/ui';
import { includesText, when } from '../lib/format';
import { to } from '../lib/links';
import { useGhAction } from './useGhAction';
import u from '../styles/utils.module.css';

function LabelChips({ names, colors }: { names: string[]; colors?: Map<string, string> }) {
  return (
    <Group gap={3}>
      {names.map((n) => <Badge key={n} size="xs" variant="outline" style={colors?.get(n) ? { borderColor: `#${colors.get(n)}` } : undefined}>{n}</Badge>)}
    </Group>
  );
}

function IssueDrawer({ d, number, onClose, canWrite }: { d: GhRepoDetail; number: number | null; onClose: () => void; canWrite: boolean }) {
  const thread = useGithubIssue(d.nwo, number);
  const act = useGhAction(d.nwo);
  const [comment, setComment] = useState('');
  const [labels, setLabels] = useState<string[] | null>(null);
  const issue = thread.data?.issue;
  const current = labels ?? issue?.labels ?? [];
  const saveLabels = async () => {
    if (!issue) return;
    const add = current.filter((x) => !issue.labels.includes(x));
    const remove = issue.labels.filter((x) => !current.includes(x));
    if (!add.length && !remove.length) return;
    const r = await act('issue.labels', { number: issue.number, add, remove }, <>Labels on #{issue.number}: {add.length ? `add ${add.join(', ')}` : ''}{add.length && remove.length ? '; ' : ''}{remove.length ? `remove ${remove.join(', ')}` : ''}.</>);
    if (r) setLabels(null);
  };
  return (
    <Drawer opened={number != null} onClose={() => { setLabels(null); setComment(''); onClose(); }} position="right" size="xl"
      title={issue ? <Text fw={600}>#{issue.number} {issue.title}</Text> : `#${number}`}>
      <Load q={thread} rows={6}>
        {(t) => (
          <Stack gap="md">
            <Group gap="xs" wrap="wrap">
              <Status tone={t.issue.state === 'open' ? 'good' : 'info'}>{t.issue.state}{t.issue.state_reason ? ` · ${t.issue.state_reason}` : ''}</Status>
              {t.issue.is_pr ? <Badge variant="light">pull request</Badge> : null}
              <Text size="xs" c="dimmed">by {t.issue.user} · opened {when(t.issue.created_at)} · updated {when(t.issue.updated_at)}</Text>
              <External href={t.issue.html_url} size="xs">on GitHub</External>
            </Group>
            <Paper p="sm" className={u.preWrap} fz={13.5}>{t.issue.body || <Text span c="dimmed" size="sm">No description.</Text>}</Paper>
            <Stack gap="xs">
              <Text size="sm" fw={600}>Labels</Text>
              <MultiSelect data={d.labels.map((l) => l.name)} value={current} onChange={setLabels} searchable clearable disabled={!canWrite} placeholder={current.length ? undefined : 'no labels'} />
              {labels ? <Group gap="xs"><Button size="xs" onClick={() => void saveLabels()}>Save labels</Button><Button size="xs" variant="default" onClick={() => setLabels(null)}>Reset</Button></Group> : null}
            </Stack>
            <Stack gap="xs">
              <Text size="sm" fw={600}>Conversation ({t.comments.length})</Text>
              {t.comments.map((c) => (
                <Paper key={c.id} p="sm">
                  <Group justify="space-between" mb={4}><Text size="xs" fw={600}>{c.user}</Text><Anchor href={c.html_url} target="_blank" rel="noopener" size="xs">{when(c.created_at)}</Anchor></Group>
                  <Text size="sm" className={u.preWrap}>{c.body}</Text>
                </Paper>
              ))}
            </Stack>
            {canWrite ? (
              <Stack gap="xs">
                <Textarea autosize minRows={3} maxLength={65536} placeholder="Leave a comment (Markdown)" value={comment} onChange={(e) => setComment(e.currentTarget.value)} />
                <Group gap="xs" wrap="wrap">
                  <Button size="xs" disabled={!comment.trim()} onClick={async () => { if (await act('issue.comment', { number: t.issue.number, body: comment }, <>Comment on #{t.issue.number} as the connected account.</>)) setComment(''); }}>Comment</Button>
                  {!t.issue.is_pr && t.issue.state === 'open' ? (
                    <>
                      <Button size="xs" variant="default" onClick={() => void act('issue.close', { number: t.issue.number, reason: 'completed' }, <>Close #{t.issue.number} as completed.</>)}>Close as completed</Button>
                      <Button size="xs" variant="default" onClick={() => void act('issue.close', { number: t.issue.number, reason: 'not_planned' }, <>Close #{t.issue.number} as not planned.</>)}>Close as not planned</Button>
                    </>
                  ) : null}
                  {!t.issue.is_pr && t.issue.state === 'closed' ? <Button size="xs" variant="default" onClick={() => void act('issue.reopen', { number: t.issue.number }, <>Reopen #{t.issue.number}.</>)}>Reopen</Button> : null}
                </Group>
                {t.issue.is_pr ? <Text size="xs" c="dimmed">Pull requests are reviewed and merged on GitHub — the console comments and labels, it never merges.</Text> : null}
              </Stack>
            ) : null}
          </Stack>
        )}
      </Load>
    </Drawer>
  );
}

function NewIssue({ d, onDone }: { d: GhRepoDetail; onDone: () => void }) {
  const act = useGhAction(d.nwo);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [labels, setLabels] = useState<string[]>([]);
  return (
    <Paper p="md" mb="md">
      <Stack gap="xs">
        <TextInput label="Title" maxLength={256} value={title} onChange={(e) => setTitle(e.currentTarget.value)} />
        <Textarea label="Body (Markdown)" autosize minRows={4} maxLength={65536} value={body} onChange={(e) => setBody(e.currentTarget.value)} />
        <MultiSelect label="Labels" data={d.labels.map((l) => l.name)} value={labels} onChange={setLabels} searchable clearable />
        <Group gap="xs">
          <Button size="xs" disabled={!title.trim()} onClick={async () => {
            if (await act('issue.create', { title, body, labels }, <>Open “{title}” in {d.nwo}{labels.length ? ` labelled ${labels.join(', ')}` : ''}.</>)) { setTitle(''); setBody(''); setLabels([]); onDone(); }
          }}>Open issue</Button>
          <Button size="xs" variant="default" onClick={onDone}>Cancel</Button>
        </Group>
      </Stack>
    </Paper>
  );
}

export function RepoManager({ nwo, showHeader = true }: { nwo: string; showHeader?: boolean }) {
  const status = useGithubStatus();
  const repo = useGithubRepo(nwo, Boolean(status.data?.connected));
  const qc = useQueryClient();
  const [sp, setSp] = useSearchParams();
  const tab = sp.get('gh') ?? 'issues';
  const setTab = (v: string | null) => { const n = new URLSearchParams(sp); if (v && v !== 'issues') n.set('gh', v); else n.delete('gh'); setSp(n, { replace: true }); };
  const [open, setOpen] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const [q, setQ] = useState('');
  const [runFilter, setRunFilter] = useState('all');
  const act = useGhAction(nwo);

  if (status.data && !status.data.connected) {
    return <Banner tone="info" title="Not connected to GitHub">Connect on the <Anchor component={Link} to={to.github()}>GitHub page</Anchor> to see and manage {nwo} live.</Banner>;
  }
  return (
    <Load q={repo} rows={6}>
      {(d) => {
        const canWrite = d.writable && Boolean(status.data?.writes_enabled);
        const colors = new Map(d.labels.map((l) => [l.name, l.color]));
        const issues = d.issues.filter((i) => includesText([i.number, i.title, i.user, ...i.labels], q));
        const runs = d.runs.filter((r) => runFilter === 'all' || (runFilter === 'failed' ? r.conclusion === 'failure' : r.status !== 'completed'));
        return (
          <>
            {showHeader ? (
              <Group gap="sm" mb="sm" wrap="wrap">
                {d.repo.private ? <Badge variant="light">private</Badge> : <Badge variant="default">public</Badge>}
                {d.repo.archived ? <Badge color="yellow" variant="light">archived</Badge> : null}
                {d.writable ? <Status tone="good">fleet repo — managed here</Status> : <Status tone="info" title="Reads only: writes are limited to fleet repos the hub owns">read-only here</Status>}
                <Text size="sm" c="dimmed">{d.repo.description}</Text>
                <External href={d.repo.html_url} size="sm">{d.nwo}</External>
                {d.fleet_name ? <Anchor component={Link} to={to.project(d.fleet_name)} size="sm">project page</Anchor> : null}
                <Button size="compact-xs" variant="subtle" leftSection={<IconRefresh size={12} />} onClick={() => void qc.invalidateQueries({ queryKey: ['github', 'repo', nwo] })}>refresh</Button>
              </Group>
            ) : null}
            {Object.keys(d.errors).length ? <Banner tone="warn" title="Some of this repo could not be read">{Object.entries(d.errors).map(([k, v]) => `${k}: ${v}`).join(' · ')}</Banner> : null}
            {d.writable && !status.data?.writes_enabled ? <Banner tone="warn">GitHub writes are switched off in this console — this view is read-only.</Banner> : null}
            <Tabs value={tab} onChange={setTab} keepMounted={false}>
              <Tabs.List mb="md">
                <Tabs.Tab value="issues">Issues <Badge size="xs" variant="light" ml={4}>{d.issues.length}</Badge></Tabs.Tab>
                <Tabs.Tab value="pulls">Pull requests <Badge size="xs" variant="light" ml={4}>{d.pulls.length}</Badge></Tabs.Tab>
                <Tabs.Tab value="runs">Runs</Tabs.Tab>
                <Tabs.Tab value="workflows">Workflows <Badge size="xs" variant="light" ml={4}>{d.workflows.length}</Badge></Tabs.Tab>
              </Tabs.List>
              <Tabs.Panel value="issues">
                <Group gap="sm" mb="sm">
                  <TextInput placeholder="Filter issues…" value={q} onChange={(e) => setQ(e.currentTarget.value)} w={260} />
                  {canWrite ? <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => setCreating((c) => !c)}>New issue</Button> : null}
                </Group>
                {creating ? <NewIssue d={d} onDone={() => setCreating(false)} /> : null}
                <DataTable<GhIssue>
                  rows={issues}
                  keys
                  rowKey={(i) => String(i.number)}
                  onActivate={(i) => setOpen(i.number)}
                  open={(i) => i.html_url}
                  empty="no open issues"
                  minWidth={760}
                  columns={[
                    { key: 'n', header: '#', num: true, sort: (i) => i.number, render: (i) => i.number, width: 60 },
                    { key: 't', header: 'title', sort: (i) => i.title, render: (i) => <div><Text size="sm" fw={500}>{i.title}</Text><LabelChips names={i.labels} colors={colors} /></div> },
                    { key: 'u', header: 'author', sort: (i) => i.user ?? '', render: (i) => <Text size="sm">{i.user}</Text> },
                    { key: 'c', header: 'comments', num: true, sort: (i) => i.comments, render: (i) => i.comments },
                    { key: 'up', header: 'updated', sort: (i) => i.updated_at, render: (i) => <Text size="xs" c="dimmed">{when(i.updated_at)}</Text> },
                  ]}
                />
              </Tabs.Panel>
              <Tabs.Panel value="pulls">
                <DataTable
                  rows={d.pulls}
                  keys
                  rowKey={(p) => String(p.number)}
                  onActivate={(p) => setOpen(p.number)}
                  open={(p) => p.html_url}
                  empty="no open pull requests"
                  minWidth={760}
                  columns={[
                    { key: 'n', header: '#', num: true, sort: (p) => p.number, render: (p) => p.number, width: 60 },
                    { key: 't', header: 'title', sort: (p) => p.title, render: (p) => <div><Text size="sm" fw={500}>{p.title}{p.draft ? <Badge ml={6} size="xs" variant="default">draft</Badge> : null}</Text><LabelChips names={p.labels} colors={colors} /></div> },
                    { key: 'b', header: 'branch', render: (p) => <Mono dim>{p.head} → {p.base}</Mono> },
                    { key: 'u', header: 'author', sort: (p) => p.user ?? '', render: (p) => <Text size="sm">{p.user}</Text> },
                    { key: 'up', header: 'updated', sort: (p) => p.updated_at, render: (p) => <Text size="xs" c="dimmed">{when(p.updated_at)}</Text> },
                  ]}
                />
              </Tabs.Panel>
              <Tabs.Panel value="runs">
                <SegmentedControl size="xs" mb="sm" value={runFilter} onChange={setRunFilter} data={[{ value: 'all', label: 'Latest 25' }, { value: 'failed', label: 'Failed' }, { value: 'active', label: 'In progress' }]} />
                <DataTable
                  rows={runs}
                  rowKey={(r) => String(r.id)}
                  onActivate={(r) => window.open(r.html_url, '_blank', 'noopener')}
                  tone={(r) => (r.conclusion === 'failure' ? 'crit' : undefined)}
                  empty="no runs"
                  minWidth={900}
                  columns={[
                    { key: 'w', header: 'workflow', sort: (r) => r.name, render: (r) => <div><External href={r.html_url} size="sm">{r.name}</External><Text size="xs" c="dimmed" lineClamp={1}>{r.display_title}</Text></div> },
                    { key: 'e', header: 'event', render: (r) => <Text size="sm">{r.event}</Text> },
                    { key: 'b', header: 'branch', render: (r) => <Mono dim>{r.branch}</Mono> },
                    { key: 'c', header: 'result', sort: (r) => r.conclusion ?? r.status, render: (r) => (r.status === 'completed' ? <Conclusion value={r.conclusion} /> : <Group gap={4}><Loader size={10} /><Text size="sm">{r.status}</Text></Group>) },
                    { key: 'a', header: 'attempt', num: true, render: (r) => r.run_attempt },
                    { key: 't', header: 'started', sort: (r) => r.created_at, render: (r) => <Text size="xs" c="dimmed">{when(r.created_at)}</Text> },
                    {
                      key: 'x', header: '', render: (r) => canWrite ? (
                        <Group gap={4} wrap="nowrap">
                          {r.status === 'completed' && r.conclusion !== 'success' ? <Button size="compact-xs" variant="light" onClick={() => void act('run.rerun_failed', { run_id: r.id }, <>Re-run the failed jobs of “{r.name}” (run {r.id}).</>)}>Re-run failed</Button> : null}
                          {r.status !== 'completed' ? <Button size="compact-xs" color="red" variant="light" onClick={() => void act('run.cancel', { run_id: r.id }, <>Cancel “{r.name}” (run {r.id}).</>, { danger: true })}>Cancel</Button> : null}
                        </Group>
                      ) : null,
                    },
                  ]}
                />
              </Tabs.Panel>
              <Tabs.Panel value="workflows">
                <Text size="sm" c="dimmed" mb="sm">Disabling a workflow stops every trigger, including its schedule — the platform's own kill switch, beside the fleet's <Mono>vars.*_ENABLED</Mono> gates.</Text>
                <DataTable
                  rows={d.workflows}
                  rowKey={(w) => String(w.id)}
                  tone={(w) => (w.state !== 'active' ? 'muted' : undefined)}
                  empty="no workflows"
                  columns={[
                    { key: 'n', header: 'workflow', sort: (w) => w.name, render: (w) => <External href={w.html_url} size="sm">{w.name}</External> },
                    { key: 'p', header: 'file', render: (w) => <Mono dim>{w.path.replace('.github/workflows/', '')}</Mono> },
                    { key: 's', header: 'state', sort: (w) => w.state, render: (w) => (w.state === 'active' ? <Status tone="good">active</Status> : <Status tone="warn">{w.state.replace(/_/g, ' ')}</Status>) },
                    {
                      key: 't', header: 'enabled', render: (w) => (
                        <Switch size="sm" checked={w.state === 'active'} disabled={!canWrite || !['active', 'disabled_manually'].includes(w.state)} aria-label={`enable ${w.name}`}
                          onChange={() => void act(w.state === 'active' ? 'workflow.disable' : 'workflow.enable', { workflow_id: w.id },
                            w.state === 'active' ? <>Disable “{w.name}”: no trigger, schedule included, will start it until it is enabled again.</> : <>Enable “{w.name}”.</>,
                            { danger: w.state === 'active' })} />
                      ),
                    },
                  ]}
                />
              </Tabs.Panel>
            </Tabs>
            <IssueDrawer d={d} number={open} onClose={() => setOpen(null)} canWrite={canWrite} />
          </>
        );
      }}
    </Load>
  );
}
