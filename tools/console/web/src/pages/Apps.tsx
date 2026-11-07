// The app portal: every frontend the registry declares (/api/apps —
// fleetcore.apps, the list `tools/dash apps` prints), opened inside the
// console. One app, two places it runs — the live site and the dev stack on
// this machine — and the verify kit's device sizes, so the same page is where
// a frontend is viewed, navigated, used and checked (ADR 0005).
//
// A frame only ever points at a registry address plus a path inside it: the
// query string picks among the app's targets, it never supplies a URL.
import { Link, useParams, useSearchParams } from 'react-router';
import {
  ActionIcon, Anchor, Badge, Button, Code, CopyButton, Group, Paper, SegmentedControl, Select, SimpleGrid, Stack, Table, Text,
  TextInput, Tooltip,
} from '@mantine/core';
import {
  IconArrowsMaximize, IconCopy, IconDeviceDesktop, IconDeviceMobile, IconDeviceTablet, IconExternalLink, IconReload, IconSearch,
} from '@tabler/icons-react';
import { useEffect, useState, type CSSProperties, type ReactNode } from 'react';
import { OPEN_EVENT, hasConsole } from '../api/backend';
import { useApps, useJobs, useOps, useReach } from '../api/hooks';
import type { AppTarget, AppsDoc, FleetApp, FleetRepo, Job } from '../api/types';
import { Banner, External, Load, Mono, PageHeader, Section, Spinner, StatTile, Status } from '../components/ui';
import { RunButton } from '../jobs/RunButton';
import { to } from '../lib/links';
import u from '../styles/utils.module.css';
import c from './Apps.module.css';
import { RepoApp } from './RepoApp';

const SURFACE: Record<string, string> = {
  browser: 'browser', desktop: 'desktop', mobile: 'mobile', vscode: 'VS Code', terminal: 'terminal',
};
const TYPE_FILTERS = [
  { value: 'all', label: 'All' }, { value: 'app', label: 'Apps' }, { value: 'site', label: 'Sites' },
  { value: 'game', label: 'Games' }, { value: 'other', label: 'Other surfaces' }, { value: 'generated', label: 'No interface' },
];
const matchesType = (a: FleetApp, f: string) =>
  f === 'all' || (f === 'other' ? a.embed === 'none' : f !== 'generated' && a.embed === 'frame' && (a.type === f || (f === 'app' && a.type === 'console')));

// What a framed app may do. Never top-navigation: an app cannot take the
// console's tab away. An app served from this page's own origin (the public
// build beside bamr87.github.io/<repo>/) is framed without allow-same-origin,
// so it cannot read what this page keeps in the browser.
const SANDBOX_ISOLATED = 'allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox allow-downloads allow-modals';
const SANDBOX_CROSS_ORIGIN = `${SANDBOX_ISOLATED} allow-same-origin`;

function sharesOrigin(url: string): boolean {
  try {
    return new URL(url).origin === window.location.origin;
  } catch {
    return false;
  }
}

/** base + a path inside it; anything that would leave the app's own address is dropped. */
export function inside(base: string, path: string): string {
  const clean = path.trim().replace(/^[/\\]+/, '');
  if (!clean) return base;
  try {
    const b = new URL(base);
    const root = b.href.endsWith('/') ? b.href : `${b.href}/`;
    const out = new URL(clean, root);
    // Same origin is not enough where apps share one (bamr87.github.io/<repo>/):
    // `../other-app` would frame a neighbour under this app's name.
    return out.href.startsWith(root) ? out.href : base;
  } catch {
    return base;
  }
}

/** How long after a start finishes a stack is given to begin answering. */
const STARTING_MS = 90_000;
const STARTING_POLL_MS = 3000;

/** The newest start or stop of this project's stack: a stop ends a start that came before it. */
function lastStackJob(jobs: Job[] | undefined, project: string | undefined): Job | undefined {
  const mine = (jobs ?? []).filter((j) => (j.op === 'dev-up' || j.op === 'dev-down') && j.params?.target === project);
  return mine.sort((a, b) => String(b.created ?? '').localeCompare(String(a.created ?? '')))[0];
}

