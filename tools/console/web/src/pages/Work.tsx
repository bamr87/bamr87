// The Work board: every open issue, pull request, roadmap spec, spec package
// and BACKLOG.md item across the fleet, on six lanes, in the order the loops
// will take them (/api/work — dash-gen work_board.py). Drag to rebalance:
// across lanes moves an item's stage (labels / roadmap status), within a lane
// sets the order (a pin in _data/work_queue.yml, which the issue pipeline and
// repo-evolution read), across priority columns reprioritises. Every change is
// staged and previewed — the next-run cut line moves as you drag — and Apply
// writes it: labels on GitHub after one confirm, files in the working tree for
// you to commit. The board never commits, merges or pushes.
import { useCallback, useMemo, useState, type KeyboardEvent } from 'react';
import { Link, useSearchParams } from 'react-router';
import {
  Anchor, Badge, Button, Group, List, Loader, Paper, SegmentedControl, Select, SimpleGrid, Stack, Tabs, Text, TextInput,
} from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { IconArrowBackUp, IconCheck, IconSearch, IconX } from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import { hasConsole } from '../api/backend';
import { post } from '../api/client';
import { useGithubStatus, useWork, useWorkPreview } from '../api/hooks';
import type { WorkApplyResult, WorkBoard, WorkItem, WorkKind } from '../api/types';
import { Banner, LocalOnly, Load, Mono, PageHeader, StatTile } from '../components/ui';
import { LogView } from '../jobs/JobLog';
import { RunButton } from '../jobs/RunButton';
import { includesText, when } from '../lib/format';
import { gh, to } from '../lib/links';
import { LANE_LOOP, Lane, PriorityColumn, WorkCtx, type WorkCtxValue } from './WorkBoard';
import { WorkFlow, Hints } from './WorkFlow';
import { WorkItemDrawer } from './WorkItem';
import {
  byKey, canDrop, dropInLane, LANE_ORDER, nudge as nudgePlan, pinTop as pinTopPlan, setPriority, unpin as unpinPlan, usePlan,
} from './workPlan';
import s from './Work.module.css';

const KINDS: { value: 'all' | WorkKind; label: string }[] = [
  { value: 'all', label: 'all' },
  { value: 'issue', label: 'issues' },
  { value: 'pr', label: 'PRs' },
  { value: 'roadmap', label: 'roadmap' },
  { value: 'spec', label: 'specs' },
  { value: 'backlog', label: 'backlog' },
];
const TARGET_LABEL: Record<string, string> = {
  github: 'GitHub labels — applied now, as the connected account',
  roadmap: '_data/roadmap.yml — in the working tree',
  work_queue: '_data/work_queue.yml — in the working tree',
};

export function Work() {
  const [sp, setSp] = useSearchParams();
  const view = sp.get('view') ?? 'board';
  const kind = sp.get('kind') ?? 'all';
  const repo = sp.get('repo') ?? '';
  const q = sp.get('q') ?? '';
  const itemKey = sp.get('item');
  const set = useCallback((k: string, v: string | null) => {
    setSp((prev) => {
      const next = new URLSearchParams(prev);
      if (v && v !== 'all' && !(k === 'view' && v === 'board')) next.set(k, v);
      else next.delete(k);
      return next;
    }, { replace: k !== 'item' });
  }, [setSp]);

  const base = useWork();
  const { plan, size, push, undo, reset, canUndo } = usePlan();
  const preview = useWorkPreview(size ? plan : null);
  const canWrite = hasConsole();

  return (
    <>
      <PageHeader
        title="Work board"
        description={<>Every open issue, pull request, roadmap spec, spec package and backlog item, in the order the loops will take it. Drag a card <b>within</b> a lane to set that order, <b>across</b> lanes to move its stage, or across the priority columns to reprioritise. Nothing is written until you apply. The order lands in <Mono>_data/work_queue.yml</Mono>, which the issue pipeline and repo-evolution read. Keys: <Mono>Alt+↑/↓</Mono> reorder, <Mono>Alt+←/→</Mono> move. See <Anchor href={gh.hubFile('docs/WORK-BOARD.md')} target="_blank" size="sm">docs/WORK-BOARD.md</Anchor>.</>}
        actions={canWrite ? (
          <>
            <RunButton op="issues">Refresh issues</RunButton>
            <RunButton op="triage">Refresh PRs</RunButton>
          </>
        ) : undefined}
      />
      <Load q={base} rows={6}>
        {(doc) => (
          <Board doc={doc} shown={size && preview.data ? preview.data : doc} plan={plan} size={size} push={push} undo={undo}
            reset={reset} canUndo={canUndo} previewing={preview.isFetching} previewError={preview.isError ? (preview.error as Error).message : null}
            canWrite={canWrite} view={view} kind={kind} repo={repo} q={q} itemKey={itemKey} set={set} />
        )}
      </Load>
    </>
  );
}

