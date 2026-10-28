// One work item, drilled into: what it is, where it sits, why it is ranked
// there, and every lever on it — each lever stages the same plan entry a drag
// would (workPlan.ts). The body comes from the item's own source: the issue's
// thread on GitHub, the spec packages a PR changes read at its head, the
// roadmap entry, the spec's tasks and text, the BACKLOG.md line.
import { useEffect, useState, type ReactNode } from 'react';
import {
  Anchor, Badge, Button, Divider, Drawer, Group, List, Progress, SegmentedControl, Select, SimpleGrid, Spoiler, Stack,
  Table, Text, Textarea, Title,
} from '@mantine/core';
import { IconCheck, IconCircleDashed, IconLoader2, IconPin, IconPinnedOff } from '@tabler/icons-react';
import { githubToken, hasConsole } from '../api/backend';
import { useData, useGithubIssue, usePullSpecs, useWorkItem } from '../api/hooks';
import type { WorkBoard, WorkItem, WorkLaneId, WorkPlan } from '../api/types';
import { Markdown } from '../components/Markdown';
import { Banner, Empty, External, Mono, RepoLink, Spinner } from '../components/ui';
import { age } from '../lib/format';
import { gh, to } from '../lib/links';
import { KIND, LOOP_SHORT, PRIO_COLOR, PrioBadge, sourceText } from './WorkBoard';
import { byKey, canDrop, dropInLane, LANE_ORDER, pinTop, setNote, setPriority, setRoadmapStatus, unpin } from './workPlan';
import s from './Work.module.css';

const PRIO_WHERE: Record<WorkItem['kind'], string> = {
  issue: 'Priority: an override in work_queue.yml. The issue pipeline ranks by it and T1 applies it as the label.',
  pr: 'Priority: an override in work_queue.yml. The board and repo-evolution’s brief carry it.',
  roadmap: 'Priority: written to _data/roadmap.yml.',
  spec: 'Priority: an override in work_queue.yml. Repo-evolution’s weekly brief carries it.',
  backlog: 'Priority: an override in work_queue.yml. Repo-evolution’s weekly brief carries it.',
};

const LANE_LABEL: Record<WorkLaneId, string> = {
  triage: 'Triage', ready: 'Ready', doing: 'In flight', review: 'Review', blocked: 'Blocked', hold: 'On hold',
};

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Stack gap={0}>
      <Text fz={11.5} c="dimmed">{label}</Text>
      <Text fz={13} component="div">{children}</Text>
    </Stack>
  );
}

interface Props {
  itemKey: string | null;
  base: WorkBoard;
  shown: WorkBoard;
  plan: WorkPlan;
  push: (p: WorkPlan) => void;
  canWrite: boolean;
  onClose: () => void;
  onOpen: (key: string) => void;
}

export function WorkItemDrawer({ itemKey, base, shown, plan, push, canWrite, onClose, onOpen }: Props) {
  const it = (itemKey && (byKey(shown).get(itemKey) ?? byKey(base).get(itemKey))) || null;
  const Icon = it ? KIND[it.kind].icon : null;
  return (
    <Drawer opened={Boolean(itemKey)} onClose={onClose} position="right" size="xl" keepMounted={false}
      title={it && Icon ? <Group gap={8}><Icon size={18} /><Mono>{`${it.repo} ${it.ref}`}</Mono><PrioBadge it={it} /></Group> : 'Work item'}>
      {it ? <Body it={it} base={base} shown={shown} plan={plan} push={push} canWrite={canWrite} onOpen={onOpen} />
        : itemKey ? <Empty>{`${itemKey} is not on the board (closed, merged or shipped since the snapshot).`}</Empty> : null}
    </Drawer>
  );
}

