// The loop switches (constitution § 17, HUB-057): every `_data/fleet.yml` `switches.loops`
// record against its live repository variable, one table per repository. A loop's toggle,
// or a repository's All on / All off, opens a dialog that needs a reason and previews the
// flip (POST /api/switches/preview: each variable's current → new value and the exact
// fleet.yml diff; nothing is written); only then does Apply submit the `switches-apply`
// operation, behind the job runner's confirm. The apply sets each variable on a repository
// the hub owns, reads it back and records the map in the working tree; committing that
// change stays with the operator. The rules the page applies live in switchPlan.ts.
import { useState } from 'react';
import { Badge, Button, Group, Modal, ScrollArea, Stack, Switch, Table, Text, Textarea, Tooltip } from '@mantine/core';
import { IconRefresh } from '@tabler/icons-react';
import { notifications } from '@mantine/notifications';
import { hasConsole } from '../api/backend';
import { post } from '../api/client';
import { useSwitches } from '../api/hooks';
import type { SwitchPlan, SwitchRepo, SwitchRow, SwitchesDoc } from '../api/types';
import { Banner, Empty, External, Load, LocalOnly, Mono, PageHeader, Section, Status, type Tone } from '../components/ui';
import { LogView } from '../jobs/JobLog';
import { useRunner } from '../jobs/JobRunner';
import { gh } from '../lib/links';
import {
  REASON_MAX, applyBlocked, flipTitle, isOn, itemChange, loopFlip, reasonOk, repoBlocked, repoFlip, rowBlocked, semanticsLabel, shown,
  type FlipRequest,
} from './switchPlan';

function Effective({ row }: { row: SwitchRow }) {
  const on = row.effective.on;
  const tone: Tone = on === true ? 'good' : on === false ? 'info' : 'warn';
  return <Status tone={tone} title={row.effective.why}>{on === true ? 'on' : on === false ? 'off' : 'unknown'}</Status>;
}

function MapState({ row }: { row: SwitchRow }) {
  const m = row.map;
  const title = [m.reason, m.set_by && `set by ${m.set_by}`, m.set_at && `on ${m.set_at}`, m.level_off && `${m.level_off} is off`]
    .filter(Boolean).join(' · ') || 'no flip recorded yet';
  return (
    <Tooltip label={title} multiline maw={420}>
      <Badge size="sm" variant={m.verified ? 'light' : 'outline'} color={m.state === 'on' ? 'teal' : m.state === 'off' ? 'gray' : 'yellow'} tt="none">
        {m.state}{m.verified ? '' : ' ?'}
      </Badge>
    </Tooltip>
  );
}

