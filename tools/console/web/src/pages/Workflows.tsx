// The hub's own GitHub Actions as one model (dash-gen workflow_atlas.py):
// the catalog, the composite actions, the standards as checks, why runs fail
// (from the lake), what to retire, and a designer that scaffolds a workflow
// inside the standards. Every row opens its workflow or action.
import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import {
  Anchor, Badge, Button, Checkbox, Code, CopyButton, Group, Paper, SegmentedControl, Select, SimpleGrid, Stack, Tabs, Text,
  TextInput, Textarea,
} from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { IconCheck, IconCopy, IconSearch } from '@tabler/icons-react';
import { hasConsole } from '../api/backend';
import { useDraftLint, useScaffold, useWorkflowHealth, useWorkflows } from '../api/hooks';
import type { Finding, Severity, Tally, WfAction, WfHealthRow, Workflow, WorkflowAtlas, WorkflowHealth } from '../api/types';
import { DataTable } from '../components/DataTable';
import { Markdown } from '../components/Markdown';
import { Banner, Conclusion, Empty, External, Load, LocalOnly, Mono, PageHeader, Section, StatTile, Status, type Tone } from '../components/ui';
import { RunButton } from '../jobs/RunButton';
import { fmt, includesText, when } from '../lib/format';
import { gh, to } from '../lib/links';

export const SEV_TONE: Record<Severity, Tone> = { error: 'crit', warn: 'warn', info: 'info' };
export const CLASS_TONE: Record<string, Tone> = { capacity: 'info', config: 'warn', transient: 'info', dependency: 'warn', defect: 'crit' };
export const GROUP_LABEL: Record<string, string> = {
  loop: 'Loop', gate: 'Gate', fanout: 'Fan-out', reusable: 'Reusable', agent: 'Agent', manual: 'Manual',
};
const TABS = ['catalog', 'actions', 'standards', 'health', 'retire', 'design'] as const;

/** Prose with `code` spans, as the rules and findings are written. */
export function Ticks({ text }: { text: string }) {
  return <>{text.split('`').map((part, i) => (i % 2 ? <Code key={i} fz={12}>{part}</Code> : part))}</>;
}

/** A row's findings: ✓, or the worst severity with its count. */
export function FindingsPill({ t }: { t: Tally }) {
  if (t.error) return <Status tone="crit">{t.error} error{t.error > 1 ? 's' : ''}</Status>;
  if (t.warn) return <Status tone="warn">{t.warn} warning{t.warn > 1 ? 's' : ''}</Status>;
  return <Status tone="good">clean</Status>;
}

export function FindingList({ findings, showTarget = true, draft = false }: { findings: Finding[]; showTarget?: boolean; draft?: boolean }) {
  if (!findings.length) return <Banner tone="good" title="Every rule passes">Nothing to fix here.</Banner>;
  return (
    <DataTable<Finding>
      rows={findings}
      rowKey={(f, i) => `${f.rule}:${f.target}:${i}`}
      dense
      columns={[
        { key: 'sev', header: 'severity', render: (f) => <Status tone={SEV_TONE[f.severity]}>{f.severity}</Status>, sort: (f) => f.severity },
        { key: 'rule', header: 'rule', render: (f) => <Anchor component={Link} to={`${to.workflows('standards')}#rule-${f.rule}`} ff="monospace" fz="sm">{f.rule}</Anchor>, sort: (f) => f.rule },
        ...(showTarget ? [{
          key: 'target', header: 'where', sort: (f: Finding) => f.target,
          render: (f: Finding) => <Anchor component={Link} to={f.kind === 'action' ? to.action(f.target) : to.workflow(f.target)} ff="monospace" fz="sm">{f.target}</Anchor>,
        }] : []),
        { key: 'msg', header: 'finding', render: (f) => <Text size="sm"><Ticks text={f.message} /></Text> },
        { key: 'line', header: 'line', render: (f) => (draft
          ? <Text size="sm" ff="monospace">{f.line ? `L${f.line}` : '—'}</Text>
          : <External href={gh.hubFile(f.file, f.line)} size="sm">{f.line ? `L${f.line}` : 'file'}</External>) },
      ]}
    />
  );
}

