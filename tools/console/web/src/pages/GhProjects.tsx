// GitHub Projects (v2) across every fleet owner, read-only (gh_projects.py,
// /api/gh-projects*; docs/PROJECTS-FRAMEWORK.md § 3a, epic #468 P1): which
// owners the token can read and why the others cannot, every project, and one
// project's items as a table or as a board grouped by its Status field.
// Console-only: it is read with the operator's token, and a private project's
// title must never reach the public snapshot, so the published page says so.
import { useMemo } from 'react';
import { useSearchParams } from 'react-router';
import { Badge, Group, Paper, SegmentedControl, Select, SimpleGrid, Stack, Text, TextInput, Title } from '@mantine/core';
import { IconSearch } from '@tabler/icons-react';
import { hasConsole } from '../api/backend';
import { useGhProjectItems, useGhProjects } from '../api/hooks';
import type { GhProject, GhProjectItem, GhProjectItemsDoc, GhProjectOwner, GhProjectsDoc } from '../api/types';
import { DataTable, type Column } from '../components/DataTable';
import { Banner, Empty, External, Load, LocalOnly, Mono, PageHeader, Section, Status, type Tone } from '../components/ui';
import { includesText } from '../lib/format';

const NO_STATUS = 'No Status';
const CARDS_PER_COLUMN = 50;
const SHOWN_FIELD_TYPES = new Set(['SINGLE_SELECT', 'ITERATION', 'NUMBER']);
const KINDS = ['all', 'issue', 'pr', 'draft'];

const OWNER_TONE: Record<GhProjectOwner['status'], Tone> = { ok: 'good', scope_missing: 'warn', error: 'crit', skipped: 'info' };
const DOC_TONE: Record<GhProjectsDoc['status'], Tone> = { fresh: 'good', partial: 'warn', scope_missing: 'warn', unavailable: 'crit' };

const statusOf = (it: GhProjectItem): string => {
  const v = it.fields?.Status;
  return v === null || v === undefined || v === '' ? NO_STATUS : String(v);
};
const refOf = (it: GhProjectItem): string => (it.repo && it.number != null ? `${it.repo}#${it.number}` : it.kind === 'draft' ? 'draft' : '—');

function OwnerPill({ o }: { o: GhProjectOwner }) {
  const label = o.status === 'ok' ? `${o.login} · ${o.projects ?? 0} project${o.projects === 1 ? '' : 's'}` : `${o.login} · ${o.status.replace('_', ' ')}`;
  return <Status tone={OWNER_TONE[o.status]} title={o.error}>{label}</Status>;
}

function KindBadge({ kind }: { kind: GhProjectItem['kind'] }) {
  return <Badge size="xs" variant="light" color={kind === 'pr' ? 'grape' : kind === 'draft' ? 'gray' : 'blue'}>{kind === 'pr' ? 'PR' : kind}</Badge>;
}

function ItemLink({ it }: { it: GhProjectItem }) {
  return it.url ? <External href={it.url} size="sm"><Mono>{refOf(it)}</Mono></External> : <Mono dim>{refOf(it)}</Mono>;
}

/** The project's single-select, iteration and number fields other than Status — the columns a table shows. */
function extraFields(project: GhProject | undefined): string[] {
  return (project?.fields ?? [])
    .filter((f) => f.name && f.name !== 'Status' && SHOWN_FIELD_TYPES.has(f.type ?? ''))
    .map((f) => f.name as string)
    .slice(0, 3);
}

/** Board columns: the Status field's options in the project's order, then any value only an item carries, then No Status. */
function boardColumns(project: GhProject | undefined, doc: GhProjectItemsDoc): string[] {
  const options = project?.fields.find((f) => f.name === 'Status')?.options ?? [];
  const seen = doc.statuses.filter((s) => s !== NO_STATUS && !options.includes(s));
  const cols = [...options, ...seen];
  if (doc.counts.by_status[NO_STATUS] || !cols.length) cols.push(NO_STATUS);
  return cols;
}

