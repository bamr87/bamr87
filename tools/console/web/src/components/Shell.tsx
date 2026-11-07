// The frame every page renders in: a header that says where you are working
// (branch, tree state, credentials, running jobs) and a sidebar grouped by
// what you are doing. Each header chip is a link to the page that fixes it.
import { Link, Outlet, useLocation, useNavigate, useNavigationType } from 'react-router';
import {
  ActionIcon, Anchor, AppShell, Badge, Box, Burger, Button, Group, Indicator, Kbd, ScrollArea, Text, Tooltip, UnstyledButton, VisuallyHidden, useComputedColorScheme, useMantineColorScheme,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { spotlight } from '@mantine/spotlight';
import {
  IconApi, IconBox, IconBrandGithub, IconCamera, IconGitBranch, IconKey, IconMoonStars, IconPlugConnected, IconRefresh, IconSearch, IconSun,
} from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { EMBEDDED, asset, consoleOrigin, hasConsole, mode } from '../api/backend';
import { useCaps, useGithubStatus, useJobs, useManifest, useSite, useStateDoc } from '../api/hooks';
import { clearSnapshotCache } from '../api/static';
import { when } from '../lib/format';
import { rememberPage } from '../lib/prefs';
import { activeIndex, FLAT } from '../nav';
import { to } from '../lib/links';
import { LAYOUT } from '../theme';
import { ErrorBoundary } from './ErrorBoundary';
import { KEYS_EVENT } from './GlobalKeys';
import { PageTitleContext, type PageTitle } from './pageTitle';
import { ShellNav } from './ShellNav';
import { Banner } from './ui';
import u from '../styles/utils.module.css';
import navClasses from './ShellNav.module.css';

/** A header chip: a fact about where you are working, linking to the page that acts on it. */
function Chip({ children, tone, href, title }: { children: ReactNode; tone?: 'good' | 'crit'; href?: string; title: string }) {
  const color = tone === 'good' ? 'var(--good)' : tone === 'crit' ? 'var(--critical)' : 'var(--grid)';
  const body = href ? (
    <Badge component={Link} to={href} variant="outline" color={color} c="dimmed" size="md" className={u.tileLink}>{children}</Badge>
  ) : (
    <Badge variant="outline" color={color} c="dimmed" size="md">{children}</Badge>
  );
  return <Tooltip label={title}>{body}</Tooltip>;
}

/** The public build without a console: how old the snapshot is, and GitHub. */
function SnapshotStatus({ stacked }: { stacked?: boolean }) {
  const m = useManifest();
  const gh = useGithubStatus();
  return (
    <Group gap={6} wrap={stacked ? 'wrap' : 'nowrap'} className={stacked ? undefined : u.clip}>
      <Chip href={to.connect()} title={m.data ? `Published snapshot of commit ${m.data.commit.slice(0, 7)}, built ${m.data.generated_at}. Read-only — connect GitHub or a console to act.` : 'Published snapshot'}>
        <IconCamera size={13} /> snapshot {m.data ? when(m.data.generated_at) : ''}
      </Chip>
      <Chip tone={gh.data?.connected ? 'good' : undefined} href={to.connect()} title={gh.data?.connected ? `Acting on GitHub as ${gh.data.login}, from this browser` : 'Connect a GitHub token to act on GitHub from this page'}>
        <IconBrandGithub size={13} /> {gh.data?.connected ? gh.data.login : 'connect'}
      </Chip>
    </Group>
  );
}

/** Where you are working. In the header from md up; below that, at the foot of the sidebar. */
function HeaderStatus({ stacked }: { stacked?: boolean }) {
  if (!hasConsole()) return <SnapshotStatus stacked={stacked} />;
  return <ConsoleStatus stacked={stacked} />;
}

/** Said once, at the top of the page, rather than as a failure on every panel. */
function ConnectionLost() {
  const jobs = useJobs();
  if (!hasConsole() || !jobs.isError || (jobs.error as { status?: number }).status === 401) return null;
  return (
    <Banner tone="warn" title="The console is not answering">
      <Group gap="sm" justify="space-between">
        <Text size="sm">
          {jobs.dataUpdatedAt ? `Last heard from ${when(new Date(jobs.dataUpdatedAt).toISOString())}. ` : ''}Pages keep showing what they last read, and this clears by itself when it answers again.
        </Text>
        <Button size="compact-xs" variant="default" loading={jobs.isFetching} onClick={() => void jobs.refetch()}>Retry now</Button>
      </Group>
    </Banner>
  );
}

function ConsoleStatus({ stacked }: { stacked?: boolean }) {
  const state = useStateDoc();
  const caps = useCaps();
  const g = state.data?.git ?? {};
  const tokens = Object.entries(caps.data?.env_tokens ?? {}).filter(([, v]) => v).map(([k]) => k);
  // Before the documents arrive the chips used to claim "clean tree", "gh
  // signed out" and "0 tokens" — three verdicts with no data behind them.
  const loaded = state.data !== undefined;
  const capsLoaded = caps.data !== undefined;
  return (
    <Group gap={6} wrap={stacked ? 'wrap' : 'nowrap'} className={stacked ? undefined : u.clip}>
      {mode() === 'remote' ? (
        <Chip tone="good" href={to.connect()} title="This public page is connected to a running console; every page acts through it.">
          <IconPlugConnected size={13} /> {consoleOrigin().replace(/^https?:\/\//, '')}
        </Chip>
      ) : null}
      <Chip title="git branch and HEAD of the hub working tree">
        <IconGitBranch size={13} /> {g.branch ?? '?'} <Text span ff="monospace" fz={11}>{g.head ?? ''}</Text>
      </Chip>
      {/* git_info reports available=false when git refused to answer; that is
          "unknown", never "clean" — the chip used to claim a clean tree then. */}
      <Chip tone={!loaded ? undefined : g.available === false ? 'crit' : g.dirty_count ? undefined : 'good'}
        title={g.available === false ? 'git did not answer in the console process, so the tree state is unknown.' : 'Uncommitted files. The console never commits: review generated data in git and commit it yourself.'}>
        {!loaded ? '… tree' : g.available === false ? '? tree unknown' : g.dirty_count ? `✎ ${g.dirty_count} uncommitted` : '✓ clean tree'}
      </Chip>
      <Chip tone={!capsLoaded ? undefined : caps.data?.gh_authenticated ? 'good' : 'crit'} href={to.github()} title="GitHub sign-in — open the GitHub page to connect through the OAuth App">
        {!capsLoaded ? '… gh' : caps.data?.gh_authenticated ? '✓ gh' : '✖ gh signed out'}
      </Chip>
      <Chip href={to.auth()} title={`Credential names present in this process (values never shown): ${tokens.join(', ') || 'none'}`}>
        <IconKey size={13} /> {!capsLoaded ? '… tokens' : `${tokens.length} token${tokens.length === 1 ? '' : 's'}`}
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

export function ThemeToggle() {
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
  overview: '/overview', apps: '/projects', harnesses: '/harnesses', schedules: '/schedules', loops: '/loops', costs: '/costs',
  observe: '/observe/traces', content: '/content', fleet: '/projects', contract: '/config', auth: '/auth', jobs: '/jobs',
};

export function Shell() {
  const [opened, { toggle, close }] = useDisclosure();
  const { pathname, hash, search } = useLocation();
  const navigate = useNavigate();
  useEffect(() => {
    const dest = pathname === '/' && LEGACY[hash.replace('#', '')];
    if (dest) navigate(dest, { replace: true });
  }, [pathname, hash, navigate]);
  // Inside a Desktop window: say where this page is, so the window's title and
  // a shared layout follow it. Addressed to this origin only — a parent on any
  // other origin never receives it.
  useEffect(() => {
    if (EMBEDDED) window.parent.postMessage({ bridge: 'fleet', v: 1, type: 'route', path: `${pathname}${search}` }, window.location.origin);
  }, [pathname, search]);
  const qc = useQueryClient();
  const site = useSite();
  const brand = site.data?.profile.site?.title ?? 'Harness Console';
  const active = activeIndex(pathname);
  useEffect(close, [pathname, close]);
  const [named, setNamed] = useState<PageTitle | null>(null);
  // The page's own name once it has said it; the sidebar's until then.
  const item = FLAT[active];
  const pageTitle = named?.path === pathname ? named.title : item?.label;
  const atHome = pathname === '/';
  useEffect(() => {
    document.title = pageTitle && !atHome ? `${pageTitle} · ${brand}` : `${brand}${site.data?.profile.name ? ` — ${site.data.profile.name}` : ''}`;
  }, [pageTitle, atHome, brand, site.data]);
  useEffect(() => {
    if (item && pageTitle && !atHome && !EMBEDDED) rememberPage({ path: pathname, label: pageTitle });
  }, [item, pageTitle, atHome, pathname]);
  // A route change moves the reader to the new page: back to its top (Back and
  // Forward keep where they were), and focus off the link that was just left.
  const main = useRef<HTMLElement>(null);
  const navigationType = useNavigationType();
  const arrived = useRef(false);
  useEffect(() => {
    if (!arrived.current) {
      arrived.current = true;
      return;
    }
    if (navigationType !== 'POP') window.scrollTo(0, 0);
    if (!document.querySelector('[role="dialog"]')) main.current?.focus({ preventScroll: true });
  }, [pathname, navigationType]);
  const refresh = () => {
    clearSnapshotCache();
    void qc.invalidateQueries();
  };

  // The reducer's "plain" experience: one scene, chrome unmounted. The window
  // on the Desktop is this page's frame, so the header and sidebar would be a
  // second one inside it.
  if (EMBEDDED) {
    return (
      <Box p="md" mih="100dvh" bg="var(--page)">
        <ErrorBoundary resetKey={pathname}><Outlet /></ErrorBoundary>
      </Box>
    );
  }

  return (
    <PageTitleContext.Provider value={setNamed}>
    <a href="#main" className={navClasses.skip} onClick={(e) => { e.preventDefault(); main.current?.focus(); }}>Skip to content</a>
    <VisuallyHidden aria-live="polite" aria-atomic>{pageTitle}</VisuallyHidden>
    <AppShell header={{ height: LAYOUT.headerHeight }} navbar={{ width: LAYOUT.navbarWidth, breakpoint: 'sm', collapsed: { mobile: !opened } }} padding="lg">
      <AppShell.Header px="md">
        <Group h="100%" justify="space-between" wrap="nowrap" gap="sm">
          <Group gap="sm" wrap="nowrap">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" aria-label="Menu" aria-expanded={opened} aria-controls="console-nav" />
            <UnstyledButton component={Link} to="/">
              <Group gap={8} wrap="nowrap">
                <img src={asset('favicon.svg')} width={24} height={24} alt="" />
                <Text fw={650} fz={16} className={u.nowrap}>{brand}</Text>
                <Text size="xs" c="dimmed" visibleFrom="lg" className={u.nowrap}>Harness Console</Text>
              </Group>
            </UnstyledButton>
            <Box visibleFrom="md" className={u.clip}><HeaderStatus /></Box>
          </Group>
          <Group gap={8} wrap="nowrap">
            <Button variant="default" size="sm" fw={400} c="dimmed" visibleFrom="xs"
              leftSection={<IconSearch size={15} />} rightSection={<Kbd size="xs">:</Kbd>} onClick={() => spotlight.open()}>
              Search or run…
            </Button>
            <ActionIcon variant="default" size="lg" hiddenFrom="xs" onClick={() => spotlight.open()} aria-label="Search"><IconSearch size={18} /></ActionIcon>
            <JobsIndicator />
            <Tooltip label="Re-read every document (r)">
              <ActionIcon variant="default" size="lg" visibleFrom="xs" onClick={refresh} aria-label="Refresh"><IconRefresh size={18} /></ActionIcon>
            </Tooltip>
            <ThemeToggle />
            {hasConsole() ? (
              <Tooltip label="API docs (/docs)">
                <ActionIcon component="a" href={`${consoleOrigin()}/docs`} target="_blank" rel="noopener" variant="default" size="lg" visibleFrom="sm" aria-label="API docs"><IconApi size={18} /></ActionIcon>
              </Tooltip>
            ) : null}
          </Group>
        </Group>
      </AppShell.Header>
      <AppShell.Navbar p="xs" id="console-nav" aria-label="Console">
        <AppShell.Section grow component={ScrollArea}>
          <ShellNav active={active} />
        </AppShell.Section>
        <AppShell.Section>
          <Box hiddenFrom="md" px={8} pt={6}><HeaderStatus stacked /></Box>
          <Group gap={6} px={8} py={6} wrap="wrap">
            <UnstyledButton onClick={() => window.dispatchEvent(new Event(KEYS_EVENT))} aria-label="Show the keyboard keys">
              <Badge variant="default" size="sm" leftSection={<Kbd size="xs">?</Kbd>} className={u.pointer}>keys</Badge>
            </UnstyledButton>
            <Text size="xs" c="dimmed">keys v1 · same as <Anchor component={Link} to={to.terminal()} size="xs">the TUI</Anchor></Text>
          </Group>
        </AppShell.Section>
      </AppShell.Navbar>
      <AppShell.Main ref={main} id="main" tabIndex={-1}>
        <Box maw={LAYOUT.contentMaxWidth} mx="auto">
          <ConnectionLost />
          <ErrorBoundary resetKey={pathname}><Outlet /></ErrorBoundary>
        </Box>
      </AppShell.Main>
    </AppShell>
    </PageTitleContext.Provider>
  );
}
