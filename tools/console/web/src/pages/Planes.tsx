// The local stack's LOG plane (Kibana over Elasticsearch) and its metrics
// (Grafana over the same indices). Both are opt-in behind the `elk` compose
// profile, so "not running" is the ordinary state and renders as an
// invitation to start it — never as an error.
//
// Both dashboards open on a RELATIVE window, so a plane whose newest line is
// older than that window renders "No data" over hundreds of thousands of
// documents. Every view here therefore states how fresh the data is and opens
// the embeds on a window that actually contains it.
import { Link, useSearchParams } from 'react-router';
import {
  Anchor, Checkbox, Code, Group, NumberInput, Paper, SegmentedControl, SimpleGrid, Stack, Text, TextInput, useComputedColorScheme,
} from '@mantine/core';
import { useState } from 'react';
import { useObservability } from '../api/hooks';
import type { Dict } from '../api/types';
import { DataTable } from '../components/DataTable';
import { Banner, External, Load, Mono, PageHeader, Section, StatTile, Status } from '../components/ui';
import { RunButton } from '../jobs/RunButton';
import { age, dash, fmt, when } from '../lib/format';
import { to } from '../lib/links';

type Row = Dict<any>;

// Relative windows both Kibana (`now-30d`) and Grafana (`from=now-30d`) parse.
const RANGES = ['24h', '7d', '30d', '90d'] as const;
type Range = (typeof RANGES)[number];
const RANGE_DAYS: Record<Range, number> = { '24h': 1, '7d': 7, '30d': 30, '90d': 90 };

const daysSince = (iso: unknown): number | null => {
  const t = iso ? new Date(String(iso)).getTime() : NaN;
  return Number.isNaN(t) ? null : Math.max(0, (Date.now() - t) / 86_400_000);
};

/** The newest indexed line across every data stream. */
function newestLine(ds: Row[]): { iso: string | null; days: number | null } {
  const iso = ds.map((d) => d.newest as string | null).filter(Boolean).sort().pop() ?? null;
  return { iso, days: daysSince(iso) };
}

/** "just now" / "3h ago" / "20d ago". */
const agoText = (days: number | null): string => (age(days) === 'now' ? 'just now' : `${age(days)} ago`);

/** The narrowest window that still holds the newest line — the dashboards' own 7d when it is fresh. */
function autoRange(days: number | null): Range {
  if (days == null || days <= RANGE_DAYS['7d']) return '7d';
  return days <= RANGE_DAYS['30d'] ? '30d' : '90d';
}

/**
 * ?range= when the reader picked one, otherwise the window that shows the data
 * the EMBED draws — `dataset` narrows that to one stream. The Logs page's
 * Kibana pane is CI-only, so live Claude Code events must not shrink its
 * window to 7d over CI lines that are weeks old.
 */
function useRange(o: Row, dataset?: string): [Range, (r: Range) => void] {
  const [sp, setSp] = useSearchParams();
  const picked = sp.get('range') as Range | null;
  const ds = ((o.datasets ?? []) as Row[]).filter((d) => !dataset || d.dataset === dataset);
  const range = picked && RANGES.includes(picked) ? picked : autoRange(newestLine(ds).days);
  const set = (r: Range) => setSp((p) => { const n = new URLSearchParams(p); n.set('range', r); return n; }, { replace: true });
  return [range, set];
}

const kibanaEmbed = (base: string, r: Range): string => `${base}&_g=(time:(from:now-${r},to:now))`;

function grafanaEmbed(base: string, r: Range, scheme: 'light' | 'dark'): string {
  // The contract's URL pins theme=dark; the pane follows the console instead.
  const themed = /[?&]theme=/.test(base) ? base.replace(/([?&])theme=[^&]*/, `$1theme=${scheme}`) : `${base}&theme=${scheme}`;
  return `${themed}&from=now-${r}&to=now`;
}