function ItemsTable({ rows, fields }: { rows: GhProjectItem[]; fields: string[] }) {
  const columns: Column<GhProjectItem>[] = [
    { key: 'kind', header: 'Kind', render: (r) => <KindBadge kind={r.kind} />, sort: (r) => r.kind, width: 70 },
    { key: 'ref', header: 'Item', render: (r) => <ItemLink it={r} />, sort: (r) => refOf(r) },
    { key: 'title', header: 'Title', render: (r) => <Text size="sm" lineClamp={2}>{r.title || '—'}</Text>, sort: (r) => r.title },
    { key: 'status', header: 'Status', render: (r) => <Text size="sm">{statusOf(r)}</Text>, sort: (r) => statusOf(r) },
    ...fields.map((name): Column<GhProjectItem> => ({
      key: `f:${name}`, header: name, render: (r) => <Text size="sm">{r.fields?.[name] ?? '—'}</Text>, sort: (r) => r.fields?.[name] as string | number | null,
    })),
    { key: 'state', header: 'State', render: (r) => <Text size="sm" c="dimmed">{r.state?.toLowerCase() ?? '—'}</Text>, sort: (r) => r.state },
    { key: 'refs', header: 'Refs', render: (r) => <Mono dim>{[...r.refs, ...r.closes.map((c) => `closes ${c}`)].join(' · ') || '—'}</Mono> },
  ];
  return (
    <DataTable
      rows={rows}
      columns={columns}
      rowKey={(r) => r.item_id}
      rowLabel={(r) => `${refOf(r)} ${r.title}`}
      open={(r) => r.url}
      copy={(r) => r.url}
      empty={<Empty>No item matches.</Empty>}
      keys
      minWidth={760}
      dense
    />
  );
}

function ItemsBoard({ rows, columns, fields }: { rows: GhProjectItem[]; columns: string[]; fields: string[] }) {
  const byStatus = new Map<string, GhProjectItem[]>(columns.map((c) => [c, []]));
  for (const r of rows) byStatus.get(statusOf(r))?.push(r);
  return (
    <SimpleGrid cols={{ base: 1, sm: 2, md: 3, xl: Math.max(1, Math.min(5, columns.length)) }} spacing="sm" data-testid="gh-board">
      {columns.map((col) => {
        const cards = byStatus.get(col) ?? [];
        return (
          <Paper key={col} p="sm" withBorder data-testid="gh-board-column" aria-label={`${col}: ${cards.length} item(s)`}>
            <Group justify="space-between" mb="xs" wrap="nowrap">
              <Title order={3} fz={14}>{col}</Title>
              <Badge size="sm" variant="default">{cards.length}</Badge>
            </Group>
            <Stack gap={6}>
              {cards.length ? null : <Empty>Nothing here.</Empty>}
              {cards.slice(0, CARDS_PER_COLUMN).map((it) => (
                <Paper key={it.item_id} p="xs" withBorder data-testid="gh-board-card">
                  <Group gap={6} wrap="wrap" mb={2}>
                    <KindBadge kind={it.kind} />
                    <ItemLink it={it} />
                  </Group>
                  <Text size="sm" lineClamp={3}>{it.title || '—'}</Text>
                  {fields.some((f) => it.fields?.[f] != null) ? (
                    <Group gap={4} mt={4} wrap="wrap">
                      {fields.filter((f) => it.fields?.[f] != null).map((f) => (
                        <Badge key={f} size="xs" variant="outline" color="gray">{f}: {String(it.fields[f])}</Badge>
                      ))}
                    </Group>
                  ) : null}
                </Paper>
              ))}
              {cards.length > CARDS_PER_COLUMN ? (
                <Text size="xs" c="dimmed">+{cards.length - CARDS_PER_COLUMN} more — narrow it with the filter, or read them in the table.</Text>
              ) : null}
            </Stack>
          </Paper>
        );
      })}
    </SimpleGrid>
  );
}

function Items({ project, view, q, kind }: { project: GhProject; view: string; q: string; kind: string }) {
  const items = useGhProjectItems(project.id);
  const fields = extraFields(project);
  return (
    <Load q={items} rows={6}>
      {(doc) => {
        const rows = doc.items.filter((r) => (kind === 'all' || r.kind === kind) && includesText([r.title, r.repo, r.number, r.state, statusOf(r)], q));
        return (
          <>
            <Group gap="xs" mb="xs" wrap="wrap">
              <Status tone={DOC_TONE[doc.status]}>{doc.status.replace('_', ' ')}</Status>
              <Text size="sm" c="dimmed">
                {rows.length} of {doc.total} item{doc.total === 1 ? '' : 's'} · {Object.entries(doc.counts.by_kind).map(([k, n]) => `${n} ${k}`).join(', ') || 'none'} · {doc.source === 'cache' ? `cached ${doc.age_s}s ago` : 'read now'}
              </Text>
            </Group>
            {doc.capped ? <Banner tone="info" title={`Only the first ${doc.max_items} items are read`}>{doc.hint}</Banner> : null}
            {doc.errors.length ? <Banner tone={doc.total ? 'warn' : 'crit'} title={doc.total ? 'The read stopped early' : 'Could not read the items'}>{doc.errors.join(' · ')}{doc.hint ? ` — ${doc.hint}` : ''}</Banner> : null}
            {view === 'board' ? <ItemsBoard rows={rows} columns={boardColumns(project, doc)} fields={fields} /> : <ItemsTable rows={rows} fields={fields} />}
          </>
        );
      }}
    </Load>
  );
}

