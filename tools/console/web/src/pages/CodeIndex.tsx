// The Kilo code index: semantic search over this worktree (Qdrant + a native
// Ollama embedder), its coverage per submodule, and "harmonize" — which
// projects share a pattern and which do not. A project row opens its page.
import { Link } from 'react-router';
import { Anchor, Button, Group, Paper, SegmentedControl, SimpleGrid, Stack, Text, TextInput } from '@mantine/core';
import { IconSearch } from '@tabler/icons-react';
import { useState } from 'react';
import { api } from '../api/client';
import { useIndexCoverage, useObservability } from '../api/hooks';
import type { Dict } from '../api/types';
import { HBars } from '../components/Charts';
import { DataTable } from '../components/DataTable';
import { Banner, Load, Mono, PageHeader, Section, Spinner, StatTile, Status } from '../components/ui';
import { RunButton } from '../jobs/RunButton';
import { fmt } from '../lib/format';
import { to } from '../lib/links';

type Row = Dict<any>;

function Search() {
  const [q, setQ] = useState('');
  const [kind, setKind] = useState<'search' | 'harmonize'>('search');
  const [busy, setBusy] = useState(false);
  const [doc, setDoc] = useState<Row | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const run = async () => {
    if (!q.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      setDoc(await api<Row>(`/api/index/${kind}?q=${encodeURIComponent(q.trim())}`));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Stack gap="sm">
      <form onSubmit={(e) => { e.preventDefault(); void run(); }}>
        <Group gap="sm" wrap="wrap">
          <TextInput data-page-search leftSection={<IconSearch size={15} />} placeholder="a pattern, e.g. journal entry posting  ( / )" value={q} onChange={(e) => setQ(e.currentTarget.value)} style={{ flex: 1, minWidth: 260 }} />
          <SegmentedControl value={kind} onChange={(v) => setKind(v as 'search' | 'harmonize')} data={[{ label: 'Search', value: 'search' }, { label: 'Harmonize', value: 'harmonize' }]} />
          <Button type="submit" loading={busy}>Go</Button>
        </Group>
      </form>
      {err ? <Banner tone="crit">{err}</Banner> : null}
      {busy ? <Spinner label="embedding…" /> : null}
      {doc && !doc.present ? <Banner tone="crit">{String(doc.error ?? 'index query failed')}</Banner> : null}
      {doc?.present && kind === 'search' ? (
        <>
          <Text size="sm" c="dimmed">{(doc.hits ?? []).length} hits at or above {doc.min_score}{doc.below_floor ? ` · ${doc.below_floor} dropped` : ''}</Text>
          <DataTable<Row>
            rows={(doc.hits ?? []) as Row[]}
            rowKey={(h, i) => `${h.filePath}:${h.startLine}:${i}`}
            href={(h) => (h.project && h.project !== '_hub' ? to.project(String(h.project)) : null)}
            empty="nothing above the floor"
            columns={[
              { key: 'score', header: 'score', num: true, render: (h) => Number(h.score).toFixed(3) },
              { key: 'project', header: 'project', render: (h) => <Mono>{String(h.project)}</Mono> },
              { key: 'where', header: 'where', render: (h) => <Mono>{String(h.filePath)}:{String(h.startLine)}</Mono> },
            ]}
          />
        </>
      ) : null}
      {doc?.present && kind === 'harmonize' ? (
        <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
          <div>
            <Text size="sm" c="dimmed" mb={6}>{(doc.matched ?? []).length}/{doc.projects} projects at or above {doc.min_score}</Text>
            <DataTable<Row>
              rows={(doc.matched ?? []) as Row[]}
              rowKey={(h) => String(h.project)}
              href={(h) => to.project(String(h.project))}
              empty="no project above the floor"
              columns={[
                { key: 'project', header: 'project', render: (h) => <Mono>{String(h.project)}</Mono> },
                { key: 'score', header: 'score', num: true, render: (h) => Number(h.score).toFixed(3) },
                { key: 'where', header: 'where', render: (h) => <Mono dim>{String(h.filePath)}:{String(h.startLine)}</Mono> },
              ]}
            />
          </div>
          <div>
            <Text size="sm" c="dimmed" mb={6}>Gaps — no hit above the floor</Text>
            <Paper p="sm">
              <Group gap={6}>{((doc.gaps ?? []) as string[]).map((n) => <Anchor key={n} component={Link} to={to.project(n)} ff="monospace" fz="sm">{n}</Anchor>)}</Group>
            </Paper>
          </div>
        </SimpleGrid>
      ) : null}
    </Stack>
  );
}

export function CodeIndex() {
  const obs = useObservability();
  const cov = useIndexCoverage();
  return (
    <>
      <PageHeader
        title="Code index"
        description="Semantic search over this worktree. Checked-out submodules are directories in the walk, so they share the hub's index; an uninitialized submodule is an empty directory and is not indexed. The scan starts when Kilo opens this workspace."
        actions={<RunButton op="observe-status">Plane status</RunButton>}
      />
      <Load q={obs} rows={3}>
        {(o) => {
          const p = ((o.planes ?? {}).indexing ?? {}) as Row;
          const subs = (p.submodules ?? {}) as Row;
          const empty = (subs.empty ?? []) as string[];
          return (
            <>
              <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }} spacing="md">
                <StatTile label="Qdrant" value={p.reachable ? <Status tone="good">up</Status> : <Status tone="crit">not running</Status>} sub={<Mono dim>{String(p.url ?? '')}</Mono>} />
                <StatTile label="Embedder" value={p.embedder_reachable ? <Status tone="good">up</Status> : <Status tone="warn">down</Status>} sub={<Mono dim>{`${String(p.provider ?? '')}/${String(p.model ?? '')}`}</Mono>} />
                <StatTile label="Points" value={fmt(p.points)} sub={((p.collections ?? []) as Row[]).map((c) => `${c.name} ${fmt(c.points)}`).join(', ') || 'no collection yet'} />
                <StatTile label="Submodules checked out" value={`${fmt(subs.checked_out)}/${fmt(subs.declared)}`} sub={`${p.configured ? 'kilo.jsonc indexing on' : 'kilo.jsonc indexing OFF'}${empty.length ? ` · ${empty.length} not checked out` : ''}`} />
              </SimpleGrid>
              {!p.reachable ? <Banner tone="info" title="Qdrant is not running">Start it with the log + metrics stack (Observe → Logs → Start), or <Mono>tools/dash observe up</Mono>.</Banner> : null}
              {empty.length ? (
                <Section title="Not checked out" description="In .gitmodules but with no working tree — git submodule update --init puts them in the index.">
                  <Group gap={6}>{empty.map((e) => <Mono key={e}>{e}</Mono>)}</Group>
                </Section>
              ) : null}
            </>
          );
        }}
      </Load>
      <Section title="Search">
        <Search />
      </Section>
      <Section title="Coverage" description="Chunks per submodule. A zero is a checked-out tree missing from the collection. .github stays at zero: the scanner skips dot-directories, so the control plane is a blind spot.">
        <Load q={cov}>
          {(c) => (c.present ? (
            <Paper p="md">
              <HBars rows={[{ project: '_hub', chunks: c.hub_chunks ?? 0 }, ...((c.projects ?? []) as Row[]), ...((c.blind_spots ?? []) as Row[]).map((b) => ({ project: b.path, chunks: b.chunks ?? 0 }))]}
                label="project" value="chunks" />
            </Paper>
          ) : <Banner tone="warn">{String(c.error ?? 'coverage unavailable')}</Banner>)}
        </Load>
      </Section>
    </>
  );
}
