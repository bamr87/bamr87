// The front door of the site, public or local: who this is, what the fleet
// looks like right now, and the three things the site is for — the portfolio,
// running the AI harnesses, and orchestrating GitHub. Every number is a link
// to the page that explains it.
import { Link } from 'react-router';
import {
  Anchor, Avatar, Badge, Button, Card, Group, SimpleGrid, Stack, Text, ThemeIcon, Title,
} from '@mantine/core';
import {
  IconArrowRight, IconBrandGithub, IconBrandLinkedin, IconFileCv, IconLink, IconMail, IconRobot, IconTopologyStar3, IconWorld,
  type Icon,
} from '@tabler/icons-react';
import { asset, mode } from '../api/backend';
import { useFleet, useManifest, useSite, useStateDoc } from '../api/hooks';
import type { FleetRow, SitePostMeta } from '../api/types';
import { LevelDot, Load, Section, StatTile } from '../components/ui';
import { fmt, usd, when } from '../lib/format';
import { to } from '../lib/links';

const LINK_ICON: Record<string, Icon> = { github: IconBrandGithub, linkedin: IconBrandLinkedin, world: IconWorld, mail: IconMail, 'file-cv': IconFileCv };

function Hero() {
  const site = useSite();
  const p = site.data?.profile;
  return (
    <Group align="flex-start" gap="xl" wrap="wrap" mb="xl">
      <Avatar src={p?.avatar ? asset(p.avatar) : undefined} size={112} radius={112} alt={p?.name ?? ''} />
      <Stack gap={6} style={{ flex: 1, minWidth: 260 }}>
        <Text size="sm" c="dimmed" ff="monospace">{p?.handle ? `@${p.handle}` : ''}{p?.location ? ` · ${p.location}` : ''}</Text>
        <Title order={1} fz={{ base: 28, sm: 34 }} lh={1.15}>{p?.name ?? ' '}</Title>
        <Text fz="lg" fw={500}>{p?.title}</Text>
        {p?.tagline ? <Text c="dimmed">{p.tagline}</Text> : null}
        {p?.summary ? <Text maw={760} mt={4}>{p.summary}</Text> : null}
        <Group gap="xs" mt="xs" wrap="wrap">
          {(p?.links ?? []).map((l) => {
            const Ico = LINK_ICON[l.icon ?? ''] ?? IconLink;
            return (
              <Button key={l.url} component="a" href={l.url} target={l.url.startsWith('mailto:') ? undefined : '_blank'} rel="noopener noreferrer"
                variant="default" size="xs" leftSection={<Ico size={15} />}>{l.label}</Button>
            );
          })}
        </Group>
      </Stack>
    </Group>
  );
}

function Vitals() {
  const fleet = useFleet({ sort: 'featured' });
  const state = useStateDoc();
  const k = fleet.data?.kpis ?? {};
  const ai = state.data?.usage.ai;
  const ac = state.data?.usage.actions;
  const aiSpend = (ai?.by_day ?? []).reduce((s, d) => s + (d.cost_usd ?? 0), 0);
  const acMin = (ac?.by_day ?? []).reduce((s, d) => s + (d.total_min ?? 0), 0);
  return (
    <SimpleGrid cols={{ base: 2, sm: 3, lg: 6 }} spacing="sm">
      <StatTile label="Projects" value={k.projects ?? '…'} sub={`${k.active ?? 0} active · ${k.featured ?? 0} featured`} href={to.portfolio()} />
      <StatTile label="Need attention" value={k.red ?? '…'} tone={k.red ? 'crit' : undefined} sub={`${k.amber ?? 0} to watch · ${k.green ?? 0} healthy`} href={to.projects()} />
      <StatTile label="Failing workflows" value={k.failing ?? '…'} tone={k.failing ? 'crit' : undefined} sub="across the fleet" href={to.inbox('workflow')} />
      <StatTile label="Triage flags" value={(k.triage_red ?? 0) + (k.triage_amber ?? 0)} sub={`${k.triage_red ?? 0} red`} href={to.inbox()} />
      <StatTile label={`Claude in CI · ${ai?.window_days ?? 30}d`} value={usd(aiSpend)} sub="agent runs across the fleet" href={to.costs()} />
      <StatTile label={`Actions · ${ac?.window_days ?? 30}d`} value={`${fmt(acMin / 60)}h`} sub="billed-minute proxy" href={to.costs()} />
    </SimpleGrid>
  );
}

