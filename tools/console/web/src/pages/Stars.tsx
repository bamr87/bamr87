// The open-source radar (tools/fleetcore/stars.py over tools/stargazer.py, docs/STARGAZER.md): the account's
// GitHub stars sorted and categorised, the repos rising this week, this month and in the fleet's topics, the
// repos most like each fleet project, what a fleet project should review, and the feed. One committed document
// (_data/stars.json through /api/stars) renders the same on a console and on the published page; every filter
// runs here, in the browser. On a console, "Read GitHub now" runs the stars-refresh operation. A repo's name,
// description and topics are third-party text: React renders them as text, never as HTML.
import { lazy, Suspense, useMemo, useState, type ReactNode } from 'react';
import { Link, useSearchParams } from 'react-router';
import {
  Anchor, Avatar, Badge, Button, Code, CopyButton, Drawer, Group, List, Paper, Select, SimpleGrid, Skeleton, Stack, Switch, Tabs, Text, TextInput, Tooltip,
} from '@mantine/core';
import { useMediaQuery } from '@mantine/hooks';
import { IconAlertTriangle, IconChartDots, IconCheck, IconCopy, IconRefresh, IconSearch, IconSparkles, IconStar } from '@tabler/icons-react';
import { hasConsole } from '../api/backend';
import { useObservability, useStars } from '../api/hooks';
import type { StarEvent, StarHealth, StarIncorporate, StarRepo, StarsDoc, StarVerdict } from '../api/types';
import { ColumnChart, HBars } from '../components/Charts';
import { DataTable, type Column } from '../components/DataTable';
import { Banner, Empty, External, Load, Mono, PageHeader, Section, StatTile, Status, type Tone } from '../components/ui';
import { SegmentBar, type Segment } from '../components/Viz';
import { useRunner } from '../jobs/JobRunner';
import { gh, to } from '../lib/links';

const DOC = gh.hubFile('docs/STARGAZER.md');
const DAY = 86_400_000;
const TABS = ['radar', 'starred', 'trending', 'fleet', 'themes', 'map', 'feed'] as const;
const StarMap = lazy(() => import('../components/StarMap'));
type Tab = (typeof TABS)[number];
const HUB = 'bamr87';

const HEALTH: Record<StarHealth, { tone: Tone; seg: Segment['tone']; hint: string }> = {
  active: { tone: 'good', seg: 'good', hint: 'pushed in the last 30 days' },
  maintained: { tone: 'info', seg: 'info', hint: 'pushed in the last 6 months' },
  slowing: { tone: 'warn', seg: 'warn', hint: 'last push 6–12 months ago' },
  stale: { tone: 'warn', seg: 'muted', hint: 'no push for over a year' },
  archived: { tone: 'crit', seg: 'crit', hint: 'archived by its owner' },
  unknown: { tone: 'info', seg: 'muted', hint: 'no push date' },
};
const VERDICT: Record<StarVerdict, { color: string; hint: string }> = {
  adopt: { color: 'green', hint: 'a fleet project should use it' },
  borrow: { color: 'blue', hint: 'take an idea, pattern or piece from it' },
  watch: { color: 'gray', hint: 'promising, not yet' },
  skip: { color: 'red', hint: 'no use to the fleet' },
};

function VerdictBadge({ r }: { r: StarRepo }) {
  if (!r.ai?.verdict) return <Text size="xs" c="dimmed">—</Text>;
  const v = VERDICT[r.ai.verdict];
  return (
    <Tooltip label={`${r.ai.summary}${r.ai.project ? ` → ${r.ai.project}` : ''}${r.ai.stale ? ' (stale: the repo changed since)' : ''}`} multiline maw={340}>
      <Badge size="sm" variant={r.ai.stale ? 'outline' : 'light'} color={v?.color ?? 'gray'}>{r.ai.verdict}</Badge>
    </Tooltip>
  );
}

const EVENT: Record<StarEvent['kind'], { color: string; label: string }> = {
  starred: { color: 'yellow', label: 'starred' },
  release: { color: 'blue', label: 'release' },
  spike: { color: 'grape', label: 'spike' },
  radar: { color: 'teal', label: 'new on radar' },
};

const k = (n: number | null | undefined): string => {
  const v = Number(n ?? 0);
  return v >= 1000 ? `${(v / 1000).toFixed(v >= 100_000 ? 0 : 1).replace(/\.0$/, '')}k` : String(v);
};
const daysSince = (iso?: string | null): number | null => (iso ? Math.max(0, Math.floor((Date.now() - Date.parse(iso.length === 10 ? `${iso}T00:00:00Z` : iso)) / DAY)) : null);
const ageLabel = (iso?: string | null): string => {
  const d = daysSince(iso);
  if (d == null) return '—';
  if (d < 1) return 'today';
  if (d < 60) return `${d}d ago`;
  if (d < 730) return `${Math.round(d / 30)}mo ago`;
  return `${(d / 365).toFixed(1)}y ago`;
};
const avatarSrc = (r: StarRepo) => (r.avatar ? `https://avatars.githubusercontent.com/${r.avatar}?s=48&v=4` : undefined);
const projectHref = (name: string) => (name === HUB ? to.overview() : to.project(name));
const matchFor = (r: StarRepo, project: string) => r.matches?.find((m) => m.project === project);
const sourceLabel = (s: string, doc: StarsDoc): string => {
  if (s === 'starred') return 'starred';
  const [kind, id] = s.split(':', 2);
  if (kind === 'trending') return doc.trending.find((t) => t.id === id)?.title ?? 'trending';
  if (kind === 'discover') return `like ${id}`;
  return s;
};

