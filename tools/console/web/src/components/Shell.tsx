// The frame every page renders in: a header that says where you are working
// (branch, tree state, credentials, running jobs) and a sidebar grouped by
// what you are doing. Each header chip is a link to the page that fixes it.
import { Link, Outlet, useLocation, useNavigate } from 'react-router';
import {
  ActionIcon, AppShell, Badge, Burger, Group, Indicator, Kbd, NavLink, ScrollArea, Text, Tooltip, UnstyledButton,
  useComputedColorScheme, useMantineColorScheme,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { spotlight } from '@mantine/spotlight';
import {
  IconApi, IconBox, IconGitBranch, IconKey, IconMoonStars, IconRefresh, IconSearch, IconSun,
} from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, type ReactNode } from 'react';
import { useCaps, useJobs, useStateDoc } from '../api/hooks';
import { NAV, activeIndex, FLAT } from '../nav';
import { to } from '../lib/links';

function Chip({ children, tone, href, title }: { children: ReactNode; tone?: 'good' | 'crit'; href?: string; title: string }) {
  const style = {
    display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, padding: '1px 9px', borderRadius: 999,
    border: `1px solid ${tone === 'good' ? 'var(--good)' : tone === 'crit' ? 'var(--critical)' : 'var(--grid)'}`,
    color: 'var(--ink-2)', textDecoration: 'none', whiteSpace: 'nowrap' as const,
  };
  const body = href ? <Link to={href} style={style}>{children}</Link> : <span style={style}>{children}</span>;
  return <Tooltip label={title}>{body}</Tooltip>;
}

function HeaderStatus() {
  const state = useStateDoc();
  const caps = useCaps();
  const g = state.data?.git ?? {};
  const tokens = Object.entries(caps.data?.env_tokens ?? {}).filter(([, v]) => v).map(([k]) => k);
  return (
    <Group gap={6} wrap="nowrap" visibleFrom="md" style={{ overflow: 'hidden' }}>
      <Chip title="git branch and HEAD of the hub working tree">
        <IconGitBranch size={13} /> {g.branch ?? '?'} <Text span ff="monospace" fz={11}>{g.head ?? ''}</Text>
      </Chip>
      <Chip tone={g.dirty_count ? undefined : 'good'} title="Uncommitted files. The console never commits: review generated data in git and commit it yourself.">
        {g.dirty_count ? `✎ ${g.dirty_count} uncommitted` : '✓ clean tree'}
      </Chip>
      <Chip tone={caps.data?.gh_authenticated ? 'good' : 'crit'} href={to.github()} title="GitHub sign-in — open the GitHub page to connect through the OAuth App">
        {caps.data?.gh_authenticated ? '✓ gh' : '✖ gh signed out'}
      </Chip>
      <Chip href={to.auth()} title={`Credential names present in this process (values never shown): ${tokens.join(', ') || 'none'}`}>
        <IconKey size={13} /> {tokens.length} token{tokens.length === 1 ? '' : 's'}
      </Chip>
    </Group>
  );
}

function JobsIndicator() {
  const jobs = useJobs();
  const running = (jobs.data ?? []).filter((j) => j.status === 'running' || j.status === 'queued').length;
  const failed = (jobs.data ?? []).filter((j) => j.status === 'failed').length;
  return (
    <Tooltip label={running ? `${running} job(s) running` : failed ? `${failed} failed job(s) this session` : 'Jobs'}>
      <Indicator disabled={!running && !failed} color={running ? 'cyan' : 'red'} label={running || failed} size={16} processing={running > 0}>
        <ActionIcon component={Link} to={to.jobs()} variant="default" size="lg" aria-label="Jobs"><IconBox size={18} /></ActionIcon>
      </Indicator>
    </Tooltip>
  );
}

function ThemeToggle() {
  const { setColorScheme } = useMantineColorScheme();
  const computed = useComputedColorScheme('dark');
  // /theme.css (fleetcore) keys its dark roles on data-theme; Mantine keys its
  // own on data-mantine-color-scheme. Keep the two attributes in step.
  useEffect(() => {
    document.documentElement.dataset.theme = computed;
  }, [computed]);
  return (
    <Tooltip label="Toggle light / dark">
      <ActionIcon variant="default" size="lg" onClick={() => setColorScheme(computed === 'dark' ? 'light' : 'dark')} aria-label="Toggle theme">
        {computed === 'dark' ? <IconSun size={18} /> : <IconMoonStars size={18} />}
      </ActionIcon>
    </Tooltip>
  );
}

// The hand-written page addressed tabs as /#harnesses; keep those bookmarks working.
const LEGACY: Record<string, string> = {
  overview: '/', apps: '/projects', harnesses: '/harnesses', schedules: '/schedules', loops: '/loops', costs: '/costs',
  observe: '/observe/traces', content: '/content', fleet: '/projects', contract: '/config', auth: '/auth', jobs: '/jobs',
};

