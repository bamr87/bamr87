// The bashOS desktop in the browser: the OS shell that hosts the App Shell
// (ADR 0005, "bashOS is the OS shell").
//
//   OS shell   this page — a desktop with an icon per app (a dock the windows
//              never cover), floating windows, a taskbar. Its state is bashOS's own layout reducer
//              (../vendor/bashos/shell.js, byte-identical to the bashOS GUI's),
//              so a window here moves, snaps, minimizes and shares its layout
//              exactly as one does in `bashos gui`.
//   App Shell  what every window shares — AppPane (./Apps): where the app
//              runs, a device size, a path, reload, open outside.
//   App        a fleet frontend from the launcher, framed under the same rules
//              as the Apps page; or, for a repo with no frontend the shell can
//              show, the repo app the shell generates (./RepoApp).
//
// A layout carries scene and app ids and geometry, never an address: a shared
// link can only open what the registry declares. Below the reducer's narrow
// width the desktop becomes a home screen: the icons, then one app at a time.
import {
  useEffect, useMemo, useReducer, useRef, useState,
  type CSSProperties, type PointerEvent as ReactPointerEvent, type ReactNode,
} from 'react';
import { Link } from 'react-router';
import { Anchor, Badge, Code, Group, Stack, Text, Title } from '@mantine/core';
import { useViewportSize } from '@mantine/hooks';
import {
  IconAppWindow, IconArrowsMinimize, IconChevronLeft, IconDeviceGamepad2, IconDeviceMobile, IconFileText, IconFolder,
  IconLayoutGrid, IconLink, IconMaximize, IconMinus, IconPlayerPlayFilled, IconPuzzle, IconStack2, IconTerminal2,
  IconWorld, IconX,
} from '@tabler/icons-react';
import { hasConsole } from '../api/backend';
import { useApps } from '../api/hooks';
import type { AppsDoc, FleetApp, FleetRepo } from '../api/types';
import { ThemeToggle } from '../components/Shell';
import { Load, Status } from '../components/ui';
import { to } from '../lib/links';
import {
  MAX_WINDOWS, decodeLayout, effectiveExperience, encodeLayout, initialState, reduce,
  type ShellAction, type ShellState, type ShellWindow,
} from '../vendor/bashos/shell.js';
import { AppPane, type AppView } from './Apps';
import { RepoApp } from './RepoApp';
import c from './Desktop.module.css';

/** What a window can hold. `app` and `repo` name a registry id in resourceId. */
const SCENES = ['welcome', 'fleet', 'app', 'repo'];
const LAYOUT_PARAM = 'windows';
const TAB_KEY = 'bashos_desktop_layout';
// The menu bar and taskbar heights in Desktop.module.css, for counting dock rows.
const MENUBAR_PX = 44;
const TASKBAR_PX = 48;
const DOCK_ROW_PX = 82; // an icon row (80) and its gap

function typeIcon(type: string | null | undefined, size = 22): ReactNode {
  if (type === 'site') return <IconWorld size={size} stroke={1.6} />;
  if (type === 'game') return <IconDeviceGamepad2 size={size} stroke={1.6} />;
  if (type === 'ext') return <IconPuzzle size={size} stroke={1.6} />;
  if (type === 'app' || type === 'console') return <IconAppWindow size={size} stroke={1.6} />;
  return <IconFileText size={size} stroke={1.6} />;
}

function repoIcon(repo: FleetRepo, size = 22): ReactNode {
  if (repo.component.kind === 'terminal') return <IconTerminal2 size={size} stroke={1.6} />;
  if (repo.surfaces.includes('mobile')) return <IconDeviceMobile size={size} stroke={1.6} />;
  return typeIcon(repo.type, size);
}

