// The Work board's two drag surfaces: the lanes (drag across to move an
// item's stage, within to set the order the loops take it in) and the
// priority columns (drag across to reprioritise). Every drop becomes a staged
// plan entry (workPlan.ts) — nothing is written until Apply.
//
// Native HTML5 drag and drop, plus the same moves from the keyboard (Alt+↑/↓
// reorder, Alt+←/→ move a lane or a priority step) and from each card's menu,
// which is also the touch path.
import { createContext, useContext, useMemo, useRef, useState, type DragEvent, type KeyboardEvent, type ReactNode } from 'react';
import { ActionIcon, Badge, Button, Group, Menu, Progress, Text, Tooltip } from '@mantine/core';
import {
  IconArrowsMove, IconCircleDot, IconDots, IconExternalLink, IconFileDescription, IconFlag, IconGitPullRequest,
  IconListDetails, IconNote, IconPin, IconPinnedOff, IconRoadSign,
} from '@tabler/icons-react';
import type { WorkBoard, WorkItem, WorkKind, WorkLane, WorkLaneId, WorkLoop, WorkLoopId } from '../api/types';
import { Meter } from '../components/ui';
import { canDrop } from './workPlan';
import s from './Work.module.css';

export const KIND: Record<WorkKind, { icon: typeof IconCircleDot; label: string; plural: string }> = {
  issue: { icon: IconCircleDot, label: 'issue', plural: 'issues' },
  pr: { icon: IconGitPullRequest, label: 'pull request', plural: 'PRs' },
  roadmap: { icon: IconRoadSign, label: 'roadmap spec', plural: 'roadmap' },
  spec: { icon: IconFileDescription, label: 'spec package', plural: 'specs' },
  backlog: { icon: IconListDetails, label: 'backlog item', plural: 'backlog' },
};
export const PRIO_COLOR: Record<string, string> = { P0: 'red', P1: 'orange', P2: 'cyan', P3: 'gray' };
export const PRIO_HINT: Record<string, string> = { P0: 'now', P1: 'soon', P2: 'later', P3: 'someday' };
export const LOOP_SHORT: Record<WorkLoopId, string> = { t1: 'T1', t2: 'T2', t3: 'T3', evolve: '/evolve', human: 'you', none: 'nobody' };
/** The loop whose next run a lane's cut line shows. */
export const LANE_LOOP: Partial<Record<WorkLaneId, WorkLoopId>> = { triage: 't1', ready: 't2', doing: 't3' };
const LANE_LABEL: Record<WorkLaneId, string> = {
  triage: 'Triage', ready: 'Ready', doing: 'In flight', review: 'Review', blocked: 'Blocked', hold: 'On hold',
};
const PAGE = 40;

export function sourceText(it: WorkItem): string {
  switch (it.priority_source) {
    case 'override': return `Set by a human in work_queue.yml. The formula says ${it.priority_auto}.`;
    case 'computed': return `Computed by the issue pipeline${it.detail.score != null ? ` (score ${it.detail.score})` : ''}.`;
    case 'label': return 'From its priority label. This snapshot predates the pipeline scoring every issue.';
    case 'default': return it.kind === 'spec' ? 'Default for a spec package (in progress → P1).' : 'No priority signal; the default.';
    case 'derived': return 'Derived from the PR: red CI → P1, dependabot → P3, otherwise P2.';
    case 'roadmap': return 'From _data/roadmap.yml.';
    case 'severity': return 'From its BACKLOG.md severity (high → P1, med → P2, low → P3).';
    default: return '';
  }
}

export interface WorkCtxValue {
  base: WorkBoard;
  shown: WorkBoard;
  baseByKey: Map<string, WorkItem>;
  canWrite: boolean;
  busy: boolean;
  active: string | null;
  dragKey: string | null;
  setDragKey: (k: string | null) => void;
  open: (key: string) => void;
  dropTo: (key: string, lane: WorkLaneId, before: string | null) => void;
  setPrio: (key: string, p: string | null) => void;
  pinTop: (key: string) => void;
  unpin: (key: string) => void;
  nudge: (key: string, delta: -1 | 1) => void;
}

