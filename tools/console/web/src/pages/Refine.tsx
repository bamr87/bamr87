// Harness refinement (JEV capability three, docs/HARNESS-REFINEMENT.md,
// ADR 0004 P2): the hub's harness surface as a sensor, the fleet sweep, one
// Propose–Probe–Compose plan per agent step with its ceiling against the
// month, the evidence trees built here, the experience library (the human-
// gated inbox) and the review queue — every unfiled loop-run preview, with
// the apply behind the console's confirm gate. Everything on this page costs
// $0 to read and to run except the approvals, which say so.
import { useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { useQueryClient } from '@tanstack/react-query';
import { notifications } from '@mantine/notifications';
import {
  Anchor, Badge, Button, Code, Group, Paper, Select, SimpleGrid, Stack, Tabs, Text, TextInput, Textarea,
} from '@mantine/core';
import { IconCheck, IconEye, IconPlus } from '@tabler/icons-react';
import { hasConsole } from '../api/backend';
import { api } from '../api/client';
import { useEvidence, useEvidenceFile, useRefine, useReviewFile } from '../api/hooks';
import type { EvidenceTree, FleetSurfaceRow, LibraryEntry, RefineDoc, RefinePlan, RefineStep, ReviewItem } from '../api/types';
import { DataTable } from '../components/DataTable';
import { Banner, Load, LocalOnly, Mono, PageHeader, Section, StatTile, Status, type Tone } from '../components/ui';
import { RunButton } from '../jobs/RunButton';
import { when } from '../lib/format';
import { to } from '../lib/links';
import u from '../styles/utils.module.css';

const TABS = ['surface', 'plans', 'review', 'evidence', 'library'] as const;
type Tab = (typeof TABS)[number];
const usd = (n: number | null | undefined) => (n == null ? '—' : `$${n.toFixed(2)}`);

export function Refine() {
  const doc = useRefine();
  const [search, setSearch] = useSearchParams();
  const tab = (TABS as readonly string[]).includes(search.get('tab') ?? '') ? (search.get('tab') as Tab) : 'surface';
  const setTab = (t: string | null) => { const next = new URLSearchParams(search); if (t && t !== 'surface') next.set('tab', t); else next.delete('tab'); setSearch(next, { replace: true }); };
  return (
    <>
      <PageHeader
        title="Refine"
        description="The harness itself, refined from the evidence of its own attempts (Harness², docs/HARNESS-REFINEMENT.md): the surface validated as a sensor, one Propose–Probe–Compose step planned per agent step, the evidence a proposer reads, the lessons the next attempt starts from, and the review queue where a person approves what a loop would file. Nothing here calls a model; the model-backed stages are ADR 0004 P1."
        actions={
          <>
            <RunButton op="refine-surface">Check the hub's surface</RunButton>
            <RunButton op="refine-surface" params={{ target: 'fleet' }}>Sweep the fleet</RunButton>
            <RunButton op="refine-library-check">Check the library</RunButton>
          </>
        }
        badges={<Load q={doc} rows={1}>{(d) => <><Status tone={d.surface.ok ? 'good' : 'crit'}>{d.surface.ok ? 'surface clean' : `${d.surface.errors.length} surface error(s)`}</Status>{d.reviews.length ? <Status tone="warn">{d.reviews.length} awaiting review</Status> : null}</>}</Load>}
      />
      <Load q={doc}>
        {(d) => (
          <Tabs value={tab} onChange={setTab} keepMounted={false}>
            <Tabs.List>
              <Tabs.Tab value="surface">Surface</Tabs.Tab>
              <Tabs.Tab value="plans">Plans</Tabs.Tab>
              <Tabs.Tab value="review">Review queue{d.reviews.length ? ` (${d.reviews.length})` : ''}</Tabs.Tab>
              <Tabs.Tab value="evidence">Evidence{d.evidence.length ? ` (${d.evidence.length})` : ''}</Tabs.Tab>
              <Tabs.Tab value="library">Library{d.library.count ? ` (${d.library.count})` : ''}</Tabs.Tab>
            </Tabs.List>
            <Tabs.Panel value="surface" pt="md"><SurfaceTab d={d} /></Tabs.Panel>
            <Tabs.Panel value="plans" pt="md"><PlansTab d={d} /></Tabs.Panel>
            <Tabs.Panel value="review" pt="md"><ReviewTab d={d} /></Tabs.Panel>
            <Tabs.Panel value="evidence" pt="md"><EvidenceTab d={d} /></Tabs.Panel>
            <Tabs.Panel value="library" pt="md"><LibraryTab d={d} /></Tabs.Panel>
          </Tabs>
        )}
      </Load>
    </>
  );
}

// ---------------------------------------------------------------- surface
function SurfaceTab({ d }: { d: RefineDoc }) {
  const s = d.surface;
  const c = s.census;
  const fs = d.fleet_surface;
  const pct = c.always_on.pct_of_cap ?? 0;
  const rowTone = (r: FleetSurfaceRow): Tone => (!r.checked_out ? 'info' : r.ok === false ? 'crit' : r.warnings ? 'warn' : 'good');
  return (
    <>
      <SimpleGrid cols={{ base: 2, md: 3, xl: 6 }} spacing="sm">
        <StatTile label="always-on text" value={`${c.always_on.chars.toLocaleString()} chars`} sub={`${pct}% of the ${c.always_on.max_chars.toLocaleString()} cap · ${c.always_on.files.join(' → ') || 'no context file'}`} tone={pct >= 100 ? 'crit' : pct >= 80 ? 'warn' : 'good'} />
        <StatTile label="skills" value={c.skills.length} sub={`${c.skills.filter((k) => k.triggered).length} named in the always-on text`} />
        <StatTile label="subagents" value={c.subagents.length} sub={c.subagents.map((a) => a.name).join(', ') || '—'} />
        <StatTile label="commands" value={c.commands.length} sub={c.commands.map((x) => `/${x.name}`).join(' ') || '—'} />
        <StatTile label="hooks" value={c.policy_as_data.hook_commands} sub={c.policy_as_data.hook_events.join(', ') || 'none'} />
        <StatTile label="MCP servers" value={c.policy_as_data.mcp_servers.length} sub={c.policy_as_data.mcp_servers.join(', ') || 'none'} />
      </SimpleGrid>
      <Section title="The hub's own surface" description={`${s.root ?? 'bamr87/bamr87'} — ${c.files} files on the eight-component surface, ${c.script_refs_checked} script references checked. An error here is what a runtime drops silently: a skill without description frontmatter, a hook of the wrong shape, a script a component names but does not ship.`}>
        {s.errors.length || s.warnings.length || s.notes.length ? (
          <Stack gap={4}>
            {s.errors.map((e) => <Text key={e} size="sm" c="red">✗ {e}</Text>)}
            {s.warnings.map((w) => <Text key={w} size="sm" c="yellow">! {w}</Text>)}
            {s.notes.map((n) => <Text key={n} size="xs" c="dimmed">{n}</Text>)}
          </Stack>
        ) : <Text size="sm" c="dimmed">Clean: no error, warning or note.</Text>}
      </Section>
      <Section title="Every checked-out fleet repository" description={fs.error ? fs.error : `${fs.totals.checked_out ?? 0} of ${fs.totals.registry ?? 0} registry repositories checked out here: ${fs.totals.clean ?? 0} clean, ${fs.totals.with_errors ?? 0} with errors, ${fs.totals.no_context_file ?? 0} with no context file. A repository that is not checked out, or that the registry tracks without a submodule, is listed, never read.`}>
        <DataTable
          rows={fs.repos}
          rowKey={(r: FleetSurfaceRow) => r.name}
          minWidth={900}
          columns={[
            { key: 'ok', header: 'surface', width: 132, render: (r: FleetSurfaceRow) => <Status tone={rowTone(r)}>{!r.checked_out ? (r.path ? 'not checked out' : 'no submodule') : r.ok === false ? `${r.errors} error(s)` : r.warnings ? `${r.warnings} warning(s)` : 'clean'}</Status> },
            { key: 'name', header: 'repo', render: (r: FleetSurfaceRow) => <Anchor component={Link} to={to.project(r.name)} size="sm">{r.name}</Anchor>, sort: (r: FleetSurfaceRow) => r.name },
            { key: 'category', header: 'category', render: (r: FleetSurfaceRow) => <Text size="xs" c="dimmed">{r.category}</Text> },
            { key: 'always_on', header: 'always-on', num: true, render: (r: FleetSurfaceRow) => <Text size="xs">{r.always_on_chars?.toLocaleString() ?? '—'}</Text>, sort: (r: FleetSurfaceRow) => r.always_on_chars ?? -1 },
            { key: 'skills', header: 'skills', num: true, render: (r: FleetSurfaceRow) => <Text size="xs">{r.skills ?? '—'}</Text>, sort: (r: FleetSurfaceRow) => r.skills ?? -1 },
            { key: 'agents', header: 'agents', num: true, render: (r: FleetSurfaceRow) => <Text size="xs">{r.subagents ?? '—'}</Text> },
            { key: 'hooks', header: 'hooks', num: true, render: (r: FleetSurfaceRow) => <Text size="xs">{r.hooks ?? '—'}</Text> },
            { key: 'mcp', header: 'MCP', num: true, render: (r: FleetSurfaceRow) => <Text size="xs">{r.mcp_servers ?? '—'}</Text> },
            { key: 'context', header: 'context files', render: (r: FleetSurfaceRow) => <Text size="xs" c="dimmed">{r.context_files.join(', ') || (r.checked_out ? 'none' : '')}</Text> },
            { key: 'problems', header: 'problems', render: (r: FleetSurfaceRow) => <Text size="xs" c={r.ok === false ? 'red' : 'dimmed'} className={u.preWrap}>{r.problems.join(' · ') || '—'}</Text> },
          ]}
        />
      </Section>
    </>
  );
}

// ------------------------------------------------------------------ plans
function PlansTab({ d }: { d: RefineDoc }) {
  return (
    <Stack gap="md">
      {d.config_error ? <Banner tone="crit" title="harness_refinement is misconfigured">{d.config_error}</Banner> : null}
      {d.plans.map((p) => <PlanCard key={`${p.loop}/${p.step ?? ''}`} p={p} local={d.local} />)}
    </Stack>
  );
}

function PlanCard({ p, local }: { p: RefinePlan; local: boolean }) {
  const [open, setOpen] = useState(false);
  if (p.error) return <Paper p="md"><Text fw={600}><Mono>{p.loop}{p.step ? `/${p.step}` : ''}</Mono></Text><Text size="sm" c="red">{p.error}</Text></Paper>;
  const b = p.budget;
  const fit: Tone = !b?.available ? 'info' : b.affordable ? 'good' : 'crit';
  return (
    <Paper p="md">
      <Stack gap={6}>
        <Group justify="space-between" wrap="wrap" gap="xs">
          <div>
            <Text fw={600}><Mono>{p.loop}/{p.step}</Mono> <Text span size="xs" c="dimmed">· {p.call_site} · k={p.k} · {p.mode}</Text></Text>
            <Text size="sm">R = 4k = {p.identity?.R} rollouts, P = 3k = {p.identity?.P} improvement sessions, then one selection and one reflection — ceiling <b>{usd(p.cost?.ceiling_usd)}</b> <Text span size="xs" c="dimmed">({p.cost?.rollouts.count} × {usd(p.cost?.rollouts.cap_usd_each)} + {p.cost?.sessions.count} × {usd(p.cost?.sessions.cap_usd_each)} + 2 × {usd(p.cost?.sessions.cap_usd_each)}, API-equivalent (estimate))</Text></Text>
          </div>
          <Group gap="xs">
            <Status tone={fit}>{!b?.available ? (local ? `budget not judged${b?.reason ? `: ${b.reason}` : ''}` : 'budget judged on a console') : `${b.month}: ${usd(b.spent_usd)} of ${usd(b.cap_usd)} spent · this step ${b.affordable ? 'fits' : 'does NOT fit'}`}</Status>
            <Status tone={p.model_backed?.enabled ? 'warn' : 'info'}>{p.model_backed?.enabled ? 'model-backed stages armed' : 'model-backed stages off (P1)'}</Status>
          </Group>
        </Group>
        <Group gap="lg" wrap="wrap">
          <Text size="xs" c="dimmed">tunable: {p.tunable?.length ? p.tunable.map((t) => `${t.path}${t.exists ? ` (${t.chars.toLocaleString()} chars)` : ' (absent)'}`).join(', ') : 'none — this loop reads only its hard rules and a generated brief'}</Text>
          <Text size="xs" c="dimmed">hard rules (read-only): <Mono>{p.hard_rules?.prompt}</Mono> sha {p.hard_rules?.template_sha256.slice(0, 12)} · {p.hard_rules?.allowed_tools} tools · {p.hard_rules?.model} · {p.hard_rules?.max_turns} turns</Text>
          <Text size="xs" c="dimmed">library: {p.library?.entries ?? 0} lesson(s) in <Mono>{p.library?.domain}</Mono></Text>
          <Text size="xs" c="dimmed">proposer: {p.proposer?.model} · {p.proposer?.max_turns} turns</Text>
        </Group>
        <Group gap="xs">
          <RunButton op="refine-plan" params={{ loop: p.loop, step: p.step }}>Plan (k=1, $0)</RunButton>
          <RunButton op="refine-plan" params={{ loop: p.loop, step: p.step, k: 2, mode: 'sequential' }}>Plan k=2 sequential ($0)</RunButton>
          <Button size="xs" variant="default" component={Link} to={to.op('refine-evidence', { loop: p.loop, step: p.step })}>Build evidence for an item…</Button>
          <Button size="xs" variant="subtle" onClick={() => setOpen((o) => !o)}>{open ? 'Hide' : 'Show'} the schedule</Button>
        </Group>
        {open && p.steps ? (
          <DataTable
            rows={p.steps.map((s, i) => ({ ...s, n: i + 1 }))}
            rowKey={(s: RefineStep & { n: number }) => `${s.kind}-${s.label}`}
            minWidth={560}
            columns={[
              { key: 'n', header: '#', num: true, render: (s: RefineStep & { n: number }) => <Text size="xs">{s.n}</Text> },
              { key: 'kind', header: 'kind', render: (s: RefineStep) => <Badge variant="light" color={s.kind === 'rollout' ? 'blue' : 'grape'}>{s.kind}</Badge> },
              { key: 'label', header: 'label', render: (s: RefineStep) => <Mono>{s.label}</Mono> },
              { key: 'dim', header: 'dim', render: (s: RefineStep) => <Text size="xs">{s.dim}</Text> },
              { key: 'harness', header: 'harness', render: (s: RefineStep) => <Mono>{s.harness}</Mono> },
              { key: 'evidence', header: 'reads', render: (s: RefineStep) => <Text size="xs" c="dimmed">{s.evidence.join(', ') || '—'}</Text> },
            ]}
          />
        ) : null}
      </Stack>
    </Paper>
  );
}

// ----------------------------------------------------------------- review
function ReviewTab({ d }: { d: RefineDoc }) {
  if (!d.local) return <LocalOnly what="The review queue (it reads .fleet/runs on the operator's machine)" />;
  if (!d.reviews.length) return <Text size="sm" c="dimmed">Nothing awaits review: every local loop-run preview has been filed or superseded. Run a loop's agent step from its page (<Anchor component={Link} to={to.loops()}>Loops</Anchor> → Run locally) to produce one.</Text>;
  return <Stack gap="md">{d.reviews.map((r) => <ReviewCard key={`${r.run_id}:${r.item}`} r={r} />)}</Stack>;
}

function ReviewCard({ r }: { r: ReviewItem }) {
  const [showing, setShowing] = useState<string | null>(null);
  const file = useReviewFile(r.run_id, showing);
  const base = { loop: r.loop, step: r.step, run_id: r.run_id, item: r.item };
  return (
    <Paper p="md" data-testid="review-item">
      <Stack gap={6}>
        <Group justify="space-between" wrap="wrap" gap="xs">
          <div>
            <Text fw={600}><Mono>{r.item}</Mono> <Text span size="xs" c="dimmed">· {r.loop}/{r.step} · run <Mono>{r.run_id}</Mono></Text></Text>
            <Text size="sm">{r.reason ?? r.status}{r.would_file != null ? ` — ${r.would_file} item(s) would be filed` : ''}{r.cost_usd != null ? ` · attempt cost ${usd(r.cost_usd)} (${r.cost_label})` : ''}{r.finished ? ` · ${when(r.finished)}` : ''}</Text>
          </div>
          <Group gap="xs">
            {r.publish_tier ? <Status tone="warn">publish tier {r.publish_tier}</Status> : null}
            {!r.can_apply ? <Status tone="info">filer cannot file yet (#488)</Status> : null}
          </Group>
        </Group>
        {r.bodies.length ? <Text size="xs" c="dimmed">bodies: {r.bodies.map((b) => b.title).join(' · ')}</Text> : null}
        <Group gap="xs" wrap="wrap">
          {r.preview ? <Button size="xs" variant="default" leftSection={<IconEye size={14} />} onClick={() => setShowing(showing === r.preview ? null : r.preview)}>{showing ? 'Hide' : 'Read'} the preview</Button> : null}
          {r.bodies.map((b) => <Button key={b.file} size="xs" variant="subtle" onClick={() => setShowing(`items/${r.dir}/bodies/${b.file}`)}>{b.title || b.file}</Button>)}
          <RunButton op="loop-run" params={base}>Check it still matches ($0)</RunButton>
          <RunButton op="loop-run" params={{ ...base, apply: true }} variant="filled" disabled={!r.can_apply}>
            <IconCheck size={14} /> Approve and file
          </RunButton>
        </Group>
        {showing ? (file.data ? <Code block className={u.preWrap}>{file.data.text}</Code> : <Text size="xs" c="dimmed">{file.isError ? (file.error as Error).message : 'loading…'}</Text>) : null}
      </Stack>
    </Paper>
  );
}

// --------------------------------------------------------------- evidence
function EvidenceTab({ d }: { d: RefineDoc }) {
  const [stamp, setStamp] = useState<string | null>(null);
  const [path, setPath] = useState<string | null>(null);
  const tree = useEvidence(stamp);
  const file = useEvidenceFile(stamp, path);
  if (!d.local) return <LocalOnly what="The evidence trees (they live under .fleet/refine on the operator's machine)" />;
  return (
    <>
      <Text size="sm" c="dimmed" mb="sm">An evidence tree is what a proposer session would read: the brief, every attempt's full redacted trajectory, the deliverables, the tunable harness, the hard rules read-only, the domain's library and the rendered mission. Build one from a loop's completed local attempts: <Anchor component={Link} to={to.op('refine-evidence')}>Refine: build the evidence tree</Anchor>.</Text>
      {d.evidence.length ? (
        <DataTable
          rows={d.evidence}
          rowKey={(e: EvidenceTree) => e.stamp}
          minWidth={720}
          columns={[
            { key: 'stamp', header: 'tree', render: (e: EvidenceTree) => <Anchor size="sm" onClick={() => { setStamp(e.stamp); setPath(null); }}><Mono>{e.stamp}</Mono></Anchor> },
            { key: 'loop', header: 'loop', render: (e: EvidenceTree) => <Text size="xs">{e.loop}/{e.step}</Text> },
            { key: 'item', header: 'item', render: (e: EvidenceTree) => <Mono>{e.item ?? '—'}</Mono> },
            { key: 'stage', header: 'stage', render: (e: EvidenceTree) => <Text size="xs">{e.stage} · k={e.k}</Text> },
            { key: 'rollouts', header: 'rollouts', render: (e: EvidenceTree) => <Text size="xs">{e.rollouts.join(', ')}</Text> },
            { key: 'files', header: 'files', num: true, render: (e: EvidenceTree) => <Text size="xs">{e.files}</Text> },
            { key: 'when', header: 'built', render: (e: EvidenceTree) => <Text size="xs" c="dimmed">{when(e.generated_at)}</Text> },
          ]}
        />
      ) : <Text size="sm" c="dimmed">No evidence tree has been built yet.</Text>}
      {stamp ? (
        <Section title={<Mono>{stamp}</Mono>} description="Pick a file; every file was redacted by the hub before it was written.">
          {tree.data ? (
            <Group align="flex-start" gap="md" wrap="nowrap">
              <Stack gap={2} miw={260}>
                {tree.data.files.map((f) => <Anchor key={f} size="xs" onClick={() => setPath(f)} fw={f === path ? 700 : 400}>{f} <Text span c="dimmed">({tree.data!.bytes[f] ?? '?'} B)</Text></Anchor>)}
              </Stack>
              <div className={u.flexFill}>
                {path ? (file.data ? <Code block className={u.preWrap}>{file.data.text}{file.data.truncated ? '\n…(truncated)' : ''}</Code> : <Text size="xs" c="dimmed">{file.isError ? (file.error as Error).message : 'loading…'}</Text>) : <Text size="xs" c="dimmed">no file picked</Text>}
              </div>
            </Group>
          ) : <Text size="xs" c="dimmed">{tree.isError ? (tree.error as Error).message : 'loading…'}</Text>}
        </Section>
      ) : null}
    </>
  );
}

// ---------------------------------------------------------------- library
const CONFIDENCES = ['high', 'medium', 'low'];

function LibraryTab({ d }: { d: RefineDoc }) {
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState<Record<string, string>>({ loop: d.plans[0]?.loop ?? 'repo-scout', step: d.plans[0]?.step ?? 'scout', domain: 'dev-tools', item: '', run_id: '', adopted: 'base1', cue: '', lesson: '', evidence: '', confidence: 'medium' });
  const set = (k: string) => (e: { currentTarget: { value: string } }) => setForm((f) => ({ ...f, [k]: e.currentTarget.value }));
  const submit = async () => {
    try {
      const out = await api<{ path: string; next: string }>('/api/refine/library', { method: 'POST', body: JSON.stringify(form) });
      notifications.show({ title: `Lesson written to ${out.path}`, message: out.next, color: 'teal' });
      setAdding(false);
      void qc.invalidateQueries({ queryKey: ['refine'] });
    } catch (e) {
      notifications.show({ title: 'Refused', message: (e as Error).message, color: 'red' });
    }
  };
  return (
    <>
      <Text size="sm" c="dimmed" mb="sm">The experience library (<Mono>{d.library.root}</Mono>): per adopted refinement a cue (the shape of situation), the lesson (an operation on a harness, naming its component), its evidence and a confidence. Entries land on the working tree and reach main by a reviewed pull request; the context pack puts a domain's newest lessons beside the brief of every local attempt, as data to re-verify.</Text>
      {d.library.problems.length ? <Banner tone="crit" title="The library cannot be read">{d.library.problems.join(' · ')}</Banner> : null}
      {d.library.uncommitted.length ? <Banner tone="warn" title="Uncommitted entries on the working tree">{d.library.uncommitted.join(', ')} — review them, then commit on a branch and open the pull request; nothing here commits.</Banner> : null}
      {d.library.entries.length ? (
        <DataTable
          rows={d.library.entries}
          rowKey={(e: LibraryEntry) => `${e.loop}/${e.domain}/${e.id}`}
          minWidth={900}
          columns={[
            { key: 'date', header: 'date', render: (e: LibraryEntry) => <Text size="xs">{e.date}</Text>, sort: (e: LibraryEntry) => e.date },
            { key: 'loop', header: 'loop / domain', render: (e: LibraryEntry) => <Text size="xs"><Mono>{e.loop}</Mono> · {e.domain}</Text> },
            { key: 'confidence', header: 'confidence', render: (e: LibraryEntry) => <Status tone={e.confidence === 'high' ? 'good' : e.confidence === 'medium' ? 'info' : 'warn'}>{e.confidence}</Status> },
            { key: 'cue', header: 'cue', render: (e: LibraryEntry) => <Text size="sm">{e.cue}</Text> },
            { key: 'lesson', header: 'lesson', render: (e: LibraryEntry) => <Text size="xs">{e.lesson}</Text> },
            { key: 'item', header: 'adopted', render: (e: LibraryEntry) => <Text size="xs" c="dimmed"><Mono>{e.adopted}</Mono> on {e.item} ({e.source}){e.has_diff ? ' · diff' : ''}</Text> },
          ]}
        />
      ) : <Text size="sm" c="dimmed">No lesson recorded yet. The first reflections are written by hand from a run's record (below), the model-backed reflector is P1.</Text>}
      {hasConsole() ? (
        <Section title="Record a lesson" description="The $0 reflector: a person writes what an adopted attempt taught, from its run record. It is validated (schema, field caps) and leak-checked (no local path, host name, address or credential) before anything is written." actions={<Button size="xs" variant="default" leftSection={<IconPlus size={14} />} onClick={() => setAdding((a) => !a)}>{adding ? 'Close' : 'New lesson'}</Button>}>
          {adding ? (
            <Paper p="md">
              <Stack gap="xs">
                <SimpleGrid cols={{ base: 1, md: 3 }} spacing="xs">
                  <Select label="Loop" data={[...new Set(d.plans.map((p) => p.loop))]} value={form.loop} onChange={(v) => setForm((f) => ({ ...f, loop: v ?? f.loop }))} />
                  <TextInput label="Step" value={form.step} onChange={set('step')} />
                  <TextInput label="Domain (registry category)" value={form.domain} onChange={set('domain')} />
                  <TextInput label="Item (owner/repo)" value={form.item} onChange={set('item')} placeholder="bamr87/SCHEMA" />
                  <TextInput label="Run id" value={form.run_id} onChange={set('run_id')} placeholder="20261103T210353Z-repo-scout-scout-f6c613" />
                  <TextInput label="Adopted label" value={form.adopted} onChange={set('adopted')} placeholder="base1 · inv1 · agg1" />
                </SimpleGrid>
                <TextInput label="Cue — the shape of situation this applies to (one line)" value={form.cue} onChange={set('cue')} maxLength={400} />
                <Textarea label="Lesson — the operation on the harness, naming its component" value={form.lesson} onChange={set('lesson')} maxLength={800} autosize minRows={2} />
                <Textarea label="Evidence — the edit rows and the execution contrast it rests on" value={form.evidence} onChange={set('evidence')} maxLength={1200} autosize minRows={2} />
                <Group justify="space-between">
                  <Select label="Confidence" data={CONFIDENCES} value={form.confidence} onChange={(v) => setForm((f) => ({ ...f, confidence: v ?? f.confidence }))} w={180} />
                  <Button size="xs" onClick={() => void submit()} disabled={!form.cue.trim() || !form.lesson.trim() || !form.evidence.trim() || !form.item.trim() || !form.run_id.trim()}>Write to the working tree</Button>
                </Group>
              </Stack>
            </Paper>
          ) : null}
        </Section>
      ) : <LocalOnly what="Recording a lesson" />}
    </>
  );
}