function useTabState() {
  const [params, setParams] = useSearchParams();
  const raw = params.get('tab') as Tab | null;
  const tab: Tab = raw && (TABS as readonly string[]).includes(raw) ? raw : 'radar';
  const set = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(patch)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    setParams(next, { replace: true });
  };
  return { params, tab, set };
}

function RepoCell({ r, open, starredBadge = true }: { r: StarRepo; open: (name: string) => void; starredBadge?: boolean }) {
  return (
    <Group gap={8} wrap="nowrap" align="flex-start">
      <Avatar src={avatarSrc(r)} size={24} radius="sm" alt="">{r.owner.slice(0, 1).toUpperCase()}</Avatar>
      <div style={{ minWidth: 0 }}>
        <Group gap={6} wrap="nowrap">
          <Anchor component="button" type="button" size="sm" fw={600} onClick={(e) => { e.stopPropagation(); open(r.name); }} style={{ textAlign: 'left' }}>{r.name}</Anchor>
          {starredBadge && r.starred_at ? <Tooltip label={`starred ${r.starred_at.slice(0, 10)}`}><IconStar size={13} aria-label="starred" color="var(--mantine-color-yellow-filled)" /></Tooltip> : null}
          {r.suspect?.length ? <Tooltip label={r.suspect.join(' · ')}><Badge size="xs" color="red" variant="light" leftSection={<IconAlertTriangle size={10} />}>suspect</Badge></Tooltip> : null}
          {r.archived ? <Badge size="xs" color="gray" variant="light">archived</Badge> : null}
        </Group>
        {r.description ? <Text size="xs" c="dimmed" lineClamp={1}>{r.description}</Text> : null}
      </div>
    </Group>
  );
}

function MatchCell({ r, project }: { r: StarRepo; project?: string }) {
  const m = project ? matchFor(r, project) : r.matches?.[0];
  if (!m) return <Text size="xs" c="dimmed">—</Text>;
  return (
    <Tooltip label={`shares ${m.shared.join(', ') || 'terms'} · similarity ${m.score.toFixed(2)}`} multiline maw={320}>
      <Group gap={6} wrap="nowrap">
        <Anchor component={Link} to={projectHref(m.project)} size="xs" onClick={(e) => e.stopPropagation()}>{m.project}</Anchor>
        <Badge size="xs" variant="light" color={m.score >= 0.3 ? 'green' : m.score >= 0.18 ? 'blue' : 'gray'}>{Math.round(m.score * 100)}</Badge>
      </Group>
    </Tooltip>
  );
}

function columns(doc: StarsDoc, open: (n: string) => void, extra: Column<StarRepo>[] = [], project?: string, omit: string[] = []): Column<StarRepo>[] {
  const cat = Object.fromEntries(doc.categories.map((c) => [c.id, c.title]));
  const all: Column<StarRepo>[] = [
    { key: 'repo', header: 'repo', sort: (r) => r.name.toLowerCase(), render: (r) => <RepoCell r={r} open={open} /> },
    { key: 'stars', header: '★', num: true, sort: (r) => r.stars, render: (r) => <Mono>{k(r.stars)}</Mono>, width: 64 },
    { key: 'd7', header: '+7d', num: true, title: 'stars gained in the last 7 days (from the committed history)', sort: (r) => r.velocity?.d7 ?? null,
      render: (r) => (r.velocity?.d7 != null ? <Mono>+{k(r.velocity.d7)}</Mono> : <Text size="xs" c="dimmed">—</Text>), width: 64 },
    ...extra,
    { key: 'category', header: 'category', sort: (r) => cat[r.category] ?? r.category, render: (r) => <Badge size="sm" variant="light">{cat[r.category] ?? r.category}</Badge> },
    { key: 'language', header: 'language', sort: (r) => r.language ?? '', render: (r) => <Text size="xs">{r.language ?? '—'}</Text> },
    { key: 'pushed', header: 'pushed', sort: (r) => r.pushed_at ?? '', render: (r) => <Mono dim>{ageLabel(r.pushed_at)}</Mono> },
    { key: 'health', header: 'health', sort: (r) => r.health, render: (r) => <Status tone={HEALTH[r.health]?.tone ?? 'info'} title={HEALTH[r.health]?.hint}>{r.health}</Status> },
    { key: 'like', header: project ? 'match' : 'like', title: 'the closest fleet project and how close (0–100)', sort: (r) => (project ? matchFor(r, project)?.score : r.matches?.[0]?.score) ?? null,
      render: (r) => <MatchCell r={r} project={project} /> },
    { key: 'ai', header: 'AI', title: 'the AI review’s verdict: adopt · borrow · watch · skip (tools/dash stars review)',
      sort: (r) => (r.ai?.verdict ? ['adopt', 'borrow', 'watch', 'skip'].indexOf(r.ai.verdict) : null), render: (r) => <VerdictBadge r={r} /> },
  ];
  return all.filter((c) => !omit.includes(c.key));
}