const Ctx = createContext<WorkCtxValue | null>(null);
export const WorkCtx = Ctx.Provider;
function useWork(): WorkCtxValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('Work board components need <WorkCtx>');
  return v;
}

export function PrioBadge({ it }: { it: WorkItem }) {
  return (
    <Tooltip label={sourceText(it)}>
      <Badge size="xs" color={PRIO_COLOR[it.priority] ?? 'gray'} variant={it.priority_source === 'override' ? 'filled' : 'light'}
        rightSection={it.priority_source === 'override' ? <IconFlag size={9} aria-label="human override" /> : undefined}>
        {it.priority}
      </Badge>
    </Tooltip>
  );
}

function Chips({ it, showLane, skipped, pinPos }: { it: WorkItem; showLane?: boolean; skipped?: string | null; pinPos?: number | null }) {
  const d = it.detail;
  const chips: ReactNode[] = [];
  if (it.next_run) {
    chips.push(
      <Tooltip key="next" label={it.loop === 'evolve' ? '/spec-driven:evolve takes this item next (the kit’s own picker).' : `The next ${LOOP_SHORT[it.loop]} run takes this item, as #${it.next_run} of its queue.`}>
        <Badge size="xs" variant="filled" color="cyan">{it.loop === 'evolve' ? '/evolve next' : `${LOOP_SHORT[it.loop]} next #${it.next_run}`}</Badge>
      </Tooltip>,
    );
  }
  if (skipped) chips.push(<Tooltip key="skip" label={`Ranked above the cut, but the ${skipped} keeps it out of the next run.`}><Badge size="xs" variant="outline" color="yellow">{skipped}</Badge></Tooltip>);
  if (pinPos) chips.push(<Badge key="pin" size="xs" variant="light" color="grape" leftSection={<IconPin size={9} />}>{`#${pinPos}`}</Badge>);
  if (it.moved) {
    chips.push(
      <Tooltip key="mv" label={it.moved.pending ? 'Staged on this board. Apply to make it real.' : 'Labels changed on GitHub. The issue-pipeline snapshot will catch up on its next run.'}>
        <Badge size="xs" variant="outline">{it.moved.pending ? 'staged' : 'moved'}</Badge>
      </Tooltip>,
    );
  }
  if (showLane) chips.push(<Badge key="lane" size="xs" variant="default">{LANE_LABEL[it.lane]}</Badge>);
  if (it.kind === 'issue') {
    if (it.readiness != null && !d.derived) chips.push(<Tooltip key="r" label="Readiness: 100 means an agent could start implementing now."><Badge size="xs" variant="default">{`ready ${it.readiness}`}</Badge></Tooltip>);
    if (it.autonomy === 'assisted') chips.push(<Tooltip key="a" label={it.autonomy_reason ?? ''}><Badge size="xs" variant="outline" color="grape">human review</Badge></Tooltip>);
    if (it.autonomy === 'blocked' && it.lane !== 'hold') chips.push(<Tooltip key="b" label={it.autonomy_reason ?? ''}><Badge size="xs" variant="outline" color="red">gated</Badge></Tooltip>);
    if (it.size) chips.push(<Badge key="sz" size="xs" variant="default">{it.size.replace('size:', '')}</Badge>);
  }
  if (it.kind === 'pr') {
    if (d.ci === 'fail') chips.push(<Badge key="ci" size="xs" color="red" variant="light">CI failing</Badge>);
    if (d.draft) chips.push(<Badge key="dr" size="xs" variant="default">draft</Badge>);
    if (d.dependabot) chips.push(<Badge key="dp" size="xs" variant="default">dependabot</Badge>);
  }
  if (it.kind === 'spec') {
    if (d.open_questions?.length) chips.push(<Tooltip key="oq" label={`Unresolved: ${d.open_questions.join(', ')} — /clarify resolves them.`}><Badge size="xs" color="yellow" variant="light">{`${d.open_questions.length} open Q`}</Badge></Tooltip>);
    if (d.requirements?.uncovered?.length) chips.push(<Tooltip key="unc" label={`No task covers ${d.requirements.uncovered.join(', ')}.`}><Badge size="xs" color="red" variant="light">{`${d.requirements.uncovered.length} uncovered`}</Badge></Tooltip>);
  }
  if (it.kind === 'backlog') chips.push(<Badge key="k" size="xs" variant="default">{d.kind}</Badge>);
  if (it.kind === 'roadmap' && it.size) chips.push(<Badge key="e" size="xs" variant="default">{`effort ${it.size}`}</Badge>);
  if ((it.idle_days ?? 0) > 14) chips.push(<Badge key="idle" size="xs" variant="outline" color="gray">{`idle ${it.idle_days}d`}</Badge>);
  if (it.note) chips.push(<Tooltip key="note" label={it.note}><IconNote size={14} aria-label="has a note" /></Tooltip>);
  return (
    <>
      {it.progress && it.progress.total ? (
        <Group gap={6} mt={5} wrap="nowrap">
          <Progress value={(100 * it.progress.done) / it.progress.total} size="sm" flex={1} aria-label="tasks done" />
          <Text span fz={11} c="dimmed">{`${it.progress.done}/${it.progress.total} tasks`}</Text>
        </Group>
      ) : null}
      {chips.length ? <div className={s.chips}>{chips}</div> : null}
    </>
  );
}