/** Started and not yet given up on: the start is running, or finished moments ago. */
function isStarting(job: Job | undefined): boolean {
  if (job?.op !== 'dev-up') return false;
  if (job.status === 'queued' || job.status === 'running') return true;
  return job.status === 'succeeded' && Date.now() - Date.parse(String(job.finished ?? '')) < STARTING_MS;
}

const hostOf = (url: string) => url.replace(/^https?:\/\//, '').replace(/\/$/, '');

/** A target as a pill: where it is, and (when asked) whether it answers from here. */
function TargetPill({ target, probe }: { target: AppTarget; probe: boolean }) {
  const reach = useReach(target.url, probe);
  const label = target.kind === 'live' ? 'Live' : 'Local';
  if (!probe || reach.data === undefined) return <Status tone="info" title={target.url}>{label}</Status>;
  if (reach.data) return <Status tone="good" title={`${target.url} answers`}>{label}</Status>;
  // A stopped local stack is the ordinary state, not a fault; a silent live site is one.
  return target.kind === 'live'
    ? <Status tone="crit" title={`${target.url} does not answer from here`}>{label} · no answer</Status>
    : <Status tone="info" title={`Nothing listens on ${hostOf(target.url)} — start it with ${target.start ?? 'its dev stack'}`}>{label} · stopped</Status>;
}

function AppCard({ app, probe }: { app: FleetApp; probe: boolean }) {
  const primary = (['live', 'local'] as const).map((k) => app.targets.find((t) => t.kind === k)).filter(Boolean) as AppTarget[];
  return (
    <Paper p="md" component={Link} to={to.app(app.id)} className={`${u.tileLink} ${c.card}`} data-embed={app.embed}>
      <Stack gap={8} h="100%">
        <Group justify="space-between" wrap="nowrap" gap="xs">
          <Text fw={600} className={u.anywhere}>{app.name}</Text>
          <Badge variant="light" size="sm">{app.type}</Badge>
        </Group>
        <Text size="sm" c="dimmed" lineClamp={2}>{app.description}</Text>
        <Mono dim>{app.framework}</Mono>
        <Group gap={6} mt="auto" wrap="wrap">
          {primary.map((t) => <TargetPill key={t.id} target={t} probe={probe} />)}
          {app.embed === 'none' ? (
            <Text size="xs" c="dimmed">{primary.length ? 'not a browser surface' : `no address yet · ${app.surfaces.map((s) => SURFACE[s] ?? s).join(', ') || 'no surface'}`}</Text>
          ) : null}
        </Group>
      </Stack>
    </Paper>
  );
}

/** A repo the launcher has no frontend for: it opens as the generated repo app. */
function RepoCard({ repo }: { repo: FleetRepo }) {
  return (
    <Paper p="md" component={Link} to={to.app(repo.id)} className={`${u.tileLink} ${c.card}`} data-embed="none">
      <Stack gap={8} h="100%">
        <Group justify="space-between" wrap="nowrap" gap="xs">
          <Text fw={600} className={u.anywhere}>{repo.name}</Text>
          <Badge variant="default" size="sm">{repo.component.kind === 'terminal' ? 'terminal' : 'repo'}</Badge>
        </Group>
        <Text size="sm" c="dimmed" lineClamp={2}>{repo.description}</Text>
        <Mono dim>{(repo.stack ?? []).slice(0, 4).join(' · ') || repo.category}</Mono>
        <Text size="xs" c="dimmed" mt="auto">opens as the generated repo app</Text>
      </Stack>
    </Paper>
  );
}

export function Apps() {
  const apps = useApps();
  const [sp, setSp] = useSearchParams();
  const [q, setQ] = useState(sp.get('q') ?? '');
  const type = sp.get('type') ?? 'all';
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(sp);
    if (v && v !== 'all') next.set(k, v); else next.delete(k);
    setSp(next, { replace: true });
  };
  // The list asks whether each address answers only where an operator is
  // looking (a console is connected). The public page lists addresses and
  // sends a visitor's browser nowhere until they open an app.
  const probe = hasConsole();

  return (
    <>
      <PageHeader
        title="Apps"
        description={<>Every repo in the fleet as an app. A repo with a frontend opens it inside the console: the live site or the stack running on this machine, at any device size. A repo without one opens as the app the console generates for it. <Code>tools/dash apps</Code> prints the frontends, <Code>tools/dash apps plan</Code> every repo.</>}
      />
      <Load q={apps} rows={8}>
        {(doc) => {
          const needle = q.trim().toLowerCase();
          const rows = doc.apps
            .filter((a) => matchesType(a, type))
            .filter((a) => !needle || `${a.name} ${a.framework ?? ''} ${a.description ?? ''} ${a.type}`.toLowerCase().includes(needle))
            .sort((a, b) => Number(b.embed === 'frame') - Number(a.embed === 'frame'));
          // Every repo is an app: the ones the launcher has no frontend for come last.
          const listed = new Set(doc.apps.map((a) => a.id));
          const rest = doc.repos
            .filter((r) => !listed.has(r.id) && (type === 'all' || type === 'generated'))
            .filter((r) => !needle || `${r.name} ${(r.stack ?? []).join(' ')} ${r.description ?? ''}`.toLowerCase().includes(needle));
          const total = doc.apps.length + doc.repos.filter((r) => !listed.has(r.id)).length;
          return (
            <>
              <SimpleGrid cols={{ base: 2, md: 4 }} spacing="md" mb="lg">
                <StatTile label="Repos" value={total} sub={`${doc.summary.apps} with a frontend of their own`} />
                <StatTile label="Open here" value={doc.summary.embeddable} sub="a browser surface with an address" />
                <StatTile label="Live" value={doc.summary.live} sub="deployed sites" />
                <StatTile label="Local stack" value={doc.summary.local} sub="a dev stack with a fixed port" />
              </SimpleGrid>
              <Group gap="sm" mb="md" wrap="wrap">
                <TextInput data-page-search leftSection={<IconSearch size={15} />} placeholder="Search apps, frameworks…  ( / )" value={q} w={280}
                  onChange={(e) => { setQ(e.currentTarget.value); set('q', e.currentTarget.value); }} aria-label="Search apps" />
                <SegmentedControl size="xs" value={type} onChange={(v) => set('type', v)} data={TYPE_FILTERS} aria-label="Kind of frontend" />
                <Text size="sm" c="dimmed">{rows.length + rest.length}/{total} shown</Text>
              </Group>
              {rows.length + rest.length ? (
                <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="md">
                  {rows.map((a) => <AppCard key={a.id} app={a} probe={probe} />)}
                  {rest.map((r) => <RepoCard key={r.id} repo={r} />)}
                </SimpleGrid>
              ) : <Text size="sm" c="dimmed" py="sm">No repo matches.</Text>}
            </>
          );
        }}
      </Load>
    </>
  );
}

