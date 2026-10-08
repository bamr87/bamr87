// The local stack's LOG plane (Kibana over Elasticsearch) and its metrics
// (Grafana over the same indices). Both are opt-in behind the `elk` compose
// profile, so "not running" is the ordinary state and renders as an
// invitation to start it — never as an error.
import { Link } from 'react-router';
import { Anchor, Checkbox, Code, Group, NumberInput, Paper, SimpleGrid, Stack, Text, TextInput } from '@mantine/core';
import { useState } from 'react';
import { useObservability } from '../api/hooks';
import type { Dict } from '../api/types';
import { DataTable } from '../components/DataTable';
import { Banner, External, Load, Mono, PageHeader, Section, StatTile, Status } from '../components/ui';
import { RunButton } from '../jobs/RunButton';
import { fmt } from '../lib/format';
import { to } from '../lib/links';

type Row = Dict<any>;

function PlaneOff({ label, why }: { label: string; why: string }) {
  return (
    <Paper p="xl" style={{ borderStyle: 'dashed', textAlign: 'center' }}>
      <Stack gap="sm" align="center">
        <Text fw={600}>{label} is not running.</Text>
        <Text size="sm" c="dimmed">{why}</Text>
        <Group gap="xs">
          <RunButton op="observe-up" variant="filled">Start the log + metrics stack</RunButton>
          <RunButton op="observe-bootstrap">Install ILM + dashboards</RunButton>
        </Group>
        <Text size="xs" c="dimmed">Or from a terminal: <Code>tools/dash observe up</Code></Text>
      </Stack>
    </Paper>
  );
}

function Embed({ src, title }: { src: string; title: string }) {
  return <iframe className="embed" src={src} loading="lazy" sandbox="allow-scripts allow-same-origin allow-forms allow-popups" title={title} />;
}

