// The fleet's harness inventory (_data/harness_registry.yml), in two views.
//
// Harnesses: every AI workflow in the fleet, one row each — how it reaches a
// model (its route), what it is capped at, and its verdict against the harness
// standard (fleet.yml `harnesses.standard`). The rebuild plan above the table
// groups the ones that fall short by the lever that fixes them.
//
// Repos: the per-repo baseline (does the repo HAVE a mention handler, agent
// context and the OAuth secret) and the kit deploy, which is a dry run unless
// you tick apply.
import { useSearchParams } from 'react-router';
import { Anchor, Checkbox, Code, Group, Paper, SegmentedControl, SimpleGrid, Stack, Table, Text, TextInput } from '@mantine/core';
import { IconSearch } from '@tabler/icons-react';
import { useState } from 'react';
import { useStateDoc } from '../api/hooks';
import type { HarnessCatalog, HarnessRepo, HarnessStandard, HarnessWorkflow } from '../api/types';
import { DataTable } from '../components/DataTable';
import { Conclusion, Empty, Load, PageHeader, Section, StatTile, Status } from '../components/ui';
import type { Tone } from '../components/ui';
import { RunButton } from '../jobs/RunButton';
import { fmt, includesText, usd } from '../lib/format';
import { gh, to } from '../lib/links';

type Row = HarnessWorkflow & { repo: HarnessRepo };

const KINDS: { value: string; label: string; icon: string }[] = [
  { value: 'mention-handler', label: 'Mention handlers', icon: '💬' },
  { value: 'scheduled-agent', label: 'Scheduled agents', icon: '⏰' },
  { value: 'event-agent', label: 'Event agents', icon: '⚙️' },
];
const kindIcon = (kind: string) => KINDS.find((k) => k.value === kind)?.icon ?? '⚙️';

/** Levers in the order a person would work them: the cheapest, widest fix first. */
const LEVER_ORDER = ['kit-upgrade', 'fix-controls', 'hub-fix', 'kit-adopt', 'lane-adopt', 'factory-recompile', 'retire'];
const leverTone = (lever?: string | null): Tone => (lever === 'none' ? 'good' : lever === 'retire' ? 'info' : 'warn');

const retired = (r: HarnessRepo) => Boolean(r.archived) || r.status === 'archived';
const gap = (r: HarnessRepo) => !(r.coverage?.exempt || r.coverage?.ok);

/** What a harness is capped at, as one short string: model / turns / dollars. */
function caps(h: HarnessWorkflow): string {
  const model = h.model ?? (h.model_source === 'route' ? 'route default' : h.model_source === 'expression' ? 'set at run time' : null);
  return [model, h.max_turns ? `${h.max_turns}t` : null, h.max_budget_usd != null ? `$${h.max_budget_usd}` : null].filter(Boolean).join(' / ');
}

function Verdict({ h, controls }: { h: HarnessWorkflow; controls: HarnessStandard['controls'] }) {
  const v = h.standard;
  if (!v) return <Text size="xs" c="dimmed">not graded</Text>;
  if (v.conformant) return <Status tone="good">{v.met}/{v.of}</Status>;
  return (
    <Group gap={4} wrap="wrap">
      <Status tone="warn">{v.met}/{v.of}</Status>
      {v.missing.map((m) => <Text key={m} size="xs" c="dimmed" title={controls?.[m]?.title}>{m}</Text>)}
    </Group>
  );
}

