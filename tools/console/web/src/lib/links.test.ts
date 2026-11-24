// links.ts is every internal route and GitHub link in one place. What is held
// here: a builder returns a router path (React Router adds the base, so the
// path never carries it), anything a caller passes survives the URL intact,
// and a default is left out of the query so the same view has one address.
import { beforeEach, describe, expect, it, vi } from 'vitest';

type Links = typeof import('./links');

/** links.ts as one build sees it: the front door and the base are build settings. */
async function load(frontDoor = '', base = '/'): Promise<Links> {
  vi.stubEnv('VITE_FRONT_DOOR', frontDoor);
  vi.stubEnv('BASE_URL', base);
  vi.resetModules();
  return import('./links');
}

/** A built link, taken apart the way the router will read it. */
function parts(href: string) {
  const url = new URL(href, 'http://console.test');
  return {
    path: url.pathname,
    segments: url.pathname.split('/').slice(1).map(decodeURIComponent),
    query: Object.fromEntries(url.searchParams),
  };
}

let to: Links['to'];
let gh: Links['gh'];
let onDesktop: Links['onDesktop'];
let SOURCE_HOME: Links['SOURCE_HOME'];

beforeEach(async () => {
  ({ to, gh, onDesktop, SOURCE_HOME } = await load());
});

describe('to: plain pages', () => {
  it('each has one fixed path', () => {
    expect(to.overview()).toBe('/overview');
    expect(to.blog()).toBe('/blog');
    expect(to.features()).toBe('/features');
    expect(to.engagements()).toBe('/engagements');
    expect(to.toolbox()).toBe('/toolbox');
    expect(to.connect()).toBe('/connect');
    expect(to.projects()).toBe('/projects');
    expect(to.apps()).toBe('/apps');
    expect(to.prs()).toBe('/prs');
    expect(to.containers()).toBe('/containers');
    expect(to.nodes()).toBe('/nodes');
    expect(to.health()).toBe('/harnesses/health');
    expect(to.loops()).toBe('/loops');
    expect(to.costs()).toBe('/costs');
    expect(to.activity()).toBe('/activity');
    expect(to.content()).toBe('/content');
    expect(to.voices()).toBe('/voices');
    expect(to.jobs()).toBe('/jobs');
    expect(to.ops()).toBe('/ops');
    expect(to.terminal()).toBe('/terminal');
    expect(to.auth()).toBe('/auth');
    expect(to.github()).toBe('/github');
  });

  it('name each observability pane', () => {
    expect(to.observe('logs')).toBe('/observe/logs');
    expect(to.observe('index')).toBe('/observe/index');
  });
});

describe('to: a name in the path', () => {
  it('puts the name after its section', () => {
    expect(to.page('about')).toBe('/about');
    expect(to.post('hello-world')).toBe('/blog/hello-world');
    expect(to.project('zer0-mistakes')).toBe('/projects/zer0-mistakes');
    expect(to.site('lifehacker')).toBe('/content/lifehacker');
    expect(to.job('j-20261107-1')).toBe('/jobs/j-20261107-1');
    expect(to.loop('issue_pipeline')).toBe('/loops/issue_pipeline');
    expect(to.workflow('fleet-pulse')).toBe('/workflows/fleet-pulse');
    expect(to.config('budget')).toBe('/config/budget');
    expect(to.config()).toBe('/config');
  });

  it.each([
    ['page', (v: string) => to.page(v), 0],
    ['post', (v: string) => to.post(v), 1],
    ['project', (v: string) => to.project(v), 1],
    ['site', (v: string) => to.site(v), 1],
    ['job', (v: string) => to.job(v), 1],
    ['loop', (v: string) => to.loop(v), 1],
    ['workflow', (v: string) => to.workflow(v), 1],
    ['op', (v: string) => to.op(v), 1],
    ['app', (v: string) => to.app(v), 1],
    ['config', (v: string) => to.config(v), 1],
  ] as const)('%s keeps a name with a slash, a space, ? and # as one path segment', (_name, build, index) => {
    const name = 'a b/c?d#e&f';
    const got = parts(build(name));
    expect(got.segments).toHaveLength(index + 1);
    expect(got.segments[index]).toBe(name);
    expect(got.query).toEqual({});
  });

  it('keeps the folders of an action id as path segments, each one encoded', () => {
    expect(to.action('utilities/publish-data')).toBe('/workflows/actions/utilities/publish-data');
    expect(parts(to.action('ai tools/claude#run')).segments).toEqual(['workflows', 'actions', 'ai tools', 'claude#run']);
  });

  it('keeps owner/name of a GitHub repo as two segments', () => {
    expect(to.ghRepo('bamr87/scripts')).toBe('/github/bamr87/scripts');
    expect(to.ghRepo('bamr87/scripts', 'issues')).toBe('/github/bamr87/scripts?tab=issues');
  });
});