function Pillar({ icon: Ico, title, body, links }: { icon: Icon; title: string; body: string; links: { label: string; to: string }[] }) {
  return (
    <Card padding="lg">
      <Group gap="sm" mb="xs">
        <ThemeIcon variant="light" size="lg"><Ico size={20} /></ThemeIcon>
        <Text fw={600}>{title}</Text>
      </Group>
      <Text size="sm" c="dimmed" mb="sm">{body}</Text>
      <Group gap={6} wrap="wrap">
        {links.map((l) => <Button key={l.to} component={Link} to={l.to} size="compact-sm" variant="light" rightSection={<IconArrowRight size={13} />}>{l.label}</Button>)}
      </Group>
    </Card>
  );
}

export function ProjectCard({ r }: { r: FleetRow }) {
  return (
    <Card padding="md" component={Link} to={to.project(r.name)} className="tile-link" style={{ textDecoration: 'none', color: 'inherit' }}>
      <Group justify="space-between" wrap="nowrap" mb={4}>
        <Text fw={600} ff="monospace" fz="sm">{r.name}</Text>
        <LevelDot level={r.worst_level ?? r.health} />
      </Group>
      <Text size="sm" c="dimmed" lineClamp={3} mb="xs">{r.description}</Text>
      <Group gap={4} wrap="wrap">
        {(r.stack ?? []).slice(0, 5).map((s) => <Badge key={s} variant="default" size="xs">{s}</Badge>)}
        {r.status && r.status !== 'active' ? <Badge variant="light" color="gray" size="xs">{r.status}</Badge> : null}
      </Group>
    </Card>
  );
}

function PostList({ posts }: { posts: SitePostMeta[] }) {
  if (!posts.length) return <Text size="sm" c="dimmed">No posts published yet.</Text>;
  return (
    <Stack gap="sm">
      {posts.slice(0, 4).map((p) => (
        <div key={p.slug}>
          <Anchor component={Link} to={to.post(p.slug)} fw={600}>{p.title}</Anchor>
          {p.draft ? <Badge ml={6} size="xs" variant="light" color="yellow">draft</Badge> : null}
          <Text size="xs" c="dimmed">{p.date}</Text>
          <Text size="sm" lineClamp={2}>{p.excerpt}</Text>
        </div>
      ))}
    </Stack>
  );
}

function Freshness() {
  const m = useManifest();
  if (mode() !== 'snapshot' || !m.data) return null;
  return (
    <Text size="xs" c="dimmed" mt="xl">
      This page is a snapshot of the fleet published {when(m.data.generated_at)} from{' '}
      <Anchor href={`https://github.com/${m.data.repo}/commit/${m.data.commit}`} target="_blank" rel="noopener" size="xs" ff="monospace">{m.data.commit.slice(0, 7)}</Anchor>
      {m.data.run_url ? <> by <Anchor href={m.data.run_url} target="_blank" rel="noopener" size="xs">this run</Anchor></> : null}. It is rebuilt every day and on every change;{' '}
      <Anchor component={Link} to={to.connect()} size="xs">connect</Anchor> to GitHub or to a running console to act on it live.
    </Text>
  );
}

export function Home() {
  const fleet = useFleet({ sort: 'featured' });
  const site = useSite();
  return (
    <>
      <Hero />
      <Vitals />
      <SimpleGrid cols={{ base: 1, md: 3 }} spacing="md" mt="xl">
        <Pillar icon={IconWorld} title="Portfolio" body="Every repository I build and maintain, from the one registry the whole site is generated from — with its live CI, security and triage state."
          links={[{ label: 'Portfolio', to: to.portfolio() }, { label: 'Experience', to: '/experience' }, { label: 'Writing', to: to.blog() }]} />
        <Pillar icon={IconRobot} title="Agentic harness management" body="Where the fleet's AI agents are deployed, what they are scheduled to do, whether the loops are healthy, and what they cost against budget."
          links={[{ label: 'Harnesses', to: to.harnesses() }, { label: 'Health', to: to.health() }, { label: 'Costs', to: to.costs() }]} />
        <Pillar icon={IconTopologyStar3} title="GitHub orchestration" body="The ranked inbox of failing workflows, issues and pull requests across ~45 repos — and the control-plane loops and fan-outs that act on them."
          links={[{ label: 'Overview', to: to.overview() }, { label: 'Inbox', to: to.inbox() }, { label: 'Loops', to: to.loops() }]} />
      </SimpleGrid>
      <Section title="Featured projects" actions={<Anchor component={Link} to={to.portfolio()} size="sm">All projects →</Anchor>}>
        <Load q={fleet} rows={3}>
          {(v) => (
            <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="sm">
              {v.rows.filter((r) => r.featured).slice(0, 6).map((r) => <ProjectCard key={r.name} r={r} />)}
            </SimpleGrid>
          )}
        </Load>
      </Section>
      <Section title="Writing" actions={<Anchor component={Link} to={to.blog()} size="sm">All posts →</Anchor>}>
        <Load q={site} rows={2}>{(s) => <PostList posts={s.posts} />}</Load>
      </Section>
      <Freshness />
    </>
  );
}