const DEVICE_ICON: Record<string, ReactNode> = {
  desktop: <IconDeviceDesktop size={15} />, tablet: <IconDeviceTablet size={15} />, mobile: <IconDeviceMobile size={15} />,
};

function Vacant({ title, children }: { title: ReactNode; children: ReactNode }) {
  return (
    <div className={c.vacant}>
      <Stack gap="sm" align="center">
        <Text fw={600}>{title}</Text>
        {children}
      </Stack>
    </div>
  );
}

function CopyCommand({ value }: { value: string }) {
  return (
    <Group gap={6} wrap="nowrap" justify="center">
      <Code>{value}</Code>
      <CopyButton value={value}>
        {({ copied, copy }) => (
          <Tooltip label={copied ? 'copied' : 'copy'}>
            <ActionIcon variant="default" size="sm" onClick={copy} aria-label={`Copy ${value}`}><IconCopy size={13} /></ActionIcon>
          </Tooltip>
        )}
      </CopyButton>
    </Group>
  );
}

/** What one open app is showing: which target, at which device size, at which path. */
export interface AppView {
  target?: string | null;
  device?: string | null;
  path?: string | null;
}

/**
 * The common App Shell: the controls every fleet frontend gets (where it runs,
 * a device size, a path, reload, open outside) around its frame. The Apps page
 * holds the view in the URL; a window on the Desktop holds it per window and
 * passes `fill`, so the frame takes the window and the registry facts stay on
 * the page.
 */