function IncorporateTable({ rows, doc, open }: { rows: StarIncorporate[]; doc: StarsDoc; open: (n: string) => void }) {
  if (!rows.length) return <Empty>Nothing on the radar is close enough to a fleet project yet.</Empty>;
  return (
    <DataTable<StarIncorporate>
      rows={rows} rowKey={(i) => i.repo} keys minWidth={760} onActivate={(i) => open(i.repo)}
      columns={[
        { key: 'repo', header: 'repo', sort: (i) => i.repo, render: (i) => (doc.repos[i.repo] ? <RepoCell r={doc.repos[i.repo]} open={open} /> : <Mono>{i.repo}</Mono>) },
        { key: 'project', header: 'for', sort: (i) => i.project, render: (i) => <Anchor component={Link} to={projectHref(i.project)} size="sm" onClick={(e) => e.stopPropagation()}>{i.project}</Anchor> },
        { key: 'why', header: 'why', render: (i) => {
          const ai = doc.repos[i.repo]?.ai;
          return (
            <div>
              <Text size="xs">{i.why}</Text>
              {ai?.ideas?.[0] ? <Text size="xs" c="dimmed" lineClamp={2}>idea: {ai.ideas[0]}</Text> : null}
            </div>
          );
        } },
        { key: 'ai', header: 'AI', sort: (i) => (i.verdict ? ['adopt', 'borrow', 'watch', 'skip'].indexOf(i.verdict) : null),
          render: (i) => (doc.repos[i.repo] ? <VerdictBadge r={doc.repos[i.repo]} /> : null) },
        { key: 'stars', header: '★', num: true, sort: (i) => doc.repos[i.repo]?.stars ?? 0, render: (i) => <Mono>{k(doc.repos[i.repo]?.stars)}</Mono> },
        { key: 'priority', header: 'priority', num: true, title: 'similarity × popularity × liveliness, a starred repo ×1.3', sort: (i) => i.priority, render: (i) => <Mono>{i.priority.toFixed(2)}</Mono> },
      ]}
    />
  );
}

function FeedList({ events, open }: { events: StarEvent[]; open: (n: string) => void }) {
  if (!events.length) return <Empty>Nothing happened in the feed window.</Empty>;
  const days = new Map<string, StarEvent[]>();
  for (const e of events) {
    const d = e.at.slice(0, 10);
    days.set(d, [...(days.get(d) ?? []), e]);
  }
  return (
    <Stack gap="sm">
      {[...days.entries()].map(([day, list]) => (
        <div key={day}>
          <Text size="xs" c="dimmed" fw={600} mb={4}>{day}</Text>
          <Stack gap={4}>
            {list.map((e, i) => (
              <Group key={`${e.kind}-${e.repo}-${i}`} gap={8} wrap="nowrap">
                <Badge size="xs" variant="light" color={EVENT[e.kind]?.color ?? 'gray'} w={92}>{EVENT[e.kind]?.label ?? e.kind}</Badge>
                <Anchor component="button" type="button" size="sm" onClick={() => open(e.repo)} style={{ textAlign: 'left' }}>{e.text}</Anchor>
                {e.url ? <External href={e.url} size="xs">notes</External> : null}
              </Group>
            ))}
          </Stack>
        </div>
      ))}
    </Stack>
  );
}

function months(doc: StarsDoc): { month: string; count: number }[] {
  if (!doc.timeline.length) return [];
  const have = Object.fromEntries(doc.timeline.map((m) => [m.month, m.count]));
  const out: { month: string; count: number }[] = [];
  let [y, m] = doc.timeline[0].month.split('-').map(Number);
  const last = doc.timeline[doc.timeline.length - 1].month;
  while (out.length < 400) {
    const key = `${y}-${String(m).padStart(2, '0')}`;
    out.push({ month: key, count: have[key] ?? 0 });
    if (key === last) break;
    m += 1;
    if (m > 12) {
      m = 1;
      y += 1;
    }
  }
  return out.slice(-36);
}

