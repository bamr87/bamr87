// The console's allowlist (core.OPS): every operation it will run, grouped,
// each with its own page — description, parameters, the loops it belongs to,
// and the jobs it has run. Nothing outside this list can be run from here.
import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router';
import { Anchor, Badge, Group, Paper, SimpleGrid, Stack, Text, TextInput, Title } from '@mantine/core';
import { IconSearch } from '@tabler/icons-react';
import { useJobs, useOps, useStateDoc } from '../api/hooks';
import type { Op } from '../api/types';
import { DataTable } from '../components/DataTable';
import { Banner, Load, Mono, PageHeader, Section } from '../components/ui';
import { JobStatus } from '../jobs/JobStatus';
import { OpForm } from '../jobs/OpForm';
import { includesText, when } from '../lib/format';
import { to } from '../lib/links';

const GROUPS: [string, string][] = [
  ['observe', 'Observe — read the fleet, refresh signals'],
  ['plan', 'Plan — build queues and briefs'],
  ['verify', 'Verify — gates and tests'],
  ['lake', 'Lake — the local data lake and traces'],
  ['content', 'Content — the content atlas'],
  ['deploy', 'Deploy — writes to GitHub with apply'],
];

function OpCard({ o }: { o: Op }) {
  return (
    <Paper p="sm" component={Link} to={to.op(o.id)} style={{ textDecoration: 'none', color: 'inherit' }}>
      <Stack gap={4}>
        <Group justify="space-between" gap={6} wrap="nowrap" align="flex-start">
          <Text size="sm" fw={600}>{o.title}</Text>
          {o.remote_write ? <Badge size="xs" color="yellow" variant="light">can write</Badge> : null}
        </Group>
        <Text size="xs" c="dimmed" lineClamp={2}>{o.desc}</Text>
        <Group gap={6}>
          <Mono dim>{o.id}</Mono>
          {o.needs_token ? <Text size="xs" c="dimmed">· needs gh auth</Text> : null}
          {o.params.length ? <Text size="xs" c="dimmed">· {o.params.join(', ')}</Text> : null}
        </Group>
      </Stack>
    </Paper>
  );
}

export function Operations() {
  const ops = useOps();
  const [q, setQ] = useState('');
  return (
    <>
      <PageHeader
        title="Operations"
        description="The allowlist. Parameters are validated by the server and become argv elements, never a shell string; anything that writes to GitHub needs an explicit confirm, and only one such job runs at a time. Press : anywhere to run one from the palette."
      />
      <TextInput data-page-search leftSection={<IconSearch size={15} />} placeholder="Filter operations…  ( / )" value={q} onChange={(e) => setQ(e.currentTarget.value)} w={320} mb="md" />
      <Load q={ops}>
        {(list) => (
          <>
            {GROUPS.map(([g, label]) => {
              const items = list.filter((o) => o.group === g && includesText([o.id, o.title, o.desc], q));
              if (!items.length) return null;
              return (
                <Section key={g} title={label} mt="lg">
                  <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="sm">{items.map((o) => <OpCard key={o.id} o={o} />)}</SimpleGrid>
                </Section>
              );
            })}
          </>
        )}
      </Load>
    </>
  );
}

export function OperationPage() {
  const { id = '' } = useParams();
  const [sp] = useSearchParams();
  const navigate = useNavigate();
  const ops = useOps();
  const jobs = useJobs();
  const state = useStateDoc();
  const preset = useMemo(() => {
    try {
      return JSON.parse(sp.get('params') ?? '{}') as Record<string, unknown>;
    } catch {
      return {};
    }
  }, [sp]);
  return (
    <Load q={ops}>
      {(list) => {
        const o = list.find((x) => x.id === id);
        if (!o) return <Banner tone="warn" title="Not on the allowlist">No operation named {id}. <Anchor component={Link} to={to.ops()}>All operations</Anchor></Banner>;
        const loops = (state.data?.loops ?? []).filter((l) => l.local_ops.includes(o.id));
        const mine = (jobs.data ?? []).filter((j) => j.op === o.id).reverse();
        return (
          <>
            <PageHeader
              crumbs={[{ label: 'Operations', to: to.ops() }, { label: o.title }]}
              title={o.title}
              badges={<><Badge variant="default">{o.group}</Badge>{o.remote_write ? <Badge color="yellow" variant="light">writes to GitHub with apply</Badge> : null}{o.needs_token ? <Badge variant="light">needs gh auth</Badge> : null}</>}
              description={o.desc}
            />
            <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="lg">
              <Paper p="md">
                <Title order={4} fz={14} mb="sm">Run</Title>
                <OpForm op={o} preset={preset} onStarted={(jid) => navigate(to.job(jid))} />
              </Paper>
              <Stack gap="md">
                <Paper p="md">
                  <Title order={4} fz={14} mb={6}>Part of</Title>
                  {loops.length ? loops.map((l) => <div key={l.id}><Anchor component={Link} to={to.loop(l.id)} size="sm">{l.title}</Anchor></div>) : <Text size="sm" c="dimmed">No loop lists this as its local half.</Text>}
                  <Text size="xs" c="dimmed" mt="sm">id <Mono>{o.id}</Mono></Text>
                </Paper>
              </Stack>
            </SimpleGrid>
            <Section title={`Jobs of this operation (${mine.length})`}>
              <DataTable
                rows={mine}
                rowKey={(j) => j.id}
                href={(j) => to.job(j.id)}
                empty="none in this console session"
                columns={[
                  { key: 's', header: 'status', render: (j) => <JobStatus status={j.status} /> },
                  { key: 'p', header: 'params', render: (j) => <Mono dim>{JSON.stringify(j.params ?? {})}</Mono> },
                  { key: 't', header: 'started', render: (j) => <Text size="xs" c="dimmed">{when(j.started)}</Text> },
                  { key: 'e', header: 'exit', num: true, render: (j) => j.exit_code ?? '' },
                ]}
              />
            </Section>
          </>
        );
      }}
    </Load>
  );
}