describe('to: one optional filter', () => {
  it('has no query without it', () => {
    expect(to.portfolio()).toBe('/portfolio');
    expect(to.roadmap()).toBe('/roadmap');
    expect(to.sprints()).toBe('/sprints');
    expect(to.inbox()).toBe('/inbox');
    expect(to.harnesses()).toBe('/harnesses');
    expect(to.schedules()).toBe('/schedules');
    expect(to.assist()).toBe('/assist');
    expect(to.project('x')).toBe('/projects/x');
  });

  it('names it in the query', () => {
    expect(to.portfolio('tools')).toBe('/portfolio?category=tools');
    expect(to.roadmap('zer0-mistakes')).toBe('/roadmap?q=zer0-mistakes');
    expect(to.sprints('2026-w47')).toBe('/sprints?sprint=2026-w47');
    expect(to.inbox('pr')).toBe('/inbox?kind=pr');
    expect(to.harnesses('gaps')).toBe('/harnesses?view=gaps');
    expect(to.project('x', 'health')).toBe('/projects/x?tab=health');
  });

  it('carries any text through the query intact', () => {
    expect(parts(to.portfolio('Web & Sites')).query).toEqual({ category: 'Web & Sites' });
    expect(parts(to.schedules('bamr87/zer0-mistakes')).query).toEqual({ q: 'bamr87/zer0-mistakes' });
    expect(parts(to.assist('why is CI red? #12 & co')).query).toEqual({ q: 'why is CI red? #12 & co' });
    expect(parts(to.assist('why is CI red? #12 & co')).path).toBe('/assist');
  });
});

describe('to.work', () => {
  it('is the board with no filter', () => {
    expect(to.work()).toBe('/work');
    expect(to.work({})).toBe('/work');
  });

  it('leaves the default view out, so the board has one address', () => {
    expect(to.work({ view: 'board' })).toBe('/work');
    expect(to.work({ view: 'flow' })).toBe('/work?view=flow');
    expect(to.work({ view: 'priority' })).toBe('/work?view=priority');
  });

  it('carries the repo, the kind and the open item', () => {
    const got = parts(to.work({ view: 'priority', repo: 'bamr87/zer0-mistakes', kind: 'issue', item: 'issue:bamr87/zer0-mistakes#12' }));
    expect(got.path).toBe('/work');
    expect(got.query).toEqual({ view: 'priority', repo: 'bamr87/zer0-mistakes', kind: 'issue', item: 'issue:bamr87/zer0-mistakes#12' });
  });

  it('leaves out what is empty', () => {
    expect(to.work({ repo: '', kind: '', item: '' })).toBe('/work');
  });
});

describe('to.app', () => {
  it('opens an app on its live target by default, with no query', () => {
    expect(to.app('zer0-mistakes')).toBe('/apps/zer0-mistakes');
    expect(to.app('zer0-mistakes', { target: 'live' })).toBe('/apps/zer0-mistakes');
  });

  it('names another target, a device and a path inside the app', () => {
    const got = parts(to.app('zer0-mistakes', { target: 'local', device: 'phone', path: '/docs/a b?x=1' }));
    expect(got.path).toBe('/apps/zer0-mistakes');
    expect(got.query).toEqual({ target: 'local', device: 'phone', path: '/docs/a b?x=1' });
  });
});

describe('to.ghProjects', () => {
  it('leaves the default table view out', () => {
    expect(to.ghProjects()).toBe('/gh-projects');
    expect(to.ghProjects({ view: 'table' })).toBe('/gh-projects');
  });

  it('names a project and the board view', () => {
    expect(parts(to.ghProjects({ project: 'PVT_kwHOA', view: 'board' })).query).toEqual({ project: 'PVT_kwHOA', view: 'board' });
    expect(to.ghProjects({ project: 'PVT_kwHOA' })).toBe('/gh-projects?project=PVT_kwHOA');
  });
});

describe('to.workflows and to.refine', () => {
  it('have no query when nothing is asked', () => {
    expect(to.workflows()).toBe('/workflows');
    expect(to.refine()).toBe('/refine');
  });

  it('carry a tab, a search, or both', () => {
    expect(to.workflows('failures')).toBe('/workflows?tab=failures');
    expect(parts(to.workflows(undefined, 'fleet pulse')).query).toEqual({ q: 'fleet pulse' });
    expect(parts(to.workflows('lint', 'cron')).query).toEqual({ tab: 'lint', q: 'cron' });
  });

  it('carry the refinement page’s own parameters beside the tab', () => {
    expect(to.refine('library')).toBe('/refine?tab=library');
    expect(parts(to.refine('review', { run: 'loop run 7' })).query).toEqual({ run: 'loop run 7', tab: 'review' });
    expect(parts(to.refine(undefined, { run: 'r7' })).query).toEqual({ run: 'r7' });
  });
});

describe('to.op', () => {
  it('is the operation page with no parameters', () => {
    expect(to.op('triage')).toBe('/ops/triage');
    expect(to.op('triage', {})).toBe('/ops/triage');
  });

  it('carries prefilled parameters as JSON the page can read back', () => {
    const params = { kit: 'schema', repos: ['a', 'b c'], dry_run: true, note: 'x & y = "z"' };
    const got = parts(to.op('fanout', params));
    expect(got.path).toBe('/ops/fanout');
    expect(Object.keys(got.query)).toEqual(['params']);
    expect(JSON.parse(got.query.params)).toEqual(params);
  });
});