/** The triggers of a workflow, compactly. */
export function triggerText(w: Workflow): string {
  const names: Record<string, string> = { workflow_dispatch: 'dispatch', workflow_call: 'call', pull_request: 'PR', issue_comment: 'comment' };
  return w.triggers.map((t) => names[t] ?? t.replace(/_/g, ' ')).join(' · ');
}

function healthByFile(h?: WorkflowHealth): Map<string, WfHealthRow> {
  return new Map((h?.workflows ?? []).map((r) => [r.path, r]));
}

export function Workflows() {
  const atlas = useWorkflows();
  const health = useWorkflowHealth(30);
  const [sp, setSp] = useSearchParams();
  const tab = (TABS as readonly string[]).includes(sp.get('tab') ?? '') ? (sp.get('tab') as string) : 'catalog';
  const setTab = (v: string | null) => {
    const next = new URLSearchParams(sp);
    if (v && v !== 'catalog') next.set('tab', v); else next.delete('tab');
    next.delete('q');
    setSp(next, { replace: true });
  };
  return (
    <>
      <PageHeader
        title="Workflows"
        description={<>The hub's own GitHub Actions read as one model from <Mono>.github/</Mono> by <Mono>workflow_atlas.py</Mono>: what each workflow does, the standards it is held to, why its runs fail, what to retire, and a designer that writes a new one already inside the standards. The same model backs <Mono>tools/dash workflows</Mono> and the <Mono>fleet_workflows</Mono> MCP tool.</>}
        actions={<><RunButton op="workflows-lint">Lint now</RunButton><RunButton op="lake-sync">Sync lake</RunButton></>}
      />
      <Load q={atlas}>
        {(a) => (
          <Tabs value={tab} onChange={setTab} keepMounted={false}>
            <Tabs.List mb="md">
              <Tabs.Tab value="catalog">Catalog <Badge size="xs" variant="light" ml={4}>{a.summary.workflows}</Badge></Tabs.Tab>
              <Tabs.Tab value="actions">Actions <Badge size="xs" variant="light" ml={4}>{a.summary.actions}</Badge></Tabs.Tab>
              <Tabs.Tab value="standards">Standards {a.summary.findings.error + a.summary.findings.warn ? <Badge size="xs" color="red" variant="light" ml={4}>{a.summary.findings.error + a.summary.findings.warn}</Badge> : null}</Tabs.Tab>
              <Tabs.Tab value="health">Run health</Tabs.Tab>
              <Tabs.Tab value="retire">Retire</Tabs.Tab>
              <Tabs.Tab value="design">Design</Tabs.Tab>
            </Tabs.List>
            <Tabs.Panel value="catalog"><Catalog a={a} h={health.data} /></Tabs.Panel>
            <Tabs.Panel value="actions"><Actions a={a} /></Tabs.Panel>
            <Tabs.Panel value="standards"><Standards a={a} /></Tabs.Panel>
            <Tabs.Panel value="health"><Health a={a} h={health.data} /></Tabs.Panel>
            <Tabs.Panel value="retire"><Retire a={a} h={health.data} /></Tabs.Panel>
            <Tabs.Panel value="design"><Design a={a} /></Tabs.Panel>
          </Tabs>
        )}
      </Load>
    </>
  );
}

// --------------------------------------------------------------------------
function Catalog({ a, h }: { a: WorkflowAtlas; h?: WorkflowHealth }) {
  const [sp, setSp] = useSearchParams();
  const q = sp.get('q') ?? '';
  const group = sp.get('group') ?? 'all';
  const flagged = sp.get('flagged') === '1';
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(sp);
    if (v) next.set(k, v); else next.delete(k);
    setSp(next, { replace: true });
  };
  const runs = healthByFile(h);
  const s = a.summary;
  const rows = a.workflows.filter((w) => (group === 'all' || w.group === group)
    && (!flagged || w.findings.error + w.findings.warn > 0)
    && includesText([w.id, w.name, w.purpose_text, w.triggers.join(' '), w.switch], q));
  const t = h?.totals ?? {};
  return (
    <>
      <SimpleGrid cols={{ base: 1, xs: 2, md: 5 }} spacing="md" mb="lg">
        <StatTile label="Workflows" value={s.workflows} sub={`${fmt(s.lines, 0)} lines · ${s.jobs} jobs`} />
        <StatTile label="Composite actions" value={s.actions} sub={`${fmt(s.action_lines, 0)} lines`} href={to.workflows('actions')} />
        <StatTile label="Scheduled" value={s.scheduled} sub={`${s.ai} run Claude (${s.ai_sites} call sites) · ${s.kill_switches} kill switches`} href={to.schedules()} />
        <StatTile label="Findings" value={s.findings.error + s.findings.warn} tone={s.findings.error ? 'crit' : undefined}
          sub={`${s.findings.error} errors · ${s.findings.warn} warnings · ${a.rules.length} rules`} href={to.workflows('standards')} />
        <StatTile label="Runs, last 30 days" value={h?.present ? fmt(t.runs, 0) : '—'}
          sub={h?.present ? `${fmt(t.failure, 0)} failed · ${fmt(t.capacity_skips, 0)} green-but-429` : 'from the local lake'} href={to.workflows('health')} />
      </SimpleGrid>
      <Group gap="sm" mb="sm" wrap="wrap">
        <TextInput data-page-search leftSection={<IconSearch size={15} />} placeholder="Filter name / trigger / switch…  ( / )" value={q} onChange={(e) => set('q', e.currentTarget.value)} w={280} />
        <SegmentedControl size="xs" value={group} onChange={(v) => set('group', v === 'all' ? '' : v)}
          data={[{ label: 'All', value: 'all' }, ...Object.entries(s.groups).map(([g, n]) => ({ label: `${GROUP_LABEL[g] ?? g} ${n}`, value: g }))]} />
        <Checkbox label="With findings" checked={flagged} onChange={(e) => set('flagged', e.currentTarget.checked ? '1' : '')} />
        <Text size="sm" c="dimmed">{rows.length} of {a.workflows.length}</Text>
      </Group>
      <DataTable<Workflow>
        rows={rows}
        rowKey={(w) => w.id}
        href={(w) => to.workflow(w.id)}
        keys
        open={(w) => gh.hubFile(w.file)}
        initialSort={{ key: 'group' }}
        tone={(w) => (w.findings.error ? 'crit' : w.findings.warn ? 'warn' : undefined)}
        columns={[
          { key: 'name', header: 'workflow', sort: (w) => w.id, render: (w) => (
            <Stack gap={0}>
              <Text size="sm" fw={600}>{w.name}</Text>
              <Mono dim>{w.id}.yml</Mono>
            </Stack>
          ) },
          { key: 'group', header: 'group', width: 96, sort: (w) => w.group, render: (w) => <Badge variant="light" size="sm" tt="none">{GROUP_LABEL[w.group] ?? w.group}</Badge> },
          { key: 'when', header: 'runs on', sort: (w) => w.crons[0]?.cron ?? triggerText(w), render: (w) => <Text size="sm" maw={220}>{w.when ?? (w.crons.map((c) => c.human).join(', ') || triggerText(w))}</Text> },
          { key: 'purpose', header: 'purpose', render: (w) => <Text size="sm" lineClamp={2} maw={420}>{w.purpose_text ?? '—'}</Text> },
          { key: 'ai', header: 'Claude', sort: (w) => w.ai_sites.length, render: (w) => (w.ai_sites.length
            ? <Text size="sm">{w.ai_sites.length} site{w.ai_sites.length > 1 ? 's' : ''} · ${w.ai_sites.reduce((n, x) => n + (x.max_budget_usd ?? 0), 0)}</Text>
            : <Text size="sm" c="dimmed">—</Text>) },
          { key: 'switch', header: 'kill switch', sort: (w) => w.switch, render: (w) => (w.switch ? <Mono>{w.switch}</Mono> : <Text size="sm" c="dimmed">—</Text>) },
          { key: 'last', header: 'last run', sort: (w) => runs.get(w.file)?.last?.created_at, render: (w) => {
            const r = runs.get(w.file);
            if (!r?.last) return <Text size="sm" c="dimmed">{h?.present ? 'none in 30d' : '—'}</Text>;
            return (
              <Stack gap={0}>
                <Conclusion value={r.last.conclusion} />
                <Text size="xs" c="dimmed">{r.runs} runs{r.success_rate != null ? ` · ${r.success_rate}%` : ''}</Text>
              </Stack>
            );
          } },
          { key: 'lines', header: 'lines', num: true, sort: (w) => w.lines, render: (w) => <Text size="sm">{w.lines}</Text> },
          { key: 'findings', header: 'standards', sort: (w) => -(w.findings.error * 100 + w.findings.warn), render: (w) => <FindingsPill t={w.findings} /> },
        ]}
      />
    </>
  );
}

