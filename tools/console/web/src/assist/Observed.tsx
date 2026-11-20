// How the assistant is observed, on the Assist page: the fleet pages sharing
// themselves with this console right now (and the operator's End), what the
// assistant did (its messages from the AI ledger, what its sessions did to pages
// from the page bridge's audit), and its registration in the agent inventory.
// One document feeds all of it (/api/assist/activity, tools/fleetcore/assistlog.py);
// the MCP layer's `assist_activity`, the lake and a terminal read the same one.
import { useState, type ReactNode } from 'react';
import { Badge, Button, Group, Paper, SegmentedControl, SimpleGrid, Stack, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useQueryClient } from '@tanstack/react-query';
import { hasConsole } from '../api/backend';
import { post } from '../api/client';
import { useAssistActivity } from '../api/hooks';
import type { AssistActivity, AssistAgentEntry, AssistRunRow, PageAuditRow, SharedPage } from '../api/types';
import { DataTable } from '../components/DataTable';
import { Empty, Load, Mono, Section, StatTile, Status } from '../components/ui';
import { dash, when } from '../lib/format';

const WINDOWS = [{ label: '7 days', value: '7' }, { label: '30 days', value: '30' }, { label: 'All time', value: '0' }];
/** An outcome that is somebody's no: the broker (the mode or the ceiling), the page (one of its rules, or an
 *  element that is gone), the person, or nobody answering. The rules working, not a fault. */
const NO = new Set(['refused', 'page', 'declined', 'timeout']);
const NO_WORDS: Record<string, string> = {
  refused: 'Refused before the page saw it: the mode or the ceiling does not allow that action',
  page: 'The page did not do it: one of its own rules (a dialog, a secret field, a link off the site, a disabled control) or an element that is no longer there',
  declined: 'The person said no when asked',
  timeout: 'Nobody answered in time: the person did not approve it, or the page was asleep',
};

const counts = (c: Record<string, number>): string => Object.entries(c).map(([k, n]) => `${n} ${k}`).join(' · ') || 'none';
const money = (n: number | null | undefined): string => (n == null ? dash : `$${n.toFixed(n < 1 ? 4 : 2)}`);

/** A short identifier or verb in monospace that never breaks mid-word (Mono wraps anywhere, for long paths). */
function Fixed({ children, dim }: { children: ReactNode; dim?: boolean }) {
  return <Text span ff="monospace" fz={12.5} c={dim ? 'dimmed' : undefined} style={{ whiteSpace: 'nowrap' }}>{children}</Text>;
}

/** An outcome as a pill: an answer is good, a no is the rules working, anything else needs a look. */
function Outcome({ value }: { value: string }) {
  if (value === 'ok') return <Status tone="good">ok</Status>;
  if (NO.has(value)) return <Status tone="info" title={NO_WORDS[value]}>{value}</Status>;
  if (value === 'usage_limit') return <Status tone="warn" title="The subscription's window was spent: capacity, not a defect">{value}</Status>;
  return <Status tone="crit">{value}</Status>;
}

export function AssistObserved() {
  const [days, setDays] = useState('7');
  const local = hasConsole();
  const q = useAssistActivity(Number(days), local);
  return (
    <Load q={q} rows={3}>
      {(doc) => (
        <>
          {local ? <SharedPages doc={doc} /> : null}
          {local ? <Activity doc={doc} days={days} setDays={setDays} /> : null}
          <Registered entry={doc.agent_entry} agent={doc.agent} />
        </>
      )}
    </Load>
  );
}

