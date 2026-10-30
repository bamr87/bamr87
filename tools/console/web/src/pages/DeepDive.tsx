// The daily repo deep-dive: one bamr87 repo a day, every repo once per cycle
// (HUB-029, PRD FR24–FR25, docs/DEEP-DIVE.md). Reads the generated projection
// _data/deep_dive.json (tools/deep_dive.py) through /api/data/deep_dive, so it
// renders the same from a console and from the published snapshot. "Today" is
// recomputed from the viewer's clock; everything else is the committed ledger.
import { Badge, Group, Paper, Progress, SimpleGrid, Text, Tooltip } from '@mantine/core';
import { useData } from '../api/hooks';
import type { Dict } from '../api/types';
import { DataTable } from '../components/DataTable';
import { External, Load, Mono, PageHeader, RepoLink, Section, StatTile, Status, type Tone } from '../components/ui';
import { gh } from '../lib/links';

type Row = Dict<any>;
const STATUS_TONE: Record<string, Tone> = { done: 'good', in_progress: 'info', pending: 'info', skipped: 'warn' };
const DAY = 86_400_000;

const isoDay = (d: Date) => d.toISOString().slice(0, 10);
const addDays = (iso: string, n: number) => isoDay(new Date(Date.parse(`${iso}T00:00:00Z`) + n * DAY));
const localToday = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

