// The PR queue: every open pull request of the hub and the registry repos, who
// moves each one next, and bulk actions an agent carries out once you confirm
// (/api/prs; tools/fleetcore/prqueue.py, docs/PR-QUEUE.md). Selecting rows and
// choosing an action makes a PLAN from live GitHub (POST /api/prs/plan), shown
// per pull request; Apply runs the prs-act / prs-agent operation with that
// plan's id behind the console's confirm, and the job re-plans and refuses a
// plan whose pull requests moved since.
import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router';
import {
  Anchor, Badge, Button, Checkbox, Code, Group, Modal, Paper, ScrollArea, SegmentedControl, Select, Stack, Table, Text,
  TextInput, Textarea, Tooltip,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useQueryClient } from '@tanstack/react-query';
import { IconGitPullRequest, IconListCheck, IconSearch } from '@tabler/icons-react';
import { hasConsole } from '../api/backend';
import { api, post } from '../api/client';
import { usePrQueue } from '../api/hooks';
import type { PrAction, PrPlan, PrQueue as Doc, PrRow, PrWho } from '../api/types';
import { DataTable, type Column } from '../components/DataTable';
import { Banner, External, Load, LocalOnly, PageHeader, Section, Status, type Tone } from '../components/ui';
import { RunButton } from '../jobs/RunButton';
import { useRunner } from '../jobs/JobRunner';
import { includesText, repoName } from '../lib/format';
import classes from './PrQueue.module.css';

const WHO: { value: PrWho | 'all'; label: string }[] = [
  { value: 'all', label: 'All' }, { value: 'amr', label: 'Amr' }, { value: 'agent', label: 'An agent' },
  { value: 'loop', label: 'A loop' }, { value: 'author', label: 'The author' },
];
const KINDS: Record<string, string> = {
  security: 'Security', dependabot: 'Dependabot', release: 'Release', batch: 'Fan-out batch', harness: 'AI harness',
  ratification: 'Ratification', draft: 'Draft',
};
const CHECK_TONE: Record<string, Tone> = {
  failing: 'crit', action_required: 'warn', cancelled: 'warn', pending: 'info', green: 'good', skipped: 'info', none: 'info',
};
const WHO_COLOR: Record<PrWho, string> = { amr: 'grape', agent: 'cyan', loop: 'gray', author: 'gray' };
/** The server's order (tools/fleetcore/prqueue.py WHO): what waits on Amr first. */
const WHO_ORDER: PrWho[] = ['amr', 'agent', 'loop', 'author'];

function ChecksCell({ r }: { r: PrRow }) {
  const c = r.checks;
  const names = [...c.failing, ...c.cancelled, ...c.pending, ...c.action_required];
  const title = names.length ? names.slice(0, 6).join(', ') : `${c.green} green, ${c.skipped} skipped`;
  return (
    <Group gap={4} wrap="nowrap">
      <Status tone={CHECK_TONE[c.state] ?? 'info'} title={title}>{c.state === 'action_required' ? 'approval' : c.state}</Status>
      {c.false_red ? (
        <Tooltip label={`GitHub shows red: ${c.superseded} superseded run(s) (a cancelled run followed by a success) are counted there and set aside here`} multiline maw={320}>
          <Badge size="xs" variant="outline" color="yellow">false red</Badge>
        </Tooltip>
      ) : null}
    </Group>
  );
}

function NextCell({ r }: { r: PrRow }) {
  const n = r.next;
  return (
    <Stack gap={2}>
      <Group gap={6} wrap="nowrap">
        <Badge size="sm" variant="light" color={WHO_COLOR[n.who]}>{WHO.find((w) => w.value === n.who)?.label}</Badge>
        <Text size="sm" lineClamp={1}>{n.action}</Text>
      </Group>
      <Text size="xs" c="dimmed" lineClamp={2}>{n.why}</Text>
      {r.triage?.next_action ? (
        <Tooltip label={<Stack gap={4}><Text size="xs">Triage, 2026-11-15 (a hint, never run): {r.triage.next_action}</Text>{r.triage.question ? <Text size="xs">Question: {r.triage.question}</Text> : null}</Stack>} multiline maw={420}>
          <Anchor href={r.triage.url ?? r.url} target="_blank" rel="noopener noreferrer" size="xs" c="dimmed">triage note</Anchor>
        </Tooltip>
      ) : null}
    </Stack>
  );
}