function SharedPages({ doc }: { doc: AssistActivity }) {
  const qc = useQueryClient();
  const [ending, setEnding] = useState<string | null>(null);
  const shared = doc.shared_pages;
  const end = async (row: SharedPage) => {
    setEnding(row.id);
    try {
      await post('/api/assist/shared-pages/end', { id: row.id });
      notifications.show({ title: 'Sharing ended', message: `${row.page.repo ?? row.origin ?? 'That page'} is no longer shared with this console. The person on it can share it again.`, color: 'teal' });
    } catch (e) {
      notifications.show({ title: 'Not ended', message: (e as Error).message, color: 'red' });
    } finally {
      setEnding(null);
      void qc.invalidateQueries({ queryKey: ['assist-activity'] });
    }
  };
  return (
    <Section
      title="Shared pages"
      description={<>Pages of other fleet sites and apps that carry the assistant kit and are sharing themselves with this console right now. A Claude Code session reaches one only with the pairing code its own panel shows. The ceiling is <Mono>{shared.setting}</Mono>: <Mono>{shared.access}</Mono>, and at most {shared.cap} pages share at once.</>}
    >
      <div data-testid="assist-shared-pages">
        <DataTable<SharedPage>
          rows={shared.sessions}
          rowKey={(s) => s.id}
          rowLabel={(s) => `${s.page.repo ?? s.origin ?? 'page'} session ${s.id}`}
          dense
          minWidth={940}
          empty={shared.access === 'off'
            ? <>Fleet pages are off (<Mono>{shared.setting}</Mono> is off): no page of another site can share itself.</>
            : 'No fleet page is sharing itself with this console.'}
          columns={[
            {
              key: 'page', header: 'page', sort: (s) => s.page.repo ?? s.origin ?? '',
              render: (s) => (
                <div>
                  <Text size="sm" fw={600}>{s.page.repo ?? s.origin}</Text>
                  <Text size="xs" c="dimmed"><Mono dim>{s.page.source ?? s.page.route ?? s.page.path ?? ''}</Mono>{s.page.repo ? <> · {s.origin}</> : null}</Text>
                </div>
              ),
            },
            { key: 'mode', header: 'mode', width: 104, sort: (s) => s.mode, render: (s) => <Badge size="sm" variant="outline">{s.mode === 'ask' ? 'ask first' : s.mode}</Badge> },
            { key: 'live', header: 'listening', width: 104, sort: (s) => (s.live ? 1 : 0), render: (s) => (s.live ? <Status tone="good">live</Status> : <Status tone="info" title="The page has not polled for a while: its tab may be asleep or closed">idle</Status>) },
            { key: 'paired', header: 'paired', num: true, width: 76, sort: (s) => s.paired, title: 'How many times a Claude Code session attached with a pairing code', render: (s) => (s.paired ? <Text span size="sm" fw={600}>{s.paired}</Text> : <Text span size="sm" c="dimmed">no</Text>) },
            { key: 'commands', header: 'commands', num: true, width: 96, sort: (s) => s.commands, render: (s) => s.commands },
            { key: 'since', header: 'shared since', width: 170, sort: (s) => s.created, render: (s) => <Text size="xs" c="dimmed">{when(s.created)}</Text> },
            { key: 'id', header: 'session', width: 96, render: (s) => <Fixed dim>{s.id}</Fixed>, title: 'The first eight characters of the session: what the audit log calls it' },
            {
              key: 'end', header: '', width: 72,
              render: (s) => (
                <Button size="compact-xs" color="red" variant="light" loading={ending === s.id} data-testid={`assist-shared-end-${s.id}`}
                  onClick={(e) => { e.stopPropagation(); void end(s); }} aria-label={`End sharing for ${s.page.repo ?? s.origin ?? s.id}`}>
                  End
                </Button>
              ),
            },
          ]}
        />
      </div>
    </Section>
  );
}

