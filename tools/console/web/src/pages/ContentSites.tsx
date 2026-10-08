// The content atlas (docs/CONTENT-ATLAS.md): what each content site
// publishes, about what, and how fresh — against the editorial plan a human
// sets in _data/editorial.yml. A site opens its page; the page is where
// suggestions are approved and directives filed.
import { Group, Paper, SimpleGrid, Text } from '@mantine/core';
import { useContent } from '../api/hooks';
import type { Dict } from '../api/types';
import { DataTable } from '../components/DataTable';
import { Banner, External, Load, Mono, PageHeader, Section, StatTile, Status } from '../components/ui';
import { RunButton } from '../jobs/RunButton';
import { ago, fmt, sharePct } from '../lib/format';
import { to } from '../lib/links';

type Row = Dict<any>;

export const offTarget = (a: Row) =>
  ((a.pillars ?? []) as Row[]).filter((p) => p.target_share != null && p.status === 'active' && Math.abs(p.recent_share - p.target_share) > p.target_share * 0.5).length;

export function ContentSites() {
  const content = useContent();
  return (
    <>
      <PageHeader
        title="Content sites"
        description={<>Sites declared in <Mono>_data/fleet.yml content.sites</Mono>, measured against the narrative and pillars in <Mono>_data/editorial.yml</Mono>. Approving a suggestion writes it there as a directive (the commit stays with you); filing turns approved directives into issues in the site's own repo.</>}
        actions={
          <>
            <RunButton op="content-sync" variant="filled">Sync all sites</RunButton>
            <RunButton op="content-sync" params={{ no_fetch: true }}>Sync local checkouts only</RunButton>
          </>
        }
      />
      <Load q={content} rows={6}>
        {(c) => {
          if (!c.present) {
            return (
              <>
                {c.error ? <Banner tone="crit">{String(c.error)}</Banner> : <Banner tone="info" title="The atlas is empty">Sync all sites: local checkouts are read where they exist and the rest are cloned (public repos need no token).</Banner>}
                <Section title={`Declared sites (${(c.declared ?? []).length})`}>
                  <DataTable<Row>
                    rows={(c.declared ?? []) as Row[]}
                    rowKey={(s) => String(s.name)}
                    href={(s) => to.site(String(s.name))}
                    columns={[
                      { key: 'name', header: 'site', render: (s) => <Mono>{String(s.name)}</Mono> },
                      { key: 'repo', header: 'repo', render: (s) => <Text size="sm">{String(s.repo ?? '—')}</Text> },
                      { key: 'live', header: 'live', render: (s) => (s.live_url ? <External href={String(s.live_url)} size="sm">{String(s.live_url)}</External> : '—') },
                    ]}
                  />
                </Section>
              </>
            );
          }
          const sites = (c.sites ?? []) as Row[];
          const f = (c.fleet ?? {}) as Row;
          return (
            <>
              {(c.unsynced ?? []).length ? <Banner tone="warn">Not synced yet: {(c.unsynced as string[]).join(', ')}</Banner> : null}
              <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }} spacing="md">
                <StatTile label="Sites" value={fmt(f.sites)} sub={`${fmt(f.docs)} published documents`} />
                <StatTile label={`New (last ${fmt(sites[0]?.totals?.recent_days)} days)`} value={fmt(f.recent)} sub="across the fleet" />
                <StatTile label="Stale (a year untouched)" value={fmt(f.stale)} sub={`${sharePct(f.docs ? f.stale / f.docs : 0)} of documents`} />
                <StatTile label="Open suggestions" value={fmt(f.suggestions)} sub={`${fmt(f.approved)} approved, not yet filed`} />
              </SimpleGrid>
              <Section title="Sites">
                <DataTable<Row>
                  rows={sites}
                  keys
                  rowKey={(a) => String(a.site)}
                  href={(a) => to.site(String(a.site))}
                  openLive={(a) => a.live_url}
                  initialSort={{ key: 'sugg', desc: true }}
                  tone={(a) => (a.error ? 'crit' : undefined)}
                  minWidth={980}
                  columns={[
                    { key: 'site', header: 'site', sort: (a) => String(a.site), render: (a) => <Group gap={6}><Text fw={600} size="sm">{String(a.site)}</Text>{a.error ? <Status tone="crit">sync failed</Status> : null}</Group> },
                    { key: 'docs', header: 'docs', num: true, sort: (a) => a.totals.docs, render: (a) => fmt(a.totals.docs) },
                    { key: 'new', header: 'new', num: true, sort: (a) => a.totals.recent, render: (a) => fmt(a.totals.recent) },
                    {
                      key: 'last', header: 'last published', sort: (a) => a.totals.days_since_publish ?? 99999, render: (a) => {
                        const late = a.totals.days_since_publish == null || a.totals.days_since_publish > 30;
                        return <Group gap={6} wrap="nowrap"><Text size="sm">{String(a.totals.last_published ?? '—')}</Text>{late ? <Status tone="warn">{ago(a.totals.days_since_publish)} ago</Status> : <Text size="xs" c="dimmed">{ago(a.totals.days_since_publish)} ago</Text>}</Group>;
                      },
                    },
                    { key: 'age', header: 'median age', num: true, sort: (a) => a.totals.median_age ?? 0, render: (a) => ago(a.totals.median_age) },
                    { key: 'stale', header: 'stale', num: true, sort: (a) => a.totals.stale, render: (a) => fmt(a.totals.stale) },
                    { key: 'hyg', header: 'hygiene', num: true, sort: (a) => a.totals.with_issues, render: (a) => fmt(a.totals.with_issues) },
                    { key: 'pill', header: 'pillars off target', num: true, sort: (a) => offTarget(a), render: (a) => ((a.pillars ?? []).length ? `${offTarget(a)} / ${(a.pillars as Row[]).filter((p) => p.target_share != null).length}` : <Text span size="xs" c="dimmed">no pillars</Text>) },
                    { key: 'sugg', header: 'suggestions', num: true, sort: (a) => (a.suggestions ?? []).length, render: (a) => fmt((a.suggestions ?? []).length) },
                    { key: 'sync', header: 'synced', render: (a) => <Text size="xs" c="dimmed">{String(a.synced_at ?? '').slice(0, 16).replace('T', ' ')} · {String(a.source ?? '')}</Text> },
                  ]}
                />
              </Section>
              {(c.overlap ?? []).length ? (
                <Section title={`Shared topics across sites (${c.overlap.length})`} description="Tags two or more sites cover — cross-link candidates, or two narratives competing for one reader.">
                  <Paper p="xs">
                    <DataTable<Row>
                      rows={c.overlap as Row[]}
                      rowKey={(o) => String(o.tag)}
                      dense
                      columns={[
                        { key: 'tag', header: 'tag', render: (o) => <Mono>{String(o.tag)}</Mono> },
                        { key: 'n', header: 'sites', num: true, sort: (o) => Object.keys(o.sites).length, render: (o) => Object.keys(o.sites).length },
                        { key: 'where', header: 'where', render: (o) => <Text size="sm">{Object.entries(o.sites as Record<string, number>).map(([s, n]) => `${s} ${n}`).join(' · ')}</Text> },
                      ]}
                    />
                  </Paper>
                </Section>
              ) : null}
            </>
          );
        }}
      </Load>
    </>
  );
}