/** The window picker plus, when the window is empty, why — and the two steps that refill it. */
function Freshness({ o, range, setRange, days, target }: {
  o: Row; range: Range; setRange: (r: Range) => void; days?: number; target?: string;
}) {
  const ds = (o.datasets ?? []) as Row[];
  const total = ds.reduce((a, d) => a + (Number(d.docs) || 0), 0);
  const newest = newestLine(ds);
  // "Behind" is about the Actions stream only: it is the one `ship` refills
  // from the lake. Claude Code's events arrive live from the collector, so a
  // fresh Claude event must not hide a CI plane that is weeks behind.
  const ci = newestLine(ds.filter((d) => d.dataset === 'actions'));
  const lakeRuns = o.lake_runs as number | null | undefined;
  const stale = ci.days != null && ci.days > RANGE_DAYS[range];
  const span = { days: String(days ?? 7), target: target ?? '' };
  return (
    <>
      <Group gap="sm" mb="sm" wrap="wrap">
        <SegmentedControl size="xs" value={range} onChange={(v) => setRange(v as Range)} data={RANGES.map((r) => ({ label: `last ${r}`, value: r }))} />
        <Text size="sm" c="dimmed">
          {total ? <>newest line {agoText(newest.days)} · {when(newest.iso)}{ci.iso && ci.iso !== newest.iso ? <> · newest CI line <Text span c={stale ? 'var(--critical)' : undefined}>{agoText(ci.days)}</Text></> : null}</> : 'nothing indexed yet'}
        </Text>
      </Group>
      {ci.days != null && ci.days > 2 ? (
        <Banner tone={stale ? 'crit' : 'warn'} title={stale ? `No CI logs in the last ${range}` : 'The CI log plane is behind'}>
          <Stack gap="xs">
            <Text size="sm">
              The newest CI log line is {age(ci.days)} old ({when(ci.iso)}) — nothing has been shipped since.
              {stale ? ' The CI panels below are empty because their window ends before it; widen the window to see older lines.' : ''}
              {' '}Shipping replays the data lake, so it can only send what was extracted first
              {lakeRuns === 0 ? <> — and <b>the lake holds no runs right now</b>, so ship would send nothing.</> : lakeRuns != null ? <> (the lake holds {fmt(lakeRuns)} run(s)).</> : '.'}
            </Text>
            <Group gap="xs">
              <RunButton op="lake-sync" params={{ ...span, jobs: 'all', logs: 'all' }} variant="filled">1 · Extract every run's logs into the lake</RunButton>
              <RunButton op="observe-ship" params={{ ...span, dry_run: false, force: false }}>2 · Ship them</RunButton>
            </Group>
          </Stack>
        </Banner>
      ) : null}
    </>
  );
}

function PlaneOff({ label, why, running }: { label: string; why: string; running?: boolean }) {
  return (
    <Paper p="xl" style={{ borderStyle: 'dashed', textAlign: 'center' }}>
      <Stack gap="sm" align="center">
        <Text fw={600}>{running ? `${label} is not embedded here.` : `${label} is not running.`}</Text>
        <Text size="sm" c="dimmed">{why}</Text>
        {running ? null : (
          <>
            <Group gap="xs">
              <RunButton op="observe-up" variant="filled">Start the log + metrics stack</RunButton>
              <RunButton op="observe-bootstrap">Install ILM + dashboards</RunButton>
            </Group>
            <Text size="xs" c="dimmed">Or from a terminal: <Code>tools/dash observe up</Code></Text>
          </>
        )}
      </Stack>
    </Paper>
  );
}

function Embed({ src, title }: { src: string; title: string }) {
  return <iframe className="embed" src={src} loading="lazy" sandbox="allow-scripts allow-same-origin allow-forms allow-popups" title={title} />;
}

