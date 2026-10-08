// When the fleet's agents fire: throughput vs the caps, AI crons by UTC hour
// (collisions marked), and the whole fleet calendar. A cron opens its project.
import { useSearchParams } from 'react-router';
import { Checkbox, Group, Paper, SimpleGrid, Stack, Text, TextInput } from '@mantine/core';
import { IconSearch } from '@tabler/icons-react';
import { useStateDoc } from '../api/hooks';
import { ColumnChart } from '../components/Charts';
import { Banner, Load, Meter, PageHeader, RepoLink, Section, StatTile } from '../components/ui';
import { cronHours, fmt, includesText } from '../lib/format';
import { to } from '../lib/links';
import { ScheduleTable } from './ProjectPage';

export function Schedules() {
  const state = useStateDoc();
  const [sp, setSp] = useSearchParams();
  const q = sp.get('q') ?? '';
  const aiOnly = sp.get('ai') === '1';
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(sp);
    if (v) next.set(k, v); else next.delete(k);
    setSp(next, { replace: true });
  };
  return (
    <Load q={state}>
      {(s) => {
        const tp = s.harnesses?.throughput ?? {};
        const sched = s.harnesses?.schedule ?? [];
        const cap = tp.cap_per_utc_hour ?? 3;
        const load = Array(24).fill(0) as number[];
        const all = Array(24).fill(0) as number[];
        sched.forEach((e) => cronHours(e.cron).forEach((h) => { all[h]++; if (e.ai) load[h]++; }));
        const hours = load.map((n, h) => ({ hour: `${String(h).padStart(2, '0')}:00`, ai: n, all: all[h] }));
        const rows = sched.filter((e) => (!aiOnly || e.ai) && includesText([e.repo, e.workflow, e.cron, e.human], q));
        return (
          <>
            <PageHeader title="Schedules" description="Single-shot crons count at their hour; hourly agents spread across all 24. The Claude loops share one OAuth account's rate limit, so a crowded hour is a real risk, not a cosmetic one. Retune a cron in its repo, or a cap on the Config page." />
            <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }} spacing="md">
              <StatTile label="Estimated scheduled AI runs / day" value={<>{fmt(tp.est_scheduled_ai_per_day)} <Text span c="dimmed" fz={14}>/ {fmt(tp.cap_fleet)}</Text></>}
                meter={<Meter value={tp.est_scheduled_ai_per_day ?? 0} cap={tp.cap_fleet ?? 1} />}
                sub={`per-repo cap ${fmt(tp.cap_per_repo)} · ${fmt(tp.cap_per_utc_hour)} AI crons per UTC hour`} href={to.config('harnesses')} />
              <StatTile label="Observed AI runs / day" value={fmt(tp.observed_ai_runs_per_day)} sub="all triggers — mention and PR traffic rides on the scheduled floor" href={to.costs()} />
              <StatTile label="Repos over the per-repo cap" value={(tp.repos_over_cap ?? []).length} tone={(tp.repos_over_cap ?? []).length ? 'crit' : undefined}
                sub={(tp.repos_over_cap ?? []).map((v) => `${v.repo} ${v.est_per_day}/d`).join(', ') || 'none'} />
              <StatTile label="UTC-hour collisions" value={(tp.hour_collisions ?? []).length} tone={(tp.hour_collisions ?? []).length ? 'crit' : undefined}
                sub={(tp.hour_collisions ?? []).map((c) => `${c.utc_hour} × ${c.count}`).join(', ') || 'none'} />
            </SimpleGrid>
            <Section title="AI crons by UTC hour" description={`Bars above the per-hour cap (${cap}) are drawn in the critical colour and marked in the table view.`}>
              <Paper p="md">
                <ColumnChart rows={hours} label="hour" series={[{ key: 'ai', label: 'AI crons' }]} height={110}
                  fmtLabel={(x) => String(x).slice(0, 2)} tone={(r) => (Number(r.ai) > cap ? 'crit' : undefined)} />
              </Paper>
              {(tp.hour_collisions ?? []).map((c) => (
                <Banner key={c.utc_hour} tone="crit" title={`${c.utc_hour} UTC — ${c.count} AI crons`}>
                  <Stack gap={2}>{c.entries.map((e) => <Text key={e} size="sm" ff="monospace">{e}</Text>)}</Stack>
                  <Text size="sm" mt={4}>Stagger one of them.</Text>
                </Banner>
              ))}
              {(tp.repos_over_cap ?? []).length ? (
                <Group gap="xs" mt="sm">{(tp.repos_over_cap ?? []).map((v) => <span key={v.repo}><RepoLink name={v.repo} /> <Text span size="xs" c="dimmed">{v.est_per_day}/day</Text></span>)}</Group>
              ) : null}
            </Section>
            <Section title={`Fleet calendar (${rows.length})`}>
              <Group gap="sm" mb="sm">
                <TextInput data-page-search leftSection={<IconSearch size={15} />} placeholder="Filter repo / workflow / cron…  ( / )" value={q} onChange={(e) => set('q', e.currentTarget.value)} w={300} />
                <Checkbox label="AI crons only" checked={aiOnly} onChange={(e) => set('ai', e.currentTarget.checked ? '1' : '')} />
              </Group>
              <ScheduleTable rows={rows} showRepo />
            </Section>
          </>
        );
      }}
    </Load>
  );
}