function CardMenu({ it }: { it: WorkItem }) {
  const w = useWork();
  const base = w.baseByKey.get(it.key);
  const lanes = base ? [base.lane, ...base.movable].filter((l, i, a) => a.indexOf(l) === i && l !== it.lane) : [];
  return (
    <Menu position="bottom-end" withinPortal shadow="md" width={220}>
      <Menu.Target>
        <ActionIcon size="xs" variant="subtle" color="gray" aria-label={`Actions for ${it.repo} ${it.ref}`}
          onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
          <IconDots size={14} />
        </ActionIcon>
      </Menu.Target>
      <Menu.Dropdown onClick={(e) => e.stopPropagation()}>
        <Menu.Item leftSection={<IconListDetails size={14} />} onClick={() => w.open(it.key)}>Details</Menu.Item>
        {w.canWrite ? (
          <>
            {lanes.length ? <Menu.Label>Move to</Menu.Label> : null}
            {lanes.map((l) => (
              <Menu.Item key={l} leftSection={<IconArrowsMove size={14} />} onClick={() => w.dropTo(it.key, l, null)}>{LANE_LABEL[l]}</Menu.Item>
            ))}
            <Menu.Label>Priority</Menu.Label>
            <Group gap={4} px="xs" pb={6}>
              {w.base.priorities.map((p) => (
                <Button key={p} size="compact-xs" variant={p === it.priority ? 'filled' : 'light'} color={PRIO_COLOR[p]} onClick={() => w.setPrio(it.key, p)}>{p}</Button>
              ))}
            </Group>
            {it.priority_source === 'override' ? <Menu.Item onClick={() => w.setPrio(it.key, null)}>{`Clear override (back to ${it.priority_auto})`}</Menu.Item> : null}
            <Menu.Divider />
            <Menu.Item leftSection={<IconPin size={14} />} onClick={() => w.pinTop(it.key)}>Pin to the top of its lane</Menu.Item>
            {it.rank != null ? <Menu.Item leftSection={<IconPinnedOff size={14} />} onClick={() => w.unpin(it.key)}>Unpin</Menu.Item> : null}
          </>
        ) : null}
        {it.url ? (
          <>
            <Menu.Divider />
            <Menu.Item leftSection={<IconExternalLink size={14} />} component="a" href={it.url} target="_blank" rel="noopener noreferrer">Open on GitHub</Menu.Item>
          </>
        ) : null}
      </Menu.Dropdown>
    </Menu>
  );
}