function Activity({ doc, days, setDays }: { doc: AssistActivity; days: string; setDays: (v: string) => void }) {
  const m = doc.messages.summary;
  const a = doc.page_audit.summary;
  const span = days === '0' ? 'all time' : `the last ${days} days`;
  return (
    <Section
      title="How it is observed"
      description="What the assistant did, read back from the two records it leaves: one row per message in the AI ledger, and one line per page command in the page bridge's audit. The MCP tool assist_activity, the lake and tools/dash apps assist activity read the same document."
      actions={<SegmentedControl size="xs" value={days} onChange={setDays} data={WINDOWS} aria-label="Window" />}
    >
      <Stack gap="md" data-testid="assist-activity">
        <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }} spacing="sm">
          <StatTile label="Messages" value={m.messages} sub={m.messages ? `${money(m.cost_usd)} ${doc.cost_label} · ${m.turns ?? 0} turns` : `none in ${span}`} />
          <StatTile
            label="Did not end as an answer" value={m.not_ok} tone={m.not_ok ? 'crit' : undefined}
            sub={m.messages ? `${counts(m.by_outcome)}${m.cost_unreported ? ` · ${m.cost_unreported} with no reported cost, charged at the cap` : ''}` : 'a cap, the clock, a spent window or a crash'}
          />
          <StatTile label="Page commands" value={a.commands} sub={a.commands ? `on ${a.sessions} page session(s) · asked by ${counts(a.by_client)}` : `none in ${span}`} />
          <StatTile
            label="Met a no" value={a.no_pct == null ? dash : `${a.no_pct}%`}
            sub={a.commands ? `${a.no} of ${a.commands} refused, declined or unanswered: the rules working${a.ended_by_operator ? ` · ${a.ended_by_operator} session(s) ended from here` : ''}` : 'refused, declined or unanswered'}
          />
        </SimpleGrid>

        <div>
          <Text size="sm" fw={600} mb={4}>Messages</Text>
          <DataTable<AssistRunRow>
            rows={doc.messages.recent}
            rowKey={(r, i) => `${r.session_id ?? 'x'}-${r.at}-${i}`}
            dense
            minWidth={700}
            maxHeight={260}
            empty={doc.messages.exists ? `No assistant message in ${span}.` : <>No AI ledger at <Mono>{doc.messages.ledger}</Mono> yet: no capped session has run on this machine.</>}
            columns={[
              { key: 'at', header: 'when', sort: (r) => r.at, render: (r) => <Text size="xs" c="dimmed">{when(r.at)}</Text> },
              { key: 'outcome', header: 'outcome', sort: (r) => r.outcome, render: (r) => <Outcome value={r.outcome} /> },
              { key: 'cost', header: 'cost', num: true, sort: (r) => r.cost_usd ?? -1, title: doc.cost_label, render: (r) => <Text span size="sm" title={r.cost_source === 'reported' ? 'reported by the CLI' : `not reported: ${r.cost_source ?? 'unknown'}`}>{money(r.cost_usd)}{r.cost_source && r.cost_source !== 'reported' ? ' *' : ''}</Text> },
              { key: 'turns', header: 'turns', num: true, sort: (r) => r.turns ?? -1, render: (r) => r.turns ?? dash },
              { key: 'took', header: 'took', num: true, sort: (r) => r.duration_s ?? -1, render: (r) => (r.duration_s == null ? dash : `${Math.round(r.duration_s)}s`) },
              { key: 'model', header: 'model', sort: (r) => r.model ?? '', render: (r) => <Fixed dim>{r.model ?? dash}</Fixed> },
              { key: 'session', header: 'session', render: (r) => <Fixed dim>{r.session_id ?? dash}</Fixed>, title: 'The first eight characters of the Claude Code session: its transcript and its lake row carry the same id' },
            ]}
          />
        </div>

        <div>
          <Text size="sm" fw={600} mb={4}>Page activity</Text>
          <DataTable<PageAuditRow>
            rows={doc.page_audit.recent}
            rowKey={(r) => r.id}
            dense
            minWidth={900}
            maxHeight={340}
            tone={(r) => (r.outcome !== 'ok' && !NO.has(r.outcome) ? 'warn' : undefined)}
            empty={doc.page_audit.exists ? `No page command in ${span}.` : <>No audit at <Mono>{doc.page_audit.path}</Mono> yet: no session has sent a page a command from this console.</>}
            columns={[
              { key: 'at', header: 'when', sort: (r) => r.at, render: (r) => <Text size="xs" c="dimmed">{when(r.at)}</Text> },
              { key: 'who', header: 'asked by', sort: (r) => r.client, title: 'dock: a session this console started. paired: a person\'s own Claude Code session. operator: an End from this page', width: 104, render: (r) => <Badge size="sm" variant={r.client === 'dock' ? 'light' : 'outline'} styles={{ root: { overflow: 'visible' }, label: { overflow: 'visible' } }}>{r.client}</Badge> },
              { key: 'page', header: 'page', sort: (r) => r.origin ?? '', render: (r) => (r.kind === 'fleet' ? <Text size="xs">{r.repo ?? r.origin}{r.repo ? <Text span c="dimmed"> · {r.origin}</Text> : null}</Text> : <Text size="xs" c="dimmed">this console</Text>) },
              { key: 'action', header: 'what', sort: (r) => r.action, title: 'The action and what it was aimed at: a ref from a snapshot, a path or a key. A fill is recorded by its length, never its text', render: (r) => <span><Fixed>{r.action}</Fixed>{r.target ? <> <Mono dim>{r.target}</Mono></> : null}</span> },
              { key: 'mode', header: 'mode', sort: (r) => r.mode, render: (r) => <Text size="xs">{r.mode === 'ask' ? 'ask first' : r.mode}</Text> },
              { key: 'outcome', header: 'outcome', width: 112, sort: (r) => r.outcome, render: (r) => <Outcome value={r.outcome} /> },
              { key: 'ms', header: 'took', num: true, sort: (r) => r.ms, render: (r) => (r.ms >= 1000 ? `${(r.ms / 1000).toFixed(1)}s` : `${r.ms}ms`) },
              { key: 'session', header: 'session', render: (r) => <Fixed dim>{r.session}</Fixed> },
            ]}
          />
        </div>

        <Text size="xs" c="dimmed">
          Messages: <Mono dim>{doc.messages.ledger}</Mono> (source <Mono dim>{doc.messages.source}</Mono>). Page audit: <Mono dim>{doc.page_audit.path}</Mono>, and the same line on this console's log, which the log plane ships.
          Each message is also a job on the Jobs page, a Claude Code transcript and, after <Mono dim>tools/dash lake assist</Mono>, rows in the lake. {doc.note}
        </Text>
      </Stack>
    </Section>
  );
}