function Radar({ doc, open, set }: { doc: StarsDoc; open: (n: string) => void; set: (p: Record<string, string | null>) => void }) {
  const t = doc.totals;
  const newest = doc.starred[0] ? doc.repos[doc.starred[0]] : undefined;
  const recent = doc.starred.filter((n) => (daysSince(doc.repos[n]?.starred_at) ?? 999) <= 30).length;
  const health: Segment[] = (Object.keys(HEALTH) as StarHealth[])
    .filter((h) => doc.health[h])
    .map((h) => ({ key: h, label: h, value: doc.health[h] ?? 0, tone: HEALTH[h].seg, hint: HEALTH[h].hint }));
  return (
    <>
      <SimpleGrid cols={{ base: 2, md: 5 }} spacing="sm">
        <StatTile label="Starred" value={t.starred ?? 0} sub={`${t.starred_relevant ?? 0} like a fleet project · ${doc.lists.length} public lists`} />
        <StatTile label="To review" value={t.incorporate ?? 0} sub="close to a fleet project, alive, not suspect" />
        <StatTile label="Trending" value={t.trending ?? 0} sub={`repos across ${doc.trending.length} searches`} />
        <StatTile label="Suspect" value={t.suspect ?? 0} tone={t.suspect ? 'crit' : undefined} sub="read as star-farmed; never recommended" />
        <StatTile label="Starred in 30 days" value={recent}
          sub={newest ? <span style={{ overflowWrap: 'anywhere' }}>newest: {newest.name}, {ageLabel(newest.starred_at)}</span> : undefined} />
      </SimpleGrid>
      <SimpleGrid cols={{ base: 1, md: 2 }} spacing="lg">
        <Section title="What you star" description="Starred repos by category. Pick one to list it.">
          <HBars rows={doc.categories.filter((c) => c.starred)} label="title" value="starred" onPick={(r) => set({ tab: 'starred', category: String(r.id) })} />
        </Section>
        <Section title="Languages" description="The primary language of each starred repo.">
          <HBars rows={doc.languages.slice(0, 10)} label="name" value="count" onPick={(r) => set({ tab: 'starred', language: String(r.name) === '—' ? null : String(r.name) })} />
        </Section>
      </SimpleGrid>
      <Section title="Stars per month" description="When each repo was starred (the last three years).">
        <ColumnChart rows={months(doc)} label="month" series={[{ key: 'count', label: 'stars' }]} />
      </Section>
      {health.length ? (
        <Section title="How alive is what you starred" description="By the date of each repo's last push.">
          <SegmentBar segments={health} label="health of the starred repos" />
        </Section>
      ) : null}
      <Section title="To review for the fleet" description="Starred and discovered repos closest to a fleet project, alive and not suspect, at most three per project. Each is a candidate to adopt, borrow from or skip; the Fleet match tab has every project's list."
        actions={<Button size="xs" variant="default" onClick={() => set({ tab: 'fleet' })}>Fleet match</Button>}>
        <IncorporateTable rows={doc.incorporate.slice(0, 12)} doc={doc} open={open} />
      </Section>
      <Section title="Latest" actions={<Button size="xs" variant="default" onClick={() => set({ tab: 'feed' })}>Feed</Button>}>
        <FeedList events={doc.feed.slice(0, 10)} open={open} />
      </Section>
    </>
  );
}

function Starred({ doc, open, params, set }: { doc: StarsDoc; open: (n: string) => void; params: URLSearchParams; set: (p: Record<string, string | null>) => void }) {
  const q = params.get('q') ?? '';
  const category = params.get('category');
  const language = params.get('language');
  const list = params.get('list');
  const project = params.get('project');
  const relevant = params.get('relevant') === '1';
  const rows = useMemo(() => {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    const members = list ? new Set(doc.lists.find((l) => l.name === list)?.repos ?? []) : null;
    return doc.starred.map((n) => doc.repos[n]).filter((r): r is StarRepo => {
      if (!r) return false;
      const hay = `${r.name} ${r.description} ${r.topics.join(' ')}`.toLowerCase();
      return words.every((w) => hay.includes(w))
        && (!category || r.category === category)
        && (!language || r.language === language)
        && (!members || members.has(r.name))
        && (!project || Boolean(matchFor(r, project)))
        && (!relevant || Boolean(r.matches?.length));
    });
  }, [doc, q, category, language, list, project, relevant]);
  const langs = [...new Set(doc.starred.map((n) => doc.repos[n]?.language).filter((x): x is string => Boolean(x)))].sort();
  return (
    <>
      <Paper p="sm" mb="sm">
        <Group gap="sm" wrap="wrap" align="flex-end">
          <TextInput label="Search" placeholder="name, description or topic" leftSection={<IconSearch size={14} />} value={q} onChange={(e) => set({ q: e.currentTarget.value || null })} w={240} />
          <Select label="Category" clearable value={category} onChange={(v) => set({ category: v })} data={doc.categories.filter((c) => c.starred).map((c) => ({ value: c.id, label: `${c.title} (${c.starred})` }))} w={240} />
          <Select label="Language" clearable searchable value={language} onChange={(v) => set({ language: v })} data={langs} w={170} />
          {doc.lists.length ? <Select label="Star list" clearable value={list} onChange={(v) => set({ list: v })} data={doc.lists.map((l) => ({ value: l.name, label: `${l.name} (${l.repos.length})` }))} w={190} /> : null}
          <Select label="Like fleet project" clearable searchable value={project} onChange={(v) => set({ project: v })} data={doc.fleet.filter((f) => f.starred.length).map((f) => f.project)} w={190} />
          <Switch label="Only repos like a fleet project" checked={relevant} onChange={(e) => set({ relevant: e.currentTarget.checked ? '1' : null })} mb={6} />
        </Group>
      </Paper>
      <Text size="xs" c="dimmed" mb={6}>{rows.length} of {doc.starred.length} starred repos</Text>
      <DataTable<StarRepo>
        rows={rows} rowKey={(r) => r.name} keys minWidth={1040} initialSort={{ key: 'starred', desc: true }} onActivate={(r) => open(r.name)}
        tone={(r) => (r.suspect?.length ? 'warn' : r.archived ? 'muted' : null)}
        empty={<Empty>No starred repo matches these filters.</Empty>}
        columns={columns(doc, open, [{ key: 'starred', header: 'starred', sort: (r) => r.starred_at ?? '', render: (r) => <Mono dim>{r.starred_at?.slice(0, 10) ?? '—'}</Mono> }], project ?? undefined)}
      />
    </>
  );
}