// ------------------------------------------------------------------ layouts
function encodeParam(state: ShellState): string {
  return btoa(JSON.stringify(encodeLayout(state))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function decodeParam(raw: string | null): unknown {
  if (!raw) return null;
  try {
    return JSON.parse(atob(raw.replace(/-/g, '+').replace(/_/g, '/')));
  } catch {
    return null;
  }
}

function readTab(): unknown {
  try {
    return JSON.parse(window.sessionStorage.getItem(TAB_KEY) ?? 'null');
  } catch {
    return null;
  }
}

function saveTab(state: ShellState): boolean {
  try {
    window.sessionStorage.setItem(TAB_KEY, JSON.stringify(encodeLayout(state)));
    return true;
  } catch {
    return false; // a private window: the layout lives for this page load only
  }
}

/** The first desktop: a shared link's layout, else this tab's last one, else Welcome. */
function boot(doc: AppsDoc): ShellState {
  const framed = new Set(doc.apps.filter((a) => a.embed === 'frame').map((a) => a.id));
  const repos = new Set(doc.repos.map((r) => r.id));
  // A layout names ids; only ones the registry declares come back as windows.
  const known = (w: ShellWindow) =>
    w.sceneId === 'welcome' || w.sceneId === 'fleet'
    || (w.sceneId === 'app' && w.resourceId !== null && framed.has(w.resourceId))
    || (w.sceneId === 'repo' && w.resourceId !== null && repos.has(w.resourceId));
  for (const payload of [decodeParam(new URLSearchParams(window.location.search).get(LAYOUT_PARAM)), readTab()]) {
    const st = decodeLayout(payload, SCENES);
    const windows = st?.windows.filter(known) ?? [];
    if (st && windows.length) {
      const focusId = windows.some((w) => w.id === st.focusId) ? st.focusId : windows[windows.length - 1].id;
      return { ...st, experience: 'os', windows, focusId };
    }
  }
  let state = reduce(initialState('welcome'), { type: 'experience', experience: 'os' });
  const first = state.windows[0];
  // Small: Welcome is a note, not the work.
  state = reduce(state, { type: 'move', id: first.id, xPct: 8, yPct: 8 });
  return reduce(state, { type: 'resize', id: first.id, wPct: 50, hPct: 56 });
}

const contentKey = (w: ShellWindow) => `${w.id}|${w.sceneId}|${w.resourceId ?? ''}`;

// ------------------------------------------------------------------- panels
function WelcomePanel({ doc, open }: { doc: AppsDoc; open: Open }) {
  const owed = doc.repos.filter((r) => !r.framed).length;
  return (
    <Stack gap="sm" className={c.panel}>
      <Title order={3} fz={18}>bashOS · the fleet desktop</Title>
      <Text size="sm">
        Every icon is a fleet frontend from the registry. Open one and it runs in a window with the same controls as every other: where it runs (the live site or the stack on this machine), a device size, and a path inside the app.
      </Text>
      <Text size="sm" c="dimmed">
        Drag a window by its title bar; drop it on the left or right edge to fill that half, or on the top edge to fill the desktop. Shift-click an icon for a second window of the same app, to put Live beside Local. The taskbar brings a minimized window back.
      </Text>
      <Group gap="xs">
        <Status tone="good">{doc.summary.embeddable} apps open in a window</Status>
        <Status tone="info">{owed} more open as the generated repo app</Status>
      </Group>
      <Group gap="md">
        <Anchor component="button" type="button" size="sm" onClick={() => open('fleet', null)}>Every repo and its component</Anchor>
        <Anchor component={Link} to={to.apps()} size="sm">The same apps as a list</Anchor>
        <Anchor component={Link} to={to.overview()} size="sm">The classic console</Anchor>
      </Group>
      <Text size="xs" c="dimmed">The same launcher in a terminal: <Code>tools/dash apps</Code>, and <Code>tools/dash apps plan</Code> for what each repo is owed.</Text>
    </Stack>
  );
}

const FLEET_GROUPS: { title: string; note: string; match: (r: FleetRepo) => boolean }[] = [
  { title: 'In the shell', note: 'opens in a window today', match: (r) => r.framed },
  { title: 'A frontend with no address yet', note: 'needs a public build or a dev-stack port', match: (r) => r.component.kind === 'own' && !r.framed },
  { title: 'A surface a browser cannot host', note: 'needs a web preview or a terminal window', match: (r) => r.component.kind === 'preview' || r.component.kind === 'terminal' },
  { title: 'No interface of its own', note: 'opens as the generated repo app', match: (r) => r.component.kind === 'generated' },
];

function FleetPanel({ doc, open }: { doc: AppsDoc; open: Open }) {
  return (
    <Stack gap="md" className={c.panel}>
      <Text size="sm" c="dimmed">
        All {doc.repos.length} repos in the registry. {doc.repos.filter((r) => r.framed).length} open their own frontend in a window; the rest open as the repo app the shell generates, and say which component of their own they are owed.
      </Text>
      {FLEET_GROUPS.map((g) => {
        const rows = doc.repos.filter(g.match);
        if (!rows.length) return null;
        return (
          <div key={g.title}>
            <Group gap="xs" mb={4}>
              <Text fw={650} size="sm">{g.title}</Text>
              <Badge variant="default" size="sm">{rows.length}</Badge>
              <Text size="xs" c="dimmed">{g.note}</Text>
            </Group>
            {rows.map((r) => (
              <button key={r.id} type="button" className={c.repoRow} onClick={() => open(r.framed ? 'app' : 'repo', r.id)}>
                {repoIcon(r, 18)}
                <span className={c.repoName}>{r.name}</span>
                <span className={c.repoWhat}>{r.component.kind === 'own' ? r.framework : r.component.kind} · {r.component.next}</span>
              </button>
            ))}
          </div>
        );
      })}
    </Stack>
  );
}

// ------------------------------------------------------------------- window
type Open = (sceneId: string, resourceId: string | null, another?: boolean) => void;

interface Described { title: string; sub?: string; icon: ReactNode }

function describe(win: ShellWindow, doc: AppsDoc, view: AppView | undefined): Described {
  if (win.sceneId === 'app') {
    const app = doc.apps.find((a) => a.id === win.resourceId);
    const target = app?.targets.find((t) => t.id === view?.target) ?? app?.targets[0];
    return { title: app?.name ?? String(win.resourceId), sub: target?.label, icon: typeIcon(app?.type, 16) };
  }
  if (win.sceneId === 'repo') {
    const repo = doc.repos.find((r) => r.id === win.resourceId);
    return { title: repo?.name ?? String(win.resourceId), sub: 'repo app', icon: repo ? repoIcon(repo, 16) : typeIcon(null, 16) };
  }
  if (win.sceneId === 'fleet') return { title: 'Fleet', sub: 'every repo', icon: <IconFolder size={16} stroke={1.6} /> };
  return { title: 'Welcome', icon: <IconPlayerPlayFilled size={14} /> };
}

function Scene({ win, doc, view, onView, open }: {
  win: ShellWindow; doc: AppsDoc; view: AppView; onView: (v: AppView) => void; open: Open;
}) {
  if (win.sceneId === 'app') {
    const app = doc.apps.find((a) => a.id === win.resourceId);
    return app ? <AppPane app={app} doc={doc} view={view} onView={onView} fill /> : <Text className={c.panel} size="sm">The registry no longer declares this app.</Text>;
  }
  if (win.sceneId === 'repo') {
    const repo = doc.repos.find((r) => r.id === win.resourceId);
    return repo ? <RepoApp repo={repo} fill /> : <Text className={c.panel} size="sm">The registry no longer lists this repo.</Text>;
  }
  if (win.sceneId === 'fleet') return <FleetPanel doc={doc} open={open} />;
  return <WelcomePanel doc={doc} open={open} />;
}

interface Drag { px: number; py: number; x: number; y: number; w: number; h: number; mode: 'move' | 'resize' }

function WindowFrame({ win, focused, only, described, dispatch, surface, onDragging, children }: {
  win: ShellWindow; focused: boolean; only: boolean; described: Described; dispatch: (a: ShellAction) => void;
  surface: React.RefObject<HTMLDivElement | null>; onDragging: (on: boolean) => void; children: ReactNode;
}) {
  const drag = useRef<Drag | null>(null);
  const begin = (mode: Drag['mode']) => (e: ReactPointerEvent<HTMLElement>) => {
    if (e.button !== 0) return;
    if (mode === 'move' && ((e.target as HTMLElement).closest('button') || win.snapped === 'max')) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { px: e.clientX, py: e.clientY, x: win.position.xPct, y: win.position.yPct, w: win.size.wPct, h: win.size.hPct, mode };
    onDragging(true);
  };
  const move = (e: ReactPointerEvent<HTMLElement>) => {
    const d = drag.current;
    const rect = surface.current?.getBoundingClientRect();
    if (!d || !rect) return;
    const dx = ((e.clientX - d.px) / rect.width) * 100;
    const dy = ((e.clientY - d.py) / rect.height) * 100;
    if (d.mode === 'move') dispatch({ type: 'move', id: win.id, xPct: d.x + dx, yPct: d.y + dy });
    else dispatch({ type: 'resize', id: win.id, wPct: d.w + dx, hPct: d.h + dy });
  };
  const end = (e: ReactPointerEvent<HTMLElement>) => {
    const d = drag.current;
    drag.current = null;
    onDragging(false);
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
    const rect = surface.current?.getBoundingClientRect();
    if (!d || d.mode !== 'move' || !rect) return;
    if (Math.abs(e.clientX - d.px) + Math.abs(e.clientY - d.py) < 4) return; // a click on the title bar, not a drag
    // Dropped against an edge: the reducer's snap geometry takes over.
    if (e.clientY <= rect.top + 6) dispatch({ type: 'snap', id: win.id, edge: 'max' });
    else if (e.clientX <= rect.left + 10) dispatch({ type: 'snap', id: win.id, edge: 'left' });
    else if (e.clientX >= rect.right - 10) dispatch({ type: 'snap', id: win.id, edge: 'right' });
  };
  const toggleMax = () => dispatch({ type: 'snap', id: win.id, edge: win.snapped === 'max' ? null : 'max' });
  const vars = {
    '--x': win.position.xPct, '--y': win.position.yPct, '--w': win.size.wPct, '--h': win.size.hPct, '--z': win.zIndex,
  } as CSSProperties;

  return (
    <section className={c.window} style={vars} hidden={win.minimized} role="group" aria-label={`${described.title} window`}
      data-window-id={win.id} data-focus={focused || undefined} data-snapped={win.snapped ?? undefined}
      onPointerDownCapture={() => { if (!focused) dispatch({ type: 'focus', id: win.id }); }}>
      <header className={c.winHead} onPointerDown={begin('move')} onPointerMove={move} onPointerUp={end} onPointerCancel={end} onDoubleClick={toggleMax}>
        <span className={c.winIcon}>{described.icon}</span>
        <span className={c.winTitle}>{described.title}{described.sub ? <span className={c.winSub}> · {described.sub}</span> : null}</span>
        <button type="button" className={c.winBtn} onClick={() => dispatch({ type: 'minimize', id: win.id })} aria-label={`Minimize ${described.title}`}><IconMinus size={15} /></button>
        <button type="button" className={c.winBtn} onClick={toggleMax} aria-label={win.snapped === 'max' ? `Restore ${described.title}` : `Maximize ${described.title}`}>
          {win.snapped === 'max' ? <IconArrowsMinimize size={15} /> : <IconMaximize size={15} />}
        </button>
        {only ? null : (
          <button type="button" className={c.winBtn} onClick={() => dispatch({ type: 'close', id: win.id })} aria-label={`Close ${described.title}`}><IconX size={15} /></button>
        )}
      </header>
      <div className={c.winBody}>{children}</div>
      {win.snapped === 'max' ? null : (
        <div className={c.resize} onPointerDown={begin('resize')} onPointerMove={move} onPointerUp={end} onPointerCancel={end} aria-hidden />
      )}
    </section>
  );
}

// ------------------------------------------------------------------ desktop
function IconButton({ label, glyph, title, open: isOpen, onClick }: {
  label: string; glyph: ReactNode; title?: string; open?: boolean; onClick: (e: React.MouseEvent) => void;
}) {
  return (
    <button type="button" className={c.icon} title={title} data-open={isOpen || undefined} onClick={onClick}>
      <span className={c.glyph}>{glyph}</span>
      <span className={c.iconLabel}>{label}</span>
    </button>
  );
}

function DesktopShell({ doc }: { doc: AppsDoc }) {
  const [state, dispatch] = useReducer(reduce, doc, boot);
  const [views, setViews] = useState<Record<string, AppView>>({});
  const [dragging, setDragging] = useState(false);
  const [home, setHome] = useState(true);
  const [copied, setCopied] = useState(false);
  const [now, setNow] = useState(() => new Date());
  const surface = useRef<HTMLDivElement | null>(null);
  const viewport = useViewportSize();
  const width = viewport.width || window.innerWidth;
  const narrow = effectiveExperience(state, width) !== 'os';
  const framed = useMemo(() => doc.apps.filter((a) => a.embed === 'frame'), [doc]);
  // The dock: as many icon rows as fit between the menu bar and the taskbar,
  // and the columns that takes (the apps, plus Fleet and Console).
  const rows = Math.max(1, Math.floor(((viewport.height || window.innerHeight) - MENUBAR_PX - TASKBAR_PX - 24) / DOCK_ROW_PX));
  const dock = { '--rows': rows, '--cols': Math.ceil((framed.length + 2) / rows) } as CSSProperties;

  useEffect(() => { saveTab(state); }, [state]);
  useEffect(() => {
    const t = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(t);
  }, []);
  useEffect(() => {
    // A click inside a framed app never reaches this page; the page losing
    // focus to a frame is how the window under it learns it was chosen.
    const onBlur = () => window.setTimeout(() => {
      const el = document.activeElement;
      const id = el instanceof HTMLIFrameElement ? el.closest<HTMLElement>('[data-window-id]')?.dataset.windowId : undefined;
      if (id) dispatch({ type: 'focus', id });
    }, 0);
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === '\\') {
        e.preventDefault();
        dispatch({ type: 'cycle' });
      }
    };
    window.addEventListener('blur', onBlur);
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('blur', onBlur);
      window.removeEventListener('keydown', onKey);
    };
  }, []);

  const open: Open = (sceneId, resourceId, another = false) => {
    const existing = state.windows.some((w) => w.sceneId === sceneId && (w.resourceId ?? null) === resourceId);
    dispatch({ type: 'navigate', sceneId, resourceId, intent: existing && !another ? 'focus' : 'new' });
    setHome(false);
  };
  const isOpen = (sceneId: string, resourceId: string | null) =>
    state.windows.some((w) => w.sceneId === sceneId && (w.resourceId ?? null) === resourceId);
  const current = state.windows.find((w) => w.id === state.focusId) ?? state.windows[0];
  const describedOf = (w: ShellWindow) => describe(w, doc, views[contentKey(w)]);
  const scene = (w: ShellWindow) => (
    <Scene key={contentKey(w)} win={w} doc={doc} open={open} view={views[contentKey(w)] ?? {}}
      onView={(v) => setViews((all) => ({ ...all, [contentKey(w)]: v }))} />
  );
  const copyLink = () => {
    const url = new URL(window.location.href);
    url.searchParams.set(LAYOUT_PARAM, encodeParam(state));
    void navigator.clipboard?.writeText(url.href).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    });
  };

  const icons = (
    <>
      {framed.map((a: FleetApp) => (
        <IconButton key={a.id} label={a.name} glyph={typeIcon(a.type, 20)} title={`${a.description ?? a.name} — shift-click for a second window`}
          open={isOpen('app', a.id)} onClick={(e) => open('app', a.id, e.shiftKey)} />
      ))}
    </>
  );
  const system = (
    <>
      <IconButton label="Fleet" glyph={<IconFolder size={20} stroke={1.6} />} title="Every repo and the frontend component it has or is owed"
        open={isOpen('fleet', null)} onClick={() => open('fleet', null)} />
      <Link className={c.icon} to={to.overview()} title="The classic console: overview, projects, loops, jobs, settings">
        <span className={c.glyph}><IconTerminal2 size={20} stroke={1.6} /></span>
        <span className={c.iconLabel}>Console</span>
      </Link>
    </>
  );

  return (
    <div className={c.os} data-narrow={narrow || undefined}>
      <header className={c.menubar}>
        <div className={c.crumbs}>
          <span>bashOS</span><span>/</span><span>Fleet</span>
          {narrow && home ? null : <><span>/</span><strong>{describedOf(current).title}</strong></>}
        </div>
        <div className={c.menuRight}>
          <span className={`${c.pill} ${c.mode}`}>{hasConsole() ? 'console connected' : 'public snapshot'}</span>
          <Link className={c.pill} to={to.overview()}>classic console</Link>
          <ThemeToggle />
        </div>
      </header>

      {narrow ? (
        <div className={c.surface}>
          {home ? (
            <nav className={c.home} aria-label="Apps">{icons}{system}</nav>
          ) : (
            <section className={c.sheet} aria-label={`${describedOf(current).title} window`}>
              <header className={c.winHead}>
                <button type="button" className={c.winBtn} onClick={() => setHome(true)} aria-label="Home"><IconChevronLeft size={16} /></button>
                <span className={c.winIcon}>{describedOf(current).icon}</span>
                <span className={c.winTitle}>{describedOf(current).title}</span>
                {state.windows.length > 1 ? (
                  <button type="button" className={c.winBtn} onClick={() => { dispatch({ type: 'close', id: current.id }); setHome(true); }} aria-label={`Close ${describedOf(current).title}`}><IconX size={15} /></button>
                ) : null}
              </header>
              <div className={c.winBody}>{scene(current)}</div>
            </section>
          )}
        </div>
      ) : (
        <div className={c.surface}>
          <nav className={c.icons} style={dock} aria-label="Apps">{icons}{system}</nav>
          <div className={c.stage} ref={surface} data-dragging={dragging || undefined}>
            {state.windows.map((w) => (
              <WindowFrame key={w.id} win={w} focused={w.id === state.focusId && !w.minimized} only={state.windows.length === 1}
                described={describedOf(w)} dispatch={dispatch} surface={surface} onDragging={setDragging}>
                {scene(w)}
              </WindowFrame>
            ))}
          </div>
        </div>
      )}

      {narrow ? null : (
        <footer className={c.taskbar}>
          <button type="button" className={c.start} onClick={() => open('welcome', null)} title="Welcome"><IconPlayerPlayFilled size={12} /> bashOS</button>
          <div className={c.tasks} role="toolbar" aria-label="Open windows">
            {state.windows.map((w) => {
              const d = describedOf(w);
              const active = w.id === state.focusId && !w.minimized;
              return (
                <button key={w.id} type="button" className={c.task} data-active={active || undefined} data-minimized={w.minimized || undefined}
                  title={active ? `Minimize ${d.title}` : `Show ${d.title}`}
                  onClick={() => dispatch(active ? { type: 'minimize', id: w.id } : { type: 'restore', id: w.id })}>
                  {d.icon} {d.title}
                </button>
              );
            })}
          </div>
          <button type="button" className={c.tray} onClick={() => dispatch({ type: 'arrange', mode: 'tile' })} title="Tile the open windows" aria-label="Tile the open windows"><IconLayoutGrid size={15} /></button>
          <button type="button" className={c.tray} onClick={() => dispatch({ type: 'arrange', mode: 'cascade' })} title="Cascade the open windows" aria-label="Cascade the open windows"><IconStack2 size={15} /></button>
          <button type="button" className={c.tray} onClick={copyLink} title="Copy a link that reopens this desktop" aria-label="Copy a link that reopens this desktop"><IconLink size={15} />{copied ? ' copied' : null}</button>
          <span className={c.clock} title={`${state.windows.length} of ${MAX_WINDOWS} windows`}>{now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
        </footer>
      )}
    </div>
  );
}

export function Desktop() {
  const apps = useApps();
  useEffect(() => {
    document.title = 'Desktop · bashOS';
  }, []);
  return <Load q={apps} rows={8}>{(doc) => <DesktopShell doc={doc} />}</Load>;
}
