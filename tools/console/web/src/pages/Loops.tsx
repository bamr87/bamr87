// The control plane's loops: cadence from fleet.yml `schedule:`, liveness from
// the age of each loop's committed outputs. A loop's page runs its local half
// (the same tools/ entrypoint CI runs) or dispatches it in CI.
import { Link, useParams } from 'react-router';
import { Anchor, Group, Paper, SimpleGrid, Stack, Text } from '@mantine/core';
import { useJobs, useOps, useStateDoc } from '../api/hooks';
import type { Loop, StateDoc } from '../api/types';
import { DataTable } from '../components/DataTable';
import { Banner, External, Load, Mono, PageHeader, Section, Status, type Tone } from '../components/ui';
import { JobStatus } from '../jobs/JobStatus';
import { RunButton } from '../jobs/RunButton';
import { age, when } from '../lib/format';
import { SOURCE_HOME, gh, to } from '../lib/links';

const DISPATCH_INPUTS: Record<string, Record<string, unknown>> = {
  'harness-fanout': { target: 'gaps', dry_run: true }, 'fleet-pulse': { dry_run: true }, 'repo-evolution': { target: 'all', dry_run: true },
  'standardize-fanout': { target: 'all', dry_run: true }, 'schema-fanout': { target: 'all', dry_run: true },
};

function freshness(l: Loop): { tone: Tone; text: string } {
  if (!l.outputs.length) return { tone: 'info', text: 'no committed output' };
  if (l.missing_outputs.length) return { tone: 'crit', text: `missing: ${l.missing_outputs.join(', ')}` };
  if (l.stalest_output_days == null) return { tone: 'info', text: 'no stamp' };
  return l.stalest_output_days > 3 ? { tone: 'warn', text: `stalest output ${age(l.stalest_output_days)}` } : { tone: 'good', text: `outputs ${age(l.stalest_output_days)} old` };
}

export function Loops() {
  const state = useStateDoc();
  return (
    <>
      <PageHeader title="Loops" description="Every reconciliation loop the hub runs. Each card opens the loop: its schedule, outputs, the operations that are its local half, and a dispatch for its CI half." />
      <Load q={state}>
        {(s) => (
          <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }} spacing="md">
            {s.loops.map((l) => {
              const f = freshness(l);
              return (
                <Paper key={l.id} p="md" component={Link} to={to.loop(l.id)} style={{ textDecoration: 'none', color: 'inherit' }}>
                  <Stack gap={6}>
                    <Group justify="space-between" align="flex-start" wrap="nowrap" gap="xs">
                      <Text fw={600}>{l.title}</Text>
                      <Status tone={f.tone}>{f.text}</Status>
                    </Group>
                    <Text size="sm" c="dimmed"><Mono>{l.workflow}.yml</Mono> · {l.cron_human}</Text>
                    <Text size="xs" c="dimmed">{l.local_ops.length} local operation(s) · {l.outputs.length} committed output(s)</Text>
                  </Stack>
                </Paper>
              );
            })}
          </SimpleGrid>
        )}
      </Load>
    </>
  );
}

function LoopBody({ l, s }: { l: Loop; s: StateDoc }) {
  const ops = useOps();
  const jobs = useJobs();
  const byId = new Map((ops.data ?? []).map((o) => [o.id, o]));
  const f = freshness(l);
  const mine = (jobs.data ?? []).filter((j) => l.local_ops.includes(j.op) || (j.op === 'dispatch' && j.argv.join(' ').includes(`${l.workflow}.yml`)));
  return (
    <>
      <PageHeader
        crumbs={[{ label: 'Loops', to: to.loops() }, { label: l.title }]}
        title={l.title}
        badges={<Status tone={f.tone}>{f.text}</Status>}
        description={<><Mono>{l.workflow}.yml</Mono> · {l.cron_human}{l.cron ? <> · <Mono>{l.cron}</Mono></> : null}</>}
        actions={
          <>
            <External href={gh.hubFile(l.doc)} size="sm">{l.doc}</External>
            <External href={gh.hubWorkflowRuns(l.workflow)} size="sm">runs on GitHub</External>
            <RunButton op="dispatch" params={{ workflow: l.workflow, fields: DISPATCH_INPUTS[l.workflow] ?? {} }} variant="filled">
              Dispatch in CI{DISPATCH_INPUTS[l.workflow] ? ' (dry run)' : ''}
            </RunButton>
          </>
        }
      />
      <Section mt={0} title="Local half" description="The same tools/ entrypoints the workflow runs, run here as jobs. Each operation's page has its parameters.">
        {l.local_ops.length ? (
          <Stack gap="xs">
            {l.local_ops.filter((o) => byId.has(o)).map((o) => {
              const op = byId.get(o)!;
              return (
                <Paper key={o} p="sm">
                  <Group justify="space-between" wrap="wrap" gap="xs">
                    <div>
                      <Anchor component={Link} to={to.op(o)} fw={600} size="sm">{op.title}</Anchor>
                      <Text size="xs" c="dimmed">{op.desc}</Text>
                    </div>
                    <RunButton op={o}>Run</RunButton>
                  </Group>
                </Paper>
              );
            })}
          </Stack>
        ) : <Text size="sm" c="dimmed">This loop runs only in CI.</Text>}
      </Section>
      <Section title="Committed outputs">
        {l.outputs.length ? (
          <DataTable
            rows={l.outputs.map((o) => ({ name: o, meta: s.sources[o] }))}
            rowKey={(r) => r.name}
            href={(r) => SOURCE_HOME[r.name]?.page}
            columns={[
              { key: 'name', header: 'source', render: (r) => <Mono>_data/{r.name}.yml</Mono> },
              { key: 'state', header: 'freshness', render: (r) => (r.meta?.present ? <Status tone={(r.meta.age_days ?? 0) > 3 ? 'warn' : 'good'}>{age(r.meta.age_days)} old</Status> : <Status tone="crit">missing</Status>) },
              { key: 'stamp', header: 'generated', render: (r) => <Text size="xs" c="dimmed">{r.meta?.generated_at ?? '—'}</Text> },
              { key: 'page', header: 'rendered on', render: (r) => <Text size="sm">{SOURCE_HOME[r.name]?.label ?? '—'}</Text> },
            ]}
          />
        ) : <Text size="sm" c="dimmed">This loop writes no committed data the console reads.</Text>}
      </Section>
      <Section title="Jobs for this loop (this console session)">
        <DataTable
          rows={mine}
          rowKey={(j) => j.id}
          href={(j) => to.job(j.id)}
          empty="none yet"
          columns={[
            { key: 'status', header: 'status', render: (j) => <JobStatus status={j.status} /> },
            { key: 'title', header: 'operation', render: (j) => <Text size="sm">{j.title}</Text> },
            { key: 'started', header: 'started', render: (j) => <Text size="xs" c="dimmed">{when(j.started)}</Text> },
          ]}
        />
      </Section>
    </>
  );
}

export function LoopPage() {
  const { id = '' } = useParams();
  const state = useStateDoc();
  return (
    <Load q={state}>
      {(s) => {
        const l = s.loops.find((x) => x.id === id);
        return l ? <LoopBody l={l} s={s} /> : <Banner tone="warn" title="No such loop">There is no loop with id {id}. <Anchor component={Link} to={to.loops()}>All loops</Anchor></Banner>;
      }}
    </Load>
  );
}
