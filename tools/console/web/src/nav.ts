// The console's information architecture: eight sections, each a group of
// pages. keys v1's 1–8 jump to a section, ] / [ step through the pages in this
// order — the same keys that move between tabs in the terminal dash.
import {
  IconActivity, IconAppWindow, IconBox, IconBrandGithub, IconBrandDocker, IconCalendarTime, IconChartBar, IconCoin, IconFileText,
  IconHeartbeat, IconHome, IconInbox, IconKey, IconListDetails, IconLogs, IconPlayerPlay, IconRepeat, IconRoute,
  IconSearch, IconSettings, IconTerminal2, IconTopologyStar3, type Icon,
} from '@tabler/icons-react';

export interface NavItem {
  label: string;
  to: string;
  icon: Icon;
  hint?: string;
  /** Also active for these path prefixes (drill-downs). */
  match?: string[];
  exact?: boolean;
}

export interface NavSection {
  label: string;
  items: NavItem[];
}

export const NAV: NavSection[] = [
  { label: 'Overview', items: [{ label: 'Overview', to: '/', icon: IconHome, exact: true, hint: 'attention, KPIs, signal freshness' }] },
  {
    label: 'Fleet',
    items: [
      { label: 'Projects', to: '/projects', icon: IconAppWindow, hint: 'every registry project — the TUI’s Apps view' },
      { label: 'Inbox', to: '/inbox', icon: IconInbox, hint: 'flagged issues, PRs and failing workflows' },
      { label: 'GitHub', to: '/github', icon: IconBrandGithub, hint: 'connect through the OAuth App; manage issues, runs and workflows' },
      { label: 'Containers', to: '/containers', icon: IconBrandDocker, hint: 'containers on every Docker host' },
    ],
  },
  {
    label: 'Harnesses',
    items: [
      { label: 'Inventory', to: '/harnesses', icon: IconTopologyStar3, exact: true, hint: 'per-repo AI harness deployment matrix' },
      { label: 'Health', to: '/harnesses/health', icon: IconHeartbeat, hint: 'trip wires and the six-layer scorecard' },
      { label: 'Schedules', to: '/schedules', icon: IconCalendarTime, hint: 'crons, caps and collisions' },
      { label: 'Loops', to: '/loops', icon: IconRepeat, hint: 'the control-plane loops' },
    ],
  },
  {
    label: 'Spend',
    items: [
      { label: 'Costs', to: '/costs', icon: IconCoin, hint: 'Claude spend and Actions minutes vs budget' },
      { label: 'Agent activity', to: '/activity', icon: IconActivity, hint: 'local sessions + CI agent runs, from the lake' },
    ],
  },
  {
    label: 'Observe',
    items: [
      { label: 'Traces', to: '/observe/traces', icon: IconRoute, hint: 'the data lake and Phoenix' },
      { label: 'Lines', to: '/observe/lines', icon: IconListDetails, hint: 'every workflow with provenance and kill switch' },
      { label: 'Logs', to: '/observe/logs', icon: IconLogs, hint: 'Kibana over the log plane' },
      { label: 'Metrics', to: '/observe/metrics', icon: IconChartBar, hint: 'Grafana' },
      { label: 'Code index', to: '/observe/index', icon: IconSearch, hint: 'semantic search over the worktree' },
    ],
  },
  { label: 'Content', items: [{ label: 'Content sites', to: '/content', icon: IconFileText, hint: 'the content atlas + editorial plan' }] },
  {
    label: 'Operate',
    items: [
      { label: 'Jobs', to: '/jobs', icon: IconBox, hint: 'every job, live logs' },
      { label: 'Operations', to: '/ops', icon: IconPlayerPlay, hint: 'the allowlisted operations' },
      { label: 'Terminal', to: '/terminal', icon: IconTerminal2, hint: 'the terminal dash, in the page' },
    ],
  },
  {
    label: 'Settings',
    items: [
      { label: 'Config', to: '/config', icon: IconSettings, hint: '_data/fleet.yml, block by block' },
      { label: 'Credentials', to: '/auth', icon: IconKey, hint: 'tokens, gh login, rotation' },
    ],
  },
];

export const FLAT: NavItem[] = NAV.flatMap((s) => s.items);

export function isActive(item: NavItem, path: string): boolean {
  if (item.exact) return path === item.to || path === `${item.to}/`;
  return path === item.to || path.startsWith(`${item.to}/`) || (item.match ?? []).some((m) => path.startsWith(m));
}

export function activeIndex(path: string): number {
  // Longest match wins, so /harnesses/health is Health, not Inventory.
  let best = -1;
  let len = -1;
  FLAT.forEach((it, i) => {
    if (isActive(it, path) && it.to.length > len) {
      best = i;
      len = it.to.length;
    }
  });
  return best;
}
