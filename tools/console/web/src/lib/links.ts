// Every place a thing can be opened, in one module, so a repo name, an
// operation or a job links the same way from every page (drill-down first,
// GitHub second).

const HUB = 'bamr87/bamr87';
const enc = encodeURIComponent;

export const to = {
  home: () => '/',
  projects: () => '/projects',
  project: (name: string, tab?: string) => `/projects/${enc(name)}${tab ? `?tab=${enc(tab)}` : ''}`,
  inbox: (kind?: string) => `/inbox${kind ? `?kind=${enc(kind)}` : ''}`,
  containers: () => '/containers',
  harnesses: (filter?: 'gaps') => `/harnesses${filter ? `?view=${filter}` : ''}`,
  health: () => '/harnesses/health',
  schedules: (repo?: string) => `/schedules${repo ? `?q=${enc(repo)}` : ''}`,
  loops: () => '/loops',
  loop: (id: string) => `/loops/${enc(id)}`,
  costs: () => '/costs',
  activity: () => '/activity',
  observe: (pane: 'logs' | 'metrics' | 'traces' | 'lines' | 'index') => `/observe/${pane}`,
  content: () => '/content',
  site: (name: string) => `/content/${enc(name)}`,
  jobs: () => '/jobs',
  job: (id: string) => `/jobs/${enc(id)}`,
  ops: () => '/ops',
  op: (id: string, params?: Record<string, unknown>) =>
    `/ops/${enc(id)}${params && Object.keys(params).length ? `?params=${enc(JSON.stringify(params))}` : ''}`,
  terminal: () => '/terminal',
  config: (section?: string) => `/config${section ? `/${enc(section)}` : ''}`,
  auth: () => '/auth',
  github: () => '/github',
  ghRepo: (nwo: string, tab?: string) => `/github/${nwo}${tab ? `?tab=${enc(tab)}` : ''}`,
};

export const gh = {
  repo: (nwo: string) => `https://github.com/${nwo}`,
  hubFile: (path: string) => `https://github.com/${HUB}/blob/main/${path}`,
  workflow: (nwo: string, path: string) => `https://github.com/${nwo}/blob/HEAD/${path}`,
  workflowRuns: (nwo: string, file: string) => `https://github.com/${nwo}/actions/workflows/${file.replace(/^.*\//, '')}`,
  hubWorkflowRuns: (wf: string) => `https://github.com/${HUB}/actions/workflows/${wf}.yml`,
};

/** A source file in _data/ → the page that renders it and the operation that refreshes it. */
export const SOURCE_HOME: Record<string, { page: string; label: string; op?: string }> = {
  harness_registry: { page: '/harnesses', label: 'Harness inventory', op: 'harnesses-offline' },
  harness_health: { page: '/harnesses/health', label: 'Harness health', op: 'harness' },
  fleet_triage: { page: '/inbox', label: 'Inbox', op: 'triage' },
  issue_pipeline: { page: '/loops/issue_pipeline', label: 'Issue pipeline', op: 'issues' },
  token_rotation: { page: '/auth', label: 'Credentials', op: 'secrets-plan' },
  actions_usage: { page: '/costs', label: 'Costs', op: 'actions' },
  ai_usage: { page: '/costs', label: 'Costs', op: 'ai-usage' },
  engagements: { page: '/projects', label: 'Projects' },
};
