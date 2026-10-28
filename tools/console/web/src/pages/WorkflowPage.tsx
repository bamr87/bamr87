// One workflow, or one composite action, from the atlas: what it is for,
// when it runs, its jobs and the actions it stands on, its Claude call sites,
// the standards it misses, and — from the lake — why its runs failed. A
// dispatchable workflow carries a form typed from its own declared inputs.
import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router';
import { Anchor, Badge, Group, Paper, SimpleGrid, Stack, Text } from '@mantine/core';
import { useWorkflowHealth, useWorkflows } from '../api/hooks';
import type { WfAction, Workflow, WorkflowAtlas } from '../api/types';
import { DataTable } from '../components/DataTable';
import { Markdown } from '../components/Markdown';
import { Banner, Conclusion, Empty, External, Load, Mono, PageHeader, Section, StatTile, Status } from '../components/ui';
import { DispatchInputs, type Fields, dispatchFields, inputDefaults } from '../jobs/DispatchInputs';
import { RunButton } from '../jobs/RunButton';
import { when } from '../lib/format';
import { gh, to } from '../lib/links';
import { CLASS_TONE, FindingList, FindingsPill, GROUP_LABEL, triggerText } from './Workflows';

function DispatchPanel({ w }: { w: Workflow }) {
  const [values, setValues] = useState<Fields>(() => inputDefaults(w.dispatch_inputs));
  useEffect(() => setValues(inputDefaults(w.dispatch_inputs)), [w.id]);
  if (!w.triggers.includes('workflow_dispatch')) return null;
  return (
    <Section title="Dispatch" description={w.dispatchable
      ? 'Runs it in CI with these inputs (gh workflow run). The form is built from the file, so it cannot drift from what the workflow accepts; the console asks before anything reaches GitHub.'
      : 'This workflow can be dispatched on GitHub, but it is not on the console\'s dispatch allowlist (DISPATCH_WORKFLOWS in tools/console/core.py).'}>
      <Paper p="md">
        <DispatchInputs inputs={w.dispatch_inputs} values={values} onChange={setValues} />
        <Group mt="md">
          {w.dispatchable
            ? <RunButton op="dispatch" params={{ workflow: w.id, fields: dispatchFields(values) }} variant="filled">Dispatch {w.id}.yml</RunButton>
            : <External href={gh.hubWorkflowRuns(w.id)} size="sm">Run it from GitHub</External>}
        </Group>
      </Paper>
    </Section>
  );
}

