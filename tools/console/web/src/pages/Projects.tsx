// Every registry project — the terminal dash's Apps view from the same data
// (/api/fleet: fleetcore.views, filtered and sorted on the server by the TUI's
// own functions, so the two surfaces cannot disagree about a number).
import { useSearchParams } from 'react-router';
import { Group, Select, Text, TextInput } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { IconSearch } from '@tabler/icons-react';
import { useState } from 'react';
import { useFleet, useStateDoc } from '../api/hooks';
import type { FleetRow } from '../api/types';
import { DataTable } from '../components/DataTable';
import { LevelDot, Load, PageHeader } from '../components/ui';
import { RunButton } from '../jobs/RunButton';
import { to } from '../lib/links';

export function Projects() {
  const [sp, setSp] = useSearchParams();
  const [q, setQ] = useState(sp.get('q') ?? '');
  const [dq] = useDebouncedValue(q, 180);
  const sort = sp.get('sort') ?? 'featured';
  const health = sp.get('health') ?? '';
  const category = sp.get('category') ?? '';
  const fleet = useFleet({ q: dq, sort, health });
  const state = useStateDoc();
  const reg = new Map((state.data?.registry.projects ?? []).map((p) => [p.name, p]));
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(sp);
    if (v) next.set(k, v); else next.delete(k);
    setSp(next, { replace: true });
  };
  const categories = [...new Set((fleet.data?.rows ?? []).map((r) => r.category).filter(Boolean))] as string[];
  const cycleSort = () => {
    const s = fleet.data?.sorts ?? [];
    if (s.length) set('sort', s[(s.indexOf(sort) + 1) % s.length]);
  };

  return (
    <>
      <PageHeader
        title="Projects"
        description="Every project in the registry with its health, CI, triage, open work and containers — the same rows the terminal dash's Apps tab shows. Click a project for everything the console knows about it."
        actions={
          <>
            <RunButton op="health">Live health</RunButton>
            <RunButton op="triage">Triage snapshot</RunButton>
            <RunButton op="status">Dash status</RunButton>
            <RunButton op="audit">Standards audit</RunButton>
            <RunButton op="reconcile">Reconcile registry</RunButton>
          </>
        }
      />
      <Group gap="sm" mb="sm" wrap="wrap">
        <TextInput data-page-search leftSection={<IconSearch size={15} />} placeholder="Search projects, stacks…  ( / )" value={q}
          onChange={(e) => { setQ(e.currentTarget.value); set('q', e.currentTarget.value); }} w={300} />
        <Select label={null} placeholder="sort" data={fleet.data?.sorts ?? ['featured']} value={sort} onChange={(v) => set('sort', v ?? 'featured')} w={150} allowDeselect={false} aria-label="Sort" />
        <Select placeholder="any level" data={['red', 'amber', 'green']} value={health || null} onChange={(v) => set('health', v ?? '')} clearable w={140} aria-label="Level" />
        <Select placeholder="any category" data={categories} value={category || null} onChange={(v) => set('category', v ?? '')} clearable w={170} aria-label="Category" />
        {fleet.data ? (
          <Text size="sm" c="dimmed">
            {fleet.data.rows.length}/{fleet.data.kpis.projects} shown · health {fleet.data.kpis.red}/{fleet.data.kpis.amber}/{fleet.data.kpis.green} ·
            triage {fleet.data.kpis.triage_red}/{fleet.data.kpis.triage_amber} · {fleet.data.kpis.failing} failing workflows
            {fleet.data.health_present ? '' : ' · live health not generated yet (Live health fills it)'}
          </Text>
        ) : null}
      </Group>
      <Load q={fleet} rows={12}>
        {(v) => (
          <DataTable<FleetRow>
            rows={category ? v.rows.filter((r) => r.category === category) : v.rows}
            keys
            onSortKey={cycleSort}
            rowKey={(r) => r.name}
            href={(r) => to.project(r.name)}
            open={(r) => r.repo_url}
            openLive={(r) => r.live_url}
            copy={(r) => r.repo_url}
            tone={(r) => (r.worst_level === 'red' ? 'crit' : r.worst_level === 'amber' ? 'warn' : undefined)}
            empty="no project matches"
            minWidth={980}
            columns={[
              { key: 'lvl', header: '', render: (r) => <LevelDot level={r.worst_level} />, width: 24 },
              {
                key: 'name', header: 'project', sort: (r) => r.name, render: (r) => (
                  <div>
                    <Text fw={600} size="sm">{r.name}{r.featured ? ' ★' : ''}</Text>
                    <Text size="xs" c="dimmed">{r.category}{reg.get(r.name)?.auto_evolve ? ' · evolves' : ''}{r.checked_out ? '' : ' · not checked out'}</Text>
                  </div>
                ),
              },
              { key: 'status', header: 'status', sort: (r) => r.status, render: (r) => <Text size="sm">{r.status}</Text> },
              { key: 'ci', header: 'CI', sort: (r) => r.ci_pass ?? -1, render: (r) => (r.ci_last ? <Text size="sm">{r.ci_last}{r.ci_pass != null ? ` ${r.ci_pass}%` : ''}</Text> : '—') },
              { key: 'age', header: 'age', num: true, title: 'days since the last commit', sort: (r) => r.last_commit_days ?? 9999, render: (r) => r.last_commit_days ?? '—' },
              { key: 'triage', header: 'triage', sort: (r) => r.triage_score ?? -1, render: (r) => <LevelDot level={r.triage_level} label={r.triage_score ?? ''} /> },
              { key: 'issues', header: 'issues', num: true, sort: (r) => r.triage_issues ?? r.issues_open ?? 0, render: (r) => r.triage_issues ?? r.issues_open ?? '—' },
              { key: 'prs', header: 'PRs', num: true, sort: (r) => r.triage_prs ?? r.prs_open ?? 0, render: (r) => r.triage_prs ?? r.prs_open ?? '—' },
              { key: 'failing', header: 'failing', num: true, sort: (r) => r.failing.length, render: (r) => (r.failing.length ? <Text c="var(--critical)" size="sm" fw={600}>{r.failing.length}</Text> : '') },
              { key: 'sec', header: 'sec', num: true, title: 'security alerts', sort: (r) => r.security_alerts ?? 0, render: (r) => r.security_alerts || '' },
              { key: 'docker', header: 'docker', sort: (r) => r.docker_total ?? 0, render: (r) => (r.docker_total ? `${r.docker_up}/${r.docker_total}` : '') },
            ]}
          />
        )}
      </Load>
      <Text size="xs" c="dimmed" mt="xs">j/k move · enter opens · o repo · l live site · y copy link · s cycles sort — keys v1, as in the terminal dash.</Text>
    </>
  );
}