interface BoardProps {
  doc: WorkBoard;
  shown: WorkBoard;
  plan: ReturnType<typeof usePlan>['plan'];
  size: number;
  push: ReturnType<typeof usePlan>['push'];
  undo: () => void;
  reset: () => void;
  canUndo: boolean;
  previewing: boolean;
  previewError: string | null;
  canWrite: boolean;
  view: string;
  kind: string;
  repo: string;
  q: string;
  itemKey: string | null;
  set: (k: string, v: string | null) => void;
}

function Board(p: BoardProps) {
  const { doc: base, shown, plan, push, canWrite, view, set } = p;
  const [dragKey, setDragKey] = useState<string | null>(null);
  const baseByKey = useMemo(() => byKey(base), [base]);
  const busy = p.previewing;

  const ctx: WorkCtxValue = useMemo(() => ({
    base, shown, baseByKey, canWrite, busy, active: p.itemKey, dragKey, setDragKey,
    open: (key) => set('item', key),
    dropTo: (key, lane, before) => push(dropInLane(plan, base, shown, key, lane, before)),
    setPrio: (key, value) => push(setPriority(plan, base, key, value)),
    pinTop: (key) => push(pinTopPlan(plan, base, shown, key)),
    unpin: (key) => push(unpinPlan(plan, base, shown, key)),
    nudge: (key, d) => push(nudgePlan(plan, base, shown, key, d)),
  }), [base, shown, baseByKey, canWrite, busy, p.itemKey, dragKey, plan, push, set]);

  const onKey = useCallback((e: KeyboardEvent, it: WorkItem) => {
    if (e.target !== e.currentTarget) return;
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      ctx.open(it.key);
      return;
    }
    if (!e.altKey || !canWrite || busy) return;
    if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
      e.preventDefault();
      if (view === 'board') ctx.nudge(it.key, e.key === 'ArrowUp' ? -1 : 1);
    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault();
      const d = e.key === 'ArrowLeft' ? -1 : 1;
      if (view === 'priority') {
        const next = base.priorities[base.priorities.indexOf(it.priority) + d];
        if (next) ctx.setPrio(it.key, next);
      } else {
        const lanes = LANE_ORDER.filter((l) => canDrop(baseByKey.get(it.key), l));
        const next = lanes[lanes.indexOf(it.lane) + d];
        if (next) ctx.dropTo(it.key, next, null);
      }
    }
  }, [ctx, canWrite, busy, view, base.priorities, baseByKey]);

  const visible = useMemo(() => shown.items.filter((it) => (p.kind === 'all' || it.kind === p.kind)
    && (!p.repo || it.repo === p.repo)
    && includesText([it.title, it.repo, it.ref, it.key, it.note, ...(it.labels ?? [])], p.q)), [shown.items, p.kind, p.repo, p.q]);

  const t = shown.totals;
  const human = shown.loops.find((l) => l.id === 'human');
  const blocked = shown.lanes.find((l) => l.id === 'blocked');
  const src = shown.sources;
  const repoOptions = useMemo(() => base.repos.map((r) => ({ value: r.repo, label: `${r.repo} (${r.total})` })), [base.repos]);

  return (
    <WorkCtx value={ctx}>
      <SimpleGrid cols={{ base: 2, md: 3, xl: 6 }} spacing="sm">
        <StatTile label="Open work" value={t.items} sub={`${t.by_kind.issue} issues · ${t.by_kind.pr} PRs · ${t.by_kind.roadmap} roadmap · ${t.by_kind.spec} specs · ${t.by_kind.backlog} backlog`} />
        <StatTile label="Next run" value={t.next_run} sub={shown.loops.filter((l) => ['t1', 't2', 't3'].includes(l.id)).map((l) => `${l.id.toUpperCase()} ${l.next_run}/${l.cap}`).join(' · ')} />
        <StatTile label="Waiting for you" value={human?.eligible ?? 0} sub={`${human?.breakdown?.reviews ?? 0} reviews · ${human?.breakdown?.approvals ?? 0} approvals`} />
        <StatTile label="Blocked" value={blocked?.count ?? 0} sub="a gap only a human can close" tone={(blocked?.count ?? 0) > 20 ? 'crit' : undefined} />
        <StatTile label="P0 / P1" value={`${t.by_priority.P0 ?? 0} / ${t.by_priority.P1 ?? 0}`} sub={`${src.work_queue.priority_overrides} set by a human`} />
        <StatTile label="Pinned" value={src.work_queue.pinned} sub={src.work_queue.updated_at ? `work_queue.yml, ${src.work_queue.updated_at}` : 'no manual order yet'} />
      </SimpleGrid>
      <Text fz={12} c="dimmed" mt={6}>
        {`Issues: issue_pipeline.yml ${when(src.issue_pipeline.generated_at)}${src.issue_pipeline.full ? '' : ' (capped queues + label-only issues)'} · PRs: fleet_triage.yml ${when(src.fleet_triage.generated_at)} · `}
        {src.local.scanned ? `specs + backlog: ${src.local.repos.length} checked-out spec-driven repo(s)` : 'specs + backlog: on a console only'}
      </Text>
      {!canWrite ? <LocalOnly what="Reprioritising (drag and drop, and every lever in an item’s drawer) and the spec / BACKLOG.md items read from submodule checkouts" /> : null}

      <Tabs value={view} onChange={(v) => set('view', v)} keepMounted={false} mt="md">
        <Tabs.List mb="sm">
          <Tabs.Tab value="board">Board</Tabs.Tab>
          <Tabs.Tab value="priority">Priorities</Tabs.Tab>
          <Tabs.Tab value="flow">Throughput {shown.hints.length ? <Badge size="xs" variant="light" ml={4}>{shown.hints.length}</Badge> : null}</Tabs.Tab>
        </Tabs.List>
        {view !== 'flow' ? (
          <Group gap="sm" mb="sm" wrap="wrap">
            <TextInput data-page-search leftSection={<IconSearch size={15} />} placeholder="Filter…  ( / )" value={p.q} onChange={(e) => set('q', e.currentTarget.value)} w={240} />
            <SegmentedControl size="xs" data={KINDS.map((k) => ({ value: k.value, label: k.value === 'all' ? 'all' : `${k.label} ${t.by_kind[k.value] ?? 0}` }))} value={p.kind} onChange={(v) => set('kind', v)} />
            <Select placeholder="any repo" data={repoOptions} value={p.repo || null} onChange={(v) => set('repo', v)} clearable searchable w={220} size="xs" />
            {visible.length !== shown.items.length ? <Text fz={12} c="dimmed">{`${visible.length} of ${shown.items.length}`}</Text> : null}
          </Group>
        ) : null}
        <Tabs.Panel value="board">
          <div className={s.lanes}>
            {shown.lanes.map((lane) => (
              <Lane key={lane.id} lane={lane} items={visible.filter((it) => it.lane === lane.id)}
                loop={LANE_LOOP[lane.id] ? shown.loops.find((l) => l.id === LANE_LOOP[lane.id]) : undefined} onKey={onKey} />
            ))}
          </div>
        </Tabs.Panel>
        <Tabs.Panel value="priority">
          <div className={s.lanes}>
            {shown.priorities.map((pr) => (
              <PriorityColumn key={pr} p={pr} items={visible.filter((it) => it.priority === pr)} onKey={onKey} />
            ))}
          </div>
        </Tabs.Panel>
        <Tabs.Panel value="flow">
          <WorkFlow doc={shown} onRepo={(r) => { set('repo', r); set('view', 'board'); }} onLane={() => set('view', 'board')} />
        </Tabs.Panel>
      </Tabs>
      {view !== 'flow' && shown.hints.length ? (
        <Stack gap={0} mt="sm"><Hints doc={{ ...shown, hints: shown.hints.slice(0, 2) }} onLane={() => set('view', 'board')} /></Stack>
      ) : null}

      {p.size ? <Tray {...p} /> : null}
      <WorkItemDrawer itemKey={p.itemKey} base={base} shown={shown} plan={plan} push={push} canWrite={canWrite}
        onClose={() => set('item', null)} onOpen={(k) => set('item', k)} />
    </WorkCtx>
  );
}

