// One project, every signal the console holds about it (/api/project/:name):
// registry entry, the Apps row and its every open item, its AI harness
// deployment and crons, the attention findings that name it, its runs and
// workflows in the local lake, its content site — and the operations that can
// be pointed at it.
import { Link, useParams, useSearchParams } from 'react-router';
import { Anchor, Badge, Group, Paper, SimpleGrid, Stack, Table, Tabs, Text } from '@mantine/core';
import { useContent, useProject } from '../api/hooks';
import type { Dict, HarnessRepo, InboxItem, LakeLine, LakeRun, ProjectDetail, ScheduleEntry } from '../api/types';
import { DataTable } from '../components/DataTable';
import { useKeyScope } from '../components/keyscope';
import {
  Banner, Conclusion, Empty, External, LevelDot, Load, Mono, PageHeader, Section, StatTile, Status,
} from '../components/ui';
import { RunButton } from '../jobs/RunButton';
import { duration, fmt, parseList, usd } from '../lib/format';
import { gh, to } from '../lib/links';
import { AttentionTable } from './Overview';
import { RepoManager } from '../github/RepoManager';

export function InboxTable({ rows, showRepo = false }: { rows: InboxItem[]; showRepo?: boolean }) {
  return (
    <DataTable<InboxItem>
      rows={rows}
      keys
      rowKey={(i, n) => `${i.repo}:${i.kind}:${i.ref}:${n}`}
      onActivate={(i) => window.open(i.url, '_blank', 'noopener')}
      open={(i) => i.url}
      copy={(i) => i.url}
      initialSort={{ key: 'pri', desc: true }}
      tone={(i) => (i.priority >= 80 ? 'crit' : i.priority >= 60 ? 'warn' : undefined)}
      empty={<Status tone="good">nothing open</Status>}
      columns={[
        { key: 'pri', header: 'pri', num: true, sort: (i) => i.priority, render: (i) => i.priority, width: 50 },
        { key: 'kind', header: 'kind', sort: (i) => i.kind, render: (i) => <Badge variant="default" size="sm">{i.kind}</Badge> },
        ...(showRepo ? [{ key: 'repo', header: 'repo', sort: (i: InboxItem) => i.repo, render: (i: InboxItem) => <Anchor component={Link} to={to.project(i.repo)} ff="monospace" fz="sm">{i.repo}</Anchor> }] : []),
        { key: 'item', header: 'item', sort: (i) => i.label, render: (i) => <External href={i.url} size="sm">{i.label}</External> },
        { key: 'why', header: 'why', render: (i) => <Text size="xs" c="dimmed">{i.why}</Text> },
        { key: 'age', header: 'age', num: true, sort: (i) => i.age_days ?? -1, render: (i) => (i.age_days == null ? '' : `${i.age_days}d`) },
      ]}
    />
  );
}

export function HarnessWorkflows({ repo }: { repo: HarnessRepo }) {
  const hs = repo.harnesses ?? [];
  if (!hs.length) return <Empty>No AI harness workflows in this repo.</Empty>;
  return (
    <DataTable
      rows={hs}
      rowKey={(h) => h.path}
      onActivate={(h) => window.open(gh.workflow(repo.nwo, h.path), '_blank', 'noopener')}
      columns={[
        { key: 'kind', header: 'kind', render: (h) => <Text size="sm">{h.kind === 'mention-handler' ? '💬' : h.kind === 'scheduled-agent' ? '⏰' : '⚙️'} {h.kind}</Text> },
        { key: 'path', header: 'workflow', render: (h) => <External href={gh.workflow(repo.nwo, h.path)} size="sm">{h.path.replace('.github/workflows/', '')}</External> },
        { key: 'model', header: 'model', render: (h) => <Text size="sm">{h.model ?? '—'}{h.max_turns ? ` / ${h.max_turns}t` : ''}</Text> },
        { key: 'auth', header: 'auth', render: (h) => (/oauth/.test(h.auth ?? '') ? <Status tone="good">{h.auth}</Status> : <Status tone="crit">{h.auth || 'none'}</Status>) },
        { key: 'kit', header: 'kit', render: (h) => (h.kit_status === 'current' ? <Status tone="good">v{h.kit}</Status> : h.kit_status === 'upgradeable' ? <Status tone="warn">v{h.kit} ↑</Status> : <Text size="sm" c="dimmed">{h.kit_status ?? '—'}</Text>) },
        { key: 'last', header: 'last run', render: (h) => <Conclusion value={h.last_conclusion} /> },
        { key: 'runs', header: '', render: (h) => <External href={gh.workflowRuns(repo.nwo, h.path)} size="xs">runs</External> },
      ]}
    />
  );
}