/** A KPI and its threshold as a sentence; a null threshold is measured, not judged. */
const KPI_WORDS: Record<string, (v: number | null) => string> = {
  accepted_per_usd: (v) => (v == null ? 'accepted outcomes per dollar: measured, not judged' : `at least ${v} accepted outcomes per dollar`),
  accepted_per_actions_min: (v) => (v == null ? 'accepted outcomes per Actions minute: measured, not judged' : `at least ${v} accepted outcomes per Actions minute`),
  time_to_outcome_h: (v) => (v == null ? 'time to an outcome: measured, not judged' : `an outcome within ${v} h`),
  false_signal_pct: (v) => (v == null ? 'false signals: measured, not judged' : `false signals at most ${v}%`),
  silent_failure_pct: (v) => (v == null ? 'silent failures: measured, not judged' : `silent failures at most ${v}%`),
};
const GAP_WORDS: Record<string, string> = {
  R1: 'registration', R2: 'run record', R3: 'KPIs', R4: 'data sources', R5: 'reflector', R6: 'local entry point',
};

function Registered({ entry, agent }: { entry: AssistAgentEntry | null; agent: string }) {
  return (
    <Section
      title="In the agent inventory"
      description="The assistant is an agent under the efficacy contract (constitution § 29): it is registered with an owner, a switch, a cap and a model, and it is held to the KPIs its kind declares. The numbers live in _data/fleet.yml, never in its prompt."
    >
      {entry ? (
        <Paper p="md" data-testid="assist-agent-entry">
          <Stack gap={6}>
            <Group gap="xs" wrap="wrap">
              <Mono>{entry.id}</Mono>
              <Badge size="sm" variant="outline" title={entry.category ?? undefined}>{entry.kind ?? entry.category}</Badge>
              <Text size="sm" c="dimmed">owner {entry.owner ?? dash}</Text>
            </Group>
            <Text size="sm">
              Model <Mono>{entry.model ?? dash}</Mono> · cap {entry.budget?.per_run_usd != null ? `$${entry.budget.per_run_usd} per message` : dash} (API-equivalent, an estimate)
              {' '}· switch <Mono>{entry.switch ? Object.values(entry.switch).join(', ') : dash}</Mono> · run records in <Mono>{entry.run_record ?? 'none'}</Mono>
            </Text>
            <Text size="sm" c="dimmed">{entry.trigger}</Text>
            {entry.kpis ? (
              <Text size="sm">
                KPIs: {Object.entries(entry.kpis).map(([k, v]) => (KPI_WORDS[k] ? KPI_WORDS[k](v) : `${k} ${v ?? '(measured, not judged)'}`)).join(' · ')}
              </Text>
            ) : null}
            {entry.reads ? <Text size="xs" c="dimmed">Reads: {Object.keys(entry.reads).join(', ')}</Text> : null}
            {entry.gaps?.length ? (
              <Group gap={6} wrap="wrap">
                <Text size="sm">Contract gaps:</Text>
                {entry.gaps.map((g) => <Badge key={g} size="sm" color="yellow" variant="light" title={GAP_WORDS[g.slice(0, 2)] ?? g}>{g}</Badge>)}
              </Group>
            ) : <Text size="sm">No contract gaps.</Text>}
            {entry.local_entry ? <Text size="xs" c="dimmed">From a terminal: <Mono dim>{entry.local_entry}</Mono></Text> : null}
          </Stack>
        </Paper>
      ) : <Empty>{agent} is not in _data/agents.yml. Run tools/dash agents.</Empty>}
    </Section>
  );
}
