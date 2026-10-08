// The fleet's AI harness deployment matrix (_data/harness_registry.yml):
// per repo, which harness workflows run, with what auth, kit version, agent
// context and secret state — graded against fleet.yml `harnesses:`. A repo
// opens its project page on the Harness tab; deploys are dry runs unless you
// tick apply.
import { useSearchParams } from 'react-router';
import { Checkbox, Code, Group, Paper, SegmentedControl, Stack, Text, TextInput } from '@mantine/core';
import { IconSearch } from '@tabler/icons-react';
import { useState } from 'react';
import { useStateDoc } from '../api/hooks';
import type { HarnessRepo } from '../api/types';
import { DataTable } from '../components/DataTable';
import { Load, PageHeader, Status } from '../components/ui';
import { RunButton } from '../jobs/RunButton';
import { fmt, includesText, usd } from '../lib/format';
import { to } from '../lib/links';

export function Inventory() {
  const state = useStateDoc();
  const [sp, setSp] = useSearchParams();
  const view = sp.get('view') ?? 'ai';
  const [q, setQ] = useState('');
  const [artifacts, setArtifacts] = useState('claude');
  const [upgrade, setUpgrade] = useState(false);
  const [apply, setApply] = useState(false);

  return (
    <Load q={state}>
      {(s) => {
        const hr = s.harnesses ?? {};
        const c = hr.contract ?? {};
        const repos = hr.repos ?? [];
        const gap = (r: HarnessRepo) => !(r.coverage?.exempt || r.coverage?.ok);
        const rows = repos.filter((r) => {
          if (view === 'gaps' && !gap(r)) return false;
          if (view === 'ai' && !(r.harnesses ?? []).length && !gap(r)) return false;
          return includesText([r.repo, ...(r.harnesses ?? []).map((h) => `${h.path} ${h.kind} ${h.model ?? ''}`)], q);
        });
        return (
          <>
            <PageHeader
              title="Harness inventory"
              description={<>Every repo's AI harnesses graded against the contract: kit <Code>{c.kit} v{c.kit_version}</Code>, baseline {Object.entries(c.baseline ?? {}).filter(([, v]) => v).map(([k]) => k.replace('require_', '')).join(', ') || '—'}, exempt {(c.exempt ?? []).join(', ') || 'none'}. {repos.filter(gap).length} repos have gaps; {fmt(hr.totals?.kit_upgradeable)} machine seeds are upgradeable.</>}
              actions={
                <>
                  <RunButton op="harnesses" variant="filled">Refresh (live scan)</RunButton>
                  <RunButton op="harnesses-offline">Offline analytics</RunButton>
                  <RunButton op="gaps">List gap repos</RunButton>
                </>
              }
            />
            <Paper p="md" mb="md">
              <Stack gap="xs">
                <Text fw={600} size="sm">Deploy the agent-context kit to every gap repo</Text>
                <Group gap="md" wrap="wrap" align="flex-end">
                  <TextInput label="Artifacts" value={artifacts} onChange={(e) => setArtifacts(e.currentTarget.value)} w={220} />
                  <Checkbox label="Upgrade machine seeds" checked={upgrade} onChange={(e) => setUpgrade(e.currentTarget.checked)} />
                  <Checkbox label="Apply — open the PRs" color="red" checked={apply} onChange={(e) => setApply(e.currentTarget.checked)} />
                  <RunButton op="deploy-gaps" params={{ artifacts, upgrade, apply }} variant="filled">Deploy to gap repos{apply ? '' : ' (dry run)'}</RunButton>
                  <RunButton op="dispatch" params={{ workflow: 'harness-fanout', fields: { target: 'gaps', artifacts, dry_run: String(!apply), upgrade: String(upgrade) } }}>Dispatch harness-fanout in CI</RunButton>
                </Group>
              </Stack>
            </Paper>
            <Group gap="sm" mb="sm" wrap="wrap">
              <TextInput data-page-search leftSection={<IconSearch size={15} />} placeholder="Filter repo / workflow / kind…  ( / )" value={q} onChange={(e) => setQ(e.currentTarget.value)} w={300} />
              <SegmentedControl size="xs" value={view} onChange={(v) => setSp(v === 'ai' ? {} : { view: v }, { replace: true })}
                data={[{ label: 'With harnesses or gaps', value: 'ai' }, { label: 'Gaps only', value: 'gaps' }, { label: 'All repos', value: 'all' }]} />
              <Text size="sm" c="dimmed">{rows.length} of {repos.length} repos</Text>
            </Group>
            <DataTable<HarnessRepo>
              rows={rows}
              keys
              rowKey={(r) => r.repo}
              href={(r) => to.project(r.repo, 'harness')}
              open={(r) => `https://github.com/${r.nwo}`}
              tone={(r) => (gap(r) ? 'warn' : undefined)}
              minWidth={1100}
              columns={[
                {
                  key: 'repo', header: 'repo', sort: (r) => r.repo, render: (r) => (
                    <div>
                      <Text fw={600} size="sm" ff="monospace">{r.repo}</Text>
                      <Text size="xs" c="dimmed">{[r.manifest && 'manifest', r.factory && 'GitFactory', r.external && 'external', r.archived && 'archived'].filter(Boolean).join(' · ')}</Text>
                    </div>
                  ),
                },
                {
                  key: 'wf', header: 'harness workflows', sort: (r) => (r.harnesses ?? []).length, render: (r) => (r.harnesses ?? []).length ? (
                    <Stack gap={2}>
                      {(r.harnesses ?? []).map((h) => (
                        <Text key={h.path} size="xs">
                          {h.kind === 'mention-handler' ? '💬' : h.kind === 'scheduled-agent' ? '⏰' : '⚙️'} <Text span ff="monospace" fz={12}>{h.path.replace('.github/workflows/', '')}</Text>
                          {h.model ? <Text span c="dimmed" fz={11}> {h.model}{h.max_turns ? `/${h.max_turns}t` : ''}</Text> : null}
                          {h.last_conclusion === 'failure' ? <> <Status tone="crit">failing</Status></> : null}
                        </Text>
                      ))}
                    </Stack>
                  ) : <Text size="xs" c="dimmed">—</Text>,
                },
                { key: 'auth', header: 'auth', render: (r) => <Stack gap={2}>{(r.harnesses ?? []).map((h) => <div key={h.path}>{/oauth/.test(h.auth ?? '') ? <Status tone="good">{h.auth}</Status> : <Status tone="crit">{h.auth || 'none'}</Status>}</div>)}</Stack> },
                { key: 'kit', header: 'kit', render: (r) => <Stack gap={2}>{(r.harnesses ?? []).map((h) => <div key={h.path}>{h.kit_status === 'current' ? <Status tone="good">v{h.kit}</Status> : h.kit_status === 'upgradeable' ? <Status tone="warn">v{h.kit} ↑</Status> : <Text size="xs" c="dimmed">{h.kit_status}</Text>}</div>)}</Stack> },
                { key: 'ctx', header: 'context', sort: (r) => r.agent_context ?? '', render: (r) => <Text size="xs" ff="monospace">{r.agent_context ?? '—'}</Text> },
                { key: 'oauth', header: 'OAuth secret', sort: (r) => r.oauth_secret ?? '', render: (r) => ['ok', 'hub'].includes(r.oauth_secret ?? '') ? <Status tone="good">{r.oauth_secret}</Status> : r.oauth_secret === 'stale' ? <Status tone="warn">stale</Status> : r.oauth_secret === 'missing' ? <Status tone="crit">missing</Status> : <Text size="xs" c="dimmed">{r.oauth_secret}</Text> },
                { key: 'sched', header: 'sched AI/d', num: true, sort: (r) => r.est_scheduled_ai_per_day ?? 0, render: (r) => fmt(r.est_scheduled_ai_per_day) },
                { key: 'cost', header: 'AI cost', num: true, sort: (r) => r.ai_usage?.cost_usd ?? -1, render: (r) => (r.ai_usage?.cost_usd != null ? usd(r.ai_usage.cost_usd) : '—') },
                { key: 'base', header: 'baseline', sort: (r) => (gap(r) ? 0 : 1), render: (r) => (r.coverage?.exempt ? <Status tone="info">exempt</Status> : r.coverage?.ok ? <Status tone="good">ok</Status> : <Group gap={4}>{(r.coverage?.missing ?? []).map((m) => <Status key={m} tone="warn">{m}</Status>)}</Group>) },
              ]}
            />
          </>
        );
      }}
    </Load>
  );
}