function LogsBody({ o, days, target }: { o: Row; days: number; target: string }) {
  const [range, setRange] = useRange(o, 'actions');
  if (!o.present) return <Banner tone="crit">{String(o.error ?? 'observability contract unreadable')}</Banner>;
  const p = ((o.planes ?? {}).logs ?? {}) as Row;
  const ds = (o.datasets ?? []) as Row[];
  const ship = (o.shipments ?? {}) as Row;
  const embeds = (o.embeds ?? {}) as Row;
  const total = ds.reduce((a, d) => a + (Number(d.docs) || 0), 0);
  const newest = newestLine(ds);
  const gb = (b: unknown) => ((Number(b) || 0) / 1073741824).toFixed(2);
  const lakeRuns = o.lake_runs as number | null | undefined;
  const shipSub = ship.last
    ? `last ${when(ship.last)}`
    : total && lakeRuns === 0 ? 'the lake is empty — these documents came from an earlier one' : 'never';
  return (
    <>
      <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }} spacing="md" mb="md">
        <StatTile label="Elasticsearch" value={p.reachable ? <Status tone={p.cluster_status === 'red' ? 'crit' : 'good'}>{String(p.cluster_status ?? 'up')}</Status> : <Status tone="crit">not running</Status>}
          sub={<>{<Mono dim>{String(p.elasticsearch ?? '')}</Mono>}{p.kibana_reachable === false ? ' · Kibana still starting' : ''}</>} />
        <StatTile label="Indexed documents" value={fmt(total)}
          sub={`across ${ds.filter((d) => d.present).length} of ${ds.length} data stream(s)${newest.iso ? ` · newest ${agoText(newest.days)}` : ''}`} />
        <StatTile label="On disk" value={`${gb(o.bytes_total)} GB`} tone={o.over_budget ? 'crit' : undefined} sub={`of a ${o.disk_budget_gb} GB budget${o.over_budget ? ' — over budget' : ''}`} href={to.config('observability')} />
        <StatTile label="Shipped runs" value={fmt(ship.count)} sub={shipSub} />
      </SimpleGrid>
      {p.reachable ? <Freshness o={o} range={range} setRange={setRange} days={days} target={target} /> : null}
      {ds.length ? (
        <Section title="Data streams" description="One dataset per source, the repo as a field. Retention is observability.logs.retention_days in fleet.yml.">
          <DataTable<Row>
            rows={ds}
            rowKey={(d) => String(d.data_stream)}
            columns={[
              { key: 'ds', header: 'data stream', render: (d) => <Mono>{String(d.data_stream)}</Mono> },
              { key: 'docs', header: 'docs', num: true, sort: (d) => Number(d.docs) || 0, render: (d) => (d.present ? fmt(d.docs) : <Text span size="sm" c="dimmed">not created yet</Text>) },
              { key: 'size', header: 'size', num: true, sort: (d) => Number(d.bytes) || 0, render: (d) => (d.present ? `${((Number(d.bytes) || 0) / 1048576).toFixed(1)} MB` : dash) },
              { key: 'span', header: 'lines from', render: (d) => (d.oldest ? `${when(d.oldest)} → ${when(d.newest)}` : dash) },
              { key: 'newest', header: 'newest', num: true, sort: (d) => daysSince(d.newest) ?? Infinity, render: (d) => (d.newest ? agoText(daysSince(d.newest)) : dash) },
              { key: 'ret', header: 'retention', num: true, render: (d) => `${d.retention_days}d` },
            ]}
          />
        </Section>
      ) : null}
      <Section title="Fleet CI" actions={<External href={String(p.url ?? '')} size="sm">Open Kibana</External>}>
        {p.reachable && p.kibana_reachable && embeds.enabled && embeds.logs
          ? <Embed key={range} src={kibanaEmbed(String(embeds.logs), range)} title="Fleet CI dashboard" />
          : (
            <PlaneOff
              label="Kibana"
              running={Boolean(p.reachable)}
              why={p.reachable
                ? (p.kibana_reachable ? 'Embedding is off in the contract (observability.portal.embed) — use the link.' : 'Elasticsearch is up but Kibana is still starting; on a cold volume it migrates its own indices first.')
                : `Nothing is answering at ${String(p.elasticsearch ?? 'the configured URL')}.`}
            />
          )}
      </Section>
    </>
  );
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
          <RunButton op="lake-sync" params={{ days: String(days), target, jobs: 'all', logs: 'all' }}>Extract into the lake</RunButton>
          <RunButton op="observe-ship" params={{ days: String(days), target, dry_run: dry, force }} variant="filled">Ship Actions logs from the lake</RunButton>
        </Group>
      </Paper>
      <Load q={obs} rows={5}>{(o) => <LogsBody o={o} days={days} target={target} />}</Load>
    </>
  );
}

