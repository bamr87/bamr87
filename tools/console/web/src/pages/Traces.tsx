// The local stack's trace half: the data lake (.dash-lake/fleet.sqlite) GitHub
// is extracted into, and Phoenix the agent runs are exported to. Repos in the
// lake open their project; runs open on GitHub, with their trace id.
import { Link } from 'react-router';
import { Anchor, Checkbox, Code, Group, NumberInput, Paper, SimpleGrid, Stack, Text, TextInput } from '@mantine/core';
import { useState } from 'react';
import { useCaps, useLake, useLakeRuns } from '../api/hooks';
import type { Dict } from '../api/types';
import { DataTable } from '../components/DataTable';
import { Banner, External, Load, Mono, PageHeader, Section, StatTile, Status } from '../components/ui';
import { RunButton } from '../jobs/RunButton';
import { fmt, repoName, usd } from '../lib/format';
import { to } from '../lib/links';
import { RunsTable } from './ProjectPage';

type Row = Dict<any>;

export function Traces() {
  const lake = useLake();
  const runs = useLakeRuns(80);
  const caps = useCaps();
  const [days, setDays] = useState(7);
  const [target, setTarget] = useState('');
  const [local, setLocal] = useState(true);
  const [dry, setDry] = useState(true);
  const [force, setForce] = useState(false);

  return (
    <>
      <PageHeader
        title="Traces"
        description={<>GitHub (runs → jobs → steps → run logs, issues, workflow files, <Code>.factory/</Code> blueprints) is extracted into the local lake; agent runs and this machine's Claude Code sessions are exported from it to Phoenix as OpenInference traces with deterministic ids. The lake is gitignored — it holds logs.</>}
        actions={<External href={lake.data?.phoenix?.ui} size="sm">Open Phoenix</External>}
      />
      <Paper p="md" mb="md">
        <Group gap="md" wrap="wrap" align="flex-end">
          <NumberInput label="Days" value={days} onChange={(v) => setDays(Number(v) || 7)} min={1} max={90} w={100} />
          <TextInput label="Repo" placeholder="all owned repos" value={target} onChange={(e) => setTarget(e.currentTarget.value)} w={200} />
          <RunButton op="lake-sync" params={{ days: String(days), target }} variant="filled">Sync lake from GitHub</RunButton>
          <RunButton op="lake-sessions" params={{ days: String(days) }}>Extract local sessions</RunButton>
          <RunButton op="lake-status">Status</RunButton>
        </Group>
        <Group gap="md" wrap="wrap" align="flex-end" mt="md">
          <Checkbox label="Local Claude Code sessions" checked={local} onChange={(e) => setLocal(e.currentTarget.checked)} />
          <Checkbox label="Dry run" checked={dry} onChange={(e) => setDry(e.currentTarget.checked)} />
          <Checkbox label="Force (resend)" checked={force} onChange={(e) => setForce(e.currentTarget.checked)} />
          <RunButton op="lake-export" params={{ days: String(days), local, dry_run: dry, force }}>Export traces to Phoenix</RunButton>
          {caps.data?.otel_exporter === false ? <Status tone="warn">OTel exporter not installed (a dry run still works)</Status> : null}
        </Group>
      </Paper>
      <Load q={lake} rows={6}>
        {(l) => {
          const t = (l.tables ?? {}) as Row;
          const ls = (l.last_sync ?? {}) as Row;
          const ag = (l.agent_runs ?? {}) as Row;
          const ex = (l.exports ?? {}) as Row;
          const se = (l.sessions ?? {}) as Row;
          const px = (l.phoenix ?? {}) as Row;
          const repos = (l.repos ?? []) as Row[];
          return (
            <>
              {l.error ? <Banner tone="crit">{String(l.error)}</Banner> : null}
              <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }} spacing="md">
                <StatTile label="Lake" value={l.present ? `${(Number(l.size_bytes) / 1e6).toFixed(1)} MB` : 'not built'} sub={<Mono dim>{String(l.db_path ?? l.lake_dir ?? '')}</Mono>} />
                <StatTile label="Last sync" value={<Text fz={16} fw={600}>{String(ls.finished_at ?? '—')}</Text>} sub={ls.window_days ? `${ls.window_days}-day window · ${ls.repos} repos` : 'sync to fill it'} />
                <StatTile label="Runs · agent runs parsed" value={`${fmt(t.runs)} · ${fmt(ag.count)}`} sub={`${fmt(t.jobs)} jobs · ${fmt(t.steps)} steps · ${fmt(t.logs)} log entries`} href={to.activity()} />
                <StatTile label="Agent spend in the lake" value={usd(ag.cost_usd)} sub={`${fmt(ag.turns)} turns · ${Object.entries((ag.models ?? {}) as Record<string, number>).map(([m, n]) => `${m}×${n}`).join(', ') || '—'}`} href={to.activity()} />
                <StatTile label="Issues · workflows · .factory files" value={`${fmt(t.issues)} · ${fmt(t.workflows)} · ${fmt(t.factory_files)}`} sub={`${repos.filter((r) => r.factory).length} GitFactory-managed repos`} href={to.observe('lines')} />
                <StatTile label="Local Claude Code sessions" value={fmt(se.count)} sub={`${usd(se.cost_usd)} · ${fmt(se.turns)} turns · ${fmt(se.tool_calls)} tool calls${se.last ? ` · last ${se.last}` : ''}`} href={to.activity()} />
                <StatTile label="Phoenix" value={px.reachable === true ? <Status tone="good">reachable</Status> : px.reachable === false ? <Status tone="crit">not reachable</Status> : <Status tone="info">not probed</Status>}
                  sub={`${fmt(ex.count)} traces / ${fmt(ex.spans)} spans exported${ex.last ? ` · last ${ex.last}` : ''}`} />
              </SimpleGrid>
              <Section title={`Repos in the lake (${repos.length})`}>
                <DataTable<Row>
                  rows={repos}
                  keys
                  rowKey={(r) => String(r.nwo)}
                  href={(r) => to.project(repoName(String(r.nwo)), 'runs')}
                  initialSort={{ key: 'runs', desc: true }}
                  empty="empty — sync first (needs gh auth)"
                  columns={[
                    { key: 'repo', header: 'repo', sort: (r) => String(r.nwo), render: (r) => <Text size="sm" ff="monospace">{String(r.nwo)}{r.factory ? ' ⚙' : ''}{r.manifest ? ' 📜' : ''}{r.archived ? ' (archived)' : ''}</Text> },
                    { key: 'runs', header: 'runs', num: true, sort: (r) => Number(r.runs ?? 0), render: (r) => fmt(r.runs) },
                    { key: 'ai', header: 'AI runs', num: true, sort: (r) => Number(r.ai_runs ?? 0), render: (r) => fmt(r.ai_runs) },
                    { key: 'wf', header: 'workflows', num: true, sort: (r) => Number(r.workflows ?? 0), render: (r) => fmt(r.workflows) },
                    { key: 'iss', header: 'open issues', num: true, sort: (r) => Number(r.open_issues ?? 0), render: (r) => fmt(r.open_issues) },
                    { key: 'last', header: 'last run', sort: (r) => String(r.last_run ?? ''), render: (r) => <Text size="xs" c="dimmed">{String(r.last_run ?? '—')}</Text> },
                    { key: 'sync', header: 'synced', render: (r) => <Text size="xs" c="dimmed">{String(r.synced_at ?? '')}</Text> },
                  ]}
                />
              </Section>
            </>
          );
        }}
      </Load>
      <Section title="Agent runs" description={<>One trace per run: workflow → jobs → steps → the Claude step (model, turns, cost from the run log) → tool calls. Runs with parsed agent facts are listed first. <Anchor component={Link} to={to.observe('lines')}>Every workflow</Anchor>.</>}>
        <Load q={runs}>{(r) => <RunsTable rows={r} />}</Load>
      </Section>
      <Section title="The local stack">
        <Stack gap={4}>
          <Text size="sm">GitHub → <Mono>tools/dash lake sync</Mono> → <Mono>.dash-lake/fleet.sqlite</Mono> → <Mono>tools/dash lake export</Mono> → Phoenix :6006.</Text>
          <Text size="sm" c="dimmed">The same <Mono>trace.id</Mono> is stamped on every log document <Anchor component={Link} to={to.observe('logs')}>the log plane</Anchor> holds, so a run pivots between its trace and its lines.</Text>
        </Stack>
      </Section>
    </>
  );
}