export function Card({ it, showLane, skipped, pinPos, onKey }: {
  it: WorkItem; showLane?: boolean; skipped?: string | null; pinPos?: number | null; onKey: (e: KeyboardEvent, it: WorkItem) => void;
}) {
  const w = useWork();
  const Icon = KIND[it.kind].icon;
  const draggable = w.canWrite && !w.busy;
  return (
    <div
      className={s.card}
      data-key={it.key}
      data-next={it.next_run ? '' : undefined}
      data-moved={it.moved ? '' : undefined}
      data-active={w.active === it.key ? '' : undefined}
      data-dragging={w.dragKey === it.key ? '' : undefined}
      draggable={draggable}
      tabIndex={0}
      role="button"
      aria-label={`${KIND[it.kind].label} ${it.repo} ${it.ref}, ${it.priority}: ${it.title}`}
      onClick={() => w.open(it.key)}
      onKeyDown={(e) => onKey(e, it)}
      onDragStart={(e) => {
        e.dataTransfer.setData('text/plain', it.key);
        e.dataTransfer.effectAllowed = 'move';
        w.setDragKey(it.key);
      }}
      onDragEnd={() => w.setDragKey(null)}
    >
      <Group gap={6} wrap="nowrap" justify="space-between" align="flex-start">
        <Group gap={5} wrap="nowrap" className={s.meta}>
          <Icon size={14} aria-hidden />
          <Text span fz={11.5} ff="monospace" truncate>{`${it.repo} ${it.ref}`}</Text>
        </Group>
        <Group gap={4} wrap="nowrap" className={s.nowrap}>
          <PrioBadge it={it} />
          <CardMenu it={it} />
        </Group>
      </Group>
      <div className={s.title}>{it.title}</div>
      <Chips it={it} showLane={showLane} skipped={skipped} pinPos={pinPos} />
    </div>
  );
}

function useDropZone(accept: (key: string) => boolean, onDrop: (key: string, before: string | null) => void, withMarker: boolean) {
  const w = useWork();
  const body = useRef<HTMLDivElement>(null);
  const [before, setBefore] = useState<string | null | undefined>(undefined);  // undefined = not over this zone
  const allowed = w.dragKey ? accept(w.dragKey) : false;
  const handlers = {
    onDragOver: (e: DragEvent) => {
      if (!w.dragKey || !allowed) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      if (!withMarker) {
        if (before === undefined) setBefore(null);
        return;
      }
      let next: string | null = null;
      for (const el of Array.from(body.current?.querySelectorAll<HTMLElement>('[data-key]') ?? [])) {
        if (el.dataset.key === w.dragKey) continue;
        const r = el.getBoundingClientRect();
        if (e.clientY < r.top + r.height / 2) {
          next = el.dataset.key ?? null;
          break;
        }
      }
      if (next !== before) setBefore(next);
    },
    onDragLeave: (e: DragEvent) => {
      if (!body.current?.contains(e.relatedTarget as Node | null)) setBefore(undefined);
    },
    onDrop: (e: DragEvent) => {
      e.preventDefault();
      const key = e.dataTransfer.getData('text/plain') || w.dragKey;
      const at = before ?? null;
      setBefore(undefined);
      w.setDragKey(null);
      if (key && accept(key)) onDrop(key, at);
    },
  };
  const state = w.dragKey ? (allowed ? 'ok' : 'no') : undefined;
  return { body, handlers, before, state };
}

function laneSkips(items: WorkItem[], loop: WorkLoop | undefined): Map<string, string> {
  // A card of the lane's loop, ranked above the last card the next run takes,
  // that the run still leaves out: a sub-cap kept it out, so say which.
  const out = new Map<string, string>();
  if (!loop) return out;
  let last = -1;
  items.forEach((it, i) => { if (it.next_run && it.loop === loop.id) last = i; });
  items.forEach((it, i) => {
    if (i < last && it.loop === loop.id && !it.next_run) out.set(it.key, loop.sub_cap ? `${loop.sub_cap.label} cap` : 'cap');
  });
  return out;
}

