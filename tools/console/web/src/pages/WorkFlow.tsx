// Throughput: what each loop can drain per run, how long its lane takes at
// that rate, and how the next run's slots are shared between repos — the
// numbers to read before dragging work around, and the levers (caps in
// _data/fleet.yml, pins on the board) that change them.
import { Anchor, Badge, Group, Paper, SimpleGrid, Stack, Table, Text, Tooltip } from '@mantine/core';
import { Link } from 'react-router';
import type { WorkBoard, WorkLaneId, WorkLoop } from '../api/types';
import { Banner, Meter, Section } from '../components/ui';
import { RunButton } from '../jobs/RunButton';
import { to } from '../lib/links';
import { LOOP_SHORT } from './WorkBoard';
import s from './Work.module.css';

const DAYS = ['Sundays', 'Mondays', 'Tuesdays', 'Wednesdays', 'Thursdays', 'Fridays', 'Saturdays'];
const LANES: WorkLaneId[] = ['triage', 'ready', 'doing', 'review', 'blocked', 'hold'];
const LANE_LABEL: Record<WorkLaneId, string> = {
  triage: 'Triage', ready: 'Ready', doing: 'In flight', review: 'Review', blocked: 'Blocked', hold: 'On hold',
};

export function describeCron(cron: string | null | undefined): string {
  const f = String(cron ?? '').split(/\s+/);
  if (f.length !== 5) return cron ? String(cron) : 'on demand';
  const [m, h, dom, , dow] = f;
  const at = /^\d+$/.test(m) && /^\d+$/.test(h) ? `${h.padStart(2, '0')}:${m.padStart(2, '0')} UTC` : `${h}:${m}`;
  if (dom === '*' && dow === '*') return `daily ${at}`;
  if (/^\d$/.test(dow)) return `${DAYS[Number(dow) % 7]} ${at}`;
  return `${cron} (UTC)`;
}

function drainText(l: WorkLoop): string {
  if (l.id === 'human') return '';
  if (l.on_demand) return 'runs when someone invokes it';
  if (!l.eligible) return 'nothing waiting';
  if (l.drain_runs == null) return '—';
  if (l.drain_runs <= 1) return 'clears in the next run';
  return `clears in ${l.drain_runs} runs (~${l.drain_days} days) at this cap`;
}