describe('the front door', () => {
  it('is the profile Home by default: Home at /, the desktop at /desktop', () => {
    expect(to.home()).toBe('/');
    expect(to.desktop()).toBe('/desktop');
  });

  it('is the profile Home for any setting but `desktop`', async () => {
    const other = await load('home');
    expect(other.to.home()).toBe('/');
    const unknown = await load('Desktop ');
    expect(unknown.to.home()).toBe('/');
    expect(unknown.to.desktop()).toBe('/desktop');
  });

  it('trades places in a desktop-first build: the desktop at /, Home at /home', async () => {
    const site = await load('desktop');
    expect(site.to.desktop()).toBe('/');
    expect(site.to.home()).toBe('/home');
  });

  it('knows the desktop at /desktop and under it in every build', async () => {
    for (const links of [await load(), await load('desktop')]) {
      expect(links.onDesktop('/desktop')).toBe(true);
      expect(links.onDesktop('/desktop/window/1')).toBe(true);
      expect(links.onDesktop('/desktops')).toBe(false);
      expect(links.onDesktop('/projects')).toBe(false);
      expect(links.onDesktop('/home')).toBe(false);
    }
  });

  it('counts / as the desktop only where the desktop is the front door', async () => {
    expect(onDesktop('/')).toBe(false);
    expect((await load('desktop')).onDesktop('/')).toBe(true);
  });
});

describe('under a base path', () => {
  it('builds the same router paths: the base is the router’s to add', async () => {
    const pages = await load('', '/bamr87/');
    expect(pages.to.home()).toBe('/');
    expect(pages.to.projects()).toBe('/projects');
    expect(pages.to.project('scripts', 'health')).toBe('/projects/scripts?tab=health');
    expect(pages.to.work({ view: 'flow' })).toBe('/work?view=flow');
  });
});

describe('gh', () => {
  it('links a repo', () => {
    expect(gh.repo('bamr87/scripts')).toBe('https://github.com/bamr87/scripts');
  });

  it('links a hub file on main, at a line when one is known', () => {
    expect(gh.hubFile('_data/fleet.yml')).toBe('https://github.com/bamr87/bamr87/blob/main/_data/fleet.yml');
    expect(gh.hubFile('_data/fleet.yml', 120)).toBe('https://github.com/bamr87/bamr87/blob/main/_data/fleet.yml#L120');
    expect(gh.hubFile('_data/fleet.yml', null)).toBe('https://github.com/bamr87/bamr87/blob/main/_data/fleet.yml');
    expect(gh.hubFile('_data/fleet.yml', 0)).toBe('https://github.com/bamr87/bamr87/blob/main/_data/fleet.yml');
  });

  it('links a workflow file on the repo’s default branch', () => {
    expect(gh.workflow('bamr87/scripts', '.github/workflows/ci.yml')).toBe('https://github.com/bamr87/scripts/blob/HEAD/.github/workflows/ci.yml');
  });

  it('links a workflow’s runs by file name, whatever path it was given', () => {
    expect(gh.workflowRuns('bamr87/scripts', '.github/workflows/ci.yml')).toBe('https://github.com/bamr87/scripts/actions/workflows/ci.yml');
    expect(gh.workflowRuns('bamr87/scripts', 'ci.yml')).toBe('https://github.com/bamr87/scripts/actions/workflows/ci.yml');
  });

  it('links a hub workflow’s runs by its id', () => {
    expect(gh.hubWorkflowRuns('fleet-pulse')).toBe('https://github.com/bamr87/bamr87/actions/workflows/fleet-pulse.yml');
  });
});

describe('SOURCE_HOME', () => {
  it('names an in-app page and a label for every source', () => {
    const entries = Object.entries(SOURCE_HOME);
    expect(entries.length).toBeGreaterThan(0);
    for (const [source, home] of entries) {
      expect(home.page, source).toMatch(/^\/(?!\/)/);
      expect(home.label, source).not.toBe('');
      if (home.op !== undefined) expect(home.op, source).toMatch(/^[a-z][a-z0-9-]*$/);
    }
  });

  it('sends each source to the page its builder names', () => {
    expect(SOURCE_HOME.harness_registry.page).toBe(to.harnesses());
    expect(SOURCE_HOME.harness_health.page).toBe(to.health());
    expect(SOURCE_HOME.fleet_triage.page).toBe(to.inbox());
    expect(SOURCE_HOME.issue_pipeline.page).toBe(to.loop('issue_pipeline'));
    expect(SOURCE_HOME.token_rotation.page).toBe(to.auth());
    expect(SOURCE_HOME.actions_usage.page).toBe(to.costs());
    expect(SOURCE_HOME.ai_usage.page).toBe(to.costs());
  });

  it('sends every source to a page the navigation has', async () => {
    const nav = await import('../nav');
    for (const [source, home] of Object.entries(SOURCE_HOME)) {
      expect(nav.activeIndex(home.page), `${source} → ${home.page}`).toBeGreaterThanOrEqual(0);
    }
  });
});