function MetricsBody({ o }: { o: Row }) {
  const [range, setRange] = useRange(o);
  const scheme = useComputedColorScheme('dark');
  if (!o.present) return <Banner tone="crit">{String(o.error ?? 'observability contract unreadable')}</Banner>;
  const p = ((o.planes ?? {}).metrics ?? {}) as Row;
  const logs = ((o.planes ?? {}).logs ?? {}) as Row;
  const tel = ((o.planes ?? {}).telemetry ?? {}) as Row;
  const embeds = (o.embeds ?? {}) as Row;
  return (
    <Stack gap="sm">
      <Group gap="sm">
        <StatusLine reachable={p.reachable} />
        <External href={String(p.url ?? '')} size="sm">Open Grafana</External>
        <Text size="sm" c="dimmed">datasources: {((p.datasources ?? []) as string[]).join(', ') || dash}</Text>
      </Group>
      {/* Claude Code's native OTel path: the collector it exports to, and the Prometheus behind the live panels. */}
      <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="md">
        <StatTile label="OTel collector" value={tel.reachable ? <Status tone="good">receiving</Status> : <Status tone="crit">not running</Status>}
          sub={<Mono dim>{String(tel.url ?? '')}</Mono>} />
        <StatTile label="Prometheus" value={tel.prometheus_reachable ? <Status tone="good">up</Status> : <Status tone="crit">not running</Status>}
          sub={tel.prometheus ? <Anchor href={String(tel.prometheus)} target="_blank" rel="noreferrer" size="xs">{String(tel.prometheus)}</Anchor> : dash} />
        <StatTile label="Claude Code export" value={<Text fw={600}>this machine</Text>}
          sub={<>enable with <Code>tools/dash observe claude enable --apply</Code>; spans land in Phoenix project <Code>{String(tel.phoenix_project ?? 'claude-code-otel')}</Code></>} />
      </SimpleGrid>
      {tel.reachable === false || tel.prometheus_reachable === false ? (
        <Group gap="xs"><RunButton op="observe-up" variant="filled">Start the collector + Prometheus</RunButton></Group>
      ) : null}
      {/* Grafana charts the same indices, so the log plane's freshness is its freshness. */}
      {logs.reachable ? <Freshness o={o} range={range} setRange={setRange} /> : null}
      {p.reachable && embeds.enabled && embeds.metrics
        ? <Embed key={`${range}-${scheme}`} src={grafanaEmbed(String(embeds.metrics), range, scheme)} title="Fleet log volume and cost" />
        : (
          <PlaneOff
            label="Grafana"
            running={Boolean(p.reachable)}
            why={p.reachable ? 'Embedding is off in the contract (observability.portal.embed) — use the link.' : `Nothing is answering at ${String(p.url ?? 'the configured URL')}.`}
          />
        )}
    </Stack>
  );
}

function StatusLine({ reachable }: { reachable: unknown }) {
  return reachable ? <Status tone="good">up</Status> : <Status tone="crit">not running</Status>;
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
      <Load q={obs}>{(o) => <MetricsBody o={o} />}</Load>
    </>
  );
}