function LoopCard({ l, onRepo }: { l: WorkLoop; onRepo: (r: string) => void }) {
  const top = l.by_repo.slice(0, 8);
  return (
    <Paper p="md">
      <Stack gap={6}>
        <Group justify="space-between" wrap="nowrap" align="flex-start">
          <div>
            <Text fw={650} fz={14}>{l.label}</Text>
            <Text fz={12} c="dimmed">{l.schedule ? `${describeCron(l.schedule)} · ${l.runs_per_week} runs a week` : l.id === 'human' ? 'no schedule: you' : 'on demand'}</Text>
          </div>
          <Badge variant="default">{`${l.eligible} waiting`}</Badge>
        </Group>
        {l.cap ? (
          <>
            <Group justify="space-between" gap={4}>
              <Text fz={12}>{`next run takes ${l.next_run} of ${l.cap}`}</Text>
              {l.sub_cap ? <Text fz={12} c="dimmed">{`≤ ${l.sub_cap.value} ${l.sub_cap.label}`}</Text> : null}
            </Group>
            <Meter value={l.next_run} cap={l.cap} tone={l.next_run >= l.cap ? 'good' : 'info'} />
          </>
        ) : null}
        {drainText(l) ? <Text fz={12.5} c={l.drain_runs != null && l.drain_runs > 7 ? 'var(--warning)' : 'dimmed'}>{drainText(l)}</Text> : null}
        {l.note ? <Text fz={12} c="dimmed">{l.note}</Text> : null}
        {l.breakdown ? (
          <Group gap={4} wrap="wrap">
            {Object.entries(l.breakdown).filter(([, n]) => n).map(([k, n]) => <Badge key={k} size="sm" variant="light">{`${n} ${k}`}</Badge>)}
          </Group>
        ) : null}
        {top.length ? (
          <Table className="dt" verticalSpacing={2} mt={4}>
            <Table.Thead><Table.Tr><Table.Th>repo</Table.Th><Table.Th className="num">waiting</Table.Th>{l.cap ? <Table.Th className="num">next run</Table.Th> : null}</Table.Tr></Table.Thead>
            <Table.Tbody>
              {top.map((r) => (
                <Table.Tr key={r.repo}>
                  <Table.Td><button type="button" className={s.repoBtn} onClick={() => onRepo(r.repo)}>{r.repo}</button></Table.Td>
                  <Table.Td className="num">{r.eligible}</Table.Td>
                  {l.cap ? <Table.Td className="num">{r.picked || <Text span c="dimmed" fz={12}>0</Text>}</Table.Td> : null}
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        ) : null}
        {l.by_repo.length > top.length ? <Text fz={11.5} c="dimmed">{`+${l.by_repo.length - top.length} more repos`}</Text> : null}
        {l.config ? <Anchor component={Link} to={to.config(l.config)} fz={12}>{`Adjust ${l.config === 'evolution' ? 'evolution' : 'the caps'} in _data/fleet.yml`}</Anchor> : null}
      </Stack>
    </Paper>
  );
}

export function Hints({ doc, onLane }: { doc: WorkBoard; onLane: (lane: WorkLaneId) => void }) {
  if (!doc.hints.length) return null;
  return (
    <Stack gap={0}>
      {doc.hints.map((h) => (
        <Banner key={h.text} tone={h.tone}>
          <Group justify="space-between" gap="sm" wrap="wrap">
            <Text fz={13}>{h.text}</Text>
            {h.lever?.startsWith('config:') ? <Anchor component={Link} to={to.config(h.lever.slice(7))} fz={13}>Open the caps</Anchor> : null}
            {h.lever?.startsWith('lane:') ? <Anchor component="button" fz={13} onClick={() => onLane(h.lever!.slice(5) as WorkLaneId)}>Show that lane</Anchor> : null}
            {h.lever === 'op:issues' ? <RunButton op="issues">Refresh the issue snapshot</RunButton> : null}
          </Group>
        </Banner>
      ))}
    </Stack>
  );
}

export function WorkFlow({ doc, onRepo, onLane }: { doc: WorkBoard; onRepo: (r: string) => void; onLane: (lane: WorkLaneId) => void }) {
  const max = Math.max(1, ...doc.repos.flatMap((r) => LANES.map((l) => Number(r[l]) || 0)));
  return (
    <>
      <Section title="Balance" mt={0} description="What the board sees in the shape of the work, each with the lever that changes it.">
        {doc.hints.length ? <Hints doc={doc} onLane={onLane} /> : <Text fz={13} c="dimmed">Nothing out of balance.</Text>}
      </Section>
      <Section title="Loops" description="What each loop takes per run, against what is waiting for it. A drain time is runs needed at today’s caps, including the per-repo and cross-repo sub-caps. Pinning an item moves it up a loop’s queue; raising a cap is the other lever.">
        <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }} spacing="sm">
          {doc.loops.map((l) => <LoopCard key={l.id} l={l} onRepo={onRepo} />)}
        </SimpleGrid>
      </Section>
      <Section title="By repository" description="Every open item per repository and lane. The next-run column counts the issue pipeline's slots (T1–T3) this repository gets. Pick a repository to filter the board to it.">
        <Table.ScrollContainer minWidth={720}>
          <Table className="dt" verticalSpacing={3}>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>repo</Table.Th>
                {LANES.map((l) => <Table.Th key={l} className="num">{LANE_LABEL[l]}</Table.Th>)}
                <Table.Th className="num"><Tooltip label="slots in the issue pipeline's next run (T1–T3)"><span>next run</span></Tooltip></Table.Th>
                <Table.Th className="num">total</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {doc.repos.map((r) => (
                <Table.Tr key={r.repo}>
                  <Table.Td><button type="button" className={s.repoBtn} onClick={() => onRepo(r.repo)}>{r.repo}</button></Table.Td>
                  {LANES.map((l) => {
                    const v = Number(r[l]) || 0;
                    return <Table.Td key={l} className={s.heat} data-v={v} data-hot={v >= max * 0.5 && v >= 5 ? '' : undefined}>{v}</Table.Td>;
                  })}
                  <Table.Td className={s.heat} data-v={r.next_run}>{r.next_run}</Table.Td>
                  <Table.Td className={s.heat} data-hot="">{r.total}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
        <Text fz={12} c="dimmed" mt={6}>{`Loops: ${Object.entries(LOOP_SHORT).filter(([k]) => k !== 'none').map(([k, v]) => `${v} = ${doc.loops.find((l) => l.id === k)?.label ?? k}`).join(' · ')}`}</Text>
      </Section>
    </>
  );
}