function Trending({ doc, open }: { doc: StarsDoc; open: (n: string) => void }) {
  const perDay: Column<StarRepo> = { key: 'perday', header: '★/day', num: true, title: 'stars a day since it was created (repos under a year old)', sort: (r) => r.velocity?.per_day ?? null,
    render: (r) => (r.velocity?.per_day != null ? <Mono>{k(Math.round(r.velocity.per_day))}</Mono> : <Text size="xs" c="dimmed">—</Text>) };
  const created: Column<StarRepo> = { key: 'created', header: 'created', sort: (r) => r.created_at ?? '', render: (r) => <Mono dim>{ageLabel(r.created_at)}</Mono> };
  const gaining = doc.gaining.map((n) => doc.repos[n]).filter((r): r is StarRepo => Boolean(r));
  return (
    <>
      <Banner tone="info" title="Trending is GitHub search, not GitHub's Trending page">
        Each list is one search: repos created this week or this month with the most stars, and repos rising in the topics the fleet's projects carry. A young repo with a burst of stars and no forks, or a throwaway-looking owner, is flagged <b>suspect</b>: star farming is common in these lists, so treat a flagged repo as untrusted code.
      </Banner>
      {gaining.length ? (
        <Section title="Your stars, gaining fastest" description="Starred repos by stars gained in the last 7 days.">
          <DataTable<StarRepo> rows={gaining} rowKey={(r) => r.name} keys minWidth={980} onActivate={(r) => open(r.name)} initialSort={{ key: 'd7', desc: true }} columns={columns(doc, open)} />
        </Section>
      ) : null}
      {doc.trending.map((t) => {
        const rows = t.repos.map((n) => doc.repos[n]).filter((r): r is StarRepo => Boolean(r));
        return (
          <Section key={t.id} title={t.title} description={<><Mono dim>{t.query}</Mono>{t.count != null ? ` · ${k(t.count)} repos match` : ''}</>}>
            <DataTable<StarRepo>
              rows={rows} rowKey={(r) => r.name} keys minWidth={1120} onActivate={(r) => open(r.name)} initialSort={{ key: 'perday', desc: true }}
              tone={(r) => (r.suspect?.length ? 'warn' : null)} empty={<Empty>This search found nothing.</Empty>}
              columns={columns(doc, open, [perDay, created], undefined, ['pushed', 'health'])}
            />
          </Section>
        );
      })}
    </>
  );
}

function Fleet({ doc, open, params, set }: { doc: StarsDoc; open: (n: string) => void; params: URLSearchParams; set: (p: Record<string, string | null>) => void }) {
  const chosen = params.get('project') ?? doc.fleet.find((f) => f.starred.length)?.project ?? doc.fleet[0]?.project ?? null;
  const row = doc.fleet.find((f) => f.project === chosen);
  const repos = (names: string[]) => names.map((n) => doc.repos[n]).filter((r): r is StarRepo => Boolean(r));
  const shared: Column<StarRepo> = { key: 'shared', header: 'shares', render: (r) => <Text size="xs">{matchFor(r, chosen ?? '')?.shared.join(', ') ?? '—'}</Text> };
  return (
    <>
      <Section title="Every fleet project" description="How many starred and discovered repos are close to each project. Discovered repos come from a GitHub search seeded by the project's most specific topics and stack." mt={0}>
        <DataTable
          rows={doc.fleet} rowKey={(f) => f.project} keys minWidth={760} dense maxHeight={320} onActivate={(f) => set({ project: f.project })}
          initialSort={{ key: 'starred', desc: true }}
          columns={[
            { key: 'project', header: 'project', sort: (f) => f.project.toLowerCase(), render: (f) => <Text size="sm" fw={f.project === chosen ? 700 : 500}>{f.project}</Text> },
            { key: 'terms', header: 'what it is about', render: (f) => <Text size="xs" c="dimmed" lineClamp={1}>{f.terms.slice(0, 6).join(', ')}</Text> },
            { key: 'starred', header: 'starred', num: true, sort: (f) => f.starred.length, render: (f) => <Mono>{f.starred.length}</Mono> },
            { key: 'discovered', header: 'discovered', num: true, sort: (f) => f.discovered.length, render: (f) => <Mono>{f.discovered.length}</Mono> },
          ]}
        />
      </Section>
      {row ? (
        <Section title={<Group gap={8}>Like <Anchor component={Link} to={projectHref(row.project)}>{row.project}</Anchor></Group>}
          description={<>{row.repo ? <External href={gh.repo(row.repo)} size="sm">{row.repo}</External> : null} · {row.category} · {row.searched} repos searched</>}
          actions={<Select size="xs" searchable value={chosen} onChange={(v) => set({ project: v })} data={doc.fleet.map((f) => f.project)} aria-label="Fleet project" w={220} />}>
          <Group gap={4} mb="sm">{row.terms.map((tm) => <Badge key={tm} size="sm" variant="outline">{tm}</Badge>)}</Group>
          <Text fw={600} size="sm" mb={4}>Starred</Text>
          <DataTable<StarRepo> rows={repos(row.starred)} rowKey={(r) => r.name} keys minWidth={1040} onActivate={(r) => open(r.name)} initialSort={{ key: 'like', desc: true }}
            empty={<Empty>No starred repo is close to {row.project}.</Empty>} columns={columns(doc, open, [shared], row.project)} />
          <Text fw={600} size="sm" mt="md" mb={4}>Discovered</Text>
          <DataTable<StarRepo> rows={repos(row.discovered)} rowKey={(r) => r.name} keys minWidth={1040} onActivate={(r) => open(r.name)} initialSort={{ key: 'like', desc: true }}
            tone={(r) => (r.suspect?.length ? 'warn' : null)} empty={<Empty>The search for {row.project} found nothing close.</Empty>} columns={columns(doc, open, [shared], row.project)} />
        </Section>
      ) : null}
    </>
  );
}