// --------------------------------------------------------------------------
function Actions({ a }: { a: WorkflowAtlas }) {
  return (
    <>
      <Text size="sm" c="dimmed" mb="sm" maw={900}>
        Composite actions under <Mono>.github/actions/</Mono>: shared steps, so a fix lands once. An action with no caller is deleted, not kept for later. External actions ride major tags ({a.summary.external_actions.length} in use).
      </Text>
      <DataTable<WfAction>
        rows={a.actions}
        rowKey={(x) => x.id}
        href={(x) => to.action(x.id)}
        keys
        tone={(x) => (x.findings.error ? 'crit' : x.findings.warn ? 'warn' : undefined)}
        columns={[
          { key: 'id', header: 'action', sort: (x) => x.id, render: (x) => <Stack gap={0}><Text size="sm" fw={600}>{x.name}</Text><Mono dim>{x.id}</Mono></Stack> },
          { key: 'desc', header: 'what it does', render: (x) => <Text size="sm" lineClamp={2} maw={480}>{x.description}</Text> },
          { key: 'io', header: 'inputs · outputs', sort: (x) => x.inputs.length, render: (x) => <Text size="sm">{x.inputs.length} · {x.outputs.length}</Text> },
          { key: 'used', header: 'used by', num: true, sort: (x) => x.used_by.length, render: (x) => <Text size="sm" c={x.used_by.length ? undefined : 'var(--critical)'}>{x.used_by.length}</Text> },
          { key: 'lines', header: 'lines', num: true, sort: (x) => x.lines, render: (x) => <Text size="sm">{x.lines}</Text> },
          { key: 'f', header: 'standards', render: (x) => <FindingsPill t={x.findings} /> },
        ]}
      />
      <Section title={`External actions (${a.summary.external_actions.length})`} description="Every third-party action the workflows call, and the refs they ride. Dependabot moves the majors.">
        <Group gap="xs">
          {a.summary.external_actions.map((e) => (
            <Badge key={e.action} variant="outline" tt="none" size="lg" fw={500}>
              {e.action}@{e.versions.join(', ')}
            </Badge>
          ))}
        </Group>
      </Section>
      <Section title="Secrets and variables the workflows read" description="Names only. The token contract lives in _data/fleet.yml; values never leave GitHub secrets or .env.">
        <Group gap={6} mb="xs">{a.summary.secrets.map((x) => <Badge key={x} variant="light" color="grape" tt="none">{x}</Badge>)}</Group>
        <Group gap={6}>{a.summary.vars.map((x) => <Badge key={x} variant="light" color="gray" tt="none">vars.{x}</Badge>)}</Group>
      </Section>
    </>
  );
}