export function Lane({ lane, items, loop, onKey }: { lane: WorkLane; items: WorkItem[]; loop?: WorkLoop; onKey: (e: KeyboardEvent, it: WorkItem) => void }) {
  const w = useWork();
  const [all, setAll] = useState(false);
  const zone = useDropZone((k) => canDrop(w.baseByKey.get(k), lane.id), (k, before) => w.dropTo(k, lane.id, before), true);
  const skips = useMemo(() => laneSkips(items, loop), [items, loop]);
  const pinPos = useMemo(() => {
    const m = new Map<string, number>();
    items.filter((it) => it.rank != null).forEach((it, i) => m.set(it.key, i + 1));
    return m;
  }, [items]);
  const lastPick = items.reduce((acc, it, i) => (it.next_run && loop && it.loop === loop.id ? i : acc), -1);
  const shown = all ? items : items.slice(0, Math.max(PAGE, lastPick + 6));
  const picks = loop ? items.filter((it) => it.next_run && it.loop === loop.id).length : 0;
  return (
    <section className={s.lane} data-drop={zone.state} aria-label={`${lane.label} lane, ${items.length} items`}>
      <div className={s.laneHead}>
        <Group justify="space-between" gap="xs" wrap="nowrap">
          <Text fw={650} fz={14}>{lane.label}</Text>
          <Group gap={4}>
            {lane.pinned ? <Tooltip label="pinned in the manual order"><Badge size="xs" variant="light" color="grape" leftSection={<IconPin size={9} />}>{lane.pinned}</Badge></Tooltip> : null}
            <Badge size="sm" variant="default">{items.length === lane.count ? lane.count : `${items.length} / ${lane.count}`}</Badge>
          </Group>
        </Group>
        <Text fz={11.5} c="dimmed" mt={2}>{lane.hint}</Text>
        {loop && loop.cap ? (
          <Tooltip label={`${loop.label}: takes ${loop.cap} a run${loop.sub_cap ? `, at most ${loop.sub_cap.value} ${loop.sub_cap.label}` : ''}. ${loop.eligible} eligible.`}>
            <div>
              <Group justify="space-between" mt={6} gap={4}>
                <Text fz={11} c="dimmed">{`${LOOP_SHORT[loop.id]} next run`}</Text>
                <Text fz={11} c="dimmed">{`${loop.next_run} / ${loop.cap}`}</Text>
              </Group>
              <Meter value={loop.next_run} cap={loop.cap} tone={loop.next_run >= loop.cap ? 'good' : 'info'} />
            </div>
          </Tooltip>
        ) : null}
      </div>
      <div className={s.laneBody} ref={zone.body} {...zone.handlers}>
        {shown.map((it, i) => (
          <div key={it.key}>
            {zone.before === it.key ? <div className={s.dropMark} /> : null}
            <Card it={it} skipped={skips.get(it.key)} pinPos={pinPos.get(it.key)} onKey={onKey} />
            {loop && i === lastPick ? <div className={s.cut}>{`${LOOP_SHORT[loop.id]} takes ${picks} above · the rest wait`}</div> : null}
          </div>
        ))}
        {zone.before === null && zone.state === 'ok' ? <div className={s.dropMark} /> : null}
        {!items.length ? <Text fz={12} c="dimmed" ta="center" py="md">nothing here</Text> : null}
        {items.length > shown.length ? (
          <Button size="compact-xs" variant="subtle" onClick={() => setAll(true)}>{`Show all ${items.length}`}</Button>
        ) : null}
      </div>
    </section>
  );
}

export function PriorityColumn({ p, items, onKey }: { p: string; items: WorkItem[]; onKey: (e: KeyboardEvent, it: WorkItem) => void }) {
  const w = useWork();
  const [all, setAll] = useState(false);
  const zone = useDropZone((k) => w.baseByKey.has(k), (k) => w.setPrio(k, p), false);
  const shown = all ? items : items.slice(0, PAGE);
  return (
    <section className={s.lane} data-drop={zone.before !== undefined ? 'ok' : undefined} aria-label={`Priority ${p}, ${items.length} items`}>
      <div className={s.laneHead}>
        <Group justify="space-between" gap="xs">
          <Group gap={6}><Badge color={PRIO_COLOR[p]} variant="light">{p}</Badge><Text fz={13} c="dimmed">{PRIO_HINT[p]}</Text></Group>
          <Badge size="sm" variant="default">{items.length}</Badge>
        </Group>
        <Text fz={11.5} c="dimmed" mt={2}>Drop a card here to make it {p}.</Text>
      </div>
      <div className={s.laneBody} ref={zone.body} {...zone.handlers}>
        {shown.map((it) => <Card key={it.key} it={it} showLane onKey={onKey} />)}
        {!items.length ? <Text fz={12} c="dimmed" ta="center" py="md">nothing here</Text> : null}
        {items.length > shown.length ? <Button size="compact-xs" variant="subtle" onClick={() => setAll(true)}>{`Show all ${items.length}`}</Button> : null}
      </div>
    </section>
  );
}

export { s as boardStyles };