function LoopTable({ doc, repo, onFlip }: { doc: SwitchesDoc; repo: SwitchRepo; onFlip: (r: FlipRequest) => void }) {
  return (
    <Table.ScrollContainer minWidth={1080}>
      <Table verticalSpacing={6} data-switches-repo={repo.repo}>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Loop</Table.Th><Table.Th>Workflow</Table.Th><Table.Th>Variable</Table.Th><Table.Th>Semantics</Table.Th>
            <Table.Th>Live value</Table.Th><Table.Th>Effective</Table.Th><Table.Th>Map</Table.Th><Table.Th>Drift</Table.Th>
            <Table.Th>Hold</Table.Th><Table.Th>Switch</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {repo.loops.map((r) => {
            const blocked = rowBlocked(doc, r);
            const on = isOn(r);
            return (
              <Table.Tr key={r.key} data-loop={r.key} data-drift={r.drift || undefined}>
                <Table.Td>
                  <Mono>{r.key}</Mono>
                  {r.note ? <Text size="xs" c="dimmed" maw={320}>{r.note}</Text> : null}
                </Table.Td>
                <Table.Td>{r.workflow ? <External href={gh.workflow(r.repo, r.workflow)} size="xs">{r.workflow.replace(/^\.github\/workflows\//, '')}</External> : null}</Table.Td>
                <Table.Td>{r.gate === 'repo_variable' ? <Mono>{r.variable}</Mono> : <Text size="xs" c="dimmed">{r.gate}</Text>}</Table.Td>
                <Table.Td><Text size="xs">{semanticsLabel(r.semantics)}</Text></Table.Td>
                <Table.Td>
                  {r.gate === 'repo_variable'
                    ? <Tooltip label={r.live.updated_at ? `updated ${r.live.updated_at}` : r.live.state}><Text size="sm" c={r.live.value === null ? 'yellow' : undefined}><Mono>{shown(r.live.value)}</Mono></Text></Tooltip>
                    : <Text size="xs" c="dimmed">n/a</Text>}
                </Table.Td>
                <Table.Td><Effective row={r} /></Table.Td>
                <Table.Td><MapState row={r} /></Table.Td>
                <Table.Td>
                  {r.drift ? <Status tone="warn" title={`the map says ${r.map.says} but ${r.variable} reads ${r.live.on ? 'on' : 'off'}: record the flip, or apply the map`}>drift</Status>
                    : r.drift === false ? <Text size="xs" c="dimmed">none</Text> : <Text size="xs" c="dimmed">—</Text>}
                </Table.Td>
                <Table.Td>
                  {r.hold ? <Status tone="warn" title={`${r.hold.kind ?? 'code'} ${r.hold.name}=${r.hold.value} (${r.hold.source ?? ''}): idles the workflow whatever the variable says. ${r.hold.lift ?? ''}`}>held</Status> : null}
                </Table.Td>
                <Table.Td>
                  <Tooltip label={blocked ?? `turn it ${on ? 'off' : 'on'}: preview first, then confirm`} multiline maw={360}>
                    <span>
                      <Switch size="sm" checked={Boolean(on)} disabled={Boolean(blocked)} aria-label={`switch ${r.key}`}
                        onChange={() => onFlip(loopFlip(r))} />
                    </span>
                  </Tooltip>
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

/** The dialog every lever opens: a reason, the preview, and only then Apply (through runOp's confirm). */
function FlipModal({ req, onClose }: { req: FlipRequest; onClose: () => void }) {
  const { runOp } = useRunner();
  const [reason, setReason] = useState('');
  const [plan, setPlan] = useState<SwitchPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const blocked = applyBlocked(plan, reason);
  const preview = async () => {
    setBusy(true);
    try {
      setPlan(await post<SwitchPlan>('/api/switches/preview', { ...req, reason: reason.trim() }));
    } catch (e) {
      notifications.show({ color: 'red', title: 'Could not preview', message: (e as Error).message, autoClose: 9000 });
    } finally {
      setBusy(false);
    }
  };
  const apply = async () => {
    if (!plan) return;
    const job = await runOp('switches-apply', { plan_id: plan.plan_id, apply: true });
    if (job) onClose();
  };
  return (
    <Modal opened onClose={onClose} size="xl" title={flipTitle(req)} data-switch-flip>
      <Stack gap="sm">
        <Text size="sm">Preview shows, for each loop, the variable's current and new value and the exact <Mono>_data/fleet.yml</Mono> change; it writes nothing. Apply sets each variable, reads it back and records the map in this working tree (state, verified, reason, who and when) — commit it yourself in a pull request the same day (constitution § 17.2–17.4).</Text>
        <Textarea label="Reason" description="recorded in the map and the fleet activity log" required autosize minRows={2} maxLength={REASON_MAX}
          value={reason} onChange={(e) => setReason(e.currentTarget.value)} data-autofocus
          error={reason && !reasonOk(reason) ? `3–${REASON_MAX} characters` : null} />
        <Group gap="xs">
          <Button onClick={() => void preview()} loading={busy} disabled={!reasonOk(reason)}>Preview</Button>
          {plan ? <Text size="xs" c="dimmed">plan <Mono>{plan.plan_id}</Mono> · {plan.counts.do} to do · {plan.counts.skip} skipped · set_by {plan.set_by ?? 'unknown'} · {plan.set_at}</Text> : null}
        </Group>
        {plan && !plan.writes.enabled ? (
          <Banner tone="warn" title="GitHub writes are off in this console">{plan.writes.why} A variable cannot be set from here; Apply is refused for any loop that needs one.</Banner>
        ) : null}
        {plan?.diff_error ? <Banner tone="crit" title="The fleet.yml change could not be made">{plan.diff_error}</Banner> : null}
        {plan ? (
          <ScrollArea.Autosize mah="34vh" type="auto" offsetScrollbars>
            <Table verticalSpacing={4} data-plan={plan.plan_id}>
              <Table.Thead><Table.Tr><Table.Th>Loop</Table.Th><Table.Th>Change</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>
                {plan.items.map((i) => (
                  <Table.Tr key={i.key} data-do={i.do || undefined}>
                    <Table.Td><Mono>{i.key}</Mono></Table.Td>
                    <Table.Td>
                      <Text size="sm" c={i.do ? undefined : 'dimmed'}>{itemChange(i)}</Text>
                      {i.warnings.map((w) => <Text key={w} size="xs" c="yellow">! {w}</Text>)}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </ScrollArea.Autosize>
        ) : null}
        {plan?.diff ? <LogView raw={plan.diff} height={260} /> : null}
        <Group justify="flex-end" gap="xs">
          {plan ? <Button variant="default" onClick={() => void runOp('switches-apply', { plan_id: plan.plan_id })}>Check it still matches</Button> : null}
          <Tooltip label={blocked ?? 'asks once more, then writes'} disabled={!blocked}>
            <span><Button color="red" disabled={Boolean(blocked)} onClick={() => void apply()}>Apply{plan ? ` to ${plan.counts.do}` : ''}</Button></span>
          </Tooltip>
          <Button variant="default" onClick={onClose}>Cancel</Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function Board({ doc, onReread, rereading }: { doc: SwitchesDoc; onReread: () => void; rereading: boolean }) {
  const [req, setReq] = useState<FlipRequest | null>(null);
  const levels = [['global', doc.global?.state], ...Object.entries(doc.groups).map(([k, g]) => [k, g?.state])] as [string, string | undefined][];
  return (
    <Stack gap="md">
      <PageHeader
        title="Switches"
        badges={<>
          <Status tone="good">{`${doc.counts.on} on`}</Status>
          <Status tone="info">{`${doc.counts.off} off`}</Status>
          {doc.counts.drift ? <Status tone="warn">{`${doc.counts.drift} drift`}</Status> : <Status tone="good">no drift</Status>}
          {doc.writes.enabled ? <Status tone="good">writes on</Status> : <Status tone="crit">writes off</Status>}
        </>}
        description={<>Every loop's kill switch. <External href={gh.hubFile('_data/fleet.yml')} size="sm">_data/fleet.yml</External> <Mono>switches:</Mono> is the one source of truth and each repository variable is its projection (constitution § 17): the live value is read from GitHub (an unreadable one is never shown as off), the effective state is the most restrictive of the global, group, repo and loop levels and then the variable and any hold, and drift is where the map and the variable disagree. A flip is previewed with a reason, then applied behind a confirm. Read as <Mono>{doc.login ?? 'nobody'}</Mono>; no secret is read.</>}
        actions={<Button size="xs" variant="default" leftSection={<IconRefresh size={14} />} loading={rereading} onClick={onReread}>Read GitHub again</Button>}
      />
      {!doc.writes.enabled ? (
        <Banner tone="warn" title="GitHub writes are off in this console">{doc.writes.why} The page reads and previews; every Apply that sets a variable is refused.</Banner>
      ) : null}
      <Group gap={4} wrap="wrap">
        <Text size="xs" c="dimmed">Levels:</Text>
        {levels.map(([k, s]) => <Badge key={k} size="xs" variant="light" color={s === 'off' ? 'red' : 'teal'} tt="none">{k} {s ?? 'on'}</Badge>)}
      </Group>
      <Text size="xs" c="dimmed">An apply edits <Mono>_data/fleet.yml</Mono> in this working tree and never commits: commit it in a pull request the same day.</Text>
      {doc.repos.map((repo) => {
        const blocked = repoBlocked(doc, repo);
        return (
          <Section key={repo.repo} mt="md" title={repo.repo}
            description={`${repo.counts.loops} loops · ${repo.counts.on} on · ${repo.counts.off} off${repo.counts.unknown ? ` · ${repo.counts.unknown} unknown` : ''}${blocked ? ` · ${blocked}` : ''}`}
            actions={<>
              {repo.writable ? <Status tone="good">writable</Status> : <Status tone="info" title="the console writes only to repositories the hub owns">read-only</Status>}
              {repo.readable ? null : <Status tone="crit" title={repo.error ?? ''}>variables unreadable</Status>}
              {repo.counts.drift ? <Status tone="warn">{`${repo.counts.drift} drift`}</Status> : null}
              <Tooltip label={blocked ?? 'preview turning every loop of this repository on'} multiline maw={360}>
                <span><Button size="xs" variant="default" disabled={Boolean(blocked)} onClick={() => setReq(repoFlip(repo.repo, 'on'))}>All on</Button></span>
              </Tooltip>
              <Tooltip label={blocked ?? 'preview turning every loop of this repository off'} multiline maw={360}>
                <span><Button size="xs" variant="default" color="red" disabled={Boolean(blocked)} onClick={() => setReq(repoFlip(repo.repo, 'off'))}>All off</Button></span>
              </Tooltip>
            </>}>
            {repo.loops.length ? <LoopTable doc={doc} repo={repo} onFlip={setReq} /> : <Empty>No loop records for this repository.</Empty>}
          </Section>
        );
      })}
      {req ? <FlipModal key={`${req.scope}:${req.key}:${req.target}`} req={req} onClose={() => setReq(null)} /> : null}
    </Stack>
  );
}

export function Switches() {
  const live = hasConsole();
  const [reread, setReread] = useState(0);
  const q = useSwitches(reread, live);
  if (!live) {
    return (
      <>
        <PageHeader title="Switches" description="Every loop's kill switch: _data/fleet.yml switches: against the live repository variables, with drift, and a flip previewed with a reason, then applied behind a confirm (constitution § 17)." />
        <LocalOnly what="The loop switches are read live with the operator's GitHub token, and a flip writes repository variables" />
      </>
    );
  }
  return <Load q={q} rows={10}>{(doc) => <Board doc={doc} rereading={q.isFetching && reread > 0} onReread={() => setReread((n) => n + 1)} />}</Load>;
}