export function Shell() {
  const [opened, { toggle, close }] = useDisclosure();
  const { pathname, hash } = useLocation();
  const navigate = useNavigate();
  useEffect(() => {
    const dest = pathname === '/' && LEGACY[hash.replace('#', '')];
    if (dest) navigate(dest, { replace: true });
  }, [pathname, hash, navigate]);
  const qc = useQueryClient();
  const active = activeIndex(pathname);
  useEffect(close, [pathname, close]);
  useEffect(() => {
    const item = FLAT[active];
    document.title = item ? `${item.label} · Harness Console` : 'Harness Console';
  }, [active]);

  return (
    <AppShell header={{ height: 54 }} navbar={{ width: 236, breakpoint: 'sm', collapsed: { mobile: !opened } }} padding="lg"
      styles={{ main: { background: 'var(--page)' }, header: { background: 'var(--surface)' }, navbar: { background: 'var(--surface)' } }}>
      <AppShell.Header px="md">
        <Group h="100%" justify="space-between" wrap="nowrap" gap="sm">
          <Group gap="sm" wrap="nowrap">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" aria-label="Menu" />
            <UnstyledButton component={Link} to="/" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <img src="/favicon.svg" width={24} height={24} alt="" />
              <Text fw={650} fz={16} style={{ whiteSpace: 'nowrap' }}>Harness Console</Text>
            </UnstyledButton>
            <HeaderStatus />
          </Group>
          <Group gap={8} wrap="nowrap">
            <UnstyledButton onClick={() => spotlight.open()} visibleFrom="xs" aria-label="Search and commands"
              style={{ display: 'flex', alignItems: 'center', gap: 8, border: '1px solid var(--grid)', borderRadius: 8, padding: '4px 10px', color: 'var(--ink-2)', fontSize: 13 }}>
              <IconSearch size={15} /> Search or run… <Kbd size="xs">:</Kbd>
            </UnstyledButton>
            <ActionIcon variant="default" size="lg" hiddenFrom="xs" onClick={() => spotlight.open()} aria-label="Search"><IconSearch size={18} /></ActionIcon>
            <JobsIndicator />
            <Tooltip label="Re-read every document (r)">
              <ActionIcon variant="default" size="lg" visibleFrom="xs" onClick={() => void qc.invalidateQueries()} aria-label="Refresh"><IconRefresh size={18} /></ActionIcon>
            </Tooltip>
            <ThemeToggle />
            <Tooltip label="API docs (/docs)">
              <ActionIcon component="a" href="/docs" target="_blank" rel="noopener" variant="default" size="lg" visibleFrom="sm" aria-label="API docs"><IconApi size={18} /></ActionIcon>
            </Tooltip>
          </Group>
        </Group>
      </AppShell.Header>
      <AppShell.Navbar p="xs">
        <AppShell.Section grow component={ScrollArea}>
          {NAV.map((section, si) => (
            <div key={section.label} style={{ marginBottom: 8 }}>
              {section.items.length > 1 || section.label !== section.items[0].label ? (
                <Group justify="space-between" px={10} pt={6} pb={2}>
                  <Text size="xs" fw={700} c="dimmed" tt="uppercase" style={{ letterSpacing: 0.6 }}>{section.label}</Text>
                  <Text size="xs" c="dimmed" ff="monospace">{si + 1}</Text>
                </Group>
              ) : null}
              {section.items.map((item) => {
                const idx = FLAT.indexOf(item);
                const Ico = item.icon;
                return (
                  <NavLink key={item.to} component={Link} to={item.to} label={item.label} active={idx === active}
                    leftSection={<Ico size={17} stroke={1.6} />} title={item.hint}
                    rightSection={section.items.length === 1 ? <Text size="xs" c="dimmed" ff="monospace">{si + 1}</Text> : undefined}
                    styles={{ root: { borderRadius: 6 }, label: { fontSize: 13.5 } }} />
                );
              })}
            </div>
          ))}
        </AppShell.Section>
        <AppShell.Section>
          <Group gap={6} px={8} py={6} wrap="wrap">
            <Badge variant="default" size="sm" leftSection={<Kbd size="xs">?</Kbd>}>keys</Badge>
            <Text size="xs" c="dimmed">keys v1 · same as <Link to={to.terminal()} style={{ color: 'var(--accent)' }}>the TUI</Link></Text>
          </Group>
        </AppShell.Section>
      </AppShell.Navbar>
      <AppShell.Main>
        <div style={{ maxWidth: 1480, margin: '0 auto' }}>
          <Outlet />
        </div>
      </AppShell.Main>
    </AppShell>
  );
}