/** The rebuild plan: one row per lever, with what its group still misses. */
function Plan({ rows, catalog, lever, pick }: { rows: Row[]; catalog: HarnessCatalog; lever: string; pick: (l: string) => void }) {
  const levers = LEVER_ORDER.filter((l) => (catalog.by_lever?.[l] ?? 0) > 0);
  if (!levers.length) return <Empty>Every graded harness is on the standard.</Empty>;
  return (
    <Table.ScrollContainer minWidth={640}>
      <Table verticalSpacing={6} fz="sm">
        <Table.Thead>
          <Table.Tr>
            <Table.Th miw={190}>lever</Table.Th>
            <Table.Th ta="right">harnesses</Table.Th>
            <Table.Th miw={200}>what the group is missing</Table.Th>
            <Table.Th>how it is rebuilt</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {levers.map((l) => {
            const group = rows.filter((r) => r.lever === l);
            const tally = new Map<string, number>();
            group.forEach((r) => (r.standard?.missing ?? []).forEach((m) => tally.set(m, (tally.get(m) ?? 0) + 1)));
            const top = [...tally.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 4);
            return (
              <Table.Tr key={l} bg={lever === l ? 'var(--mantine-color-default-hover)' : undefined}>
                <Table.Td>
                  <Anchor component="button" type="button" size="sm" fw={600} ta="left" onClick={() => pick(lever === l ? '' : l)} aria-pressed={lever === l}>
                    {catalog.levers?.[l]?.title ?? l}
                  </Anchor>
                </Table.Td>
                <Table.Td ta="right">{catalog.by_lever?.[l]}</Table.Td>
                <Table.Td><Text size="xs" c="dimmed">{top.length ? top.map(([m, n]) => `${m} (${n})`).join(' · ') : l === 'retire' ? 'in an archived repo' : 'behind the current kit'}</Text></Table.Td>
                <Table.Td>
                  <Stack gap={4} align="flex-start">
                    <Text size="xs">{catalog.levers?.[l]?.action}</Text>
                    {l === 'kit-upgrade' ? <RunButton op="deploy-gaps" params={{ artifacts: 'claude', upgrade: true, apply: false }} size="compact-xs">Upgrade seeds (dry run)</RunButton> : null}
                  </Stack>
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

/** The standard itself: each control, the rule it comes from, and how many harnesses miss it. */
function Controls({ standard, catalog, missing, pick }: { standard: HarnessStandard; catalog: HarnessCatalog; missing: string; pick: (c: string) => void }) {
  const controls = Object.entries(standard.controls ?? {});
  if (!controls.length) return null;
  return (
    <Table.ScrollContainer minWidth={640}>
      <Table verticalSpacing={4} fz="sm">
        <Table.Thead>
          <Table.Tr>
            <Table.Th miw={150}>control</Table.Th>
            <Table.Th miw={200}>what it asks</Table.Th>
            <Table.Th>from</Table.Th>
            <Table.Th ta="right">missing</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {controls.map(([id, c]) => {
            const n = catalog.missing_by_control?.[id] ?? 0;
            return (
              <Table.Tr key={id} bg={missing === id ? 'var(--mantine-color-default-hover)' : undefined}>
                <Table.Td>
                  <Anchor component="button" type="button" size="sm" ff="monospace" ta="left" onClick={() => pick(missing === id ? '' : id)} aria-pressed={missing === id}>{id}</Anchor>
                </Table.Td>
                <Table.Td><Text size="xs">{c.title}</Text></Table.Td>
                <Table.Td><Text size="xs" c="dimmed">{c.rule}</Text></Table.Td>
                <Table.Td ta="right">{n ? <Status tone="warn">{n}</Status> : <Status tone="good">0</Status>}</Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

export function Inventory() {
  const state = useStateDoc();
  const [sp, setSp] = useSearchParams();
  // `?view=` is the repos view's older filter; a link that carries it lands there.
  const view = sp.get('view') ?? 'ai';
  const tab = sp.get('tab') ?? (sp.has('view') ? 'repos' : 'harnesses');
  const kind = sp.get('kind') ?? '';
  const lever = sp.get('lever') ?? '';
  const missing = sp.get('missing') ?? '';
  const std = sp.get('std') ?? '';
  const [q, setQ] = useState('');
  const [artifacts, setArtifacts] = useState('claude');
  const [upgrade, setUpgrade] = useState(false);
  const [apply, setApply] = useState(false);

  const set = (patch: Record<string, string>) => {
    const next = new URLSearchParams(sp);
    Object.entries(patch).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    setSp(next, { replace: true });
  };

  return (
    <Load q={state}>
      {(s) => {
        const hr = s.harnesses ?? {};
        const c = hr.contract ?? {};
        const standard = c.standard ?? {};
        const catalog = hr.catalog ?? {};
        const repos = hr.repos ?? [];
        const all: Row[] = repos.flatMap((r) => (r.harnesses ?? []).map((h) => ({ ...h, repo: r })));
        const live = all.filter((r) => !retired(r.repo));
        const graded = catalog.graded ?? 0;
        const rows = all.filter((r) => {
          // retired harnesses are listed only when asked for by their lever
          if (lever ? r.lever !== lever : retired(r.repo)) return false;
          if (kind && r.kind !== kind) return false;
          if (missing && !(r.standard?.missing ?? []).includes(missing)) return false;
          if (std === 'off' && (r.standard?.conformant ?? true)) return false;
          if (std === 'on' && !r.standard?.conformant) return false;
          return includesText([r.repo.repo, r.path, r.kind, r.route ?? '', r.model ?? '', r.switch ?? '', r.lever ?? ''], q);
        });
        const repoRows = repos.filter((r) => {
          if (view === 'gaps' && !gap(r)) return false;
          if (view === 'ai' && !(r.harnesses ?? []).length && !gap(r)) return false;
          return includesText([r.repo, ...(r.harnesses ?? []).map((h) => `${h.path} ${h.kind} ${h.model ?? ''}`)], q);
        });
        return (
          <>
            <PageHeader
              title="Harness inventory"
              description={<>Every AI workflow in the fleet, by how it reaches a model, graded against the harness standard{standard.version ? <> (v{standard.version})</> : null}: {fmt(catalog.conformant, 0)} of {fmt(graded, 0)} are on it. Scanned {hr.scan?.scanned_at ?? hr.generated_at ?? '—'}{hr.scan?.mode && hr.scan.mode !== 'live' ? <> ({hr.scan.mode} scan)</> : null}.</>}
              actions={
                <>
                  <RunButton op="harnesses" variant="filled">Refresh (live scan)</RunButton>
                  <RunButton op="harnesses-offline">Offline analytics</RunButton>
                  <RunButton op="gaps">List gap repos</RunButton>
                </>
              }
            />
            <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="sm" mb="md">
              <StatTile label="On the standard" value={`${fmt(catalog.conformant, 0)} / ${fmt(graded, 0)}`} href={`?std=off`}
                sub={graded ? `${fmt(graded - (catalog.conformant ?? 0), 0)} to rebuild${catalog.retired ? ` · ${catalog.retired} retired` : ''}` : 'run a live scan to grade the fleet'} />
              {KINDS.map((k) => {
                const n = catalog.by_kind?.[k.value];
                return <StatTile key={k.value} label={`${k.icon} ${k.label}`} value={n ? `${n.conformant} / ${n.harnesses}` : fmt(live.filter((r) => r.kind === k.value).length, 0)} href={`?kind=${k.value}`} sub={n ? 'on the standard' : undefined} />;
              })}
            </SimpleGrid>
            <SegmentedControl mb="md" size="sm" value={tab} onChange={(v) => setSp(v === 'harnesses' ? {} : { tab: v }, { replace: true })}
              data={[{ label: `Harnesses (${live.length})`, value: 'harnesses' }, { label: `Repos (${repos.length})`, value: 'repos' }]} />

            {tab === 'harnesses' ? (
              <>
                <Section mt={0} title="Rebuild plan" description="Harnesses off the standard, grouped by the action that brings the group onto it. Pick a lever to list its harnesses.">
                  <Plan rows={all} catalog={catalog} lever={lever} pick={(l) => set({ lever: l })} />
                </Section>
                <Section title="Harnesses" description="One row per AI workflow. Route is how it reaches a model; the verdict counts the controls it meets and names the ones it misses.">
                  <Group gap="sm" mb="sm" wrap="wrap">
                    <TextInput data-page-search leftSection={<IconSearch size={15} />} placeholder="Filter repo / workflow / route / model…  ( / )" value={q} onChange={(e) => setQ(e.currentTarget.value)} w={300} />
                    <SegmentedControl size="xs" value={kind} onChange={(v) => set({ kind: v })}
                      data={[{ label: 'All kinds', value: '' }, ...KINDS.map((k) => ({ label: k.label, value: k.value }))]} />
                    <SegmentedControl size="xs" value={std} onChange={(v) => set({ std: v })}
                      data={[{ label: 'Any verdict', value: '' }, { label: 'Off the standard', value: 'off' }, { label: 'On it', value: 'on' }]} />
                    <Text size="sm" c="dimmed">
                      {rows.length} of {live.length} harnesses
                      {lever ? <> · lever <Code>{lever}</Code></> : null}
                      {missing ? <> · missing <Code>{missing}</Code></> : null}
                      {lever || missing || kind || std ? <> · <Anchor component="button" type="button" size="sm" onClick={() => set({ lever: '', missing: '', kind: '', std: '' })}>clear</Anchor></> : null}
                    </Text>
                  </Group>
                  <DataTable<Row>
                    rows={rows}
                    keys
                    rowKey={(r) => r.id ?? `${r.repo.repo}:${r.path}`}
                    rowLabel={(r) => `${r.repo.repo} ${r.path.replace('.github/workflows/', '')}`}
                    href={(r) => to.project(r.repo.repo, 'harness')}
                    open={(r) => gh.workflow(r.repo.nwo, r.path)}
                    tone={(r) => (retired(r.repo) ? 'muted' : r.last_conclusion === 'failure' ? 'crit' : undefined)}
                    initialSort={{ key: 'std' }}
                    minWidth={1320}
                    maxHeight={640}
                    empty={<Empty>No harness matches these filters.</Empty>}
                    columns={[
                      {
                        key: 'repo', header: 'repo', sort: (r) => r.repo.repo, render: (r) => (
                          <div>
                            <Text fw={600} size="sm" ff="monospace">{r.repo.repo}</Text>
                            <Text size="xs" c="dimmed">{[r.factory && 'GitFactory line', r.repo.external && 'external', retired(r.repo) && 'archived'].filter(Boolean).join(' · ')}</Text>
                          </div>
                        ),
                      },
                      {
                        key: 'wf', header: 'workflow', sort: (r) => r.path, render: (r) => (
                          <Text size="sm"><span title={r.kind}>{kindIcon(r.kind)}</span> <Text span ff="monospace" fz={12}>{r.path.replace('.github/workflows/', '')}</Text></Text>
                        ),
                      },
                      {
                        key: 'route', header: 'route', width: 165, sort: (r) => r.route ?? '', title: 'How the workflow reaches a model', render: (r) => (
                          r.route ? <Status tone={standard.routes?.[r.route]?.standard === false ? 'warn' : 'info'} title={standard.routes?.[r.route]?.title}>{r.route}</Status> : <Text size="xs" c="dimmed">—</Text>
                        ),
                      },
                      { key: 'caps', header: 'model / caps', width: 150, sort: (r) => r.max_budget_usd ?? -1, render: (r) => <Text size="xs">{caps(r) || '—'}</Text> },
                      { key: 'switch', header: 'switch', width: 125, sort: (r) => r.switch ?? '', render: (r) => (r.switch ? <Text size="xs" ff="monospace" title={r.switch}>{r.switch.replace(/_ENABLED$/, '')}</Text> : <Text size="xs" c="dimmed">—</Text>) },
                      {
                        key: 'std', header: 'standard', width: 250, title: 'Controls met of those that bind this harness', sort: (r) => (r.standard ? r.standard.met / Math.max(r.standard.of, 1) : 2),
                        render: (r) => <Verdict h={r} controls={standard.controls} />,
                      },
                      {
                        key: 'lever', header: 'lever', width: 150, sort: (r) => r.lever ?? '', render: (r) => (
                          r.lever ? <Status tone={leverTone(r.lever)} title={catalog.levers?.[r.lever]?.action}>{r.lever === 'none' ? 'on standard' : r.lever}</Status> : <Text size="xs" c="dimmed">—</Text>
                        ),
                      },
                      { key: 'last', header: 'last run', sort: (r) => r.last_conclusion ?? '', render: (r) => <Conclusion value={r.last_conclusion} /> },
                      { key: 'cost', header: 'AI cost', num: true, sort: (r) => r.cost_usd_window ?? -1, render: (r) => (r.cost_usd_window != null ? usd(r.cost_usd_window) : '—') },
                    ]}
                  />
                </Section>
                <Section title="The standard" description={<>What every harness is built to, declared in <Code>_data/fleet.yml</Code> <Code>harnesses.standard</Code>. A control binds only the kinds it names, and only where it can: a workflow no stranger can trigger has no author gate to check. Pick a control to list the harnesses that miss it.</>}>
                  <Controls standard={standard} catalog={catalog} missing={missing} pick={(m) => set({ missing: m })} />
                </Section>
              </>
            ) : (
              <>
                <Text size="sm" c="dimmed" mb="sm" maw={900}>The baseline each repo is held to: kit <Code>{c.kit} v{c.kit_version}</Code>, {Object.entries(c.baseline ?? {}).filter(([, v]) => v).map(([k]) => k.replace('require_', '')).join(', ') || '—'}, exempt {(c.exempt ?? []).join(', ') || 'none'}. {repos.filter(gap).length} repos have gaps; {fmt(hr.totals?.kit_upgradeable)} machine seeds are upgradeable.</Text>
                <Paper p="md" mb="md">
                  <Stack gap="xs">
                    <Text fw={600} size="sm">Deploy the agent-context kit to every gap repo</Text>
                    <Group gap="md" wrap="wrap" align="flex-end">
                      <TextInput label="Artifacts" value={artifacts} onChange={(e) => setArtifacts(e.currentTarget.value)} w={220} />
                      <Checkbox label="Upgrade machine seeds" checked={upgrade} onChange={(e) => setUpgrade(e.currentTarget.checked)} />
                      <Checkbox label="Apply — open the PRs" color="red" checked={apply} onChange={(e) => setApply(e.currentTarget.checked)} />
                      <RunButton op="deploy-gaps" params={{ artifacts, upgrade, apply }} variant="filled">Deploy to gap repos{apply ? '' : ' (dry run)'}</RunButton>
                      <RunButton op="dispatch" params={{ workflow: 'fanout', fields: { kit: 'harness', target: 'gaps', artifacts, dry_run: String(!apply), upgrade: String(upgrade) } }}>Dispatch fanout (harness) in CI</RunButton>
                    </Group>
                  </Stack>
                </Paper>
                <Group gap="sm" mb="sm" wrap="wrap">
                  <TextInput data-page-search leftSection={<IconSearch size={15} />} placeholder="Filter repo / workflow / kind…  ( / )" value={q} onChange={(e) => setQ(e.currentTarget.value)} w={300} />
                  <SegmentedControl size="xs" value={view} onChange={(v) => setSp({ tab: 'repos', ...(v === 'ai' ? {} : { view: v }) }, { replace: true })}
                    data={[{ label: 'With harnesses or gaps', value: 'ai' }, { label: 'Gaps only', value: 'gaps' }, { label: 'All repos', value: 'all' }]} />
                  <Text size="sm" c="dimmed">{repoRows.length} of {repos.length} repos</Text>
                </Group>
                <DataTable<HarnessRepo>
                  rows={repoRows}
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
                          <Text size="xs" c="dimmed">{[r.manifest && 'manifest', r.factory && 'GitFactory', r.external && 'external', r.archived && 'archived', r.workflows_truncated && `read ${r.workflows_total} of ${r.workflows_listed} workflows`].filter(Boolean).join(' · ')}</Text>
                        </div>
                      ),
                    },
                    {
                      key: 'wf', header: 'harness workflows', sort: (r) => (r.harnesses ?? []).length, render: (r) => (r.harnesses ?? []).length ? (
                        <Stack gap={2}>
                          {(r.harnesses ?? []).map((h) => (
                            <Text key={h.path} size="xs">
                              {kindIcon(h.kind)} <Text span ff="monospace" fz={12}>{h.path.replace('.github/workflows/', '')}</Text>
                              {h.model ? <Text span c="dimmed" fz={11}> {h.model}{h.max_turns ? `/${h.max_turns}t` : ''}</Text> : null}
                              {h.last_conclusion === 'failure' ? <> <Status tone="crit">failing</Status></> : null}
                            </Text>
                          ))}
                        </Stack>
                      ) : <Text size="xs" c="dimmed">—</Text>,
                    },
                    { key: 'auth', header: 'auth', render: (r) => <Stack gap={2}>{(r.harnesses ?? []).map((h) => <div key={h.path}>{/oauth|ordered/.test(h.auth ?? '') ? <Status tone="good">{h.auth}</Status> : <Status tone="crit">{h.auth || 'none'}</Status>}</div>)}</Stack> },
                    { key: 'kit', header: 'kit', render: (r) => <Stack gap={2}>{(r.harnesses ?? []).map((h) => <div key={h.path}>{h.kit_status === 'current' ? <Status tone="good">v{h.kit}</Status> : h.kit_status === 'upgradeable' ? <Status tone="warn" title={h.kit_pristine === false ? 'edited by hand: the fan-out will not replace it' : undefined}>v{h.kit} {h.kit_pristine === false ? '✎' : '↑'}</Status> : <Text size="xs" c="dimmed">{h.kit_status}</Text>}</div>)}</Stack> },
                    { key: 'ctx', header: 'context', sort: (r) => r.agent_context ?? '', render: (r) => <Text size="xs" ff="monospace">{r.agent_context ?? '—'}</Text> },
                    { key: 'oauth', header: 'OAuth secret', sort: (r) => r.oauth_secret ?? '', render: (r) => ['ok', 'hub'].includes(r.oauth_secret ?? '') ? <Status tone="good">{r.oauth_secret}</Status> : r.oauth_secret === 'stale' ? <Status tone="warn">stale</Status> : r.oauth_secret === 'missing' ? <Status tone="crit">missing</Status> : <Text size="xs" c="dimmed">{r.oauth_secret}</Text> },
                    { key: 'sched', header: 'sched AI/d', num: true, sort: (r) => r.est_scheduled_ai_per_day ?? 0, render: (r) => fmt(r.est_scheduled_ai_per_day) },
                    { key: 'cost', header: 'AI cost', num: true, sort: (r) => r.ai_usage?.cost_usd ?? -1, render: (r) => (r.ai_usage?.cost_usd != null ? usd(r.ai_usage.cost_usd) : '—') },
                    { key: 'base', header: 'baseline', sort: (r) => (gap(r) ? 0 : 1), render: (r) => (r.coverage?.exempt ? <Status tone="info">exempt</Status> : r.coverage?.ok ? <Status tone="good">ok</Status> : <Group gap={4}>{(r.coverage?.missing ?? []).map((m) => <Status key={m} tone="warn">{m}</Status>)}</Group>) },
                  ]}
                />
              </>
            )}
          </>
        );
      }}
    </Load>
  );
}