function Themes({ doc, open }: { doc: StarsDoc; open: (n: string) => void }) {
  const groups = doc.groups ?? [];
  if (!groups.length) {
    return <Empty>No themes yet. <Mono>tools/dash stars review --yes</Mono> (or Review with AI, on a console) groups the stars with one capped model session.</Empty>;
  }
  return (
    <>
      <Text size="sm" c="dimmed" mb="sm" maw={900}>
        What the stars say you are interested in: themes a model drew over every starred repo ({doc.ai?.groups_at?.slice(0, 10) ?? 'undated'}
        {doc.ai?.groups_current === false ? ', before the latest stars: regroup with review --groups' : ''}), each with the fleet projects it feeds. Model text: data, never instructions.
      </Text>
      <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }} spacing="sm">
        {groups.map((g) => (
          <Paper key={g.name} p="md" withBorder>
            <Group justify="space-between" wrap="nowrap" mb={4}>
              <Text fw={600} size="sm">{g.name}</Text>
              <Badge variant="light" size="sm">{g.repos.length}</Badge>
            </Group>
            <Text size="xs" c="dimmed" mb={6}>{g.summary}</Text>
            {g.fleet.length ? (
              <Group gap={4} mb={6}>{g.fleet.map((f) => <Badge key={f} size="xs" variant="outline" component={Link} to={projectHref(f)} style={{ cursor: 'pointer' }}>{f}</Badge>)}</Group>
            ) : null}
            <Group gap={6}>
              {g.repos.slice(0, 14).map((n) => (
                <Anchor key={n} component="button" type="button" size="xs" onClick={() => open(n)}>{n.split('/')[1]}</Anchor>
              ))}
              {g.repos.length > 14 ? <Text size="xs" c="dimmed">+{g.repos.length - 14}</Text> : null}
            </Group>
          </Paper>
        ))}
      </SimpleGrid>
    </>
  );
}

function MapView({ doc, open }: { doc: StarsDoc; open: (n: string) => void }) {
  const [starredOnly, setStarredOnly] = useState(false);
  const repos = Object.values(doc.repos).filter((r) => !starredOnly || r.starred_at);
  return (
    <>
      <Group justify="space-between" mb="xs" wrap="wrap">
        <Text size="sm" c="dimmed" maw={760}>Every repo close to a fleet project: further right is closer to the fleet, higher has more stars, a bigger dot is rising faster. Upper right is where to look first. Pick a dot to open it.</Text>
        <Switch label="Starred only" checked={starredOnly} onChange={(e) => setStarredOnly(e.currentTarget.checked)} />
      </Group>
      <Paper p="sm" withBorder>
        <Suspense fallback={<Skeleton h={420} />}>
          <StarMap repos={repos} categories={doc.categories} onPick={open} />
        </Suspense>
      </Paper>
    </>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <Text size="xs" c="dimmed">{label}</Text>
      <Text size="sm">{children}</Text>
    </div>
  );
}