function RunsPanel({ w }: { w: Workflow }) {
  const health = useWorkflowHealth(30);
  const h = health.data;
  if (!h) return null;
  if (!h.present) return <Section title="Runs"><Text size="sm" c="dimmed">{h.snapshot ? 'Run health comes from the local lake and is not part of the published page.' : h.error}</Text></Section>;
  const r = h.workflows.find((x) => x.path === w.file);
  if (!r) return <Section title="Runs"><Empty>No run in the last {h.days} days.</Empty></Section>;
  return (
    <Section title={`Runs, last ${h.days} days`} description="From the lake. Each failure is classified from its error lines.">
      <SimpleGrid cols={{ base: 2, md: 5 }} spacing="md" mb="sm">
        <StatTile label="Runs" value={r.runs} sub={Object.entries(r.events).map(([e, n]) => `${e} ${n}`).join(' · ')} />
        <StatTile label="Success rate" value={r.success_rate != null ? `${r.success_rate}%` : '—'} sub={`${r.success} ok · ${r.failure} failed · ${r.skipped} skipped`} />
        <StatTile label="Last run" value={<Conclusion value={r.last?.conclusion} />} sub={when(r.last?.created_at)} />
        <StatTile label="p50 duration" value={r.p50_min != null ? `${r.p50_min} min` : '—'} />
        <StatTile label="429s absorbed" value={r.capacity_skips} sub="green runs that hit the usage window" />
      </SimpleGrid>
      <DataTable
        rows={r.failures}
        rowKey={(f) => String(f.id)}
        open={(f) => f.html_url}
        empty="No failures in the window."
        columns={[
          { key: 'at', header: 'when', render: (f) => <Text size="xs" c="dimmed">{when(f.created_at)}</Text> },
          { key: 'class', header: 'class', render: (f) => <Status tone={CLASS_TONE[f.class] ?? 'info'} title={f.hint}>{f.class}</Status> },
          { key: 'cause', header: 'cause', render: (f) => <Mono>{f.cause}</Mono> },
          { key: 'ev', header: 'evidence', render: (f) => <Stack gap={0}><Text size="sm">{f.evidence || '—'}</Text>{f.failed_step ? <Text size="xs" c="dimmed">{f.failed_step}</Text> : null}</Stack> },
          { key: 'run', header: 'run', render: (f) => <External href={f.html_url} size="sm">#{f.id}</External> },
        ]}
      />
    </Section>
  );
}

function perms(p: Workflow['permissions']): string {
  if (p == null) return '—';
  if (typeof p === 'string') return p;
  return Object.entries(p).map(([k, v]) => `${k}: ${v}`).join(', ') || '{}';
}

function WorkflowBody({ w, a }: { w: Workflow; a: WorkflowAtlas }) {
  const findings = a.findings.filter((f) => f.kind === 'workflow' && f.target === w.id);
  const callers = a.workflows.filter((x) => x.uses.some((r) => r.kind === 'workflow' && r.target === w.id));
  const actions = new Map(a.actions.map((x) => [x.id, x]));
  return (
    <>
      <PageHeader
        crumbs={[{ label: 'Workflows', to: to.workflows() }, { label: w.name }]}
        title={w.name}
        badges={<><Badge variant="light" tt="none">{GROUP_LABEL[w.group] ?? w.group}</Badge><FindingsPill t={w.findings} />{w.switch ? <Badge variant="outline" tt="none">switch vars.{w.switch}</Badge> : null}</>}
        description={w.purpose ? <Markdown source={w.purpose} /> : w.purpose_text}
        actions={
          <>
            <External href={gh.hubFile(w.file)} size="sm">{w.file}</External>
            <External href={gh.hubWorkflowRuns(w.id)} size="sm">runs on GitHub</External>
            {w.loop ? <Anchor component={Link} to={to.loop(w.loop)} size="sm">its loop</Anchor> : null}
          </>
        }
      />
      {w.parse_error ? <Banner tone="crit" title="The file does not parse">{w.parse_error}</Banner> : null}
      <SimpleGrid cols={{ base: 2, md: 5 }} spacing="md">
        <StatTile label="Runs on" value={<Text fz={15} fw={600}>{w.crons.map((c) => c.human).join(', ') || triggerText(w)}</Text>} sub={w.when ?? triggerText(w)} />
        <StatTile label="Jobs" value={w.jobs.length} sub={`${w.lines} lines`} />
        <StatTile label="Claude call sites" value={w.ai_sites.length} sub={w.ai_sites.map((s) => `$${s.max_budget_usd ?? '?'} cap`).join(' · ') || 'none'} />
        <StatTile label="Concurrency" value={<Text fz={15} fw={600}>{w.concurrency ? 'serialized' : 'none'}</Text>} sub={w.concurrency ? <Mono>{w.concurrency.group}</Mono> : 'runs may overlap'} />
        <StatTile label="Token" value={<Text fz={15} fw={600}>{w.permissions == null ? 'inherited' : 'declared'}</Text>} sub={perms(w.permissions)} />
      </SimpleGrid>

      {findings.length ? <Section title="Standards"><FindingList findings={findings} showTarget={false} /></Section> : null}
      <RunsPanel w={w} />
      <DispatchPanel w={w} />

      <Section title="Triggers">
        <Stack gap="xs">
          {w.crons.map((c) => (
            <Paper key={c.cron} p="sm">
              <Group gap="sm" wrap="wrap">
                <Mono>{c.cron}</Mono><Text size="sm">{c.human}</Text>
                {c.schedule_key ? <Anchor component={Link} to={to.config('schedule')} size="sm">fleet.yml schedule.{c.schedule_key}</Anchor> : <Status tone="crit">not in fleet.yml</Status>}
                {c.on_hour ? <Status tone="crit">on the hour</Status> : null}
              </Group>
            </Paper>
          ))}
          {w.events.map((e) => (
            <Paper key={e.name} p="sm">
              <Group gap="sm" wrap="wrap" align="flex-start">
                <Badge variant="light" tt="none">{e.name}</Badge>
                {e.branches ? <Text size="sm">branches {e.branches.join(', ')}</Text> : null}
                {e.types ? <Text size="sm">types {e.types.join(', ')}</Text> : null}
                {e.paths ? <Text size="xs" c="dimmed" ff="monospace" maw={720}>{e.paths.join('  ')}</Text> : null}
              </Group>
            </Paper>
          ))}
          {w.call_inputs.length ? <Text size="sm">Called with inputs: {w.call_inputs.map((i) => <Mono key={i.name}>{i.name} </Mono>)}{w.call_secrets.length ? <> · secrets {w.call_secrets.join(', ')}</> : null}</Text> : null}
          {callers.length ? <Text size="sm">Called by {callers.map((c) => <Anchor key={c.id} component={Link} to={to.workflow(c.id)} mr={6}>{c.id}</Anchor>)}</Text> : null}
        </Stack>
      </Section>

      <Section title={`Jobs (${w.jobs.length})`}>
        <DataTable
          rows={w.jobs}
          rowKey={(j) => j.id}
          open={(j) => gh.hubFile(w.file, j.line)}
          columns={[
            { key: 'id', header: 'job', render: (j) => <Stack gap={0}><Mono>{j.id}</Mono><Text size="xs" c="dimmed">{j.name}</Text></Stack> },
            { key: 'needs', header: 'needs', render: (j) => <Text size="sm">{j.needs.join(', ') || '—'}</Text> },
            { key: 'runs', header: 'runs', render: (j) => (j.uses ? <Mono>{j.uses}</Mono> : <Text size="sm">{j.runs_on ?? '—'} · {j.steps} steps{j.matrix ? ' · matrix' : ''}</Text>) },
            { key: 'timeout', header: 'timeout', num: true, render: (j) => <Text size="sm" c={j.timeout == null && !j.uses ? 'var(--critical)' : undefined}>{j.timeout ?? (j.uses ? '—' : 'none')}</Text> },
            { key: 'perms', header: 'permissions', render: (j) => <Text size="xs" c="dimmed" maw={280}>{perms(j.permissions)}</Text> },
            { key: 'if', header: 'if', render: (j) => <Text size="xs" ff="monospace" c="dimmed" lineClamp={2} maw={360}>{j.if ?? ''}</Text> },
          ]}
        />
      </Section>

      {w.ai_sites.length ? (
        <Section title="Claude call sites" description="Each cap must equal its budget.call_sites entry; a scheduled site pairs continue-on-error with usage-limit: skip, so a spent window is a warning, not a red run.">
          <DataTable
            rows={w.ai_sites}
            rowKey={(s) => s.site}
            columns={[
              { key: 'site', header: 'site', render: (s) => <Stack gap={0}><Mono>{s.site}</Mono><Text size="xs" c="dimmed">{s.step} · {s.kind}</Text></Stack> },
              { key: 'model', header: 'model', render: (s) => <Text size="sm">{s.model ?? '—'}</Text> },
              { key: 'turns', header: 'max turns', num: true, render: (s) => <Text size="sm">{s.max_turns ?? '—'}</Text> },
              { key: 'cap', header: 'cap', render: (s) => <Text size="sm">${s.max_budget_usd ?? '?'} {s.declared_usd != null && s.declared_usd !== s.max_budget_usd ? <Status tone="crit">fleet.yml ${s.declared_usd}</Status> : null}</Text> },
              { key: 'limit', header: 'on a 429', render: (s) => (s.continue_on_error === 'expression' ? <Status tone="info">decided at run time</Status>
                : s.usage_limit === 'skip' && s.continue_on_error ? <Status tone="good">warning, green run</Status>
                  : <Status tone={w.crons.length ? 'crit' : 'info'}>{s.cost_step ? 'fails the job' : 'no cost step'}</Status>) },
            ]}
          />
        </Section>
      ) : null}

      <Section title="Stands on">
        <Stack gap={6}>
          {w.uses.map((r) => (
            <Group key={r.ref} gap="sm" wrap="nowrap">
              <Badge size="sm" variant="light" color={r.kind === 'external' ? 'gray' : undefined} w={84}>{r.kind}</Badge>
              {r.kind === 'action' && actions.has(r.target) ? <Anchor component={Link} to={to.action(r.target)} ff="monospace" fz="sm">{r.target}</Anchor>
                : r.kind === 'workflow' ? <Anchor component={Link} to={to.workflow(r.target)} ff="monospace" fz="sm">{r.ref}</Anchor>
                  : <Mono>{r.ref}</Mono>}
              <Text size="xs" c="dimmed">in {r.jobs.join(', ')}</Text>
            </Group>
          ))}
          {w.publishes.length ? <Text size="sm" mt={4}>Publishes {w.publishes.map((p) => <Mono key={p}>{p} </Mono>)} through publish-data.</Text> : null}
        </Stack>
      </Section>

      <Section title="Secrets and variables">
        <Group gap={6}>
          {w.secrets.map((x) => <Badge key={x} variant="light" color="grape" tt="none">secrets.{x}</Badge>)}
          {w.vars.map((x) => <Badge key={x} variant="light" color="gray" tt="none">vars.{x}</Badge>)}
          {!w.secrets.length && !w.vars.length ? <Text size="sm" c="dimmed">None beyond the job token.</Text> : null}
        </Group>
      </Section>

      {w.header ? (
        <Section title="From the file" description="The header comment — the workflow's own account of why it is the way it is.">
          <Paper p="md"><Text size="sm" ff="monospace" style={{ whiteSpace: 'pre-wrap' }}>{w.header}</Text></Paper>
        </Section>
      ) : null}
    </>
  );
}

function ActionBody({ x, a }: { x: WfAction; a: WorkflowAtlas }) {
  const findings = a.findings.filter((f) => f.kind === 'action' && f.target === x.id);
  return (
    <>
      <PageHeader
        crumbs={[{ label: 'Workflows', to: to.workflows() }, { label: 'Actions', to: to.workflows('actions') }, { label: x.id }]}
        title={x.name ?? x.id}
        badges={<><Badge variant="light">{x.using ?? 'action'}</Badge><FindingsPill t={x.findings} /></>}
        actions={<External href={gh.hubFile(x.file)} size="sm">{x.file}</External>}
      />
      <Paper p="md"><Markdown source={x.description} /></Paper>
      {findings.length ? <Section title="Standards"><FindingList findings={findings} showTarget={false} /></Section> : null}
      <Section title={`Used by (${x.used_by.length})`}>
        <Group gap="xs">
          {x.used_by.map((u) => (u.startsWith('action:')
            ? <Anchor key={u} component={Link} to={to.action(u.slice(7))} ff="monospace" fz="sm">{u}</Anchor>
            : <Anchor key={u} component={Link} to={to.workflow(u)} ff="monospace" fz="sm">{u}.yml</Anchor>))}
          {!x.used_by.length ? <Status tone="warn">no caller — delete it</Status> : null}
        </Group>
      </Section>
      <Section title={`Inputs (${x.inputs.length})`}>
        <DataTable
          rows={x.inputs}
          rowKey={(i) => i.name}
          empty="No inputs."
          columns={[
            { key: 'name', header: 'input', render: (i) => <Mono>{i.name}</Mono> },
            { key: 'req', header: 'required', render: (i) => (i.required ? <Status tone="warn">required</Status> : <Text size="sm" c="dimmed">optional</Text>) },
            { key: 'def', header: 'default', render: (i) => <Mono dim>{i.default == null ? '' : String(i.default)}</Mono> },
            { key: 'desc', header: 'description', render: (i) => <Text size="sm" maw={560}>{i.description}</Text> },
          ]}
        />
      </Section>
      <Section title="Outputs and steps">
        <Text size="sm">{x.outputs.length ? x.outputs.map((o) => <Mono key={o}>{o} </Mono>) : 'No outputs.'} · {x.steps} step(s) · {x.lines} lines</Text>
        {x.uses.length ? <Text size="sm" mt={4}>Calls {x.uses.map((u) => <Mono key={u}>{u} </Mono>)}</Text> : null}
      </Section>
    </>
  );
}

export function WorkflowPage() {
  const { id = '' } = useParams();
  const atlas = useWorkflows();
  return (
    <Load q={atlas}>
      {(a) => {
        const w = a.workflows.find((x) => x.id === id);
        return w ? <WorkflowBody w={w} a={a} /> : <Banner tone="warn" title="No such workflow">There is no <Mono>{id}.yml</Mono> in .github/workflows. <Anchor component={Link} to={to.workflows('retire')}>Retired workflows</Anchor></Banner>;
      }}
    </Load>
  );
}

export function ActionPage() {
  const params = useParams();
  const id = params['*'] ?? '';
  const atlas = useWorkflows();
  return (
    <Load q={atlas}>
      {(a) => {
        const x = a.actions.find((y) => y.id === id);
        return x ? <ActionBody x={x} a={a} /> : <Banner tone="warn" title="No such action">There is no <Mono>.github/actions/{id}</Mono>. <Anchor component={Link} to={to.workflows('actions')}>All actions</Anchor></Banner>;
      }}
    </Load>
  );
}