// --------------------------------------------------------------------------
function Standards({ a }: { a: WorkflowAtlas }) {
  const by = useMemo(() => {
    const m = new Map<string, Finding[]>();
    a.findings.forEach((f) => m.set(f.rule, [...(m.get(f.rule) ?? []), f]));
    return m;
  }, [a.findings]);
  const failing = a.rules.filter((r) => by.has(r.id)).length;
  return (
    <>
      {failing
        ? <Banner tone={a.summary.findings.error ? 'crit' : 'warn'} title={`${failing} of ${a.rules.length} rules have findings`}>Each one below says what it costs and how to fix it. <Mono>tools/dash workflows lint</Mono> prints the same list; CI fails on an error.</Banner>
        : <Banner tone="good" title={`All ${a.rules.length} rules pass on every workflow and action`}>The README's <Mono>## Standards</Mono> and AGENTS.md's standing rules, checked. <Mono>test_workflow_atlas.py</Mono> keeps it that way in CI: any error fails the build.</Banner>}
      <Stack gap="sm" mt="md">
        {a.rules.map((r) => {
          const hits = by.get(r.id) ?? [];
          return (
            <Paper key={r.id} p="md" id={`rule-${r.id}`}>
              <Group justify="space-between" align="flex-start" wrap="wrap" gap="xs" mb={4}>
                <Group gap="xs">
                  <Text fw={600}>{r.title}</Text>
                  <Mono dim>{r.id}</Mono>
                  <Status tone={SEV_TONE[r.severity]}>{r.severity}</Status>
                  {r.gate ? <Badge size="sm" variant="outline" tt="none">enforced by {r.gate}</Badge> : <Badge size="sm" variant="outline" color="gray" tt="none">enforced by the atlas</Badge>}
                </Group>
                {hits.length ? <Status tone={SEV_TONE[r.severity]}>{hits.length} finding{hits.length > 1 ? 's' : ''}</Status> : <Status tone="good">passes</Status>}
              </Group>
              <Text size="sm"><b>Why:</b> <Ticks text={r.why} /></Text>
              <Text size="sm" c="dimmed"><b>Fix:</b> <Ticks text={r.fix} /> <External href={gh.hubFile(r.doc.split('#')[0])} size="sm">{r.doc}</External></Text>
              {hits.length ? <Stack mt="sm"><FindingList findings={hits} /></Stack> : null}
            </Paper>
          );
        })}
      </Stack>
    </>
  );
}