function Projects({ doc }: { doc: GhProjectsDoc }) {
  const [sp, setSp] = useSearchParams();
  const set = (k: string, v: string | null, dflt = '') => {
    const next = new URLSearchParams(sp);
    if (v && v !== dflt) next.set(k, v); else next.delete(k);
    setSp(next, { replace: true });
  };
  const showClosed = sp.get('closed') === '1';
  const visible = doc.projects.filter((p) => showClosed || !p.closed);
  const chosen = visible.find((p) => p.id === sp.get('project')) ?? visible[0];
  const view = sp.get('view') === 'board' ? 'board' : 'table';
  const q = sp.get('q') ?? '';
  const kind = KINDS.includes(sp.get('kind') ?? '') ? (sp.get('kind') as string) : 'all';
  const groups = useMemo(() => {
    const out: { group: string; items: { value: string; label: string }[] }[] = [];
    for (const p of visible) {
      let g = out.find((x) => x.group === p.owner);
      if (!g) out.push((g = { group: p.owner, items: [] }));
      g.items.push({ value: p.id, label: `#${p.number} ${p.title}${p.closed ? ' (closed)' : ''}` });
    }
    return out;
  }, [visible]);

  return (
    <>
      <Group gap="xs" wrap="wrap" mb="xs" aria-label="Owners">
        {doc.owners.map((o) => <OwnerPill key={o.login} o={o} />)}
      </Group>
      {doc.status !== 'fresh' ? (
        <Banner tone={DOC_TONE[doc.status]} title={doc.status === 'scope_missing' ? 'The token cannot read Projects' : doc.status === 'partial' ? 'Some owners could not be read' : 'GitHub could not be read'}>
          {doc.hint ?? 'Each owner above says why'}. Token: <Mono>{doc.token_source ?? 'none'}</Mono>.
        </Banner>
      ) : null}
      <Section
        title="Project"
        mt="md"
        description={`${doc.counts.projects} project${doc.counts.projects === 1 ? '' : 's'} across ${doc.counts.read} of ${doc.counts.owners} owners · ${doc.source === 'cache' ? `cached ${doc.age_s}s ago` : doc.source === 'none' ? 'no token' : 'read now'} · token ${doc.token_source ?? 'none'} · ${doc.budget.left} of ${doc.budget.limit} GraphQL calls left this window`}
      >
        {visible.length ? (
          <Group gap="sm" wrap="wrap" align="flex-end">
            <Select
              label="Project"
              data={groups}
              value={chosen?.id ?? null}
              onChange={(v) => set('project', v)}
              allowDeselect={false}
              searchable
              w={{ base: '100%', sm: 360 }}
            />
            {chosen ? <External href={chosen.url} size="sm">open on GitHub</External> : null}
            <SegmentedControl size="xs" aria-label="View" data={[{ value: 'table', label: 'Table' }, { value: 'board', label: 'Board' }]} value={view} onChange={(v) => set('view', v, 'table')} />
            <SegmentedControl size="xs" aria-label="Closed projects" data={[{ value: '0', label: 'Open' }, { value: '1', label: 'With closed' }]} value={showClosed ? '1' : '0'} onChange={(v) => set('closed', v, '0')} />
          </Group>
        ) : (
          <Empty>{doc.projects.length ? 'Every project is closed — show the closed ones.' : 'No project is readable with this token.'}</Empty>
        )}
      </Section>
      {chosen ? (
        <Section title={`#${chosen.number} ${chosen.title}`} description={`${chosen.owner} · read-only: moving or editing an item is a confirmed plan (constitution § 11), which this page does not offer yet.`}>
          <Group gap="sm" mb="sm" wrap="wrap">
            <TextInput data-page-search leftSection={<IconSearch size={15} />} placeholder="Filter…  ( / )" aria-label="Filter items" value={q} onChange={(e) => set('q', e.currentTarget.value)} w={{ base: '100%', sm: 260 }} />
            <SegmentedControl size="xs" aria-label="Kind" data={KINDS} value={kind} onChange={(v) => set('kind', v, 'all')} />
          </Group>
          <Items project={chosen} view={view} q={q} kind={kind} />
        </Section>
      ) : null}
    </>
  );
}

export function GhProjects() {
  const live = hasConsole();
  const doc = useGhProjects(live);
  return (
    <>
      <PageHeader
        title="GitHub Projects"
        description="Projects (v2) across every fleet owner — bamr87, year-of-ai, ai-world-view, bash-365 and EissaLab — read with PROJECTS_TOKEN, else the console's own GitHub login. An owner the token cannot read says why instead of looking empty. Read-only, cached for ten minutes, inside a GraphQL call budget (docs/PROJECTS-FRAMEWORK.md § 3a)."
      />
      {live ? <Load q={doc} rows={6}>{(d) => <Projects doc={d} />}</Load> : <LocalOnly what="GitHub Projects are read with the operator's token, and a private project's title is never published" />}
    </>
  );
}