export function ScheduleTable({ rows, showRepo }: { rows: ScheduleEntry[]; showRepo?: boolean }) {
  return (
    <DataTable<ScheduleEntry>
      rows={rows}
      keys={showRepo}
      rowKey={(s, i) => `${s.repo}:${s.workflow}:${s.cron}:${i}`}
      href={showRepo ? (s) => to.project(s.repo) : undefined}
      initialSort={{ key: 'est', desc: true }}
      empty="no crons"
      columns={[
        { key: 'ai', header: '', render: (s) => (s.ai ? <span title="AI workflow">🤖</span> : ''), width: 28 },
        ...(showRepo ? [{ key: 'repo', header: 'repo', sort: (s: ScheduleEntry) => s.repo, render: (s: ScheduleEntry) => <Mono>{s.repo}</Mono> }] : []),
        { key: 'wf', header: 'workflow', sort: (s) => s.workflow, render: (s) => <Text size="sm">{s.workflow}</Text> },
        { key: 'cron', header: 'cron', render: (s) => <Mono>{s.cron}</Mono> },
        { key: 'human', header: 'schedule', sort: (s) => s.human, render: (s) => <Text size="sm">{s.human}</Text> },
        { key: 'est', header: 'est/day', num: true, sort: (s) => s.est_per_day ?? -1, render: (s) => (s.est_per_day == null ? '?' : s.est_per_day) },
      ]}
    />
  );
}

export function RunsTable({ rows, showRepo = true }: { rows: LakeRun[]; showRepo?: boolean }) {
  return (
    <DataTable<LakeRun>
      rows={rows}
      rowKey={(r) => String(r.id)}
      onActivate={(r) => r.html_url && window.open(r.html_url, '_blank', 'noopener')}
      tone={(r) => (r.conclusion === 'failure' ? 'crit' : undefined)}
      empty="no runs in the lake yet — sync it (Traces → Sync lake)"
      minWidth={860}
      columns={[
        ...(showRepo ? [{ key: 'repo', header: 'repo', sort: (r: LakeRun) => r.nwo, render: (r: LakeRun) => <Anchor component={Link} to={to.project(r.nwo.split('/').pop() ?? '')} ff="monospace" fz="sm">{r.nwo}</Anchor> }] : []),
        { key: 'wf', header: 'workflow', sort: (r) => r.workflow_name, render: (r) => <External href={r.html_url} size="sm">{r.workflow_name}</External> },
        { key: 'event', header: 'event', render: (r) => <Text size="sm">{r.event}</Text> },
        { key: 'concl', header: 'conclusion', sort: (r) => r.conclusion ?? '', render: (r) => <Conclusion value={r.conclusion ?? r.status} /> },
        { key: 'model', header: 'model', render: (r) => <Text size="sm">{r.model ?? '—'}</Text> },
        { key: 'turns', header: 'turns', num: true, sort: (r) => r.num_turns ?? -1, render: (r) => fmt(r.num_turns) },
        { key: 'cost', header: 'cost', num: true, sort: (r) => r.cost_usd ?? -1, render: (r) => (r.cost_usd == null ? '—' : usd(r.cost_usd)) },
        { key: 'dur', header: 'time', num: true, sort: (r) => r.duration_ms ?? -1, render: (r) => duration(r.duration_ms) },
        { key: 'trace', header: 'trace', render: (r) => (r.trace_id ? <Mono>{r.trace_id.slice(0, 12)}…</Mono> : <Text size="xs" c="dimmed">not exported</Text>) },
        { key: 'when', header: 'created', sort: (r) => r.created_at ?? '', render: (r) => <Text size="xs" c="dimmed">{(r.created_at ?? '').replace('T', ' ').slice(0, 16)}</Text> },
      ]}
    />
  );
}