// --------------------------------------------------------------------------
function failureRows(h: WorkflowHealth) {
  return h.workflows.flatMap((w) => w.failures.map((f) => ({ ...f, path: w.path }))).sort((x, y) => String(y.created_at).localeCompare(String(x.created_at)));
}

function verdictTone(v: string): Tone {
  return v === 'healthy' ? 'good' : v === 'defect' ? 'crit' : v === 'config' || v === 'dependency' ? 'warn' : 'info';
}

function Health({ a, h }: { a: WorkflowAtlas; h?: WorkflowHealth }) {
  if (!h) return <Empty>Loading run health…</Empty>;
  if (!h.present) {
    return h.snapshot
      ? <LocalOnly what="Run health is read from the local data lake (run logs never leave the operator's machine)" />
      : <Banner tone="info" title="No run data yet">{h.error} <RunButton op="lake-sync">Sync lake</RunButton></Banner>;
  }
  const known = new Set(a.workflows.map((w) => w.file));
  const t = h.totals;
  const fails = failureRows(h);
  return (
    <>
      <Text size="sm" c="dimmed" mb="md" maw={900}>
        {h.nwo} over the last {h.days} days, from the lake (synced {when(h.synced_at)}). Every failed run's error lines are read and classified, so a spent Claude window or a repo setting stops reading like a bug. A green run that logged a 429 counts as a capacity skip.
      </Text>
      <SimpleGrid cols={{ base: 2, sm: 4, xl: 7 }} spacing="md" mb="md">
        <StatTile label="Runs" value={fmt(t.runs, 0)} sub={`${fmt(t.skipped, 0)} skipped · ${fmt(t.cancelled, 0)} cancelled`} />
        <StatTile label="Failed" value={fmt(t.failure, 0)} tone={t.failure ? 'crit' : undefined} />
        {(['capacity', 'config', 'transient', 'dependency', 'defect'] as const).map((c) => (
          <StatTile key={c} label={c} value={h.classes[c] ?? 0} tone={c === 'defect' && h.classes[c] ? 'crit' : undefined} sub={c === 'capacity' ? `+ ${fmt(t.capacity_skips, 0)} green-but-429` : undefined} />
        ))}
      </SimpleGrid>
      <Paper p="md" mb="md">
        <Stack gap={4}>
          {Object.entries(h.class_hints).map(([c, hint]) => (
            <Text key={c} size="sm"><Status tone={CLASS_TONE[c] ?? 'info'}>{c}</Status> <Text span c="dimmed">{hint}</Text></Text>
          ))}
        </Stack>
      </Paper>
      <Section mt={0} title="Per workflow">
        <DataTable<WfHealthRow>
          rows={h.workflows}
          rowKey={(w) => w.path}
          href={(w) => (known.has(w.path) ? to.workflow(w.path.replace(/^.*\//, '').replace(/\.ya?ml$/, '')) : null)}
          tone={(w) => (w.ghost ? 'muted' : w.verdict === 'defect' ? 'crit' : undefined)}
          initialSort={{ key: 'fail', desc: true }}
          columns={[
            { key: 'path', header: 'workflow', sort: (w) => w.path, render: (w) => <Group gap={6}><Mono>{w.path.replace(/^.*\//, '')}</Mono>{w.ghost ? <Status tone="warn" title="Runs exist but the file does not — retire it">ghost</Status> : null}</Group> },
            { key: 'runs', header: 'runs', num: true, sort: (w) => w.runs, render: (w) => <Text size="sm">{w.runs}</Text> },
            { key: 'rate', header: 'success', num: true, sort: (w) => w.success_rate, render: (w) => <Text size="sm">{w.success_rate != null ? `${w.success_rate}%` : '—'}</Text> },
            { key: 'fail', header: 'failed', num: true, sort: (w) => w.failure, render: (w) => <Text size="sm" c={w.failure ? 'var(--critical)' : undefined}>{w.failure}</Text> },
            { key: 'causes', header: 'causes', render: (w) => <Group gap={4}>{Object.entries(w.causes).map(([c, n]) => <Badge key={c} size="sm" variant="light" tt="none">{c} ×{n}</Badge>)}{w.capacity_skips ? <Badge size="sm" variant="light" color="gray" tt="none">429 skipped ×{w.capacity_skips}</Badge> : null}</Group> },
            { key: 'p50', header: 'p50 min', num: true, sort: (w) => w.p50_min, render: (w) => <Text size="sm">{w.p50_min ?? '—'}</Text> },
            { key: 'verdict', header: 'now', sort: (w) => w.verdict, render: (w) => <Status tone={verdictTone(w.verdict)}>{w.verdict}</Status> },
          ]}
        />
      </Section>
      <Section title={`Failures (${fails.length})`} description="Newest first. The evidence is the error line the class was read from.">
        <DataTable
          rows={fails}
          rowKey={(f) => String(f.id)}
          open={(f) => f.html_url}
          empty="No failed runs in the window."
          columns={[
            { key: 'at', header: 'when', sort: (f) => f.created_at, render: (f) => <Text size="xs" c="dimmed">{when(f.created_at)}</Text> },
            { key: 'wf', header: 'workflow', render: (f) => <Mono>{f.path.replace(/^.*\//, '')}</Mono> },
            { key: 'class', header: 'class', sort: (f) => f.class, render: (f) => <Status tone={CLASS_TONE[f.class] ?? 'info'}>{f.class}</Status> },
            { key: 'cause', header: 'cause', render: (f) => <Mono>{f.cause}</Mono> },
            { key: 'ev', header: 'evidence', render: (f) => <Stack gap={0}><Text size="sm" lineClamp={2} maw={520}>{f.evidence || '—'}</Text>{f.failed_step ? <Text size="xs" c="dimmed">{f.failed_step}</Text> : null}</Stack> },
            { key: 'run', header: 'run', render: (f) => <External href={f.html_url} size="sm">#{f.id}</External> },
          ]}
        />
      </Section>
    </>
  );
}

// --------------------------------------------------------------------------
interface Candidate { key: string; what: string; reason: string; lever: string; href?: string; external?: string }

function Retire({ a, h }: { a: WorkflowAtlas; h?: WorkflowHealth }) {
  const runs = healthByFile(h);
  const cands: Candidate[] = [];
  (h?.workflows ?? []).filter((w) => w.ghost).forEach((w) => cands.push({
    key: `ghost:${w.path}`, what: w.path.replace(/^.*\//, ''), reason: `${w.runs} run(s) in ${h?.days}d, but the file is gone`,
    lever: 'GitHub lists a workflow while it has runs: delete them to drop it from the Actions sidebar', external: gh.hubWorkflowRuns(w.path.replace(/^.*\//, '').replace(/\.ya?ml$/, '')),
  }));
  a.workflows.forEach((w) => {
    const r = runs.get(w.file);
    if (h?.present && w.crons.length && r && r.runs && r.skipped === r.runs) {
      cands.push({ key: `skip:${w.id}`, what: `${w.id}.yml`, reason: `every one of its ${r.runs} runs was skipped`, lever: 'A schedule that never runs is a dead loop (git-digs ran 17 times, all skipped): set its switch or retire it', href: to.workflow(w.id) });
    } else if (h?.present && w.crons.length && !r) {
      cands.push({ key: `idle:${w.id}`, what: `${w.id}.yml`, reason: `scheduled, but no run in ${h.days} days`, lever: 'Check its trigger and kill switch, or the lake window', href: to.workflow(w.id) });
    }
  });
  a.findings.filter((f) => f.rule === 'action-unused').forEach((f) => cands.push({
    key: `act:${f.target}`, what: f.target, reason: 'no workflow or action calls it', lever: 'Delete it (.github/actions/README.md: no caller, no action)', href: to.action(f.target),
  }));
  a.readme_orphans.forEach((o) => cands.push({ key: `orphan:${o}`, what: o, reason: 'listed in the workflows README, but the file is gone', lever: 'Remove the row, or record it under ## Retired', external: gh.hubFile('.github/workflows/README.md') }));
  return (
    <>
      <Section mt={0} title={`Candidates (${cands.length})`} description="What the evidence says can go: ghost workflows that still have runs, scheduled workflows that never run or always skip, actions with no caller, README rows for files that no longer exist.">
        {!h?.present ? <Banner tone="info" title="Run-based candidates need the lake">Ghosts and dead schedules are read from the local lake{h?.snapshot ? ', which the published page does not carry' : ''}. The structural candidates below still show.</Banner> : null}
        <DataTable<Candidate>
          rows={cands}
          rowKey={(c) => c.key}
          href={(c) => c.href}
          open={(c) => c.external}
          empty="Nothing to retire: every workflow runs, every action has a caller."
          columns={[
            { key: 'what', header: 'candidate', render: (c) => <Mono>{c.what}</Mono> },
            { key: 'reason', header: 'evidence', render: (c) => <Text size="sm">{c.reason}</Text> },
            { key: 'lever', header: 'what to do', render: (c) => <Text size="sm" c="dimmed">{c.lever}</Text> },
          ]}
        />
      </Section>
      <Section title={`Retired (${a.retired.length})`} description="The README's record of what was removed and why — recover any of them from git history.">
        <DataTable
          rows={a.retired}
          rowKey={(r, i) => `${r.date}:${i}`}
          columns={[
            { key: 'date', header: 'date', render: (r) => <Text size="sm" ff="monospace">{r.date}</Text> },
            { key: 'removed', header: 'removed', render: (r) => <Text size="sm" maw={260}>{r.removed}</Text> },
            { key: 'why', header: 'why', render: (r) => <Markdown source={r.why} /> },
          ]}
        />
      </Section>
    </>
  );
}

// --------------------------------------------------------------------------
function Design({ a }: { a: WorkflowAtlas }) {
  const [kind, setKind] = useState('agent-loop');
  const [id, setId] = useState('');
  const [name, setName] = useState('');
  const [cron, setCron] = useState('');
  const [purpose, setPurpose] = useState('');
  const [draft, setDraft] = useState('');
  const [draftId, setDraftId] = useState('draft');
  const [params] = useDebouncedValue(id ? { kind, id, name, cron, purpose } : null, 300);
  const [draftText] = useDebouncedValue(draft, 400);
  const sc = useScaffold(params);
  const [lintId] = useDebouncedValue(/^[a-z][a-z0-9-]{1,40}$/.test(draftId) ? draftId : 'draft', 300);
  const lint = useDraftLint(draftText || null, lintId);
  if (!hasConsole()) return <LocalOnly what="The designer runs the scaffold and the lint in the console's Python" />;
  const idErr = id && !/^[a-z][a-z0-9-]{1,40}$/.test(id) ? 'lowercase letters, digits and dashes' : null;
  const exists = a.workflows.some((w) => w.id === id);
  return (
    <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="lg">
      <Stack gap="sm">
        <Text size="sm" c="dimmed">A new workflow from a template that passes every rule by construction. The preview is linted against the hub's fleet.yml as it will be after the companion edits; <b>Write</b> creates the file in the working tree and commits nothing.</Text>
        <Select label="Kind" value={kind} onChange={(v) => setKind(v ?? 'agent-loop')} allowDeselect={false}
          data={Object.entries(a.kinds).map(([k, d]) => ({ value: k, label: `${k} — ${d}` }))} />
        <Group grow>
          <TextInput label="File id" placeholder="nightly-audit" value={id} error={idErr ?? (exists ? 'a workflow with this id exists' : null)} onChange={(e) => setId(e.currentTarget.value.trim())} />
          <TextInput label="Name" placeholder="Nightly Audit" value={name} onChange={(e) => setName(e.currentTarget.value)} />
        </Group>
        {kind === 'loop' || kind === 'agent-loop'
          ? <TextInput label="Cron (UTC)" placeholder={sc.data?.cron ?? (kind === 'agent-loop' ? '37 11 * * *' : '7 1 * * *')} description={sc.data?.cron_human ? `${sc.data.cron_human}${cron ? '' : ' — the first free slot'}` : 'blank: the first free :07 / :37 slot'} value={cron} onChange={(e) => setCron(e.currentTarget.value)} />
          : null}
        <Textarea label="Purpose" description="Becomes the header comment and the README row: what it is for, and what breaks without it." autosize minRows={3} value={purpose} onChange={(e) => setPurpose(e.currentTarget.value)} />
        {sc.isError ? <Banner tone="crit" title="Cannot scaffold that">{(sc.error as Error).message}</Banner> : null}
        {sc.data && id ? (
          <>
            {sc.data.findings.length ? <FindingList findings={sc.data.findings} showTarget={false} draft /> : <Banner tone="good" title="Passes every rule">Once the companion edits below are made.</Banner>}
            <Section mt="xs" title="Companion edits" description="The workflow alone is not done; these make the gates agree.">
              <Stack gap={6}>
                {sc.data.companion.map((c) => (
                  <Paper key={c.file + c.where} p="xs">
                    <Text size="sm"><Mono>{c.file}</Mono> <Text span c="dimmed">› {c.where}</Text></Text>
                    <Code block>{c.snippet}</Code>
                    <Text size="xs" c="dimmed">{c.why}</Text>
                  </Paper>
                ))}
              </Stack>
            </Section>
            <Group>
              <RunButton op="workflow-new" params={{ kind, id, name, cron, purpose }} variant="filled" disabled={Boolean(idErr || exists || sc.data.exists)}>Write {sc.data.file}</RunButton>
              <CopyButton value={sc.data.text}>
                {({ copied, copy }) => <Button size="xs" variant="default" leftSection={copied ? <IconCheck size={14} /> : <IconCopy size={14} />} onClick={copy}>{copied ? 'Copied' : 'Copy YAML'}</Button>}
              </CopyButton>
              <Button size="xs" variant="subtle" onClick={() => { setDraft(sc.data!.text); setDraftId(id); }}>Edit in the linter →</Button>
            </Group>
          </>
        ) : null}
      </Stack>
      <Stack gap="sm">
        {sc.data && id ? <Code block mah={520} style={{ overflow: 'auto' }}>{sc.data.text}</Code> : null}
        <Section mt={sc.data && id ? 'md' : 0} title="Lint a draft" description="Paste or edit any workflow; it is checked against the same rules as the tree and the hub's fleet.yml as it is now, so a new workflow's cron-declared and ai-budget findings clear once its companion edits land.">
          <TextInput label="As file" description=".github/workflows/<id>.yml — its fleet.yml schedule key and call sites" w={280} mb="xs" value={draftId} onChange={(e) => setDraftId(e.currentTarget.value.trim())} />
          <Textarea autosize minRows={10} maxRows={30} ff="monospace" fz={12.5} placeholder={'name: …\non:\n  schedule:\n    - cron: …'} value={draft} onChange={(e) => setDraft(e.currentTarget.value)} />
          {lint.isError ? <Banner tone="crit" title="Could not lint">{(lint.error as Error).message}</Banner> : null}
          {draft.trim() && lint.data ? (
            <Stack gap="xs" mt="sm">
              <Text size="sm" c="dimmed">{lint.data.workflow.name} · {triggerText(lint.data.workflow) || 'no triggers'} · {lint.data.workflow.jobs.length} job(s) · {lint.data.workflow.ai_sites.length} Claude site(s)</Text>
              <FindingList findings={lint.data.findings} showTarget={false} draft />
            </Stack>
          ) : null}
        </Section>
      </Stack>
    </SimpleGrid>
  );
}

