// Claude activity on both planes, from the local lake (/api/lake/review — pure
// SQL, no network): this machine's Claude Code sessions and the CI agent runs
// claude-code-action produced. Cost, turns, tool use and failures, and the
// ranked findings. Repos open their project page; runs open on GitHub.
import { Link } from 'react-router';
import { Anchor, Group, NumberInput, Paper, SimpleGrid, Stack, Text } from '@mantine/core';
import { useState } from 'react';
import { useLakeReview } from '../api/hooks';
import type { Dict } from '../api/types';
import { HBars } from '../components/Charts';
import { DataTable } from '../components/DataTable';
import { Banner, Conclusion, External, Load, Mono, PageHeader, Section, StatTile, Status } from '../components/ui';
import { RunButton } from '../jobs/RunButton';
import { duration, fmt, repoName, usd } from '../lib/format';
import { to } from '../lib/links';

type Row = Dict<any>;

export function Activity() {
  const [days, setDays] = useState(30);
  const review = useLakeReview(days);
  return (
    <>
      <PageHeader
        title="Agent activity"
        description="Both planes Claude runs in, unified: this machine's Claude Code sessions (extracted from ~/.claude) and the fleet's CI agent runs (extracted from run logs). Extract first, then this review is reproducible offline."
        actions={
          <>
            <NumberInput aria-label="window in days" value={days} onChange={(v) => setDays(Number(v) || 30)} min={1} max={365} w={110} size="xs" suffix=" days" />
            <RunButton op="lake-sessions" params={{ days: String(days) }}>Extract local sessions</RunButton>
            <RunButton op="lake-sync" params={{ days: String(Math.min(days, 90)) }}>Sync CI runs</RunButton>
          </>
        }
      />
      <Load q={review} rows={6}>
        {(r) => {
          const local = (r.local ?? {}) as Row;
          const ci = (r.ci ?? {}) as Row;
          const totals = (r.totals ?? {}) as Row;
          const findings = (r.findings ?? []) as Row[];
          return (
            <>
              {r.present === false ? <Banner tone="warn" title="The lake is not readable">{String(r.error ?? 'build it first with Sync CI runs')}</Banner> : null}
              <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }} spacing="md">
                <StatTile label="Total agent cost" value={usd(totals.cost_usd)} sub={`${fmt(totals.turns)} turns · ${fmt(totals.traces)} traced, ${fmt(totals.untraced)} not`} />
                <StatTile label="Local sessions" value={fmt(local.sessions)} sub={`${usd(local.cost_usd)} · ${fmt(local.tool_calls)} tool calls · ${fmt(local.tool_errors)} errors`} />
                <StatTile label="CI agent runs" value={fmt(ci.agent_runs)} sub={`${usd(ci.cost_usd)} · ${fmt(ci.turns)} turns · ${fmt(ci.denials)} permission denials`} />
                <StatTile label="Failed AI workflow runs" value={`${fmt(ci.failed_runs)} / ${fmt(ci.runs)}`} tone={ci.failed_runs ? 'crit' : undefined} sub="in the window" href={to.observe('lines')} />
              </SimpleGrid>
              <Section title="Findings">
                <Stack gap="xs">
                  {findings.length ? findings.map((f, i) => (
                    <Paper key={i} p="sm">
                      <Group gap="xs" wrap="nowrap" align="flex-start">
                        <Status tone={f.severity === 'error' ? 'crit' : f.severity === 'warn' ? 'warn' : 'info'}>{String(f.severity)}</Status>
                        <div>
                          <Text size="sm" fw={600}>{String(f.title)} <Text span size="xs" c="dimmed">({String(f.plane)})</Text></Text>
                          <Text size="xs" c="dimmed">{String(f.detail ?? '')}</Text>
                        </div>
                      </Group>
                    </Paper>
                  )) : <Text size="sm" c="dimmed">No findings.</Text>}
                </Stack>
              </Section>
              <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="lg">
                <Section title="CI cost by repo">
                  <DataTable<Row>
                    rows={(ci.repos ?? []) as Row[]}
                    rowKey={(x) => String(x.repo)}
                    href={(x) => to.project(repoName(String(x.repo)), 'runs')}
                    initialSort={{ key: 'cost', desc: true }}
                    empty="no CI agent runs in the lake"
                    columns={[
                      { key: 'repo', header: 'repo', sort: (x) => String(x.repo), render: (x) => <Mono>{String(x.repo)}</Mono> },
                      { key: 'runs', header: 'runs', num: true, sort: (x) => Number(x.runs), render: (x) => fmt(x.runs) },
                      { key: 'turns', header: 'turns', num: true, sort: (x) => Number(x.turns), render: (x) => fmt(x.turns) },
                      { key: 'cost', header: 'cost', num: true, sort: (x) => Number(x.cost_usd), render: (x) => usd(x.cost_usd) },
                    ]}
                  />
                </Section>
                <Section title="Local cost by repo">
                  <DataTable<Row>
                    rows={(local.repos ?? []) as Row[]}
                    rowKey={(x) => String(x.repo)}
                    href={(x) => (x.repo ? to.project(repoName(String(x.repo))) : null)}
                    initialSort={{ key: 'cost', desc: true }}
                    empty="no local sessions in the lake"
                    columns={[
                      { key: 'repo', header: 'repo', sort: (x) => String(x.repo), render: (x) => <Mono>{String(x.repo ?? '—')}</Mono> },
                      { key: 'sessions', header: 'sessions', num: true, sort: (x) => Number(x.sessions), render: (x) => fmt(x.sessions) },
                      { key: 'turns', header: 'turns', num: true, sort: (x) => Number(x.turns), render: (x) => fmt(x.turns) },
                      { key: 'cost', header: 'cost', num: true, sort: (x) => Number(x.cost_usd), render: (x) => usd(x.cost_usd) },
                    ]}
                  />
                </Section>
              </SimpleGrid>
              <Section title="Most expensive CI agent runs">
                <DataTable<Row>
                  rows={(ci.top_runs ?? []) as Row[]}
                  rowKey={(x) => String(x.id)}
                  onActivate={(x) => x.html_url && window.open(String(x.html_url), '_blank', 'noopener')}
                  tone={(x) => (x.is_error ? 'crit' : undefined)}
                  empty="none"
                  minWidth={860}
                  columns={[
                    { key: 'repo', header: 'repo', render: (x) => <Anchor component={Link} to={to.project(repoName(String(x.nwo)))} ff="monospace" fz="sm">{String(x.nwo)}</Anchor> },
                    { key: 'wf', header: 'workflow', render: (x) => <External href={String(x.html_url ?? '')} size="sm">{String(x.workflow_name)}</External> },
                    { key: 'c', header: 'conclusion', render: (x) => <Conclusion value={x.conclusion} /> },
                    { key: 'model', header: 'model', render: (x) => <Text size="sm">{String(x.model ?? '—')}</Text> },
                    { key: 'turns', header: 'turns', num: true, render: (x) => fmt(x.num_turns) },
                    { key: 'den', header: 'denials', num: true, render: (x) => fmt(x.permission_denials) },
                    { key: 'dur', header: 'time', num: true, render: (x) => duration(x.duration_ms) },
                    { key: 'cost', header: 'cost', num: true, render: (x) => usd(x.cost_usd) },
                  ]}
                />
              </Section>
              <Section title="Most expensive local sessions">
                <DataTable<Row>
                  rows={(local.top_sessions ?? []) as Row[]}
                  rowKey={(x) => String(x.key)}
                  empty="none"
                  minWidth={860}
                  columns={[
                    { key: 'repo', header: 'repo', render: (x) => (x.repo ? <Anchor component={Link} to={to.project(repoName(String(x.repo)))} ff="monospace" fz="sm">{String(x.repo)}</Anchor> : '—') },
                    { key: 'branch', header: 'branch', render: (x) => <Mono dim>{String(x.git_branch ?? '')}</Mono> },
                    { key: 'prompt', header: 'first prompt', render: (x) => <Text size="xs" lineClamp={2}>{String(x.first_prompt ?? '')}</Text> },
                    { key: 'turns', header: 'turns', num: true, render: (x) => fmt(x.turns) },
                    { key: 'tools', header: 'tools', num: true, render: (x) => `${fmt(x.tool_calls)}${x.tool_errors ? ` (${x.tool_errors} err)` : ''}` },
                    { key: 'cost', header: 'cost', num: true, render: (x) => usd(x.cost_usd) },
                    { key: 'when', header: 'started', render: (x) => <Text size="xs" c="dimmed">{String(x.started_at ?? '').replace('T', ' ').slice(0, 16)}</Text> },
                  ]}
                />
              </Section>
              <Section title="Local tool use" description="Calls per tool, with errors — a tool that fails often is a harness gap.">
                <Paper p="md">
                  <HBars rows={((local.tools ?? []) as Row[]).slice(0, 20)} label="name" value="calls" extra={(x) => (x.errors ? ` · ${x.errors} errors` : '')} />
                </Paper>
              </Section>
            </>
          );
        }}
      </Load>
    </>
  );
}