export function AppPane({ app, doc, view, onView, fill = false }: {
  app: FleetApp; doc: AppsDoc; view: AppView; onView: (next: AppView) => void; fill?: boolean;
}) {
  const [nonce, setNonce] = useState(0);
  const [forced, setForced] = useState<string | null>(null);
  const [asked, setAsked] = useState<string | null>(null);
  const target = app.targets.find((t) => t.id === view.target) ?? app.targets[0];
  const device = doc.viewports.find((v) => v.id === view.device);
  const path = view.path ?? '';
  const [draft, setDraft] = useState(path);
  const set = (patch: AppView) => {
    onView({ ...view, ...patch });
    if ('path' in patch) setDraft(patch.path ?? '');
  };

  // A local stack answers only on the machine that runs it. The public page
  // asks the reader before their browser is sent to 127.0.0.1.
  const needsAsk = target?.kind === 'local' && !hasConsole() && asked !== target.id;
  // A console can start this target's stack: its last start says whether to
  // keep asking the address, and whether the start failed.
  const canRun = target?.kind === 'local' && hasConsole() && Boolean(target.project);
  const stackJob = lastStackJob(useJobs(canRun).data, target?.project);
  const starting = canRun && isStarting(stackJob);
  const reach = useReach(target?.url, Boolean(target) && !needsAsk, starting ? STARTING_POLL_MS : 0);
  // When a start or stop ends, ask the address again. The job's log drawer
  // refreshes documents only while it is open, and it may already be closed.
  const stackDone = stackJob && !['queued', 'running'].includes(stackJob.status) ? stackJob.id : null;
  useEffect(() => {
    if (stackDone) void reach.refetch();
  }, [stackDone]); // eslint-disable-line react-hooks/exhaustive-deps -- reach.refetch is stable
  // Offered once the operations are known: a run before that has nothing to run.
  const stackOps = useOps();
  const noDocker = stackOps.data?.find((o) => o.id === 'dev-up')?.unavailable ?? null;
  const canStart = canRun && Boolean(stackOps.data) && !noDocker;
  if (!target) {
    return (
      <Paper className={u.dashed}>
        <Vacant title={`${app.name} has no address the console can open.`}>
          <Text size="sm" c="dimmed">
            {app.surfaces.length ? <>Its surface is {app.surfaces.map((s) => SURFACE[s] ?? s).join(', ')}. </> : null}
            A frontend appears here once the registry gives it a live URL (<Code>frontend.entry_url</Code>) or its dev stack has a port in <Code>_data/ports.yml</Code>.
          </Text>
          <Group gap="md">
            <Anchor component={Link} to={to.project(app.name)} size="sm">Project signals</Anchor>
            {app.repo_url ? <External href={app.repo_url} size="sm">repository</External> : null}
          </Group>
        </Vacant>
      </Paper>
    );
  }

  const src = inside(target.url, path);
  const own = sharesOrigin(src);
  const locals = app.targets.filter((t) => t.kind === 'local');
  const kinds = [...new Set(app.targets.map((t) => t.kind))];
  const showFrame = app.embed === 'frame' && !needsAsk && (reach.data === true || forced === target.id);
  const stageVars = device ? ({ '--frame-w': `${device.width}px`, '--frame-h': `${device.height}px` } as CSSProperties) : undefined;

  return (
    <div className={c.pane} data-fill={fill || undefined}>
      <Group gap="sm" mb="sm" wrap="wrap" align="flex-end">
        <SegmentedControl size="xs" value={target.kind} aria-label="Where the app runs"
          onChange={(k) => set({ target: app.targets.find((t) => t.kind === k)?.id ?? null, path: null })}
          data={kinds.map((k) => ({ value: k, label: k === 'live' ? 'Live' : 'Local' }))} disabled={kinds.length < 2} />
        {target.kind === 'local' && locals.length > 1 ? (
          <Select size="xs" w={190} aria-label="Local service" allowDeselect={false} value={target.id}
            onChange={(v) => set({ target: v, path: null })}
            data={locals.map((t) => ({ value: t.id, label: `${t.service} :${t.port}` }))} />
        ) : null}
        <SegmentedControl size="xs" value={device?.id ?? 'fit'} aria-label="Device size" onChange={(v) => set({ device: v === 'fit' ? null : v })}
          data={[
            { value: 'fit', label: <Group gap={4} wrap="nowrap"><IconArrowsMaximize size={15} /><span>Fit</span></Group> },
            ...doc.viewports.map((v) => ({
              value: v.id,
              label: <Group gap={4} wrap="nowrap" title={`${v.width} × ${v.height}`}>{DEVICE_ICON[v.id] ?? null}<span>{v.id}</span></Group>,
            })),
          ]} />
        <form className={u.flexFillWide} onSubmit={(e) => { e.preventDefault(); set({ path: draft.trim() || null }); setNonce((n) => n + 1); }}>
          <TextInput size="xs" value={draft} onChange={(e) => setDraft(e.currentTarget.value)} placeholder="/path inside the app — Enter to go"
            aria-label="Path inside the app" leftSection={<Text size="xs" c="dimmed">/</Text>} />
        </form>
        <Tooltip label="Reload the frame">
          <ActionIcon variant="default" size="md" onClick={() => { void reach.refetch(); setNonce((n) => n + 1); }} aria-label="Reload the frame"><IconReload size={15} /></ActionIcon>
        </Tooltip>
        <Tooltip label="Open in a new tab">
          <ActionIcon component="a" href={src} target="_blank" rel="noopener noreferrer" variant="default" size="md" aria-label="Open in a new tab"><IconExternalLink size={15} /></ActionIcon>
        </Tooltip>
      </Group>

      <Group gap="sm" mb="sm" wrap="wrap">
        {needsAsk ? <Status tone="info">not checked</Status>
          : reach.data === undefined ? <Spinner label="checking…" />
            : reach.data ? <Status tone="good">answers</Status>
              : <Status tone={target.kind === 'live' ? 'crit' : 'info'}>{target.kind === 'live' ? 'no answer' : 'stopped'}</Status>}
        <Mono dim>{src}</Mono>
        {device ? <Text size="xs" c="dimmed">{device.width} × {device.height}</Text> : null}
        {canStart && reach.data ? (
          <>
            <RunButton op="dev-logs" params={{ target: target.project }} size="compact-xs">Logs</RunButton>
            <RunButton op="dev-down" params={{ target: target.project }} size="compact-xs">Stop the stack</RunButton>
          </>
        ) : null}
      </Group>

      {own && showFrame ? (
        <Banner tone="info">
          {app.name} is served from this page's own address, so it runs isolated here: it cannot read what this page stores, and it starts without its own saved sign-in or preferences. An app that depends on browser storage may not render in the frame — <External href={src}>open it in a new tab</External> for the full app.
        </Banner>
      ) : null}

      <div className={c.stage} data-device={device?.id ?? 'fit'} style={stageVars}>
        {app.embed !== 'frame' ? (
          <Vacant title={`${app.name} is not a browser surface.`}>
            <Text size="sm" c="dimmed">Its surface is {app.surfaces.map((s) => SURFACE[s] ?? s).join(', ') || 'not declared'}; the console frames what a browser renders.</Text>
            <External href={src} size="sm">Open its address</External>
          </Vacant>
        ) : needsAsk ? (
          <Vacant title="A local stack answers only on the machine that runs it.">
            <Text size="sm" c="dimmed">This is the public page. If {app.name} is running on this computer, check {hostOf(target.url)} — your browser may ask before it lets a website reach your own machine.</Text>
            <Button size="xs" variant="default" onClick={() => setAsked(target.id)}>Check {hostOf(target.url)}</Button>
          </Vacant>
        ) : showFrame ? (
          <iframe key={`${src}#${nonce}`} className={c.frame} src={src} title={`${app.name} — ${target.label}`}
            sandbox={own ? SANDBOX_ISOLATED : SANDBOX_CROSS_ORIGIN} allow="fullscreen; clipboard-write" referrerPolicy="no-referrer" />
        ) : reach.data === undefined ? (
          <Vacant title={`Checking ${hostOf(target.url)}…`}><Spinner /></Vacant>
        ) : target.kind === 'local' ? (
          <Vacant title={starting ? `Starting ${app.name}…` : `Nothing is listening on ${hostOf(target.url)}.`}>
            {starting ? (
              <>
                <Spinner label={`waiting for ${hostOf(target.url)} to answer; the app opens here when it does`} />
                <Text size="xs" c="dimmed">A first start can take minutes while its images build.</Text>
              </>
            ) : (
              <>
                <Text size="sm" c="dimmed">The {target.service} service of {app.name}'s dev stack is not running on this machine.</Text>
                {stackJob?.op === 'dev-up' && stackJob.status === 'failed' ? (
                  <Banner tone="crit" title="The last start failed">
                    <Anchor component={Link} to={to.job(stackJob.id)} size="sm" onClick={(e) => {
                      if (!fill) return;
                      e.preventDefault();
                      window.dispatchEvent(new CustomEvent(OPEN_EVENT, { detail: { path: to.job(stackJob.id) } }));
                    }}>Read its log</Anchor>
                  </Banner>
                ) : null}
                {canStart ? <RunButton op="dev-up" params={{ target: target.project }} variant="filled">Start the stack</RunButton> : null}
                {canRun && noDocker ? <Text size="xs" c="dimmed">This console has no Docker access, so it cannot start a stack itself.</Text> : null}
                <Text size="sm" c="dimmed">{canStart ? 'Or from a terminal:' : 'Start it from a terminal:'}</Text>
                {target.start ? <CopyCommand value={target.start} /> : null}
                <Group gap="xs">
                  <Button size="xs" variant="default" onClick={() => void reach.refetch()} loading={reach.isFetching}>Check again</Button>
                  <Button size="xs" variant="subtle" onClick={() => setForced(target.id)}>Load it anyway</Button>
                </Group>
              </>
            )}
          </Vacant>
        ) : (
          <Vacant title={`${hostOf(target.url)} is not answering from here.`}>
            <Text size="sm" c="dimmed">The live site did not respond to this browser. It may be down, or this network may not reach it.</Text>
            <Group gap="xs">
              <Button size="xs" variant="default" onClick={() => void reach.refetch()} loading={reach.isFetching}>Check again</Button>
              <Button size="xs" variant="subtle" onClick={() => setForced(target.id)}>Load it anyway</Button>
            </Group>
          </Vacant>
        )}
      </div>
      {showFrame && !fill ? (
        <Text size="xs" c="dimmed" mt={6}>
          An empty or refused frame means the app forbids being framed — open it in a new tab; <Code>tools/dash apps check {app.id}</Code> reports its frame policy.
        </Text>
      ) : null}

      {fill ? null : (
      <Section title="Platform" description="What the registry says about this frontend (constitution § 18): its tier decides which shared layers it takes, and the check stays warn-only until its adoption PR merges.">
        <Paper p="xs">
          <Table verticalSpacing={4}>
            <Table.Tbody>
              {([
                ['framework', app.framework ?? '—'],
                ['surfaces', app.surfaces.map((s) => SURFACE[s] ?? s).join(', ') || '—'],
                ['tier', app.tier],
                ['shell', app.shell === 'own' ? 'its own (not yet the fleet shell)' : app.shell ?? '—'],
                ['tokens', app.token_version && app.token_version !== 'none' ? app.token_version : 'none adopted yet'],
                ['enforcement', app.enforce ? 'failing on drift' : 'warn-only'],
                ['deep link', app.deep_link],
              ] as [string, string][]).map(([k, v]) => (
                <Table.Tr key={k}>
                  <Table.Td w={140}><Mono dim>{k}</Mono></Table.Td>
                  <Table.Td><Text size="sm">{v}</Text></Table.Td>
                </Table.Tr>
              ))}
              {app.targets.map((t) => (
                <Table.Tr key={t.id}>
                  <Table.Td><Mono dim>{t.id}</Mono></Table.Td>
                  <Table.Td><External href={t.url} size="sm">{t.url}</External>{t.start ? <Text span size="xs" c="dimmed"> · {t.start}</Text> : null}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Paper>
      </Section>
      )}
    </div>
  );
}

/** The Apps page's workspace: the App Shell with its view kept in the URL, so a link restores it. */
function Workspace({ app, doc }: { app: FleetApp; doc: AppsDoc }) {
  const [sp, setSp] = useSearchParams();
  const view: AppView = { target: sp.get('target'), device: sp.get('device'), path: sp.get('path') };
  const onView = (next: AppView) => {
    const qs = new URLSearchParams(sp);
    for (const k of ['target', 'device', 'path'] as const) {
      const v = next[k];
      if (v) qs.set(k, v); else qs.delete(k);
    }
    setSp(qs, { replace: true });
  };
  return <AppPane app={app} doc={doc} view={view} onView={onView} />;
}

export function AppWorkspace() {
  const { id = '' } = useParams();
  const apps = useApps();
  const same = (x: { id: string; name: string }) => x.id.toLowerCase() === id.toLowerCase() || x.name.toLowerCase() === id.toLowerCase();
  const app = apps.data?.apps.find(same);
  const repo = apps.data?.repos.find(same);
  // The repo app is what a repo opens as when the shell has nothing of its own to frame.
  const generated = repo && !(app && app.embed === 'frame') ? repo : undefined;
  if (generated) {
    return (
      <>
        <PageHeader
          crumbs={[{ label: 'Apps', to: to.apps() }, { label: generated.name }]}
          title={generated.name}
          badges={<Badge variant="default">{generated.component.kind === 'generated' ? 'repo app' : `repo app · ${generated.component.kind} owed`}</Badge>}
        />
        <RepoApp repo={generated} />
      </>
    );
  }
  return (
    <>
      <PageHeader
        crumbs={[{ label: 'Apps', to: to.apps() }, { label: app?.name ?? id }]}
        title={app?.name ?? id}
        badges={app ? (
          <>
            <Badge variant="light">{app.type}</Badge>
            {app.framework ? <Badge variant="outline">{app.framework}</Badge> : null}
          </>
        ) : null}
        description={app?.description}
        actions={app ? (
          <>
            <Anchor component={Link} to={to.project(app.name)} size="sm">project signals</Anchor>
            {app.repo_url ? <External href={app.repo_url} size="sm">repository</External> : null}
          </>
        ) : null}
      />
      <Load q={apps} rows={8}>
        {(doc) => (app
          ? <Workspace key={app.id} app={app} doc={doc} />
          : <Banner tone="crit" title="No such frontend">The registry has no frontend named <Code>{id}</Code>. <Anchor component={Link} to={to.apps()}>Every app</Anchor>.</Banner>)}
      </Load>
    </>
  );
}