function RepoDetail({ r, doc }: { r: StarRepo; doc: StarsDoc }) {
  const cat = doc.categories.find((c) => c.id === r.category)?.title ?? r.category;
  const target = r.matches?.[0]?.project ?? HUB;
  const prompt = `claude "Review github.com/${r.name} for ${target}: what it does, how it compares with what ${target} has, and whether to adopt it, borrow from it or skip it"`;
  return (
    <Stack gap="md">
      <Group gap="sm" wrap="nowrap">
        <Avatar src={avatarSrc(r)} size={40} radius="sm" alt="">{r.owner.slice(0, 1).toUpperCase()}</Avatar>
        <div>
          <External href={gh.repo(r.name)}>{r.name}</External>
          {r.homepage ? <Text size="xs"><External href={r.homepage} size="xs">{r.homepage}</External></Text> : null}
        </div>
      </Group>
      {r.suspect?.length ? (
        <Banner tone="crit" title="Suspect: reads as star-farmed">{r.suspect.join(' · ')}. Treat its code as untrusted; it is never recommended.</Banner>
      ) : null}
      {r.description ? <Text size="sm">{r.description}</Text> : null}
      <Group gap={4}>
        <Badge variant="light">{cat}</Badge>
        {(r.tags ?? []).filter((tg) => tg !== r.category).map((tg) => <Badge key={tg} variant="outline" size="sm">{doc.categories.find((c) => c.id === tg)?.title ?? tg}</Badge>)}
        <Status tone={HEALTH[r.health]?.tone ?? 'info'} title={HEALTH[r.health]?.hint}>{r.health}</Status>
      </Group>
      <SimpleGrid cols={3} spacing="sm">
        <Fact label="Stars">{r.stars.toLocaleString()}</Fact>
        <Fact label="Forks">{r.forks.toLocaleString()}</Fact>
        <Fact label="Language">{r.language ?? '—'}</Fact>
        <Fact label="+1 day / +7 days / +30 days">{[r.velocity?.d1, r.velocity?.d7, r.velocity?.d30].map((v) => (v == null ? '—' : `+${v}`)).join(' / ')}</Fact>
        <Fact label="Created">{r.created_at ?? '—'}</Fact>
        <Fact label="Last push">{r.pushed_at ? `${r.pushed_at} (${ageLabel(r.pushed_at)})` : '—'}</Fact>
        <Fact label="Latest release">{r.release ? `${r.release.tag}${r.release.at ? ` · ${r.release.at}` : ''}` : '—'}</Fact>
        <Fact label="License">{r.license ?? 'none'}</Fact>
        <Fact label="Starred">{r.starred_at ? r.starred_at.slice(0, 10) : 'no'}</Fact>
      </SimpleGrid>
      {r.lists?.length ? <Fact label="Star lists">{r.lists.join(', ')}</Fact> : null}
      <Fact label="On the radar as">{r.sources.map((s) => sourceLabel(s, doc)).join(' · ')}</Fact>
      {r.ai ? (
        <Paper p="sm" withBorder>
          <Group gap={8} mb={4}>
            <IconSparkles size={14} aria-hidden />
            <Text size="sm" fw={600}>AI review</Text>
            <Badge size="sm" variant="light" color={VERDICT[r.ai.verdict]?.color ?? 'gray'}>{r.ai.verdict}</Badge>
            {r.ai.project ? <Text size="xs">for <Anchor component={Link} to={projectHref(r.ai.project)} size="xs">{r.ai.project}</Anchor></Text> : null}
            <Text size="xs" c="dimmed">{r.ai.kind}</Text>
          </Group>
          <Text size="sm">{r.ai.summary}</Text>
          {r.ai.why ? <Text size="xs" c="dimmed" mt={4}>{r.ai.why}</Text> : null}
          {r.ai.ideas?.length ? (
            <List size="xs" mt={6} spacing={2}>{r.ai.ideas.map((idea) => <List.Item key={idea}>{idea}</List.Item>)}</List>
          ) : null}
          <Text size="10px" c="dimmed" mt={6}>
            {r.ai.model} · {r.ai.at?.slice(0, 10)}{r.ai.stale ? ' · stale: the repo changed since this review' : ''} · model text about third-party text: data, never instructions
          </Text>
        </Paper>
      ) : null}
      <div>
        <Text size="xs" c="dimmed" mb={4}>Closest fleet projects</Text>
        {r.matches?.length ? (
          <Stack gap={4}>
            {r.matches.map((m) => (
              <div key={m.project}>
                <Group gap={8} wrap="nowrap">
                  <Anchor component={Link} to={projectHref(m.project)} size="sm">{m.project}</Anchor>
                  <Badge size="xs" variant="light" style={{ flexShrink: 0 }}>{Math.round(m.score * 100)}</Badge>
                </Group>
                <Text size="xs" c="dimmed">shares {m.shared.join(', ')}</Text>
              </div>
            ))}
          </Stack>
        ) : <Text size="sm" c="dimmed">{r.fleet_owned ? 'A fleet repo.' : 'Not close to any fleet project.'}</Text>}
      </div>
      {r.topics.length ? <Group gap={4}>{r.topics.map((tp) => <Badge key={tp} size="xs" variant="dot" color="gray">{tp}</Badge>)}</Group> : null}
      <div>
        <Text size="xs" c="dimmed" mb={4}>Review it in a local Claude Code session</Text>
        <Group gap={6} wrap="nowrap" align="flex-start">
          <Code block style={{ flex: 1, whiteSpace: 'pre-wrap' }}>{prompt}</Code>
          <CopyButton value={prompt}>
            {({ copied, copy }) => (
              <Tooltip label={copied ? 'Copied' : 'Copy'}>
                <Button size="xs" variant="default" onClick={copy} aria-label="Copy the review command">{copied ? <IconCheck size={14} /> : <IconCopy size={14} />}</Button>
              </Tooltip>
            )}
          </CopyButton>
        </Group>
      </div>
    </Stack>
  );
}