function Tray(p: BoardProps) {
  const qc = useQueryClient();
  const ghs = useGithubStatus();
  const changes = p.shown.changes ?? [];
  const [applying, setApplying] = useState(false);
  const groups = Object.entries(changes.reduce<Record<string, string[]>>((acc, c) => {
    (acc[c.target] ??= []).push(c.what);
    return acc;
  }, {}));
  const labels = changes.filter((c) => c.target === 'github').length;

  const apply = () => modals.openConfirmModal({
    title: labels ? 'This writes to GitHub and to the working tree' : 'This writes to the working tree',
    size: 'lg',
    children: (
      <Stack gap="sm">
        {groups.map(([target, whats]) => (
          <div key={target}>
            <Text fw={600} fz={13}>{TARGET_LABEL[target] ?? target}</Text>
            <List size="sm" spacing={2}>{whats.map((w) => <List.Item key={w}>{w}</List.Item>)}</List>
          </div>
        ))}
        {labels ? <Text fz={12} c="dimmed">{`Label changes go through the console's GitHub write path as ${ghs.data?.login ?? 'the connected account'} and land in its action log.`}</Text> : null}
        <Text fz={12} c="dimmed">Files are written, never committed. Commit them to make this order the record the loops read on their next run.</Text>
      </Stack>
    ),
    labels: { confirm: `Apply ${changes.length} change${changes.length === 1 ? '' : 's'}`, cancel: 'Cancel' },
    confirmProps: { color: labels ? 'red' : undefined },
    onConfirm: () => void run(),
  });

  const run = async () => {
    setApplying(true);
    try {
      const r = await post<WorkApplyResult>('/api/work/apply', { plan: p.plan, confirm: true });
      qc.setQueryData(['work'], r.board);
      await qc.invalidateQueries({ queryKey: ['work'] });
      await qc.invalidateQueries({ queryKey: ['github', 'log'] });
      p.reset();
      const failed = r.results.filter((x) => !x.ok);
      notifications.show({
        color: failed.length ? 'yellow' : 'teal',
        title: failed.length ? `${failed.length} of ${r.results.length} changes failed` : `Applied ${r.results.length} change${r.results.length === 1 ? '' : 's'}`,
        message: failed.length ? failed.map((f) => `${f.what}: ${f.error}`).join('\n') : 'Review the diff, then commit it.',
        autoClose: failed.length ? 12000 : 5000,
      });
      modals.open({
        title: 'Applied',
        size: 'xl',
        children: (
          <Stack gap="sm">
            <List size="sm" spacing={2}>
              {r.results.map((x) => (
                <List.Item key={`${x.target}:${x.what}`} icon={x.ok ? <IconCheck size={14} color="var(--good)" /> : <IconX size={14} color="var(--critical)" />}>
                  {x.what}{x.error ? <Text span c="var(--critical)" fz={12}>{` — ${x.error}`}</Text> : null}
                </List.Item>
              ))}
            </List>
            {r.pruned.length ? <Text fz={12} c="dimmed">{`Pruned ${r.pruned.length} key(s) for items that have closed: ${r.pruned.join(', ')}`}</Text> : null}
            {r.diff ? (
              <>
                <Text fw={600} fz={13}>In the working tree — commit it to make it the record</Text>
                <LogView raw={r.diff} height={300} />
              </>
            ) : null}
          </Stack>
        ),
      });
    } catch (e) {
      notifications.show({ color: 'red', title: 'Not applied', message: (e as Error).message, autoClose: 10000 });
    } finally {
      setApplying(false);
    }
  };

  return (
    <Paper className={s.tray} p="sm" shadow="md">
      <Group justify="space-between" wrap="wrap" gap="sm" align="flex-start">
        <Stack gap={4} flex={1} miw={260}>
          <Group gap="xs">
            <Text fw={650} fz={14}>{`${p.size} staged change${p.size === 1 ? '' : 's'}`}</Text>
            {p.previewing ? <Loader size="xs" /> : <Text fz={12} c="dimmed">previewed: the lanes, the cut lines and the throughput numbers show the result</Text>}
          </Group>
          {p.previewError ? <Banner tone="crit" title="The board cannot make this change">{p.previewError} Undo it to carry on.</Banner> : null}
          <div className={s.trayList}>
            <List size="sm" spacing={1}>
              {changes.map((c) => <List.Item key={`${c.target}:${c.what}`}><Badge size="xs" variant="default" mr={6}>{c.target === 'github' ? 'GitHub' : c.target === 'roadmap' ? 'roadmap.yml' : 'work_queue.yml'}</Badge>{c.what}</List.Item>)}
            </List>
          </div>
        </Stack>
        <Group gap="xs">
          <Button size="xs" variant="subtle" leftSection={<IconArrowBackUp size={14} />} disabled={!p.canUndo || applying} onClick={p.undo}>Undo</Button>
          <Button size="xs" variant="default" disabled={applying} onClick={p.reset}>Discard all</Button>
          <Button size="xs" color={labels ? 'red' : undefined} loading={applying} disabled={p.previewing || Boolean(p.previewError) || !changes.length} onClick={apply}>
            Apply…
          </Button>
        </Group>
      </Group>
      <Text fz={11.5} c="dimmed" mt={4}>{`Order and priority overrides go to ${p.shown.queue_path ?? '_data/work_queue.yml'}; roadmap moves to _data/roadmap.yml; issue moves are agent: label changes. `}<Anchor component={Link} to={to.github()} fz={11.5}>GitHub action log</Anchor></Text>
    </Paper>
  );
}
