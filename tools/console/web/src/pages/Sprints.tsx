// The live expedite-sprint record (constitution § 27.7, docs/EXPEDITE-SPRINTS.md): one
// committed state document per sprint in _data/sprints/, read through /api/sprints
// (tools/sprint_record.py), so it renders the same on a console and on the published
// snapshot. Read-only by design: a record changes only by a pull request, so nothing on
// this page writes. ?sprint=<slug> picks the record shown in full; the active one is
// the default.
import { Link, useSearchParams } from 'react-router';
import { Anchor, Badge, Group, List, Paper, SimpleGrid, Stack, Text, Title } from '@mantine/core';
import { useSprints } from '../api/hooks';
import type { Sprint, SprintGate, SprintItem, SprintTripWire, SprintsDoc } from '../api/types';
import { DataTable } from '../components/DataTable';
import { Banner, External, Load, Meter, Mono, PageHeader, Section, StatTile, Status, type Tone } from '../components/ui';
import { gh, to } from '../lib/links';

const REF_RX = /^([A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+)#(\d+)$/;
const STATE_TONE: Record<string, Tone> = { proposed: 'info', active: 'info', stopped: 'warn', demoted: 'warn', done: 'good' };
const TRIP_TONE: Record<string, Tone> = { armed: 'info', tripped: 'crit', cleared: 'good' };
const GATE_LABEL: Record<string, string> = { declaration: 'Declaration (A)', spec: 'Spec approval (B)', merge: 'Merge (C)' };
const GATE_NEXT: Record<string, string> = { declaration: 'the declaration (gate A)', spec: 'spec approval (gate B)', merge: 'the merge (gate C)' };
// The gate that opens each phase (docs/EXPEDITE-SPRINTS.md): scope after A, build after B, deploy after C.
const OPENED_BY: Record<number, string> = { 1: 'after gate A', 2: 'after gate B', 4: 'after gate C' };
const DORA_ISSUE = 'https://github.com/bamr87/bamr87/issues/690';

const issueUrl = (ref: string, kind?: string): string | null => {
  const m = REF_RX.exec(ref);
  return m ? `https://github.com/${m[1]}/${kind === 'pr' ? 'pull' : 'issues'}/${m[2]}` : null;
};
const when = (iso?: string | null) => (iso ? `${iso.replace('T', ' ').slice(0, 16)} UTC` : '—');
const usd = (n?: number | null) => (typeof n === 'number' && Number.isFinite(n) ? `$${n.toFixed(2)}` : '—');

/** A gate's evidence or an item: a GitHub reference or URL links out; anything else is shown as written. */
function Ref({ value, kind }: { value?: string | null; kind?: string }) {
  if (!value) return <Text span c="dimmed" size="sm">—</Text>;
  if (/^https?:\/\//.test(value)) return <External href={value} size="sm">{value.replace(/^https?:\/\/(www\.)?github\.com\//, '')}</External>;
  const url = issueUrl(value, kind);
  return url ? <External href={url} size="sm">{value}</External> : <Mono>{value}</Mono>;
}

function Findings({ title, items, tone }: { title: string; items: string[]; tone: Tone }) {
  if (!items.length) return null;
  return (
    <Banner tone={tone} title={title}>
      <List size="sm" spacing={2}>{items.map((e) => <List.Item key={e}>{e}</List.Item>)}</List>
    </Banner>
  );
}

function Phases({ phases, current }: { phases: string[]; current?: number }) {
  return (
    <SimpleGrid cols={{ base: 2, xs: 4, md: 7 }} spacing={6} aria-label="Sprint phases">
      {phases.map((name, i) => {
        const now = i === current;
        const past = current !== undefined && i < current;
        return (
          <Paper key={name} p={8} withBorder aria-current={now ? 'step' : undefined}
            style={{ border: now ? '2px solid var(--mantine-color-blue-filled)' : undefined, background: past ? 'var(--mantine-color-green-light)' : undefined }}>
            <Group justify="space-between" gap={4} wrap="nowrap">
              <Text size="xs" c="dimmed">{i}</Text>
              {past ? <Text size="xs" c="dimmed" aria-label="done">✓</Text> : null}
            </Group>
            <Text size="sm" fw={now ? 700 : 500}>{name}</Text>
            <Text size="10px" c="dimmed">{OPENED_BY[i] ?? (now ? 'now' : ' ')}</Text>
          </Paper>
        );
      })}
    </SimpleGrid>
  );
}

function SprintRecord({ s, doc }: { s: Sprint; doc: SprintsDoc }) {
  if (s.withheld) {
    return <Findings tone="crit" title={`${s.path} is withheld — it failed the record's own checks`} items={s.findings} />;
  }
  const gates = s.gates ?? { declaration: null, spec: null, merge: null };
  const wires = s.trip_wires ?? [];
  const tripped = wires.filter((w) => w.state === 'tripped').length;
  const next = doc.gates.find((g) => !gates[g as keyof typeof gates]);
  const used = s.spend?.usd ?? 0;
  const cap = s.spend?.cap_usd ?? 0;
  const dora = s.dora && Object.keys(s.dora).length ? s.dora : null;
  const lessons = s.retro?.lessons ?? [];
  const debt = s.retro?.debt ?? [];
  const recordLink = s.path.startsWith('_data/') ? <External href={gh.hubFile(s.path)} size="xs">{s.path}</External> : <Mono dim>{s.path}</Mono>;
  return (
    <Stack gap={0} data-testid="sprint-record">
      <Group gap="sm" align="center" wrap="wrap" mb={6}>
        <Title order={2} fz={18}>{s.title}</Title>
        <Status tone={STATE_TONE[s.state ?? ''] ?? 'info'}>{s.state ?? 'unknown'}</Status>
        <Badge variant="light">phase {s.phase ?? '—'} · {s.phase_name ?? '—'}</Badge>
      </Group>
      <Text size="sm" c="dimmed" mb="md">
        Item <Ref value={s.item} /> {s.target_repo ? <>in <Mono>{s.target_repo}</Mono></> : null} · record {recordLink}{s.updated_at ? <> · updated {when(s.updated_at)}</> : null}
      </Text>
      <Findings tone="crit" title="This record breaks the standard" items={s.findings} />
      <Findings tone="warn" title="Needs attention" items={s.warnings} />
      <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }} spacing="md">
        <StatTile label="Spend vs cap" value={<>{usd(used)} <Text span c="dimmed" fz={14}>/ {usd(cap)}</Text></>}
          meter={<Meter value={used} cap={cap || 1} />}
          sub={`${doc.cost_label}${s.spend?.updated_at ? ` · as of ${when(s.spend.updated_at)}` : ''}`} />
        <StatTile label="Appetite (a ceiling)" value={`${s.appetite?.hours ?? '—'} h`}
          sub={s.appetite?.ends_at ? `time box ends ${when(s.appetite.ends_at)}` : 'no end time recorded'} />
        <StatTile label="Gates passed" value={`${s.gates_passed ?? 0}/3`}
          sub={next ? `waiting on ${GATE_NEXT[next] ?? next} — Amr's` : 'all three passed'} />
        <StatTile label="Trip wires" value={`${tripped}/${wires.length} tripped`} tone={tripped ? 'crit' : undefined}
          sub={wires.length ? `${wires.filter((w) => w.state === 'armed').length} armed · ${wires.filter((w) => w.state === 'cleared').length} cleared` : 'none recorded'} />
      </SimpleGrid>

      {s.stop ? (
        <Banner tone="warn" title={`Stopped ${when(s.stop.at)} — ${s.stop.reason === 'cap' || s.stop.reason === 'time-box' ? `the circuit breaker (${s.stop.reason})` : s.stop.reason}`}>
          <Text size="sm">
            {s.stop.by ? <>By {s.stop.by}. </> : null}
            {s.stop.filed?.length ? <>Filed as drafts: {s.stop.filed.map((r, i) => <span key={r}>{i ? ', ' : ''}<Ref value={r} kind="pr" /></span>)}. </> : null}
            {s.stop.note ?? 'A stopped sprint is never extended automatically; going on needs a new declaration.'}
          </Text>
        </Banner>
      ) : null}

      <Section title="Phase" description="Intake to retro, as the standard runs them. A phase starts only after the gate before it has passed.">
        <Phases phases={doc.phases} current={s.phase} />
      </Section>

      <Section title="Gates" description="Declaration, then spec approval, then merge — each passed by Amr alone (§ 27.2), with who, when and the evidence.">
        <div data-testid="sprint-gates">
          <DataTable<{ gate: string; g: SprintGate | null }>
            rows={doc.gates.map((gate) => ({ gate, g: gates[gate as keyof typeof gates] ?? null }))}
            rowKey={(r) => r.gate} minWidth={780} dense
            columns={[
              { key: 'gate', header: 'gate', width: 150, render: (r) => <Text size="sm" fw={500}>{GATE_LABEL[r.gate] ?? r.gate}</Text> },
              { key: 'st', header: 'status', width: 110, render: (r) => (r.g ? <Status tone="good">passed</Status> : <Status tone="info">waiting</Status>) },
              { key: 'by', header: 'by', width: 90, render: (r) => <Mono dim={!r.g}>{r.g?.by ?? '—'}</Mono> },
              { key: 'at', header: 'when', width: 170, render: (r) => <Mono dim>{when(r.g?.at)}</Mono> },
              { key: 'ref', header: 'evidence', render: (r) => <Ref value={r.g?.ref} /> },
            ]}
          />
        </div>
      </Section>

      <Section title={`Items and pull requests (${(s.items ?? []).length})`}>
        <DataTable<SprintItem>
          rows={s.items ?? []} rowKey={(r) => r.ref} minWidth={780} dense
          empty="No items recorded yet."
          open={(r) => issueUrl(r.ref, r.kind)}
          columns={[
            { key: 'ref', header: 'ref', width: 240, sort: (r) => r.ref, render: (r) => <Ref value={r.ref} kind={r.kind} /> },
            { key: 'kind', header: 'kind', width: 130, sort: (r) => r.kind, render: (r) => <Badge variant="default" size="sm">{r.kind === 'pr' ? 'pull request' : 'issue'}</Badge> },
            { key: 'title', header: 'title', render: (r) => <Text size="sm">{r.title ?? '—'}</Text> },
            { key: 'state', header: 'state', width: 80, sort: (r) => r.state ?? '', render: (r) => <Text size="sm">{r.state ?? '—'}</Text> },
            { key: 'phase', header: 'phase', width: 64, sort: (r) => r.phase ?? -1, render: (r) => <Mono dim>{r.phase ?? '—'}</Mono> },
          ]}
        />
      </Section>

      <Section title={`Trip wires (${wires.length})`} description="The conditions that stop or escalate the sprint, and when each one fired.">
        <DataTable<SprintTripWire>
          rows={wires} rowKey={(r) => r.id} minWidth={760} dense
          empty="No trip wires recorded."
          tone={(r) => (r.state === 'tripped' ? 'crit' : undefined)}
          columns={[
            { key: 'id', header: 'id', width: 170, render: (r) => <Mono>{r.id}</Mono> },
            { key: 'rule', header: 'rule', render: (r) => <Text size="sm">{r.rule}</Text> },
            { key: 'state', header: 'state', width: 110, render: (r) => <Status tone={TRIP_TONE[r.state] ?? 'info'}>{r.state}</Status> },
            { key: 'at', header: 'when', width: 170, render: (r) => <Mono dim>{when(r.at)}</Mono> },
          ]}
        />
      </Section>

      <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md" mt="xl">
        <Paper p="md" data-testid="sprint-dora">
          <Title order={2} fz={15} mb={6}>DORA delivery metrics</Title>
          {dora ? (
            <Stack gap={2}>{Object.entries(dora).map(([k, v]) => <Text key={k} size="sm"><Mono>{k}</Mono> {typeof v === 'object' ? JSON.stringify(v) : String(v)}</Text>)}</Stack>
          ) : (
            <Text size="sm" c="dimmed">
              Not measured yet. The read-only DORA projection (<External href={DORA_ISSUE} size="sm">#690</External>) fills this snapshot for {s.target_repo ? <Mono>{s.target_repo}</Mono> : 'the target repo'} once it lands — a guide per app, never a target.
            </Text>
          )}
        </Paper>
        <Paper p="md" data-testid="sprint-retro">
          <Title order={2} fz={15} mb={6}>Retro</Title>
          {lessons.length || debt.length ? (
            <>
              <List size="sm" spacing={4}>{lessons.map((l) => <List.Item key={l}>{l}</List.Item>)}</List>
              <Text size="sm" mt="sm">
                Quality debt filed: {debt.length ? debt.map((r, i) => <span key={r}>{i ? ', ' : ''}<Ref value={r} /></span>) : 'none'}
              </Text>
            </>
          ) : (
            <Text size="sm" c="dimmed">Written when the sprint ends: each failure routed to the strongest ratchet rung, and the remaining quality debt filed as issues before it closes (§ 27.8).</Text>
          )}
        </Paper>
      </SimpleGrid>
    </Stack>
  );
}

function SprintsBody({ doc, selected }: { doc: SprintsDoc; selected: string | null }) {
  const shown = doc.sprints.find((s) => s.slug === selected) ?? doc.sprints[0];
  return (
    <>
      <Findings tone="crit" title="The sprint records break the standard (drift check (q))" items={doc.errors.filter((e) => !shown || !e.startsWith(`${shown.slug}: `))} />
      {doc.sprints.length === 0 ? (
        <Paper p="lg" data-testid="sprints-empty">
          <Title order={2} fz={16} mb={6}>No expedite sprint is declared</Title>
          <Text size="sm" maw={900}>
            An expedite sprint starts when Amr commits its item to <Mono>_data/work_queue.yml</Mono> <Mono>order:</Mono> with an appetite: hours, and a USD ceiling that is {doc.cost_label}. The pull request that does it adds <Mono>{doc.dir}/&lt;slug&gt;.yml</Mono>, and its record appears here. Until then every item waits its turn on the <Anchor component={Link} to={to.work()} size="sm">Work board</Anchor>.
          </Text>
          <Text size="sm" c="dimmed" mt="sm">
            The format: <External href={gh.hubFile(`${doc.dir}/README.md`)} size="sm">{doc.dir}/README.md</External> · the standard: <External href={gh.hubFile(doc.standard)} size="sm">{doc.standard}</External>
          </Text>
        </Paper>
      ) : (
        <>
          {shown ? <SprintRecord s={shown} doc={doc} /> : null}
          <Section title={`Every sprint (${doc.sprints.length})`} description="At most one is active fleet-wide (WIP 1). Pick one to read its record.">
            <DataTable<Sprint>
              rows={doc.sprints} keys rowKey={(r) => r.slug} minWidth={900} dense
              href={(r) => to.sprints(r.slug)}
              tone={(r) => (r.findings.length ? 'crit' : r.state === 'active' ? undefined : 'muted')}
              columns={[
                { key: 'slug', header: 'sprint', sort: (r) => r.slug, render: (r) => <Stack gap={0}><Text size="sm" fw={r.slug === shown?.slug ? 700 : 500}>{r.title}</Text><Mono dim>{r.slug}</Mono></Stack> },
                { key: 'state', header: 'state', width: 120, sort: (r) => r.state ?? '', render: (r) => <Status tone={STATE_TONE[r.state ?? ''] ?? 'info'}>{r.withheld ? 'withheld' : (r.state ?? '—')}</Status> },
                { key: 'phase', header: 'phase', width: 100, sort: (r) => r.phase ?? -1, render: (r) => <Text size="sm">{r.phase ?? '—'} · {r.phase_name ?? '—'}</Text> },
                { key: 'item', header: 'item', width: 230, render: (r) => <Mono dim>{r.item ?? '—'}</Mono> },
                { key: 'spend', header: `spend (${doc.cost_label})`, width: 170, num: true, sort: (r) => r.spend_ratio ?? -1, render: (r) => <Text size="sm">{usd(r.spend?.usd)} / {usd(r.spend?.cap_usd)}</Text> },
              ]}
            />
          </Section>
        </>
      )}
      <Findings tone="warn" title="Warnings" items={doc.warnings.filter((w) => !shown || !w.startsWith(`${shown.slug}: `))} />
    </>
  );
}

export function Sprints() {
  const q = useSprints();
  const [sp] = useSearchParams();
  return (
    <div data-testid="sprints-page">
      <PageHeader
        title="Sprints"
        description={<>The live expedite-sprint record (constitution § 27): at most one sprint is active fleet-wide, its three gates are Amr's, and its appetite is a ceiling, not an estimate. Each record is a file in <Mono>_data/sprints/</Mono> that changes only by a pull request, so this page only reads it. Every dollar figure is API-equivalent (estimate). The standard: <External href={gh.hubFile('docs/EXPEDITE-SPRINTS.md')} size="sm">docs/EXPEDITE-SPRINTS.md</External>.</>}
      />
      <Load q={q}>{(doc) => <SprintsBody doc={doc} selected={sp.get('sprint')} />}</Load>
    </div>
  );
}