export function LinesTable({ rows, showRepo = true }: { rows: LakeLine[]; showRepo?: boolean }) {
  return (
    <DataTable<LakeLine>
      rows={rows}
      keys={showRepo}
      rowKey={(w) => `${w.nwo}:${w.path}`}
      onActivate={(w) => window.open(gh.workflow(w.nwo, w.path), '_blank', 'noopener')}
      tone={(w) => (w.last_conclusion === 'failure' ? 'crit' : undefined)}
      empty="no lines match — sync the lake first"
      minWidth={1000}
      columns={[
        ...(showRepo ? [{ key: 'repo', header: 'repo', sort: (w: LakeLine) => w.nwo, render: (w: LakeLine) => <Anchor component={Link} to={to.project(w.nwo.split('/').pop() ?? '')} ff="monospace" fz="sm">{w.nwo}</Anchor> }] : []),
        { key: 'wf', header: 'workflow', sort: (w) => w.path, render: (w) => <External href={gh.workflow(w.nwo, w.path)} size="sm">{w.path.replace('.github/workflows/', '')}</External> },
        { key: 'kind', header: 'kind', sort: (w) => w.kind ?? '', render: (w) => (w.ai ? <Text size="sm">{w.kind === 'mention-handler' ? '💬' : w.kind === 'scheduled-agent' ? '⏰' : '⚙️'} {w.kind}</Text> : <Text size="xs" c="dimmed">non-AI</Text>) },
        { key: 'line', header: 'line', render: (w) => (w.factory_blueprint ? <Mono>⚙ {w.factory_blueprint.replace('.factory/', '')}@{w.factory_hash ?? '?'}{w.blueprint_in_lake ? ' ✓' : ''}</Mono> : <Text size="xs" c="dimmed">hand-built</Text>) },
        { key: 'gate', header: 'gate', render: (w) => (w.switch ? <Status tone="good">{w.switch}</Status> : w.kind === 'scheduled-agent' ? <Status tone="warn">no switch</Status> : <Text size="xs" c="dimmed">—</Text>) },
        { key: 'trig', header: 'triggers / crons', render: (w) => { const c = parseList(w.crons); return <Text size="xs">{parseList(w.triggers).join(', ')}{c.length ? <Mono> {c.join(' | ')}</Mono> : null}</Text>; } },
        { key: 'model', header: 'model', render: (w) => <Text size="sm">{w.model ?? '—'}{w.max_turns ? ` / ${w.max_turns}t` : ''}</Text> },
        { key: 'auth', header: 'auth', render: (w) => (w.ai ? (/oauth/.test(w.auth ?? '') ? <Status tone="good">{w.auth}</Status> : <Status tone="crit">{w.auth || 'none'}</Status>) : null) },
        { key: 'last', header: 'last', sort: (w) => w.last_conclusion ?? '', render: (w) => <Conclusion value={w.last_conclusion} /> },
        { key: 'runs', header: 'runs', num: true, sort: (w) => w.runs ?? 0, render: (w) => fmt(w.runs) },
      ]}
    />
  );
}

function ContentTab({ name }: { name: string }) {
  const content = useContent();
  return (
    <Load q={content}>
      {(c) => {
        const all = ((c.sites ?? c.declared ?? []) as Dict<any>[]);
        const mine = all.filter((s) => String(s.repo ?? '').toLowerCase().endsWith(`/${name.toLowerCase()}`) || (s.site ?? s.name) === name);
        if (!mine.length) return <Empty>This project is not a declared content site (_data/fleet.yml content.sites).</Empty>;
        return (
          <Stack gap="xs">
            {mine.map((s) => {
              const site = String(s.site ?? s.name);
              return (
                <Paper key={site} p="md" component={Link} to={to.site(site)} style={{ textDecoration: 'none', color: 'inherit' }}>
                  <Group justify="space-between">
                    <Text fw={600}>{site}</Text>
                    <Text size="sm" c="dimmed">{s.totals ? `${fmt(s.totals.docs)} documents · ${fmt((s.suggestions ?? []).length)} suggestions` : 'not synced yet'}</Text>
                  </Group>
                </Paper>
              );
            })}
          </Stack>
        );
      }}
    </Load>
  );
}