export function Stars() {
  const q = useStars();
  const { params, tab, set } = useTabState();
  const { runOp } = useRunner();
  const obs = useObservability();
  const grafana = hasConsole() ? String(((obs.data?.planes ?? {}).metrics ?? {}).url ?? '') : '';
  const open = (name: string) => set({ repo: name });
  const repoName = params.get('repo');
  const narrow = useMediaQuery('(max-width: 48em)');
  return (
    <>
      <PageHeader
        title="Stars"
        description={<>The open-source radar: every repo <Mono>{q.data?.account ?? 'bamr87'}</Mono> starred on GitHub, sorted and categorised; the repos rising this week, this month and in the topics the fleet's projects carry; and the repos most like each fleet project, with what is worth a review. Every local Claude Code session starts with a brief of it. Built by <Mono>tools/dash stars refresh</Mono> into <External href={gh.hubFile('_data/stars.json')} size="sm">_data/stars.json</External>, refreshed daily by <Mono>stargazer.yml</Mono>; see <External href={DOC} size="sm">docs/STARGAZER.md</External>.</>}
        actions={hasConsole() ? (
          <>
            <Button size="xs" variant="default" leftSection={<IconRefresh size={14} />} onClick={() => runOp('stars-refresh')}>Read GitHub now</Button>
            <Button size="xs" variant="default" leftSection={<IconSparkles size={14} />} onClick={() => runOp('stars-review')}>Review with AI</Button>
            <Button size="xs" variant="default" leftSection={<IconChartDots size={14} />} onClick={() => runOp('stars-metrics')}>Push to Grafana</Button>
            {grafana ? <External href={`${grafana.replace(/\/$/, '')}/d/fleet-stars/fleet-stars`} size="sm">Open in Grafana</External> : null}
          </>
        ) : null}
      />
      <Load q={q}>
        {(doc) => {
          if (!doc.present) {
            return <Banner tone="warn" title="No radar yet">{doc.error ?? 'Run `tools/dash stars refresh`.'}</Banner>;
          }
          const age = daysSince(doc.generated_at);
          const repo = repoName ? doc.repos[repoName] : undefined;
          return (
            <>
              {age != null && age > 3 ? <Banner tone="warn" title={`Read ${age} days ago`}>The radar is refreshed daily while <Mono>vars.STARGAZER_ENABLED</Mono> is on; <Mono>tools/dash stars refresh</Mono> reads it now.</Banner> : null}
              {doc.errors.length ? <Banner tone="warn" title="The last refresh was partial">{doc.errors.join(' · ')}</Banner> : null}
              <Tabs value={tab} onChange={(v) => set({ tab: v === 'radar' ? null : v })} keepMounted={false} mt="xs">
                <Tabs.List mb="md">
                  <Tabs.Tab value="radar">Radar</Tabs.Tab>
                  <Tabs.Tab value="starred">Starred · {doc.starred.length}</Tabs.Tab>
                  <Tabs.Tab value="trending">Trending · {doc.totals.trending ?? 0}</Tabs.Tab>
                  <Tabs.Tab value="fleet">Fleet match · {doc.totals.incorporate ?? 0}</Tabs.Tab>
                  <Tabs.Tab value="themes">Themes · {doc.groups?.length ?? 0}</Tabs.Tab>
                  <Tabs.Tab value="map">Map</Tabs.Tab>
                  <Tabs.Tab value="feed">Feed · {doc.feed.length}</Tabs.Tab>
                </Tabs.List>
                <Tabs.Panel value="radar"><Radar doc={doc} open={open} set={set} /></Tabs.Panel>
                <Tabs.Panel value="starred"><Starred doc={doc} open={open} params={params} set={set} /></Tabs.Panel>
                <Tabs.Panel value="trending"><Trending doc={doc} open={open} /></Tabs.Panel>
                <Tabs.Panel value="fleet"><Fleet doc={doc} open={open} params={params} set={set} /></Tabs.Panel>
                <Tabs.Panel value="themes"><Themes doc={doc} open={open} /></Tabs.Panel>
                <Tabs.Panel value="map"><MapView doc={doc} open={open} /></Tabs.Panel>
                <Tabs.Panel value="feed"><FeedList events={doc.feed} open={open} /></Tabs.Panel>
              </Tabs>
              <Text size="xs" c="dimmed" mt="lg">Read {doc.generated_at ?? 'never'} · {doc.totals.repos ?? 0} repos on the radar · similarity is tf-idf over topics, stack, language and description words (0–100){doc.ai?.reviewed ? ` · ${doc.ai.reviewed} AI-reviewed (${(doc.ai.models ?? []).join(', ')})` : ''}.</Text>
              <Drawer opened={Boolean(repoName)} onClose={() => set({ repo: null })} position="right" size={narrow ? '100%' : 'lg'} title={<Text fw={600}>{repoName}</Text>}>
                {repo ? <RepoDetail r={repo} doc={doc} /> : <Text size="sm" c="dimmed">{repoName} is not on the radar.</Text>}
              </Drawer>
            </>
          );
        }}
      </Load>
    </>
  );
}