export function LogsPlane() {
  const obs = useObservability();
  const [days, setDays] = useState(7);
  const [target, setTarget] = useState('');
  const [dry, setDry] = useState(true);
  const [force, setForce] = useState(false);
  return (
    <>
      <PageHeader
        title="Logs"
        description={<>Every line the fleet's CI and this machine's containers produced. Actions logs are replayed out of the data lake by <Code>dash observe ship</Code>; container logs arrive through Filebeat's label-gated autodiscover. One Logstash pipeline maps to ECS and redacts. Each document carries its run's <Code>trace.id</Code> — the same id as its <Anchor component={Link} to={to.observe('traces')}>Phoenix trace</Anchor>.</>}
        actions={
          <>
            <RunButton op="observe-status">Plane status</RunButton>
            <RunButton op="observe-verify">Verify contract</RunButton>
            <RunButton op="observe-down">Stop the stack</RunButton>
          </>
        }
      />
      <Paper p="md" mb="md">
        <Group gap="md" wrap="wrap" align="flex-end">
          <NumberInput label="Days" value={days} onChange={(v) => setDays(Number(v) || 7)} min={1} max={90} w={100} />
          <TextInput label="Repo" placeholder="all owned repos" value={target} onChange={(e) => setTarget(e.currentTarget.value)} w={200} />
          <Checkbox label="Dry run" checked={dry} onChange={(e) => setDry(e.currentTarget.checked)} />
          <Checkbox label="Force" checked={force} onChange={(e) => setForce(e.currentTarget.checked)} />
          <RunButton op="observe-ship" params={{ days: String(days), target, dry_run: dry, force }} variant="filled">Ship Actions logs from the lake</RunButton>
        </Group>
      </Paper>
      <Load q={obs} rows={5}>
        {(o) => {
          if (!o.present) return <Banner tone="crit">{String(o.error ?? 'observability contract unreadable')}</Banner>;
          const p = ((o.planes ?? {}).logs ?? {}) as Row;
          const ds = (o.datasets ?? []) as Row[];
          const ship = (o.shipments ?? {}) as Row;
          const embeds = (o.embeds ?? {}) as Row;
          const gb = (b: unknown) => ((Number(b) || 0) / 1073741824).toFixed(2);
          return (
            <>
              <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }} spacing="md">
                <StatTile label="Elasticsearch" value={p.reachable ? <Status tone={p.cluster_status === 'red' ? 'crit' : 'good'}>{String(p.cluster_status ?? 'up')}</Status> : <Status tone="crit">not running</Status>}
                  sub={<>{<Mono dim>{String(p.elasticsearch ?? '')}</Mono>}{p.kibana_reachable === false ? ' · Kibana still starting' : ''}</>} />
                <StatTile label="Indexed documents" value={fmt(ds.reduce((a, d) => a + (Number(d.docs) || 0), 0))} sub={`across ${ds.length} data stream(s)`} />
                <StatTile label="On disk" value={`${gb(o.bytes_total)} GB`} tone={o.over_budget ? 'crit' : undefined} sub={`of a ${o.disk_budget_gb} GB budget${o.over_budget ? ' — over budget' : ''}`} href={to.config()} />
                <StatTile label="Shipped runs" value={fmt(ship.count)} sub={ship.last ? `last ${ship.last}` : 'never'} />
              </SimpleGrid>
              {ds.length ? (
                <Section title="Data streams" description="One dataset per source, the repo as a field. Retention is observability.logs.retention_days in fleet.yml.">
                  <DataTable<Row>
                    rows={ds}
                    rowKey={(d) => String(d.data_stream)}
                    columns={[
                      { key: 'ds', header: 'data stream', render: (d) => <Mono>{String(d.data_stream)}</Mono> },
                      { key: 'docs', header: 'docs', num: true, sort: (d) => Number(d.docs), render: (d) => fmt(d.docs) },
                      { key: 'size', header: 'size', num: true, sort: (d) => Number(d.bytes), render: (d) => `${((Number(d.bytes) || 0) / 1048576).toFixed(1)} MB` },
                      { key: 'ret', header: 'retention', num: true, render: (d) => `${d.retention_days}d` },
                    ]}
                  />
                </Section>
              ) : null}
              <Section title="Fleet CI" actions={<External href={String(p.url ?? '')} size="sm">Open Kibana</External>}>
                {p.reachable && p.kibana_reachable && embeds.enabled && embeds.logs
                  ? <Embed src={String(embeds.logs)} title="Fleet CI dashboard" />
                  : <PlaneOff label="Kibana" why={p.reachable ? (p.kibana_reachable ? 'Embedding is off in the contract (observability.portal.embed) — use the link.' : 'Elasticsearch is up but Kibana is still starting; on a cold volume it migrates its own indices first.') : `Nothing is answering at ${String(p.elasticsearch ?? 'the configured URL')}.`} />}
              </Section>
            </>
          );
        }}
      </Load>
    </>
  );
}

export function MetricsPlane() {
  const obs = useObservability();
  return (
    <>
      <PageHeader
        title="Metrics"
        description="Grafana reads the same Elasticsearch indices Kibana searches: how much, over time. Its dashboard and datasource are provisioned from tools/observability/grafana/ and generated from fleet.yml — edits made in Grafana's UI are discarded on the next provision."
        actions={<RunButton op="observe-status">Plane status</RunButton>}
      />
      <Load q={obs}>
        {(o) => {
          if (!o.present) return <Banner tone="crit">{String(o.error ?? 'observability contract unreadable')}</Banner>;
          const p = ((o.planes ?? {}).metrics ?? {}) as Row;
          const embeds = (o.embeds ?? {}) as Row;
          return (
            <Stack gap="sm">
              <Group gap="sm">
                <External href={String(p.url ?? '')} size="sm">Open Grafana</External>
                <Text size="sm" c="dimmed">datasources: {((p.datasources ?? []) as string[]).join(', ') || '—'}</Text>
              </Group>
              {p.reachable && embeds.enabled && embeds.metrics
                ? <Embed src={String(embeds.metrics)} title="Fleet log volume and cost" />
                : <PlaneOff label="Grafana" why={p.reachable ? 'Embedding is off in the contract (observability.portal.embed) — use the link.' : `Nothing is answering at ${String(p.url ?? 'the configured URL')}.`} />}
            </Stack>
          );
        }}
      </Load>
    </>
  );
}