function Body({ it, base, shown, plan, push, canWrite, onOpen }: Omit<Props, 'itemKey' | 'onClose'> & { it: WorkItem }) {
  const detail = useWorkItem(it.key, hasConsole());
  const b = byKey(base).get(it.key);
  const staged = (shown.changes ?? []).filter((c) => c.key === it.key);
  const loop = shown.loops.find((l) => l.id === it.loop);
  return (
    <Stack gap="md">
      <div>
        <Title order={3} fz={17} lh={1.3}>{it.title}</Title>
        <Group gap="sm" mt={6} wrap="wrap">
          <RepoLink name={it.repo} />
          {it.url ? <External href={it.url} size="sm">{it.kind === 'spec' || it.kind === 'backlog' ? 'source' : 'GitHub'}</External> : null}
          {it.nwo ? <Anchor href={to.ghRepo(it.nwo)} size="sm">repo on the GitHub page</Anchor> : null}
          <Mono dim>{it.key}</Mono>
        </Group>
      </div>

      <SimpleGrid cols={{ base: 2, sm: 3 }} spacing="sm" verticalSpacing="xs">
        <Fact label="Lane">{LANE_LABEL[it.lane]}{it.stage !== it.lane ? <Text span c="dimmed" fz={12}>{` (${it.stage})`}</Text> : null}</Fact>
        <Fact label="Priority"><Group gap={6}><PrioBadge it={it} /><Text span fz={12} c="dimmed">{it.priority_source}</Text></Group></Fact>
        <Fact label="Taken by">{loop ? `${loop.label}${it.next_run ? ` — next run, #${it.next_run}` : ''}` : LOOP_SHORT[it.loop]}</Fact>
        <Fact label="Order">{it.rank != null ? 'pinned (manual order)' : 'by its loop’s ranking'}</Fact>
        <Fact label="Age">{age(it.age_days)}{it.idle_days != null ? ` · idle ${age(it.idle_days)}` : ''}</Fact>
        {it.size ? <Fact label={it.kind === 'roadmap' ? 'Effort' : 'Size'}>{it.size}</Fact> : null}
        {it.readiness != null && !it.detail.derived ? <Fact label="Readiness">{`${it.readiness} / 100`}</Fact> : null}
        {it.autonomy ? <Fact label="Autonomy">{it.autonomy}{it.autonomy_reason ? <Text fz={12} c="dimmed">{it.autonomy_reason}</Text> : null}</Fact> : null}
      </SimpleGrid>
      <Text fz={12} c="dimmed">{sourceText(it)}</Text>
      {it.note ? <Banner tone="info" title="Note">{it.note}</Banner> : null}

      {canWrite && b ? <Levers it={it} b={b} base={base} shown={shown} plan={plan} push={push} staged={staged.map((c) => c.what)} /> : null}

      <Divider />
      {it.kind === 'issue' ? <IssueBody it={it} /> : null}
      {it.kind === 'pr' ? <PrBody it={it} base={base} onOpen={onOpen} /> : null}
      {it.kind === 'roadmap' ? <RoadmapBody it={it} entry={detail.data?.entry} /> : null}
      {it.kind === 'spec' ? <SpecBody it={it} q={detail} /> : null}
      {it.kind === 'backlog' ? <BacklogBody it={it} q={detail} base={base} onOpen={onOpen} /> : null}
    </Stack>
  );
}

function Levers({ it, b, base, shown, plan, push, staged }: {
  it: WorkItem; b: WorkItem; base: WorkBoard; shown: WorkBoard; plan: WorkPlan; push: (p: WorkPlan) => void; staged: string[];
}) {
  const lanes = LANE_ORDER.filter((l) => canDrop(b, l));
  const [note, setNoteText] = useState(it.note ?? '');
  const [reason, setReason] = useState('');
  const [status, setStatus] = useState(it.stage);
  useEffect(() => { setNoteText(it.note ?? ''); setStatus(it.stage); }, [it.key, it.note, it.stage]);
  return (
    <Stack gap="sm">
      <Text fw={600} fz={14}>Rebalance</Text>
      {lanes.length > 1 ? (
        <div>
          <Text fz={12} c="dimmed" mb={4}>{it.kind === 'issue' ? 'Lane — applied as its agent: labels on GitHub' : 'Lane — applied as its status in _data/roadmap.yml'}</Text>
          <SegmentedControl size="xs" value={it.lane} data={lanes.map((l) => ({ value: l, label: LANE_LABEL[l] }))}
            onChange={(v) => push(dropInLane(plan, base, shown, it.key, v as WorkLaneId, null))} />
        </div>
      ) : (
        <Text fz={12} c="dimmed">{it.kind === 'pr' ? 'Its lane follows the pull request (draft or open).' : it.kind === 'spec' ? 'Its lane follows its spec.md status, which the spec chain moves.' : it.kind === 'backlog' ? 'Its lane follows its BACKLOG.md section (Open / Claimed).' : 'An issue with an open PR is in flight until the PR closes; it can only be parked.'}</Text>
      )}
      <div>
        <Text fz={12} c="dimmed" mb={4}>{PRIO_WHERE[it.kind]}</Text>
        <Group gap="xs">
          <SegmentedControl size="xs" value={it.priority} data={base.priorities} onChange={(v) => push(setPriority(plan, base, it.key, v))} />
          {it.priority_source === 'override' ? <Button size="compact-xs" variant="subtle" onClick={() => push(setPriority(plan, base, it.key, null))}>{`Clear override (${it.priority_auto})`}</Button> : null}
        </Group>
      </div>
      <Group gap="xs">
        <Button size="compact-sm" variant="light" leftSection={<IconPin size={14} />} onClick={() => push(pinTop(plan, base, shown, it.key))}>Pin to the top of {LANE_LABEL[it.lane]}</Button>
        {it.rank != null ? <Button size="compact-sm" variant="subtle" leftSection={<IconPinnedOff size={14} />} onClick={() => push(unpin(plan, base, shown, it.key))}>Unpin</Button> : null}
      </Group>
      {it.kind === 'roadmap' ? (
        <Group gap="xs" align="flex-end">
          <Select size="xs" label="Status" w={170} data={base.roadmap_statuses} value={status} onChange={(v) => v && setStatus(v)} allowDeselect={false} />
          {status === 'declined' ? <Textarea size="xs" label="Reason (required to decline)" autosize minRows={1} w={260} value={reason} onChange={(e) => setReason(e.currentTarget.value)} /> : null}
          <Button size="xs" variant="light" disabled={status === it.stage || (status === 'declined' && !reason.trim())}
            onClick={() => push(setRoadmapStatus(plan, base, it.key, status, reason))}>Stage status</Button>
        </Group>
      ) : null}
      <Group gap="xs" align="flex-end">
        <Textarea size="xs" label="Note — why (shown on the board and in the evolution brief)" autosize minRows={1} maxLength={280} flex={1}
          value={note} onChange={(e) => setNoteText(e.currentTarget.value)} />
        <Button size="xs" variant="light" disabled={note.trim() === (b.note ?? '')} onClick={() => push(setNote(plan, base, it.key, note))}>Stage note</Button>
      </Group>
      {staged.length ? (
        <Banner tone="info" title="Staged for this item">
          <List size="sm">{staged.map((w) => <List.Item key={w}>{w}</List.Item>)}</List>
        </Banner>
      ) : null}
    </Stack>
  );
}

function Gaps({ gaps }: { gaps: { id: string; by: string; what: string }[] }) {
  if (!gaps?.length) return <Text fz={13} c="dimmed">No gaps: the report has what an agent needs.</Text>;
  return (
    <Table className="dt" verticalSpacing={3}>
      <Table.Tbody>
        {gaps.map((g) => (
          <Table.Tr key={g.id}>
            <Table.Td w={90}><Badge size="xs" variant="light" color={g.by === 'human' ? 'red' : 'cyan'}>{g.by}</Badge></Table.Td>
            <Table.Td>{g.what}</Table.Td>
            <Table.Td><Mono dim>{g.id}</Mono></Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}

function IssueBody({ it }: { it: WorkItem }) {
  const live = hasConsole() || Boolean(githubToken());
  const thread = useGithubIssue(it.nwo ?? '', live ? it.detail.number : null);
  return (
    <Stack gap="sm">
      <Text fw={600} fz={14}>What blocks an agent</Text>
      <Text fz={12} c="dimmed">An agent can close an <b>agent</b> gap itself during intake. Only a person can close a <b>human</b> gap; an issue with one stays blocked.</Text>
      <Gaps gaps={it.detail.gaps} />
      {it.detail.pr ? <Text fz={13}>Open PR: <External href={it.detail.pr.url}>{`#${it.detail.pr.number}`}</External></Text> : null}
      {it.labels.length ? <Group gap={4}>{it.labels.map((l) => <Badge key={l} size="xs" variant="default">{l}</Badge>)}</Group> : null}
      <Text fw={600} fz={14} mt="xs">The issue</Text>
      {!live ? <Text fz={13} c="dimmed">Connect a console or a GitHub token to read the thread here.</Text>
        : thread.isError ? <Text fz={13} c="dimmed">{(thread.error as Error).message}</Text>
          : !thread.data ? <Spinner label="reading the thread…" />
            : (
              <Stack gap={6}>
                <Spoiler maxHeight={320} showLabel="Show all" hideLabel="Show less">
                  <Markdown source={thread.data.issue.body || '_(no description)_'} />
                </Spoiler>
                <Text fz={12} c="dimmed">{`${thread.data.comments.length} comment(s) · opened by ${thread.data.issue.user ?? '?'}`}</Text>
              </Stack>
            )}
    </Stack>
  );
}

const SPEC_TONE: Record<string, string> = { draft: 'yellow', clarified: 'cyan', planned: 'cyan', 'in-progress': 'blue', shipped: 'teal', superseded: 'gray' };

function PrBody({ it, base, onOpen }: { it: WorkItem; base: WorkBoard; onOpen: (k: string) => void }) {
  const d = it.detail;
  const specs = usePullSpecs(hasConsole() ? it.nwo : null, hasConsole() ? d.number : null);
  const onBoard = byKey(base);
  return (
    <Stack gap="sm">
      <Group gap="xs" wrap="wrap">
        {d.draft ? <Badge variant="default">draft</Badge> : <Badge variant="light" color="teal">open</Badge>}
        {d.ci ? <Badge variant="light" color={d.ci === 'fail' ? 'red' : d.ci === 'pass' ? 'teal' : 'gray'}>{`CI ${d.ci}`}</Badge> : null}
        {d.pipeline ? <Badge variant="light" color="cyan">issue pipeline · T3</Badge> : null}
        {d.human_review ? <Badge variant="outline" color="grape">human-review</Badge> : null}
        {d.mergeable_state ? <Badge variant="default">{d.mergeable_state}</Badge> : null}
        {d.author ? <Text fz={12} c="dimmed">{`by ${d.author}`}</Text> : null}
      </Group>
      {d.linked_issues?.length ? (
        <Text fz={13}>Resolves {d.linked_issues.map((n: number, i: number) => {
          const k = `issue:${it.nwo}#${n}`;
          return <span key={n}>{i ? ', ' : ''}{onBoard.has(k) ? <Anchor component="button" fz={13} onClick={() => onOpen(k)}>{`#${n}`}</Anchor> : `#${n}`}</span>;
        })}</Text>
      ) : null}
      <Text fw={600} fz={14} mt="xs">Specs in this pull request</Text>
      {!hasConsole() ? <Text fz={13} c="dimmed">Reading a PR’s specs at its head runs on a console. Connect one to see them here.</Text>
        : specs.isError ? <Text fz={13} c="dimmed">{(specs.error as Error).message}</Text>
          : !specs.data ? <Spinner label="reading the PR at its head…" />
            : <PullSpecsView data={specs.data} repo={it.repo} onBoard={onBoard} onOpen={onOpen} />}
    </Stack>
  );
}

function PullSpecsView({ data, repo, onBoard, onOpen }: { data: NonNullable<ReturnType<typeof usePullSpecs>['data']>; repo: string; onBoard: Map<string, WorkItem>; onOpen: (k: string) => void }) {
  return (
    <Stack gap="sm">
      {data.specs.length ? (
        <Table className="dt" verticalSpacing={4}>
          <Table.Thead><Table.Tr><Table.Th>spec</Table.Th><Table.Th>status</Table.Th><Table.Th>tasks</Table.Th><Table.Th>gaps</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>
            {data.specs.map((sp) => {
              const k = `spec:${repo}/${sp.slug}`;
              return (
                <Table.Tr key={sp.slug}>
                  <Table.Td>
                    {onBoard.has(k) ? <Anchor component="button" fz={13} onClick={() => onOpen(k)}>{sp.slug}</Anchor> : <External href={sp.url} size="sm">{sp.slug}</External>}
                    <Text fz={12} c="dimmed" lineClamp={1}>{sp.title}</Text>
                    <Text fz={11} c="dimmed">{`changes ${sp.changed.join(', ')}.md`}</Text>
                  </Table.Td>
                  <Table.Td w={104}><Badge size="xs" variant="light" color={SPEC_TONE[sp.status] ?? 'gray'} className={s.nowrap}>{sp.status}</Badge></Table.Td>
                  <Table.Td w={130}>
                    {sp.tasks.total ? (
                      <>
                        <Progress value={(100 * sp.tasks.done) / sp.tasks.total} size="sm" aria-label="tasks done" />
                        <Text fz={11} c="dimmed">{`${sp.tasks.done}/${sp.tasks.total}${sp.tasks.doing ? ` · ${sp.tasks.doing} doing` : ''}`}</Text>
                      </>
                    ) : <Text fz={12} c="dimmed">no tasks.md</Text>}
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4}>
                      {sp.open_questions.length ? <Badge size="xs" color="yellow" variant="light">{sp.open_questions.join(' ')}</Badge> : null}
                      {sp.requirements.uncovered.length ? <Badge size="xs" color="red" variant="light">{`uncovered ${sp.requirements.uncovered.join(' ')}`}</Badge> : null}
                      {!sp.open_questions.length && !sp.requirements.uncovered.length ? <Text fz={12} c="dimmed">{`${sp.requirements.FR} FR · ${sp.requirements.AC} AC, all covered`}</Text> : null}
                    </Group>
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      ) : <Text fz={13} c="dimmed">This pull request changes no spec package.</Text>}
      {data.specs_truncated ? <Text fz={12} c="dimmed">{`+${data.specs_truncated} more spec packages not read`}</Text> : null}
      {data.mentioned.length ? <Text fz={13}>Mentions without changing: {data.mentioned.map((m) => <Mono key={m}>{`${m} `}</Mono>)}</Text> : null}
      {data.backlog.added.length || data.backlog.moved.length || data.backlog.removed.length ? (
        <div>
          <Text fw={600} fz={13}>BACKLOG.md</Text>
          <List size="sm" spacing={2}>
            {data.backlog.added.map((b) => <List.Item key={`a${b.id}`}><Badge size="xs" color="teal" variant="light">added</Badge> <Mono>{b.id}</Mono> {b.text}</List.Item>)}
            {data.backlog.moved.map((id) => <List.Item key={`m${id}`}><Badge size="xs" variant="light">moved</Badge> <Mono>{id}</Mono></List.Item>)}
            {data.backlog.removed.map((b) => <List.Item key={`r${b.id}`}><Badge size="xs" color="red" variant="light">removed</Badge> <Mono>{b.id}</Mono> — BACKLOG.md is append-only, so the spec gate will refuse this</List.Item>)}
          </List>
        </div>
      ) : null}
      <Text fz={12} c="dimmed">{`${data.files.total} files changed: ${Object.entries(data.files.by_area).slice(0, 6).map(([a, n]) => `${a} ${n}`).join(' · ')}`}</Text>
    </Stack>
  );
}

function RoadmapBody({ it, entry }: { it: WorkItem; entry?: Record<string, any> | null }) {
  const all = useData<Record<string, any>[]>('roadmap');
  const e = entry ?? (all.data ?? []).find((x) => x.id === it.ref);
  if (!e) return <Spinner />;
  return (
    <Stack gap="sm">
      <Group gap="xs"><Badge variant="default">{e.category}</Badge><Badge variant="default">{`effort ${e.effort}`}</Badge><Text fz={12} c="dimmed">{`${e.source} · ${String(e.created ?? '')}`}</Text></Group>
      <div><Text fw={600} fz={13}>Problem</Text><Text fz={13}>{e.problem}</Text></div>
      <div><Text fw={600} fz={13}>Proposal</Text><Text fz={13}>{e.proposal}</Text></div>
      {e.acceptance?.length ? <div><Text fw={600} fz={13}>Acceptance</Text><List size="sm" spacing={2}>{e.acceptance.map((a: string) => <List.Item key={a}>{a}</List.Item>)}</List></div> : null}
      {e.scope ? (
        <SimpleGrid cols={2}>
          <div><Text fw={600} fz={13}>In scope</Text><List size="sm">{(e.scope.in ?? []).map((x: string) => <List.Item key={x}>{x}</List.Item>)}</List></div>
          <div><Text fw={600} fz={13}>Out of scope</Text><List size="sm">{(e.scope.out ?? []).map((x: string) => <List.Item key={x}>{x}</List.Item>)}</List></div>
        </SimpleGrid>
      ) : null}
      {e.risks?.length ? <div><Text fw={600} fz={13}>Risks</Text><List size="sm">{e.risks.map((r: string) => <List.Item key={r}>{r}</List.Item>)}</List></div> : null}
      {e.issue_url ? <External href={e.issue_url} size="sm">mirrored issue</External> : <Text fz={12} c="dimmed">Not mirrored to an issue yet.</Text>}
      <Anchor href={gh.hubFile('_data/roadmap.yml')} target="_blank" size="sm">_data/roadmap.yml</Anchor>
    </Stack>
  );
}

const TASK_ICON = { done: IconCheck, doing: IconLoader2, todo: IconCircleDashed } as const;
const TASK_CLASS = { done: s.taskDone, doing: s.taskDoing, todo: s.taskTodo } as const;

function SpecBody({ it, q }: { it: WorkItem; q: ReturnType<typeof useWorkItem> }) {
  const d = it.detail;
  return (
    <Stack gap="sm">
      <Group gap="xs">
        <Badge variant="light" color={SPEC_TONE[it.stage] ?? 'gray'}>{it.stage}</Badge>
        <Text fz={12} c="dimmed">{`${d.requirements.FR} FR · ${d.requirements.NFR} NFR · ${d.requirements.AC} AC · ${d.followups} follow-ups`}</Text>
      </Group>
      {d.open_questions.length ? <Banner tone="warn" title={`Open questions: ${d.open_questions.join(', ')}`}>Run <Mono>/spec-driven:clarify</Mono> to resolve them before the spec advances. The gate fails a spec past draft that still carries one.</Banner> : null}
      {d.requirements.uncovered.length ? <Banner tone="warn" title="Requirements no task covers">{d.requirements.uncovered.join(', ')}</Banner> : null}
      {!hasConsole() ? <Text fz={13} c="dimmed">The spec text is read from the checkout on a console.</Text>
        : q.isError ? <Text fz={13} c="dimmed">{(q.error as Error).message}</Text>
          : !q.data?.spec ? <Spinner />
            : (
              <>
                <Text fw={600} fz={14}>Tasks</Text>
                <Stack gap={3}>
                  {q.data.spec.task_list.map((t) => {
                    const I = TASK_ICON[t.state];
                    return <Group key={t.id} gap={6} wrap="nowrap" className={TASK_CLASS[t.state]}><I size={14} aria-label={t.state} /><Mono>{t.id}</Mono><Text fz={13} c="var(--ink)">{t.title}</Text></Group>;
                  })}
                  {!q.data.spec.task_list.length ? <Text fz={13} c="dimmed">No tasks.md yet — /spec-driven:tasks writes it.</Text> : null}
                </Stack>
                {q.data.spec.open_question_lines.length ? <List size="sm">{q.data.spec.open_question_lines.map((l) => <List.Item key={l}>{l}</List.Item>)}</List> : null}
                <Text fw={600} fz={14}>spec.md</Text>
                <Spoiler maxHeight={360} showLabel="Show all" hideLabel="Show less"><Markdown source={q.data.spec.markdown} /></Spoiler>
              </>
            )}
    </Stack>
  );
}

function BacklogBody({ it, q, base, onOpen }: { it: WorkItem; q: ReturnType<typeof useWorkItem>; base: WorkBoard; onOpen: (k: string) => void }) {
  const d = it.detail;
  const claim = d.claimed_by ? `spec:${it.repo}/${String(d.claimed_by).replace(/^specs\//, '')}` : null;
  return (
    <Stack gap="sm">
      <Group gap="xs">
        <Badge variant="default">{d.kind}</Badge>
        <Badge variant="light" color={PRIO_COLOR[it.priority_auto]}>{`severity ${d.severity}`}</Badge>
        <Badge variant="default">{d.section}</Badge>
        {d.evolve_pick ? <Badge variant="filled" color="cyan">/evolve takes this next</Badge> : null}
      </Group>
      {claim ? (
        <Text fz={13}>Claimed by {byKey(base).has(claim) ? <Anchor component="button" fz={13} onClick={() => onOpen(claim)}>{d.claimed_by}</Anchor> : <Mono>{d.claimed_by}</Mono>}</Text>
      ) : null}
      {d.surfaced_in ? <Text fz={13} c="dimmed">{`Surfaced in ${d.surfaced_in}`}</Text> : null}
      {q.data?.backlog ? <Markdown source={q.data.backlog.text} /> : <Text fz={13}>{it.title}</Text>}
      <Text fz={12} c="dimmed">BACKLOG.md is append-only: the spec chain moves an item to Claimed when a spec takes it and to Done when it ships. The board orders and prioritises it; repo-evolution’s weekly brief carries that order.</Text>
    </Stack>
  );
}