/** Mirror of tools/deep_dive.py today(): the repo for a date. */
function pick(repos: Row[], start: string, days: number, on: string): { day: number; repo: string | null; kind: string } {
  const day = Math.round((Date.parse(`${on}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / DAY) + 1;
  if (day < 1) return { day: 0, repo: repos[0]?.repo ?? null, kind: 'not started' };
  if (day > days) return { day, repo: null, kind: 'cycle over' };
  if (day <= repos.length) return { day, repo: repos[day - 1].repo, kind: 'scheduled' };
  const late = repos.find((r) => r.status !== 'done' && r.day < day);
  return { day, repo: late?.repo ?? null, kind: 'catch-up' };
}

const scoreTone = (s: number | null | undefined): Tone | undefined => (s == null ? undefined : s >= 80 ? 'good' : s >= 60 ? 'warn' : 'crit');

function Calendar({ repos, start, days, today }: { repos: Row[]; start: string; days: number; today: string }) {
  const cells = Array.from({ length: days }, (_, i) => {
    const date = addDays(start, i);
    const r = repos[i];
    return { i: i + 1, date, r };
  });
  return (
    <SimpleGrid cols={{ base: 3, sm: 6, lg: 7 }} spacing={6}>
      {cells.map(({ i, date, r }) => {
        const tone = r ? STATUS_TONE[r.status] : undefined;
        const border = date === today ? '2px solid var(--mantine-color-blue-filled)' : undefined;
        const bg = r?.status === 'done' ? 'var(--mantine-color-green-light)' : r?.status === 'skipped' ? 'var(--mantine-color-yellow-light)' : r?.status === 'in_progress' ? 'var(--mantine-color-blue-light)' : undefined;
        return (
          <Tooltip key={i} label={r ? `${r.repo} — ${r.status}${r.last_processed ? ` (${r.last_processed})` : ''}` : 'catch-up slot for skipped or late repos'}>
            <Paper p={6} withBorder style={{ border, background: bg, minHeight: 58 }}>
              <Group justify="space-between" gap={2} wrap="nowrap">
                <Text size="xs" c="dimmed">D{i}</Text>
                <Text size="xs" c="dimmed">{date.slice(5)}</Text>
              </Group>
              {r ? <Text size="xs" fw={600} truncate="end">{r.repo}</Text> : <Text size="xs" c="dimmed" fs="italic">catch-up</Text>}
              {r && tone ? <Text size="10px" c="dimmed">{r.status.replace('_', ' ')}</Text> : null}
            </Paper>
          </Tooltip>
        );
      })}
    </SimpleGrid>
  );
}

export function DeepDive() {
  const data = useData<Row>('deep_dive');
  return (
    <>
      <PageHeader
        title="Deep dive"
        description={<>One repo a day, every repo once per cycle: a daily routine reviews, analyses, documents and improves the day's repo and files what it finds as issues and PRs labelled <Mono>deep-dive</Mono>. The ledger is <External href={gh.hubFile('_data/deep-dive.yml')} size="sm">_data/deep-dive.yml</External>, kept by <Mono>tools/deep_dive.py</Mono> and refreshed daily by <Mono>deep-dive.yml</Mono>; see <External href={gh.hubFile('docs/DEEP-DIVE.md')} size="sm">docs/DEEP-DIVE.md</External>.</>}
      />
      <Load q={data}>
        {(doc) => {
          const s = doc.summary ?? {};
          const repos: Row[] = doc.repos ?? [];
          const owner = doc.owner ?? 'bamr87';
          const label = doc.label ?? 'deep-dive';
          const today = localToday();
          const t = pick(repos, s.cycle_start, s.cycle_days, today);
          const n = pick(repos, s.cycle_start, s.cycle_days, addDays(today, 1));
          const done = repos.filter((r) => r.status === 'done').length;
          const labelUrl = (repo: string, kind: 'issues' | 'pulls') => `https://github.com/${owner}/${repo}/${kind}?q=${encodeURIComponent(`is:open label:${label}`)}`;
          return (
            <>
              <SimpleGrid cols={{ base: 2, md: 4 }} spacing="sm" mb="md">
                <StatTile label={`Cycle ${s.cycle} progress`} value={`${done}/${repos.length}`} sub={`${s.cycle_start} → ${s.cycle_end} · ${s.cycle_days} days`}
                  meter={<Progress value={repos.length ? (100 * done) / repos.length : 0} size="sm" />} />
                <StatTile label={`Today · day ${t.day}/${s.cycle_days}`} value={t.repo ?? '—'} sub={t.kind} />
                <StatTile label="Last processed" value={s.last ?? '—'} sub={s.last_date ? `on ${s.last_date}` : 'nothing recorded yet'} />
                <StatTile label="Next" value={n.repo ?? '—'} sub={`${n.kind} · avg score ${s.avg_score ?? '—'} · ${s.open_issues ?? 0} issues / ${s.open_prs ?? 0} PRs open`} />
              </SimpleGrid>
              <Section title={`${s.cycle_days}-day calendar`}>
                <Calendar repos={repos} start={s.cycle_start} days={s.cycle_days} today={today} />
              </Section>
              <Section title="Per-repo status">
                <DataTable<Row>
                  rows={repos} keys rowKey={(r) => String(r.repo)} initialSort={{ key: 'day' }} minWidth={980}
                  open={(r) => gh.repo(`${owner}/${r.repo}`)}
                  columns={[
                    { key: 'day', header: 'day', sort: (r) => r.day, render: (r) => <Mono>D{r.day}</Mono>, width: 56 },
                    { key: 'date', header: 'scheduled', sort: (r) => r.scheduled, render: (r) => <Mono dim>{r.scheduled}</Mono>, width: 100 },
                    { key: 'repo', header: 'repo', sort: (r) => r.repo, render: (r) => <RepoLink name={r.repo} /> },
                    { key: 'st', header: 'status', sort: (r) => r.status, render: (r) => <Status tone={STATUS_TONE[r.status] ?? 'info'}>{String(r.status).replace('_', ' ')}</Status> },
                    { key: 'last', header: 'last run', sort: (r) => r.last_processed ?? '', render: (r) => <Mono dim>{r.last_processed ?? '—'}</Mono> },
                    { key: 'score', header: 'score', sort: (r) => r.score ?? -1, render: (r) => (r.score == null ? <Text size="xs" c="dimmed">—</Text> : <Badge variant="light" color={scoreTone(r.score) === 'good' ? 'green' : scoreTone(r.score) === 'warn' ? 'yellow' : 'red'}>{r.score}</Badge>) },
                    { key: 'open', header: 'open', sort: (r) => (r.open_issues ?? 0) + (r.open_prs ?? 0), render: (r) => (
                      <Group gap={6} wrap="nowrap">
                        <External href={labelUrl(r.repo, 'issues')} size="xs">{r.open_issues ?? 0} issues</External>
                        <External href={labelUrl(r.repo, 'pulls')} size="xs">{r.open_prs ?? 0} PRs</External>
                      </Group>
                    ) },
                    { key: 'f', header: 'findings · next focus', render: (r) => (
                      <div>
                        <Text size="xs" lineClamp={2}>{r.findings || '—'}</Text>
                        {r.next_focus ? <Text size="xs" c="dimmed" lineClamp={1}>next: {r.next_focus}</Text> : null}
                        {[...(r.issues ?? []), ...(r.prs ?? [])].length ? (
                          <Group gap={4} mt={2}>{[...(r.issues ?? []), ...(r.prs ?? [])].slice(0, 6).map((u: string) => <External key={u} href={u} size="xs">#{u.split('/').pop()}</External>)}</Group>
                        ) : null}
                      </div>
                    ) },
                  ]}
                />
              </Section>
              <Text size="xs" c="dimmed" mt="sm">Counts refreshed {doc.refreshed_at ?? 'never'} from the GitHub search API.</Text>
            </>
          );
        }}
      </Load>
    </>
  );
}
