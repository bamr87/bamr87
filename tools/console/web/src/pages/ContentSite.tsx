// One content site: its narrative, pillar coverage against target shares, the
// deterministic suggestions (approve / reject), the directives (move, add,
// file as issues), publishing and commit cadence, aging, topics, sections,
// authors, hygiene, and every document. Every write goes to
// _data/editorial.yml in the working tree, comments preserved, and the diff is
// shown — the commit stays with you.
import { useEffect, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router';
import {
  Accordion, Anchor, Badge, Button, Code, Group, NumberInput, Paper, Select, SimpleGrid, Stack, Tabs, Text, TextInput, Textarea, Tooltip,
} from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { IconSearch } from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import { api, post, put } from '../api/client';
import { useContent, useContentDocs } from '../api/hooks';
import type { Dict } from '../api/types';
import { ColumnChart, HBars } from '../components/Charts';
import { DataTable } from '../components/DataTable';
import { Banner, External, Load, Mono, PageHeader, Section, StatTile, Status, type Tone } from '../components/ui';
import { LogView } from '../jobs/JobLog';
import { RunButton } from '../jobs/RunButton';
import { ago, fmt, sharePct } from '../lib/format';
import { to } from '../lib/links';

type Row = Dict<any>;

const NEXT: Record<string, [string, string][]> = {
  proposed: [['approved', 'Approve'], ['rejected', 'Reject'], ['remove', 'Remove']],
  approved: [['done', 'Done'], ['rejected', 'Reject'], ['proposed', 'Un-approve']],
  filed: [['done', 'Done'], ['approved', 'Back to approved']],
  rejected: [['proposed', 'Reopen'], ['remove', 'Remove']],
  done: [['proposed', 'Reopen']],
};
const DIR_TONE: Record<string, Tone> = { approved: 'good', filed: 'info', done: 'good', rejected: 'info', proposed: 'warn' };

function usePlanWrite(setDiff: (d: string) => void) {
  const qc = useQueryClient();
  return async (path: string, method: 'POST' | 'PUT', body: unknown, ok: string) => {
    try {
      const r = await (method === 'POST' ? post<Row>(path, body) : put<Row>(path, body));
      notifications.show({ color: 'teal', title: 'Saved to editorial.yml', message: ok });
      if (r.diff) setDiff(String(r.diff));
      await qc.invalidateQueries({ queryKey: ['content'] });
      return true;
    } catch (e) {
      notifications.show({ color: 'red', title: 'Not saved', message: (e as Error).message, autoClose: 9000 });
      return false;
    }
  };
}

function Narrative({ a, write }: { a: Row; write: ReturnType<typeof usePlanWrite> }) {
  const [edit, setEdit] = useState(false);
  const [text, setText] = useState(String(a.narrative ?? ''));
  const [aud, setAud] = useState(String(a.audience ?? ''));
  const [voice, setVoice] = useState(String(a.voice ?? ''));
  useEffect(() => { setText(String(a.narrative ?? '')); setAud(String(a.audience ?? '')); setVoice(String(a.voice ?? '')); }, [a]);
  return (
    <Paper p="md" h="100%">
      <Group justify="space-between" mb="xs"><Text fw={600}>Narrative</Text>{edit ? null : <Button size="compact-xs" variant="default" onClick={() => setEdit(true)}>Edit</Button>}</Group>
      {edit ? (
        <Stack gap="xs">
          <Textarea autosize minRows={4} maxLength={2000} value={text} onChange={(e) => setText(e.currentTarget.value)} />
          <TextInput label="Audience" maxLength={400} value={aud} onChange={(e) => setAud(e.currentTarget.value)} />
          <TextInput label="Voice" maxLength={400} value={voice} onChange={(e) => setVoice(e.currentTarget.value)} />
          <Group gap="xs">
            <Button size="xs" onClick={async () => { if (await write(`/api/editorial/${encodeURIComponent(a.site)}`, 'PUT', { fields: { narrative: text, audience: aud, voice } }, 'narrative saved')) setEdit(false); }}>Save to editorial.yml</Button>
            <Button size="xs" variant="default" onClick={() => setEdit(false)}>Cancel</Button>
          </Group>
        </Stack>
      ) : (
        <Stack gap={6}>
          {a.narrative ? <Text size="sm">{String(a.narrative)}</Text> : <Text size="sm" c="dimmed">No narrative yet — the story this site tells, in a paragraph. Every filed directive quotes it back.</Text>}
          <Text size="xs" c="dimmed"><b>Audience</b> {String(a.audience ?? '—')}</Text>
          <Text size="xs" c="dimmed"><b>Voice</b> {String(a.voice ?? '—')}</Text>
        </Stack>
      )}
    </Paper>
  );
}

function Pillars({ a, write, onView }: { a: Row; write: ReturnType<typeof usePlanWrite>; onView: (v: string) => void }) {
  const pillars = (a.pillars ?? []) as Row[];
  const t = a.totals as Row;
  const [targets, setTargets] = useState<Record<string, string>>({});
  useEffect(() => {
    setTargets(Object.fromEntries(pillars.map((p) => [p.id, p.target_share == null ? '' : String(Math.round(100 * p.target_share))])));
  }, [a]); // pillars derive from a
  const [np, setNp] = useState({ id: '', title: '', target: '', tags: '', sections: '', collections: '', keywords: '' });
  const csv = (v: string) => v.split(',').map((x) => x.trim()).filter(Boolean);

  const saveTargets = async () => {
    const changed = pillars.filter((p) => (p.target_share == null ? '' : String(Math.round(100 * p.target_share))) !== (targets[p.id] ?? ''));
    if (!changed.length) {
      notifications.show({ message: 'no target changed' });
      return;
    }
    for (const p of changed) {
      const v = targets[p.id];
      const ok = await write(`/api/editorial/${encodeURIComponent(a.site)}`, 'PUT', { fields: { pillar: { id: p.id, target_share: v === '' ? null : Number(v) / 100 } } }, `target for ${p.id} saved`);
      if (!ok) return;
    }
  };
  const savePillar = async () => {
    if (!np.id.trim()) {
      notifications.show({ color: 'red', message: 'a pillar needs an id' });
      return;
    }
    const p: Row = { id: np.id.trim() };
    if (np.title.trim()) p.title = np.title.trim();
    if (np.target !== '') p.target_share = Number(np.target) / 100;
    const m = { tags: csv(np.tags), sections: csv(np.sections), collections: csv(np.collections), keywords: csv(np.keywords) };
    if (Object.values(m).some((v) => v.length)) p.match = m;
    if (await write(`/api/editorial/${encodeURIComponent(a.site)}`, 'PUT', { fields: { pillar: p } }, `pillar ${p.id} saved`)) {
      setNp({ id: '', title: '', target: '', tags: '', sections: '', collections: '', keywords: '' });
    }
  };

  return (
    <Paper p="md" h="100%">
      <Text fw={600}>Pillar coverage</Text>
      <Text size="xs" c="dimmed" mb="xs">share of the last {t.recent_days} days' new work · the tick is the target</Text>
      {pillars.length ? (
        <>
          <DataTable<Row>
            rows={pillars}
            rowKey={(p) => String(p.id)}
            dense
            columns={[
              { key: 'p', header: 'pillar', render: (p) => <div><Text size="sm" fw={600}>{String(p.title)}</Text><Mono dim>{String(p.id)}</Mono></div> },
              {
                key: 'm', header: 'recent share', render: (p) => (
                  <Tooltip label={<span style={{ whiteSpace: 'pre' }}>{`${p.title}\nrecent share ${sharePct(p.recent_share)} (${p.recent} of ${t.recent})\ntarget ${sharePct(p.target_share)}`}</span>}>
                    <div className="pillar-meter"><i style={{ width: `${Math.min(100, 100 * (p.recent_share || 0))}%` }} />{p.target_share != null ? <b style={{ left: `calc(${Math.min(100, 100 * p.target_share)}% - 1px)` }} /> : null}</div>
                  </Tooltip>
                ),
              },
              { key: 'r', header: '', num: true, render: (p) => sharePct(p.recent_share) },
              { key: 't', header: 'target %', render: (p) => <NumberInput size="xs" w={78} min={0} max={100} value={targets[p.id] ?? ''} onChange={(v) => setTargets((s) => ({ ...s, [p.id]: v === '' ? '' : String(v) }))} aria-label={`target for ${p.id}`} /> },
              {
                key: 's', header: '', render: (p) => {
                  const tgt = p.target_share;
                  const r = p.recent_share || 0;
                  if (tgt == null || p.status !== 'active') return <Status tone="info">{tgt == null ? 'tracked' : String(p.status)}</Status>;
                  return r < tgt * 0.5 ? <Status tone="warn">under</Status> : r > tgt * 1.75 ? <Status tone="warn">over</Status> : <Status tone="good">on target</Status>;
                },
              },
              { key: 'd', header: 'docs', num: true, render: (p) => <Anchor size="sm" onClick={() => onView(`pillar:${p.id}`)}>{fmt(p.docs)}</Anchor> },
              { key: 'n', header: 'newest', num: true, render: (p) => ago(p.newest_age) },
            ]}
          />
          <Group gap="xs" mt="xs" wrap="wrap">
            <Button size="xs" variant="default" onClick={() => void saveTargets()}>Save targets</Button>
            <Text size="xs" c="dimmed">{fmt(a.unmapped?.docs)} documents ({sharePct(a.unmapped?.share)}) match no pillar — <Anchor size="xs" onClick={() => onView('unmapped')}>show them</Anchor>
              {(a.unmapped?.top_tags ?? []).length ? `; top tags: ${(a.unmapped.top_tags as Row[]).slice(0, 6).map((x) => x.tag).join(', ')}` : ''}</Text>
          </Group>
        </>
      ) : <Text size="sm" c="dimmed">No pillars declared. Add one below, or approve the define-pillars suggestion.</Text>}
      <Accordion variant="contained" mt="sm">
        <Accordion.Item value="add">
          <Accordion.Control>Add or re-match a pillar</Accordion.Control>
          <Accordion.Panel>
            <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="xs">
              <TextInput size="xs" label="id" value={np.id} onChange={(e) => setNp({ ...np, id: e.currentTarget.value })} />
              <TextInput size="xs" label="title" value={np.title} onChange={(e) => setNp({ ...np, title: e.currentTarget.value })} />
              <TextInput size="xs" label="target %" value={np.target} onChange={(e) => setNp({ ...np, target: e.currentTarget.value.replace(/[^0-9]/g, '') })} />
              <TextInput size="xs" label="tags" placeholder="comma-separated" value={np.tags} onChange={(e) => setNp({ ...np, tags: e.currentTarget.value })} />
              <TextInput size="xs" label="sections" value={np.sections} onChange={(e) => setNp({ ...np, sections: e.currentTarget.value })} />
              <TextInput size="xs" label="collections" value={np.collections} onChange={(e) => setNp({ ...np, collections: e.currentTarget.value })} />
              <TextInput size="xs" label="title keywords" value={np.keywords} onChange={(e) => setNp({ ...np, keywords: e.currentTarget.value })} />
            </SimpleGrid>
            <Button size="xs" mt="sm" onClick={() => void savePillar()}>Save pillar</Button>
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
    </Paper>
  );
}

function Directives({ a, write }: { a: Row; write: ReturnType<typeof usePlanWrite> }) {
  const dirs = (a.directives ?? []) as Row[];
  const approved = dirs.filter((d) => d.status === 'approved').length;
  const [nd, setNd] = useState({ title: '', kind: 'write', priority: 'P2', pillar: '', brief: '' });
  const add = async () => {
    const title = nd.title.trim();
    if (!title) {
      notifications.show({ color: 'red', message: 'a directive needs a title' });
      return;
    }
    const key = `human:${title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60)}`;
    if (await write('/api/editorial/decision', 'POST', { site: a.site, action: 'add', key, fields: { title, brief: nd.brief, kind: nd.kind, priority: nd.priority, pillar: nd.pillar || null } }, 'directive added')) {
      setNd({ title: '', kind: 'write', priority: 'P2', pillar: '', brief: '' });
    }
  };
  return (
    <Stack gap="sm">
      <Group gap="xs" wrap="wrap">
        <RunButton op="content-file" params={{ target: a.site }}>File approved — dry run</RunButton>
        <RunButton op="content-file" params={{ target: a.site, apply: true }} disabled={!approved} variant="filled">File {approved} approved as issues in {String(a.repo ?? '—')}</RunButton>
        <Text size="xs" c="dimmed">labelled editorial:directive; the site's issue loop or a human takes it from there</Text>
      </Group>
      <DataTable<Row>
        rows={dirs}
        rowKey={(d) => String(d.key)}
        tone={(d) => (d.status === 'rejected' ? 'muted' : undefined)}
        empty="No directives yet — approve a suggestion or add your own."
        minWidth={820}
        columns={[
          { key: 's', header: 'status', sort: (d) => String(d.status ?? 'proposed'), render: (d) => <Status tone={DIR_TONE[d.status ?? 'proposed'] ?? 'warn'}>{String(d.status ?? 'proposed')}</Status> },
          { key: 't', header: 'directive', render: (d) => <div><Text size="sm" fw={600}>{String(d.title)}</Text><Text size="xs" c="dimmed">{String(d.brief ?? '')}</Text></div> },
          { key: 'k', header: 'kind', render: (d) => <Text size="sm">{String(d.kind)} · {String(d.priority)}{d.pillar ? ` · ${d.pillar}` : ''}</Text> },
          { key: 'i', header: 'issue', render: (d) => (d.issue ? <External href={String(d.issue)} size="sm">issue</External> : '—') },
          { key: 'dec', header: 'decided', render: (d) => <Text size="xs" c="dimmed">{String(d.decided ?? '')} · {String(d.source ?? '')}</Text> },
          {
            key: 'a', header: '', render: (d) => (
              <Group gap={4} wrap="nowrap">
                {(NEXT[d.status ?? 'proposed'] ?? []).map(([s, l]) => (
                  <Button key={s} size="compact-xs" variant="default" onClick={() => void write('/api/editorial/decision', 'POST', s === 'remove' ? { site: a.site, action: 'remove', key: d.key } : { site: a.site, action: 'status', key: d.key, fields: { status: s } }, `${d.key} → ${s}`)}>{l}</Button>
                ))}
              </Group>
            ),
          },
        ]}
      />
      <Accordion variant="contained">
        <Accordion.Item value="add">
          <Accordion.Control>Add a directive of your own</Accordion.Control>
          <Accordion.Panel>
            <Stack gap="xs">
              <TextInput label="Title" placeholder="what should be published or changed" maxLength={200} value={nd.title} onChange={(e) => setNd({ ...nd, title: e.currentTarget.value })} />
              <Group gap="xs" grow>
                <Select label="Kind" data={['write', 'refresh', 'fix', 'hold', 'pillar', 'cadence']} value={nd.kind} onChange={(v) => setNd({ ...nd, kind: v ?? 'write' })} allowDeselect={false} />
                <Select label="Priority" data={['P1', 'P2', 'P3']} value={nd.priority} onChange={(v) => setNd({ ...nd, priority: v ?? 'P2' })} allowDeselect={false} />
                <Select label="Pillar" data={[{ value: '', label: '(no pillar)' }, ...((a.pillars ?? []) as Row[]).map((p) => ({ value: String(p.id), label: String(p.title) }))]} value={nd.pillar} onChange={(v) => setNd({ ...nd, pillar: v ?? '' })} />
              </Group>
              <Textarea label="Brief" autosize minRows={3} maxLength={2000} placeholder="the angle, the audience, what done looks like" value={nd.brief} onChange={(e) => setNd({ ...nd, brief: e.currentTarget.value })} />
              <Group><Button size="xs" onClick={() => void add()}>Add as approved</Button></Group>
            </Stack>
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
    </Stack>
  );
}

function Documents({ a, view, setView }: { a: Row; view: string; setView: (v: string) => void }) {
  const [q, setQ] = useState('');
  const [dq] = useDebouncedValue(q, 250);
  const docs = useContentDocs(String(a.site), view, dq);
  const link = (p: string) => (a.repo ? `https://github.com/${a.repo}/blob/HEAD/${p.split('/').map(encodeURIComponent).join('/')}` : null);
  const views = ['all', 'recent', 'stale', 'issues', 'thin', 'drafts', 'unmapped', ...((a.pillars ?? []) as Row[]).map((p) => `pillar:${p.id}`)];
  return (
    <Stack gap="sm">
      <Group gap="sm" wrap="wrap">
        <Select data={views} value={view} onChange={(v) => setView(v ?? 'all')} w={200} allowDeselect={false} aria-label="View" />
        <TextInput data-page-search leftSection={<IconSearch size={15} />} placeholder="filter by path, title or tag  ( / )" value={q} onChange={(e) => setQ(e.currentTarget.value)} w={300} />
        <Text size="sm" c="dimmed">{docs.data ? `${docs.data.length}${docs.data.length === 300 ? '+' : ''} shown` : ''}</Text>
      </Group>
      <Load q={docs}>
        {(rows) => (
          <DataTable<Row>
            rows={rows}
            keys
            rowKey={(d) => String(d.path)}
            onActivate={(d) => { const u = link(String(d.path)); if (u) window.open(u, '_blank', 'noopener'); }}
            open={(d) => link(String(d.path))}
            tone={(d) => ((d.issues ?? []).includes('frontmatter-invalid') ? 'crit' : (d.age ?? 0) > 365 ? 'warn' : undefined)}
            empty="no documents in this view"
            minWidth={980}
            columns={[
              { key: 'doc', header: 'document', sort: (d) => String(d.title ?? d.path), render: (d) => <div><External href={link(String(d.path))} size="sm">{String(d.title || d.path)}</External>{d.draft ? <> <Status tone="info">draft</Status></> : null}<Text size="xs" c="dimmed" style={{ overflowWrap: 'anywhere' }}>{String(d.path)}</Text></div> },
              { key: 'sec', header: 'section', sort: (d) => String(d.section), render: (d) => <Text size="sm">{String(d.section)}</Text> },
              { key: 'pub', header: 'published', sort: (d) => String(d.date ?? ''), render: (d) => <Text size="sm">{String(d.date ?? '—')}</Text> },
              { key: 'upd', header: 'updated', sort: (d) => String(d.updated ?? ''), render: (d) => <Text size="sm">{String(d.updated ?? '—')}</Text> },
              { key: 'age', header: 'age', num: true, sort: (d) => Number(d.age ?? 0), render: (d) => ago(d.age) },
              { key: 'w', header: 'words', num: true, sort: (d) => Number(d.words ?? 0), render: (d) => fmt(d.words) },
              { key: 'tags', header: 'tags', render: (d) => <Group gap={3}>{((d.tags ?? []) as string[]).slice(0, 5).map((x) => <Badge key={x} size="xs" variant="default">{x}</Badge>)}</Group> },
              { key: 'iss', header: 'issues', render: (d) => <Group gap={3}>{((d.issues ?? []) as string[]).map((i) => <Status key={i} tone={i === 'frontmatter-invalid' ? 'crit' : 'warn'}>{i}</Status>)}</Group> },
            ]}
          />
        )}
      </Load>
    </Stack>
  );
}

function SiteBody({ a }: { a: Row }) {
  const [sp, setSp] = useSearchParams();
  const tab = sp.get('tab') ?? 'plan';
  const view = sp.get('view') ?? 'all';
  const [diff, setDiff] = useState('');
  const [brief, setBrief] = useState('');
  const write = usePlanWrite(setDiff);
  const t = a.totals as Row;
  const setView = (v: string) => setSp({ tab: 'documents', view: v }, { replace: true });
  const suggestions = (a.suggestions ?? []) as Row[];

  return (
    <>
      <PageHeader
        crumbs={[{ label: 'Content sites', to: to.content() }, { label: String(a.site) }]}
        title={String(a.site)}
        badges={a.error ? <Status tone="crit">last sync failed</Status> : null}
        description={<>read from {String(a.source ?? '—')} @ <Code>{String(a.head ?? '—')}</Code>, synced {String(a.synced_at ?? '').replace('T', ' ').slice(0, 16)} · {fmt(a.skipped)} Markdown files without front matter skipped</>}
        actions={
          <>
            {a.repo ? <Anchor component={Link} to={to.project(String(a.repo).split('/').pop() ?? '')} size="sm">project</Anchor> : null}
            {a.repo ? <External href={`https://github.com/${a.repo}`} size="sm">{String(a.repo)}</External> : null}
            {a.live_url ? <External href={String(a.live_url)} size="sm">live site</External> : null}
            <RunButton op="content-sync" params={{ target: a.site }}>Re-sync</RunButton>
            <Button size="xs" variant="default" onClick={async () => {
              try { setBrief(String((await api<Row>(`/api/content/${encodeURIComponent(a.site)}/brief`)).markdown ?? '')); setSp({ tab: 'brief' }, { replace: true }); } catch (e) { notifications.show({ color: 'red', message: (e as Error).message }); }
            }}>Render brief</Button>
          </>
        }
      />
      {a.error ? <Banner tone="crit" title="Last sync failed">{String(a.error)}</Banner> : null}
      <SimpleGrid cols={{ base: 1, xs: 2, md: 3, lg: 6 }} spacing="sm" mb="md">
        <StatTile label="Published documents" value={fmt(t.docs)} sub={`${fmt(t.drafts)} drafts · ${fmt(Math.round((t.words ?? 0) / 1000))}k words`} />
        <StatTile label={`New (last ${t.recent_days} days)`} value={fmt(t.recent)} sub={`last published ${t.last_published ?? '—'}`} />
        <StatTile label="Median age" value={ago(t.median_age)} sub="since last update" />
        <StatTile label="Stale" value={fmt(t.stale)} sub={`${sharePct(t.stale_share)} untouched a year`} />
        <StatTile label="Hygiene" value={fmt(t.with_issues)} sub="front-matter issues" />
        <StatTile label="Bot share of commits" value={sharePct(t.bot_share)} sub={`${fmt(t.commits)} content commits`} />
      </SimpleGrid>
      {diff ? (
        <Paper p="sm" mb="md">
          <Group justify="space-between" mb={6}><Text size="sm" fw={600}>_data/editorial.yml in the working tree — commit it to make it the record</Text><Button size="compact-xs" variant="subtle" onClick={() => setDiff('')}>Hide</Button></Group>
          <LogView raw={diff} height={220} />
        </Paper>
      ) : null}
      <Tabs value={tab} onChange={(v) => setSp(v && v !== 'plan' ? { tab: v } : {}, { replace: true })} keepMounted={false}>
        <Tabs.List mb="md">
          <Tabs.Tab value="plan">Plan</Tabs.Tab>
          <Tabs.Tab value="suggestions">Suggestions <Badge size="xs" variant="light" ml={4}>{suggestions.length}</Badge></Tabs.Tab>
          <Tabs.Tab value="directives">Directives <Badge size="xs" variant="light" ml={4}>{(a.directives ?? []).length}</Badge></Tabs.Tab>
          <Tabs.Tab value="activity">Activity</Tabs.Tab>
          <Tabs.Tab value="documents">Documents</Tabs.Tab>
          {brief ? <Tabs.Tab value="brief">Brief</Tabs.Tab> : null}
        </Tabs.List>
        <Tabs.Panel value="plan">
          <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="md">
            <Narrative a={a} write={write} />
            <Pillars a={a} write={write} onView={setView} />
          </SimpleGrid>
        </Tabs.Panel>
        <Tabs.Panel value="suggestions">
          <Text size="sm" c="dimmed" mb="sm">Deterministic, from the numbers. Each has a stable key: a decision sticks across re-syncs, and a rejected one never comes back.</Text>
          <Stack gap="xs">
            {suggestions.length ? suggestions.map((sg) => (
              <Paper key={String(sg.key)} p="sm">
                <Group justify="space-between" wrap="wrap" gap="xs" align="flex-start">
                  <Group gap="xs" wrap="nowrap" align="flex-start" style={{ flex: 1, minWidth: 260 }}>
                    <Status tone={sg.priority === 'P1' ? 'crit' : sg.priority === 'P2' ? 'warn' : 'info'}>{String(sg.priority)}</Status>
                    <div>
                      <Text size="sm" fw={600}>{String(sg.title)} <Mono dim>{String(sg.key)}</Mono></Text>
                      <Text size="xs" c="dimmed">{String(sg.brief)}</Text>
                    </div>
                  </Group>
                  <Group gap={6}>
                    <Button size="compact-sm" onClick={() => void write('/api/editorial/decision', 'POST', { site: a.site, action: 'approve', key: sg.key }, `approved: ${sg.key}`)}>Approve</Button>
                    <Button size="compact-sm" variant="default" onClick={() => void write('/api/editorial/decision', 'POST', { site: a.site, action: 'reject', key: sg.key }, `rejected: ${sg.key}`)}>Reject</Button>
                  </Group>
                </Group>
              </Paper>
            )) : <Text size="sm" c="dimmed">No open suggestions — the site matches its plan.</Text>}
          </Stack>
        </Tabs.Panel>
        <Tabs.Panel value="directives"><Directives a={a} write={write} /></Tabs.Panel>
        <Tabs.Panel value="activity">
          <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="md">
            <Paper p="md"><ColumnChart title={<Text fw={600} size="sm">Published per month <Text span c="dimmed" size="xs">last 24 months</Text></Text>} rows={(a.timeline ?? []) as Row[]} label="month" series={[{ key: 'published', label: 'documents published' }]} fmtLabel={(m) => String(m).slice(2).replace('-', '/')} /></Paper>
            <Paper p="md"><ColumnChart title={<Text fw={600} size="sm">Content commits per week <Text span c="dimmed" size="xs">last 26 weeks</Text></Text>} rows={(a.cadence ?? []) as Row[]} label="week" series={[{ key: 'human', label: 'human' }, { key: 'bot', label: 'bot / agent', cls: 's2' }]} fmtLabel={(w) => String(w).slice(5)} /></Paper>
            <Paper p="md"><ColumnChart title={<Text fw={600} size="sm">Age since last update</Text>} rows={(a.aging ?? []) as Row[]} label="bucket" series={[{ key: 'docs', label: 'documents' }]} /></Paper>
            <Paper p="md">
              <Text fw={600} size="sm">Topics</Text>
              <Text size="xs" c="dimmed" mb={6}>top tags · arrows compare the last {t.recent_days} days with the {t.recent_days} before</Text>
              <HBars rows={((a.topics ?? []) as Row[]).slice(0, 14)} label="tag" value="docs" extra={(r) => (Number(r.trend) ? ` ${Number(r.trend) > 0 ? '▲' : '▼'}${Math.abs(Number(r.trend))}` : '')} />
              {(a.rising ?? []).length || (a.fading ?? []).length ? (
                <Text size="xs" c="dimmed" mt="xs">
                  {(a.rising ?? []).length ? `rising: ${(a.rising as Row[]).map((x) => x.tag).join(', ')}` : ''}
                  {(a.fading ?? []).length ? ` · fading: ${(a.fading as Row[]).map((x) => x.tag).join(', ')}` : ''}
                </Text>
              ) : null}
            </Paper>
          </SimpleGrid>
          <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="md">
            <Section title="Sections">
              <DataTable<Row>
                rows={(a.sections ?? []) as Row[]}
                rowKey={(c) => String(c.name)}
                dense
                columns={[
                  { key: 'n', header: 'section', sort: (c) => String(c.name), render: (c) => <Text size="sm">{String(c.name)}</Text> },
                  { key: 'd', header: 'docs', num: true, sort: (c) => Number(c.docs), render: (c) => fmt(c.docs) },
                  { key: 'r', header: 'new', num: true, sort: (c) => Number(c.recent), render: (c) => fmt(c.recent) },
                  { key: 's', header: 'stale', num: true, sort: (c) => Number(c.stale), render: (c) => fmt(c.stale) },
                  { key: 'w', header: 'newest', render: (c) => <Text size="sm">{String(c.newest ?? '—')}</Text> },
                ]}
              />
            </Section>
            <div>
              <Section title="Authors"><Paper p="md"><HBars rows={(a.authors ?? []) as Row[]} label="author" value="docs" /></Paper></Section>
              <Section title="Hygiene" actions={(a.issues ?? []).length ? <Anchor size="sm" onClick={() => setView('issues')}>show affected documents</Anchor> : null}>
                <Paper p="md">{(a.issues ?? []).length ? <HBars rows={a.issues as Row[]} label="issue" value="docs" /> : <Text size="sm" c="dimmed">clean</Text>}</Paper>
              </Section>
            </div>
          </SimpleGrid>
        </Tabs.Panel>
        <Tabs.Panel value="documents"><Documents a={a} view={view} setView={setView} /></Tabs.Panel>
        <Tabs.Panel value="brief"><LogView raw={brief} height={600} /></Tabs.Panel>
      </Tabs>
    </>
  );
}

export function ContentSite() {
  const { site = '' } = useParams();
  const content = useContent();
  return (
    <Load q={content} rows={8}>
      {(c) => {
        const a = ((c.sites ?? []) as Row[]).find((s) => s.site === site);
        if (a) return <SiteBody a={a} />;
        const declared = ((c.declared ?? []) as Row[]).find((s) => s.name === site);
        return (
          <>
            <PageHeader crumbs={[{ label: 'Content sites', to: to.content() }, { label: site }]} title={site}
              actions={<RunButton op="content-sync" params={{ target: site }} variant="filled">Sync this site</RunButton>} />
            <Banner tone={declared ? 'info' : 'warn'} title={declared ? 'Not synced yet' : 'Not a declared content site'}>
              {declared ? 'Sync it to read its documents and git history into the atlas.' : <>Declare it under <Mono>content.sites</Mono> in _data/fleet.yml first.</>}
            </Banner>
          </>
        );
      }}
    </Load>
  );
}