function RegistryFacts({ d }: { d: ProjectDetail }) {
  const skip = new Set(['name', 'description']);
  const rows = Object.entries(d.registry).filter(([k, v]) => !skip.has(k) && v !== null && v !== '' && !(Array.isArray(v) && !v.length));
  return (
    <Table className="dt" verticalSpacing={4}>
      <Table.Tbody>
        {rows.map(([k, v]) => (
          <Table.Tr key={k}>
            <Table.Td w={180}><Mono dim>{k}</Mono></Table.Td>
            <Table.Td className="wrap-anywhere">
              {typeof v === 'string' && /^https?:\/\//.test(v) ? <External href={v} size="sm">{v}</External>
                : Array.isArray(v) ? <Text size="sm">{v.map(String).join(', ')}</Text>
                  : typeof v === 'object' ? <Mono>{JSON.stringify(v)}</Mono>
                    : <Text size="sm">{String(v)}</Text>}
            </Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}

function Signals({ d }: { d: ProjectDetail }) {
  const r = d.row;
  const h = d.harness;
  return (
    <>
      <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }} spacing="md">
        <StatTile label="Health" value={<LevelDot level={r?.health} label={r?.health ?? 'unknown'} />} sub={(r?.reasons ?? []).join(' · ') || 'live monitor signal'} />
        <StatTile label="CI" value={r?.ci_last ?? '—'} sub={r?.ci_pass != null ? `${r.ci_pass}% pass rate` : 'no CI data'} tone={r?.ci_last === 'failure' ? 'crit' : undefined} />
        <StatTile label="Triage" value={<LevelDot level={r?.triage_level} label={r?.triage_score ?? '—'} />} sub={(r?.triage_reasons ?? []).join(' · ') || 'open-state score'} />
        <StatTile label="Open work" value={`${fmt(r?.triage_issues ?? r?.issues_open)} · ${fmt(r?.triage_prs ?? r?.prs_open)}`} sub="issues · pull requests" href={`?tab=work`} />
        <StatTile label="Failing workflows" value={fmt(r?.failing.length ?? 0)} tone={r?.failing.length ? 'crit' : undefined} href={`?tab=work`} sub="latest run failed" />
        <StatTile label="Last commit" value={r?.last_commit_days == null ? '—' : `${r.last_commit_days}d ago`} sub={`${fmt(r?.commits_30d)} commits in 30 days`} />
        <StatTile label="AI harnesses" value={fmt(h?.harnesses?.length ?? 0)} href={`?tab=harness`}
          sub={h ? (h.coverage?.exempt ? 'exempt from baseline' : h.coverage?.ok ? 'at baseline' : `missing: ${(h.coverage?.missing ?? []).join(', ')}`) : 'not in the harness inventory'} />
        <StatTile label="Containers" value={r?.docker_total ? `${r.docker_up}/${r.docker_total}` : '—'} sub={r?.docker_status ?? 'none seen on the Docker hosts'} href={to.containers()} />
      </SimpleGrid>
      {r?.failing.length ? (
        <Section title="Failing workflows">
          <Stack gap={4}>{r.failing.map((f) => <External key={f.url} href={f.url} size="sm">{f.workflow}</External>)}</Stack>
        </Section>
      ) : null}
      {d.attention.length ? (
        <Section title="Attention" description="Findings from the harness inventory that name this project.">
          <AttentionTable rows={d.attention} showRepo={false} />
        </Section>
      ) : null}
      <Section title="Registry" description="_data/projects.yml — edit the registry to change any of this; every surface follows.">
        <Paper p="xs"><RegistryFacts d={d} /></Paper>
      </Section>
    </>
  );
}

function Actions({ d }: { d: ProjectDetail }) {
  const n = d.name;
  return (
    <Stack gap="lg">
      <Section mt={0} title="Harness kit" description="Deploy the agent-context kit to this repo. A dry run lists what the PR would contain; apply opens the PR (confirm-gated).">
        <Group gap="xs">
          <RunButton op="deploy-target" params={{ target: n, artifacts: 'claude' }}>Deploy kit — dry run</RunButton>
          <RunButton op="deploy-target" params={{ target: n, artifacts: 'claude', upgrade: true }}>Upgrade seeds — dry run</RunButton>
          <RunButton op="deploy-target" params={{ target: n, artifacts: 'claude', apply: true }}>Deploy kit — open PR</RunButton>
        </Group>
      </Section>
      <Section mt={0} title="Claude auth" description="Resolve which Claude credential this repo tries first, and project CLAUDE_AUTH_ORDER onto it.">
        <Group gap="xs">
          <RunButton op="ai-auth" params={{ target: n }}>Resolve auth order</RunButton>
          <RunButton op="ai-auth-sync" params={{ target: n }}>Sync — dry run</RunButton>
          <RunButton op="ai-auth-sync" params={{ target: n, apply: true }}>Sync CLAUDE_AUTH_ORDER</RunButton>
        </Group>
      </Section>
      <Section mt={0} title="Data" description="Pull this repo's runs, logs and workflows into the local lake; review its agent activity.">
        <Group gap="xs">
          <RunButton op="lake-sync" params={{ target: n, days: '14' }}>Sync lake (14 days)</RunButton>
          <RunButton op="lake-review" params={{ target: n }}>Review agent activity</RunButton>
          <RunButton op="observe-ship" params={{ target: n, dry_run: true }}>Ship logs — dry run</RunButton>
        </Group>
      </Section>
      <Section mt={0} title="Evolution" description="Dispatch the repo-evolution loop for this repo only (dry run).">
        <Group gap="xs">
          <RunButton op="dispatch" params={{ workflow: 'repo-evolution', fields: { target: n, dry_run: 'true' } }}>Dispatch repo-evolution (dry run)</RunButton>
        </Group>
      </Section>
    </Stack>
  );
}

export function ProjectPage() {
  const { name = '' } = useParams();
  const [sp, setSp] = useSearchParams();
  const tab = sp.get('tab') ?? 'overview';
  const q = useProject(name);
  const row = q.data?.row;
  useKeyScope({
    open: () => row?.repo_url && window.open(row.repo_url, '_blank', 'noopener'),
    openLive: () => row?.live_url && window.open(row.live_url, '_blank', 'noopener'),
    copy: () => row?.repo_url && void navigator.clipboard?.writeText(row.repo_url),
  });

  return (
    <>
      <PageHeader
        crumbs={[{ label: 'Projects', to: to.projects() }, { label: name }]}
        title={name}
        badges={row ? (
          <>
            <LevelDot level={row.worst_level} label={row.worst_level ?? 'no signal'} />
            {row.status ? <Badge variant="default">{row.status}</Badge> : null}
            {row.category ? <Badge variant="light">{row.category}</Badge> : null}
            {row.featured ? <Badge color="yellow" variant="light">featured</Badge> : null}
          </>
        ) : null}
        description={row?.description}
        actions={row ? (
          <>
            <External href={row.repo_url} size="sm">repository</External>
            {row.live_url ? <External href={row.live_url} size="sm">live site</External> : null}
            {row.docs_url ? <External href={row.docs_url} size="sm">docs</External> : null}
          </>
        ) : null}
      />
      {row?.stack?.length ? <Group gap={6} mb="md">{row.stack.map((s) => <Badge key={s} variant="outline" size="sm">{s}</Badge>)}</Group> : null}
      <Load q={q} rows={8}>
        {(d) => (
          <Tabs value={tab} onChange={(v) => setSp(v && v !== 'overview' ? { tab: v } : {}, { replace: true })} keepMounted={false}>
            <Tabs.List mb="md">
              <Tabs.Tab value="overview">Overview</Tabs.Tab>
              <Tabs.Tab value="work">Open work <Badge size="xs" variant="light" ml={4}>{d.inbox.length}</Badge></Tabs.Tab>
              <Tabs.Tab value="harness">Harness</Tabs.Tab>
              <Tabs.Tab value="schedule">Schedule <Badge size="xs" variant="light" ml={4}>{d.schedule.length}</Badge></Tabs.Tab>
              <Tabs.Tab value="runs">Runs</Tabs.Tab>
              <Tabs.Tab value="workflows">Workflows</Tabs.Tab>
              <Tabs.Tab value="github">GitHub</Tabs.Tab>
              <Tabs.Tab value="content">Content</Tabs.Tab>
              <Tabs.Tab value="act">Act</Tabs.Tab>
            </Tabs.List>
            <Tabs.Panel value="overview"><Signals d={d} /></Tabs.Panel>
            <Tabs.Panel value="work">
              <Text size="sm" c="dimmed" mb="sm">Every open item this repo carries (fleet_triage.yml by_repo), ranked with the inbox's priorities. Enter or click opens it on GitHub.</Text>
              <InboxTable rows={d.inbox} />
            </Tabs.Panel>
            <Tabs.Panel value="harness">
              {d.harness ? (
                <Stack gap="md">
                  <Group gap="xs" wrap="wrap">
                    {d.harness.coverage?.exempt ? <Status tone="info">exempt from baseline</Status> : d.harness.coverage?.ok ? <Status tone="good">at baseline</Status>
                      : (d.harness.coverage?.missing ?? []).map((m) => <Status key={m} tone="warn">missing {m}</Status>)}
                    <Status tone={['ok', 'hub'].includes(d.harness.oauth_secret ?? '') ? 'good' : d.harness.oauth_secret === 'stale' ? 'warn' : 'crit'}>OAuth secret: {d.harness.oauth_secret ?? '—'}</Status>
                    <Text size="sm" c="dimmed">agent context {d.harness.agent_context ?? '—'} · {fmt(d.harness.workflows_total)} workflows · AI cost in window {usd(d.harness.ai_usage?.cost_usd)} over {fmt(d.harness.ai_usage?.runs)} runs</Text>
                  </Group>
                  <HarnessWorkflows repo={d.harness} />
                  <Anchor component={Link} to={to.harnesses()} size="sm">See the whole fleet's inventory</Anchor>
                </Stack>
              ) : <Banner tone="info">Not in the harness inventory — refresh it from the Inventory page.</Banner>}
            </Tabs.Panel>
            <Tabs.Panel value="schedule">
              <ScheduleTable rows={d.schedule} />
              <Anchor component={Link} to={to.schedules()} size="sm" mt="xs" display="block">The fleet calendar and per-hour caps</Anchor>
            </Tabs.Panel>
            <Tabs.Panel value="runs">
              <Text size="sm" c="dimmed" mb="sm">This repo's workflow runs in the local data lake, agent runs (with parsed model, turns and cost) first.</Text>
              <RunsTable rows={d.lake_runs} showRepo={false} />
            </Tabs.Panel>
            <Tabs.Panel value="workflows">
              <LinesTable rows={d.lake_lines} showRepo={false} />
            </Tabs.Panel>
            <Tabs.Panel value="github">
              {(() => {
                const m = /^https?:\/\/github\.com\/([^/]+\/[^/#?]+?)(?:\.git)?\/?$/.exec(String(d.row?.repo_url ?? d.registry.repo_url ?? ''));
                return m ? <RepoManager nwo={m[1]} /> : <Banner tone="info">This project's repo is not on github.com.</Banner>;
              })()}
            </Tabs.Panel>
            <Tabs.Panel value="content"><ContentTab name={name} /></Tabs.Panel>
            <Tabs.Panel value="act"><Actions d={d} /></Tabs.Panel>
          </Tabs>
        )}
      </Load>
    </>
  );
}