function PlanModal({ plan, onClose }: { plan: PrPlan | null; onClose: () => void }) {
  const { runOp } = useRunner();
  if (!plan) return null;
  const apply = async () => {
    const job = await runOp(plan.op, { plan_id: plan.plan_id, apply: true });
    if (job) onClose();
  };
  return (
    <Modal opened onClose={onClose} size="xl" title={`Plan ${plan.plan_id}: ${plan.title}`}>
      <Stack gap="sm">
        <Text size="sm">{plan.counts.do} to do, {plan.counts.skip} skipped. Writes {plan.writes}. Governed by {plan.governed}.</Text>
        {plan.ceiling_usd != null ? <Text size="sm">Ceiling: ${plan.ceiling_usd} {plan.cost_label}.</Text> : null}
        {!plan.enabled ? <Banner tone="warn" title="This action is off">{plan.why}. The plan is shown so you can see what it would do; Apply is refused.</Banner> : null}
        <ScrollArea.Autosize mah="55vh" type="auto" offsetScrollbars>
          <Table verticalSpacing={6} data-plan={plan.plan_id}>
            <Table.Thead><Table.Tr><Table.Th>Pull request</Table.Th><Table.Th>Does</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>
              {[...plan.items].sort((a, b) => Number(b.do) - Number(a.do)).map((i) => (
                <Table.Tr key={i.key} data-do={i.do || undefined}>
                  <Table.Td>
                    <External href={i.url}>{i.key}</External>
                    {i.head_sha ? <Text size="xs" c="dimmed">at {i.head_sha.slice(0, 9)}</Text> : null}
                  </Table.Td>
                  <Table.Td>
                    {i.do ? <Code block className={classes.preview}>{i.preview}</Code> : <Text size="sm" c="dimmed">skip: {i.skip}</Text>}
                    {i.warnings.map((w) => <Text key={w} size="xs" c="yellow">! {w}</Text>)}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </ScrollArea.Autosize>
        <Text size="xs" c="dimmed">Apply runs the {plan.op} operation with this plan's id. It reads GitHub again first and refuses the plan if any pull request moved since this preview; nothing here is merged, forced or deleted.</Text>
        <Group justify="flex-end" gap="xs">
          <Button variant="default" onClick={() => void runOp(plan.op, { plan_id: plan.plan_id })}>Check it still matches</Button>
          <Button color="red" disabled={!plan.enabled || plan.counts.do === 0} onClick={() => void apply()}>Apply to {plan.counts.do}</Button>
          <Button variant="default" onClick={onClose}>Close</Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function BulkBar({ doc, selected, rows, onClear, onSelectAll }: {
  doc: Doc; selected: Set<string>; rows: PrRow[]; onClear: () => void; onSelectAll: () => void;
}) {
  const [action, setAction] = useState<string | null>(null);
  const [note, setNote] = useState('');
  const [reason, setReason] = useState('');
  const [task, setTask] = useState('fix-ci');
  const [busy, setBusy] = useState(false);
  const [plan, setPlan] = useState<PrPlan | null>(null);
  const picked = doc.rows.filter((r) => selected.has(r.key));
  const meta: PrAction | undefined = doc.actions.find((a) => a.id === action);
  const applies = (id: string) => picked.filter((r) => r.applies.includes(id)).length;
  const makePlan = async () => {
    if (!action) return;
    setBusy(true);
    try {
      const params = action === 'comment' ? { note } : action === 'close' ? { reason } : action === 'agent' ? { task } : {};
      setPlan(await post<PrPlan>('/api/prs/plan', { action, prs: picked.map((r) => r.key), params }));
    } catch (e) {
      notifications.show({ color: 'red', title: 'Could not plan', message: (e as Error).message, autoClose: 9000 });
    } finally {
      setBusy(false);
    }
  };
  return (
    <Paper withBorder p="sm" className={classes.bar} data-bulk-bar>
      <Group gap="sm" wrap="wrap" align="flex-end">
        <Text size="sm" fw={600} data-selected-count>{selected.size} selected</Text>
        <Button size="xs" variant="default" onClick={onSelectAll}>Select the {rows.length} shown</Button>
        <Button size="xs" variant="default" onClick={onClear} disabled={!selected.size}>Clear</Button>
        <Select size="xs" w={300} placeholder="Choose an action" value={action} onChange={setAction} aria-label="Bulk action"
          data={doc.actions.map((a) => ({ value: a.id, label: `${a.title}${selected.size ? ` (${applies(a.id)} of ${selected.size})` : ''}${a.enabled ? '' : ' · off'}` }))} />
        {action === 'comment' ? <Textarea size="xs" w={260} autosize maxRows={3} placeholder="Optional note (≤ 500 chars)" value={note} onChange={(e) => setNote(e.currentTarget.value)} /> : null}
        {action === 'close' ? <TextInput size="xs" w={260} placeholder="Why: superseded by #123" value={reason} onChange={(e) => setReason(e.currentTarget.value)} /> : null}
        {action === 'agent' ? <SegmentedControl size="xs" value={task} onChange={setTask} data={[{ value: 'fix-ci', label: 'Fix CI' }, { value: 'address-review', label: 'Address review' }]} /> : null}
        <Button size="xs" leftSection={<IconListCheck size={14} />} loading={busy} disabled={!action || !selected.size || (action === 'close' && !reason.trim())}
          onClick={() => void makePlan()}>Plan</Button>
      </Group>
      {meta ? <Text size="xs" c="dimmed" mt={6}>Writes {meta.writes}. Governed by {meta.governed}.{meta.enabled ? '' : ` Off: ${meta.why}`}</Text> : null}
      <PlanModal plan={plan} onClose={() => setPlan(null)} />
    </Paper>
  );
}

function Queue({ doc }: { doc: Doc }) {
  const [sp, setSp] = useSearchParams();
  const who = (sp.get('who') ?? 'all') as PrWho | 'all';
  const kind = sp.get('kind') ?? '';
  const gate = sp.get('gate') ?? 'all';
  const batch = sp.get('batch') ?? '';
  const repo = sp.get('repo') ?? '';
  const q = sp.get('q') ?? '';
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(sp);
    if (v && v !== 'all') next.set(k, v); else next.delete(k);
    setSp(next, { replace: true });
  };
  const rows = useMemo(() => doc.rows.filter((r) => (who === 'all' || r.next.who === who) && (!kind || r.kinds.includes(kind))
    && (gate === 'all' || r.gate.gated === (gate === 'gated')) && (!batch || r.head === batch) && (!repo || r.repo === repo)
    && includesText([r.key, r.title, r.author, r.head, r.next.action, r.gate.reason], q)), [doc.rows, who, kind, gate, batch, repo, q]);
  const toggle = (key: string) => setSelected((s) => { const n = new Set(s); if (n.has(key)) n.delete(key); else n.add(key); return n; });
  const allShown = rows.length > 0 && rows.every((r) => selected.has(r.key));
  const repos = [...new Set(doc.rows.map((r) => r.repo))].sort((a, b) => repoName(a).localeCompare(repoName(b)));

  const columns: Column<PrRow>[] = [
    {
      key: 'sel', header: <Checkbox size="xs" aria-label="Select every row shown" checked={allShown} indeterminate={!allShown && rows.some((r) => selected.has(r.key))}
        onChange={() => setSelected((s) => { const n = new Set(s); rows.forEach((r) => (allShown ? n.delete(r.key) : n.add(r.key))); return n; })} />,
      render: (r) => <Checkbox size="xs" aria-label={`Select ${r.key}`} checked={selected.has(r.key)} onChange={() => toggle(r.key)} />, width: 32,
    },
    {
      key: 'pr', header: 'Pull request', sort: (r) => `${repoName(r.repo)}#${String(r.number).padStart(6, '0')}`,
      render: (r) => (
        <Stack gap={2}>
          <Group gap={6} wrap="wrap">
            <Text size="xs" c="dimmed" ff="monospace">{repoName(r.repo)}#{r.number}</Text>
            {r.draft ? <Badge size="xs" variant="outline" color="gray" className={classes.noShrink}>draft</Badge> : null}
            {r.private ? <Badge size="xs" variant="outline" color="gray">private</Badge> : null}
          </Group>
          <External href={r.url} size="sm">{r.title}</External>
          <Group gap={4}>{r.kinds.filter((k) => k !== 'draft').map((k) => <Badge key={k} size="xs" variant="light" color="gray">{KINDS[k] ?? k}</Badge>)}</Group>
        </Stack>
      ),
    },
    { key: 'checks', header: 'Checks', sort: (r) => r.checks.state, render: (r) => <ChecksCell r={r} />, width: 150 },
    {
      key: 'gate', header: 'Gate', sort: (r) => (r.gate.gated ? 0 : 1), width: 110,
      render: (r) => <Tooltip label={r.gate.reason} multiline maw={360}><span>{r.gate.gated ? <Status tone="warn">gated</Status> : <Status tone="good">open</Status>}</span></Tooltip>,
    },
    { key: 'merge', header: 'Merge', sort: (r) => r.merge_method ?? '', width: 80, render: (r) => <Text size="sm">{r.merge_method ?? '—'}</Text> },
    { key: 'next', header: 'Who moves next', sort: (r) => `${WHO_ORDER.indexOf(r.next.who)}${r.gate.gated ? 0 : 1}`, render: (r) => <NextCell r={r} /> },
    { key: 'idle', header: 'Idle', num: true, sort: (r) => r.idle_days ?? 0, width: 60, render: (r) => <Text size="sm">{r.idle_days ?? '—'}d</Text> },
  ];

  return (
    <>
      <Group gap="sm" mb="sm" wrap="wrap" data-who-tabs>
        <SegmentedControl size="xs" value={who} onChange={(v) => set('who', v)}
          data={WHO.map((w) => ({ value: w.value, label: `${w.label} ${w.value === 'all' ? doc.counts.total : doc.counts.who[w.value as PrWho]}` }))} />
        <Text size="sm" c="dimmed">{doc.counts.gated} gated · {doc.counts.false_red} false red · {doc.counts.agent_mergeable} an agent may merge (§ 12.2) · {doc.counts.triaged} with a triage note</Text>
      </Group>
      <Group gap="sm" mb="sm" wrap="wrap">
        <TextInput data-page-search leftSection={<IconSearch size={15} />} placeholder="Filter…  ( / )" value={q} onChange={(e) => set('q', e.currentTarget.value)} w={220} />
        <Select size="xs" w={200} placeholder="Every repo" clearable searchable value={repo || null} onChange={(v) => set('repo', v ?? '')} data={repos.map((r) => ({ value: r, label: repoName(r) }))} aria-label="Repo" />
        <Select size="xs" w={170} placeholder="Every kind" clearable value={kind || null} onChange={(v) => set('kind', v ?? '')} aria-label="Kind"
          data={Object.entries(KINDS).map(([value, label]) => ({ value, label: `${label} (${doc.counts.kinds[value] ?? 0})` }))} />
        <SegmentedControl size="xs" value={gate} onChange={(v) => set('gate', v)} data={[{ value: 'all', label: 'Gated or not' }, { value: 'gated', label: `Gated ${doc.counts.gated}` }, { value: 'ungated', label: `Ungated ${doc.counts.ungated}` }]} />
        {batch ? <Badge variant="light" rightSection={<Anchor size="xs" component="button" onClick={() => set('batch', '')}>×</Anchor>}>batch {batch}</Badge> : null}
        <Text size="sm" c="dimmed" data-shown-count>{rows.length} of {doc.counts.total}</Text>
      </Group>
      {doc.batches.length ? (
        <Group gap="xs" mb="sm" wrap="wrap" data-batches>
          <Text size="xs" c="dimmed">Fan-out batches:</Text>
          {doc.batches.map((b) => (
            <Tooltip key={b.head} label={`${b.count} pull requests in ${b.repos} repos: ${b.green} green, ${b.gated} gated, ${b.draft} drafts`}>
              <Button size="compact-xs" variant={batch === b.head ? 'filled' : 'light'} onClick={() => set('batch', batch === b.head ? '' : b.head)}>
                {b.head} · {b.count}
              </Button>
            </Tooltip>
          ))}
        </Group>
      ) : null}
      {hasConsole() ? (
        <BulkBar doc={doc} selected={selected} rows={rows} onClear={() => setSelected(new Set())}
          onSelectAll={() => setSelected((s) => new Set([...s, ...rows.map((r) => r.key)]))} />
      ) : null}
      <DataTable rows={rows} columns={columns} rowKey={(r) => r.key} rowLabel={(r) => r.key} onActivate={(r) => toggle(r.key)}
        tone={(r) => (r.checks.state === 'failing' ? 'crit' : r.gate.gated ? undefined : 'muted')} open={(r) => r.url}
        initialSort={{ key: 'next', desc: false }} keys empty="Nothing matches these filters." minWidth={900} />
    </>
  );
}

export function PrQueue() {
  const queue = usePrQueue();
  const qc = useQueryClient();
  const [reading, setReading] = useState(false);
  // One forced read, put in the cache the page already renders; later refetches go back to `auto`
  // (served from the index and the detail cache until their TTL), so a refocus never forces a re-read.
  const readNow = async () => {
    setReading(true);
    try {
      qc.setQueryData(['prs', 'auto'], await api<Doc>('/api/prs?refresh=force&budget=60'));
    } catch (e) {
      notifications.show({ color: 'red', title: 'Could not read GitHub', message: (e as Error).message, autoClose: 9000 });
    } finally {
      setReading(false);
    }
  };
  return (
    <>
      <PageHeader
        title="PR queue"
        badges={queue.data ? <Status tone={queue.data.status === 'fresh' ? 'good' : queue.data.status === 'unavailable' ? 'crit' : 'warn'}>{queue.data.status}</Status> : null}
        description="Every open pull request of the hub and the registry repos: checks collapsed per check (a cancelled run followed by a success is green), the review gate (§ 12.3), the merge method the repo allows, and who moves it next. Select rows, choose an action, and review its plan; an agent applies it only after you confirm."
        actions={hasConsole() ? (
          <>
            <Button size="xs" variant="default" leftSection={<IconGitPullRequest size={14} />} loading={reading || queue.isFetching}
              onClick={() => void readNow()}>Read GitHub now</Button>
            <RunButton op="prs-refresh">Refresh as a job</RunButton>
          </>
        ) : null}
      />
      {!hasConsole() ? <LocalOnly what="The PR queue reads GitHub under the console's own identity and can hold a private repo's titles, so it is never published" /> : (
        <Load q={queue}>
          {(doc) => (
            <>
              {doc.warnings.length || doc.errors.length ? (
                <Banner tone={doc.status === 'unavailable' ? 'crit' : 'warn'} title={`The queue is ${doc.status}`}>
                  <Stack gap={2}>
                    {doc.warnings.map((w) => <Text key={w} size="sm">{w}</Text>)}
                    {doc.errors.slice(0, 3).map((e, i) => <Text key={i} size="sm">{e.stage}/{e.kind}: {e.message}</Text>)}
                    {doc.hint ? <Text size="sm">{doc.hint}</Text> : null}
                  </Stack>
                </Banner>
              ) : null}
              {!doc.switches.github_writes ? <Banner tone="info" title="GitHub writes are off">DASH_CONSOLE_GITHUB_WRITES=off: plans work, every apply is refused.</Banner> : null}
              <Queue doc={doc} />
              <Section title="The actions" description="What each bulk action writes and what governs it. Merge and close stay off until an amendment says a merge or close the maintainer confirms here is his own.">
                <Stack gap={4}>
                  {doc.actions.map((a) => (
                    <Group key={a.id} gap="xs" wrap="nowrap" align="flex-start">
                      <Status tone={a.enabled ? 'good' : 'warn'}>{a.enabled ? 'on' : 'off'}</Status>
                      <Text size="sm"><b>{a.title}</b> — writes {a.writes}. {a.governed}.</Text>
                    </Group>
                  ))}
                </Stack>
              </Section>
            </>
          )}
        </Load>
      )}
    </>
  );
}
