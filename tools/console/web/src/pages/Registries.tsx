// The committed registries that used to be Jekyll boards, as console pages:
// the roadmap, the fleet feature index, the engagement ledger and the toolbox.
// Each reads one _data file through /api/data/<name> (site_docs.PUBLIC_DATA),
// so it renders the same from a console and from the published snapshot.
import { useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { Anchor, Badge, Group, SegmentedControl, SimpleGrid, Text, TextInput } from '@mantine/core';
import { IconSearch } from '@tabler/icons-react';
import { useData } from '../api/hooks';
import type { Dict } from '../api/types';
import { DataTable } from '../components/DataTable';
import { External, Load, Mono, PageHeader, RepoLink, Section, StatTile, Status } from '../components/ui';
import { includesText, usd, when } from '../lib/format';
import { gh, to } from '../lib/links';

type Row = Dict<any>;

function SearchBox({ q, set }: { q: string; set: (v: string) => void }) {
  return <TextInput data-page-search leftSection={<IconSearch size={15} />} placeholder="Filter…  ( / )" value={q} onChange={(e) => set(e.currentTarget.value)} w={260} />;
}

function useQ(): [string, (v: string) => void] {
  const [sp, setSp] = useSearchParams();
  return [sp.get('q') ?? '', (v) => setSp(v ? { q: v } : {}, { replace: true })];
}

// --- Roadmap ---------------------------------------------------------------
const STATUS_TONE: Record<string, 'good' | 'info' | 'warn'> = { shipped: 'good', 'in-progress': 'info', approved: 'info', proposed: 'warn', backlog: 'info' };

export function Roadmap() {
  const data = useData<Row[]>('roadmap');
  const [q, setQ] = useQ();
  const [status, setStatus] = useState('open');
  return (
    <>
      <PageHeader title="Roadmap" description={<>Feature ideas across the fleet, each a full spec (problem, proposal, acceptance), captured with <Mono>/future-features</Mono> and approved by a human before it lands in <External href={gh.hubFile('_data/roadmap.yml')} size="sm">_data/roadmap.yml</External>.</>} />
      <Load q={data}>
        {(all) => {
          const rows = (all ?? []).filter((r) => (status === 'all' || (status === 'open' ? r.status !== 'shipped' : r.status === status)) && includesText([r.id, r.title, r.project, r.category, r.problem], q));
          return (
            <>
              <Group gap="sm" mb="sm" wrap="wrap">
                <SearchBox q={q} set={setQ} />
                <SegmentedControl size="xs" value={status} onChange={setStatus} data={['open', 'proposed', 'approved', 'in-progress', 'shipped', 'all']} />
                <Text size="sm" c="dimmed">{rows.length} of {(all ?? []).length}</Text>
              </Group>
              <DataTable<Row>
                rows={rows} keys rowKey={(r) => String(r.id)}
                href={(r) => (r.project ? to.project(r.project) : null)} open={(r) => r.issue_url}
                initialSort={{ key: 'pri' }} minWidth={860}
                columns={[
                  { key: 'id', header: 'id', sort: (r) => r.id, render: (r) => <Mono>{r.id}</Mono>, width: 90 },
                  { key: 'pri', header: 'pri', sort: (r) => `${r.priority}${r.id}`, render: (r) => <Badge variant="default" size="sm">{r.priority}</Badge>, width: 56 },
                  { key: 't', header: 'feature', render: (r) => (<div><Text size="sm" fw={600}>{r.title}</Text><Text size="xs" c="dimmed" lineClamp={2}>{r.problem}</Text></div>) },
                  { key: 'p', header: 'project', sort: (r) => r.project, render: (r) => <RepoLink name={r.project} /> },
                  { key: 'e', header: 'effort', sort: (r) => r.effort, render: (r) => r.effort },
                  { key: 's', header: 'status', sort: (r) => r.status, render: (r) => <Status tone={STATUS_TONE[r.status] ?? 'info'}>{r.status}</Status> },
                  { key: 'i', header: '', render: (r) => (r.issue_url ? <External href={r.issue_url} size="xs">issue</External> : null) },
                ]}
              />
            </>
          );
        }}
      </Load>
    </>
  );
}

// --- Features --------------------------------------------------------------
export function Features() {
  const data = useData<Row>('features_index');
  return (
    <>
      <PageHeader title="Features" description={<>What every repo does for a user and what proves it. Each repo's <Mono>features/features.yml</Mono> is aggregated by <Mono>dash features fleet --write</Mono>, and coverage is graded from files on disk: covered (a test or scenario), evidenced (an evidence bundle), verified (a stamp). Standard: <External href={gh.hubFile('docs/VERIFICATION.md')} size="sm">docs/VERIFICATION.md</External>.</>} />
      <Load q={data}>
        {(fx) => {
          if (!fx) return <Text c="dimmed">No index yet — the daily fleet-pulse run writes _data/features_index.yml.</Text>;
          const t = fx.totals ?? {};
          const items: Row[] = (fx.repos ?? []).flatMap((r: Row) => (r.items ?? []).map((i: Row) => ({ ...i, repo: r.name, repo_url: r.repo_url, branch: r.branch })));
          return (
            <>
              <SimpleGrid cols={{ base: 2, md: 5 }} spacing="sm">
                <StatTile label="Features" value={t.features} sub={`in ${t.repos_with_index}/${t.repos_scanned} indexed repos`} />
                <StatTile label="Covered" value={`${fx.pct?.coverage ?? 0}%`} sub="a test or a user scenario" />
                <StatTile label="UI covered" value={`${t.ui_covered} / ${t.ui}`} />
                <StatTile label="Evidenced" value={`${fx.pct?.evidence ?? 0}%`} sub={`${t.screenshots} screenshots`} />
                <StatTile label="Verified" value={`${fx.pct?.verified ?? 0}%`} sub={`${t.verified} stamped`} />
              </SimpleGrid>
              <Text size="xs" c="dimmed" mt={6}>Snapshot {when(fx.generated_at)} · kit verify v{fx.kit_version} · {t.scenarios} scenarios · {t.dangling} dangling links</Text>
              {(fx.attention ?? []).length ? (
                <Section title="Attention">
                  <DataTable<Row> rows={fx.attention} rowKey={(a, i) => `${a.repo}:${i}`} href={(a) => to.project(a.repo)}
                    columns={[
                      { key: 'k', header: 'kind', render: (a) => <Mono>{a.kind}</Mono> },
                      { key: 'r', header: 'repo', render: (a) => <RepoLink name={a.repo} /> },
                      { key: 'd', header: 'finding', render: (a) => <Text size="sm">{a.detail}</Text> },
                      { key: 'l', header: 'lever', render: (a) => <Mono dim>{a.lever}</Mono> },
                    ]} />
                </Section>
              ) : null}
              <Section title="Every feature">
                <DataTable<Row> rows={items} keys rowKey={(i) => `${i.repo}:${i.id}`} href={(i) => to.project(i.repo)} minWidth={900}
                  columns={[
                    { key: 'id', header: 'id', sort: (i) => i.id, render: (i) => <Mono>{i.id}</Mono> },
                    { key: 'r', header: 'repo', sort: (i) => i.repo, render: (i) => <RepoLink name={i.repo} /> },
                    { key: 't', header: 'feature', sort: (i) => i.title, render: (i) => <Text size="sm">{i.title}</Text> },
                    { key: 's', header: 'surface', sort: (i) => i.surface, render: (i) => i.surface },
                    { key: 'c', header: 'proof', sort: (i) => (i.covered ? 0 : 1), render: (i) => (i.covered ? <Status tone="good">covered</Status> : <Status tone="warn">no proof</Status>) },
                    { key: 'e', header: 'evidence', sort: (i) => (i.evidenced ? 0 : 1), render: (i) => (i.evidenced ? <Status tone="good">yes</Status> : <Text size="xs" c="dimmed">—</Text>) },
                    { key: 'v', header: 'verified', sort: (i) => String(i.verified?.date ?? i.verified ?? ''), render: (i) => (i.verified ? <Status tone="good">{String(i.verified?.date ?? 'yes')}</Status> : <Text size="xs" c="dimmed">—</Text>) },
                  ]} />
              </Section>
            </>
          );
        }}
      </Load>
    </>
  );
}

// --- Engagements -----------------------------------------------------------
export function Engagements() {
  const data = useData<Row>('engagements');
  return (
    <>
      <PageHeader title="Engagements" description={<>Every registry project treated as a client: deterministic estimates from open issues (estimator-v1 and the rate card), actuals accrued from agent usage, and the leverage over doing it the pre-AI way. Estimates are proposals; status changes are a human's. See <External href={gh.hubFile('docs/ESTIMATION.md')} size="sm">docs/ESTIMATION.md</External>.</>} />
      <Load q={data}>
        {(e) => {
          if (!e) return <Text c="dimmed">No ledger yet.</Text>;
          const s = e.summary ?? {};
          return (
            <>
              <SimpleGrid cols={{ base: 2, md: 5 }} spacing="sm">
                <StatTile label="Engagements" value={s.engagements} sub={`${s.clients} clients`} />
                <StatTile label="Pipeline" value={usd(s.pipeline_usd)} sub="estimated, not started" />
                <StatTile label="In flight" value={usd(s.in_flight_usd)} />
                <StatTile label="Delivered" value={usd(s.delivered_actual_usd)} sub={`est. ${usd(s.delivered_est_usd)}`} />
                <StatTile label="Avg. leverage" value={`${s.avg_leverage_est ?? '—'}×`} sub="vs. the traditional estimate" />
              </SimpleGrid>
              <Text size="xs" c="dimmed" mt={6}>Updated {when(s.updated_at)}</Text>
              <Section title="Clients">
                <DataTable<Row> rows={e.clients ?? []} rowKey={(c) => c.name} href={(c) => to.project(c.name)} initialSort={{ key: 'est', desc: true }}
                  columns={[
                    { key: 'n', header: 'client', sort: (c) => c.name, render: (c) => <RepoLink name={c.name} /> },
                    { key: 'e', header: 'engagements', num: true, sort: (c) => c.engagements, render: (c) => c.engagements },
                    { key: 'o', header: 'open', num: true, sort: (c) => c.open, render: (c) => c.open },
                    { key: 'est', header: 'estimated', num: true, sort: (c) => c.est_usd, render: (c) => usd(c.est_usd) },
                    { key: 'a', header: 'actual', num: true, sort: (c) => c.actual_usd, render: (c) => usd(c.actual_usd) },
                  ]} />
              </Section>
              <Section title="Engagements">
                <DataTable<Row> rows={e.engagements ?? []} keys rowKey={(x) => x.id} open={(x) => x.source?.url ?? x.source} minWidth={900}
                  columns={[
                    { key: 'id', header: 'id', sort: (x) => x.id, render: (x) => <Mono>{x.id}</Mono> },
                    { key: 'c', header: 'client', sort: (x) => x.client, render: (x) => <RepoLink name={x.client} /> },
                    { key: 't', header: 'work', render: (x) => <Text size="sm">{x.title}</Text> },
                    { key: 'ty', header: 'type', sort: (x) => x.type, render: (x) => x.type },
                    { key: 's', header: 'status', sort: (x) => x.status, render: (x) => <Status tone={x.status === 'delivered' || x.status === 'reconciled' ? 'good' : 'info'}>{x.status}</Status> },
                    { key: 'est', header: 'estimate', num: true, sort: (x) => x.estimate?.total_usd, render: (x) => usd(x.estimate?.total_usd) },
                    { key: 'l', header: 'leverage', num: true, sort: (x) => x.estimate?.leverage, render: (x) => (x.estimate?.leverage != null ? `${x.estimate.leverage}×` : '—') },
                  ]} />
              </Section>
            </>
          );
        }}
      </Load>
    </>
  );
}

// --- Toolbox ---------------------------------------------------------------
export function Toolbox() {
  const scripts = useData<Row[]>('scripts');
  const skills = useData<Row[]>('skills');
  const templates = useData<Row[]>('templates');
  return (
    <>
      <PageHeader title="Toolbox" description={<>What the hub provides to the fleet and to the agents working in it: scripts, Claude skills and the seedable kits. The full index is <External href={gh.hubFile('CATALOG.md')} size="sm">CATALOG.md</External>; the operations a console can run are on <Anchor component={Link} to={to.ops()} size="sm">Operations</Anchor>.</>} />
      <Section title="Scripts" mt={0}>
        <Load q={scripts}>{(rows) => <DataTable<Row> rows={rows ?? []} rowKey={(r) => r.name} columns={[
          { key: 'n', header: 'script', render: (r) => <Mono>{r.name}</Mono> },
          { key: 'd', header: 'what it does', render: (r) => <Text size="sm">{r.description}</Text> },
          { key: 'u', header: 'usage', render: (r) => <Mono dim>{r.usage}</Mono> },
        ]} />}</Load>
      </Section>
      <Section title="Skills">
        <Load q={skills}>{(rows) => <DataTable<Row> rows={rows ?? []} rowKey={(r) => r.name} columns={[
          { key: 'n', header: 'skill', render: (r) => <Mono>{r.name}</Mono> },
          { key: 'd', header: 'what it does', render: (r) => <Text size="sm">{r.description}</Text> },
        ]} />}</Load>
      </Section>
      <Section title="Template kits">
        <Load q={templates}>{(rows) => <DataTable<Row> rows={rows ?? []} rowKey={(r) => r.name} open={(r) => (String(r.path).startsWith('http') ? r.path : gh.hubFile(r.path))} columns={[
          { key: 'n', header: 'kit', render: (r) => <External href={String(r.path).startsWith('http') ? r.path : gh.hubFile(r.path)} size="sm">{r.name}</External> },
          { key: 'd', header: 'what it seeds', render: (r) => <Text size="sm">{r.description}</Text> },
        ]} />}</Load>
      </Section>
    </>
  );
}
