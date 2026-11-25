// Shapes of the console API documents (tools/console/core.py and
// tools/fleetcore/views.py). Every field is optional where the source file can
// be absent: the console renders a degraded page rather than failing.

import type { SubscriptionModel } from '../components/SubscriptionPanel';

export type Level = 'red' | 'amber' | 'green';
export type Dict<T = unknown> = Record<string, T>;

export interface SourceMeta {
  present: boolean;
  generated_at?: string | null;
  age_days?: number | null;
}

export interface Attention {
  severity: number;
  kind: string;
  summary: string;
  action: string;
  repo?: string | null;
  /** On a `standard-gap` finding: the lever that rebuilds the group. */
  lever?: string | null;
}

/** A harness's verdict against the harness standard (fleet.yml `harnesses.standard`). */
export interface HarnessVerdict {
  conformant: boolean;
  met: number;
  of: number;
  missing: string[];
}

export interface HarnessWorkflow {
  path: string;
  kind: string;
  /** `ci:<repo>:<workflow stem>`, the id _data/agents.yml gives the same workflow. */
  id?: string;
  workflow?: string | null;
  triggers?: string[];
  crons?: string[];
  /** How the workflow reaches a model; null on a scan from before routes were read. */
  route?: string | null;
  model?: string | null;
  model_source?: string | null;
  max_turns?: number | null;
  max_budget_usd?: number | null;
  auth?: string | null;
  switch?: string | null;
  kit?: string | null;
  kit_status?: string | null;
  /** Byte-identical to a shape the kit seeded, so the fan-out may replace it. */
  kit_pristine?: boolean | null;
  factory?: { blueprint?: string | null; hash?: string | null } | null;
  standard?: HarnessVerdict | null;
  lever?: string | null;
  cost_usd_window?: number | null;
  runs_window?: number | null;
  last_conclusion?: string | null;
}

export interface HarnessRepo {
  repo: string;
  nwo: string;
  category?: string;
  status?: string;
  external?: boolean;
  archived?: boolean;
  manifest?: boolean;
  factory?: boolean;
  agent_context?: string | null;
  oauth_secret?: string | null;
  workflows_total?: number;
  workflows_listed?: number;
  workflows_truncated?: boolean;
  harnesses?: HarnessWorkflow[];
  ai_usage?: { runs?: number; cost_usd?: number | null; minutes?: number | null };
  deployable?: boolean;
  est_scheduled_ai_per_day?: number | null;
  coverage?: { exempt?: boolean; ok?: boolean; missing?: string[] };
}

export interface ScheduleEntry {
  repo: string;
  workflow: string;
  path?: string;
  cron: string;
  human: string;
  est_per_day?: number | null;
  ai?: boolean;
}

export interface Trend {
  status?: string;
  window_total?: number | null;
  daily_avg?: number | null;
  last7?: number | null;
  prior7?: number | null;
  wow_delta_pct?: number | null;
  projected_monthly?: number | null;
  budget_monthly?: number | null;
  /** Claude spend: how much of the window is measured vs estimated. */
  measured_total?: number | null;
  estimated_total?: number | null;
  estimated_share_pct?: number | null;
  cost_basis?: string | null;
  /** Actions minutes: the billing meter's own month-to-date and last month. */
  source?: string | null;
  billed_this_month?: number | null;
  billed_previous_month?: number | null;
  mom_delta_pct?: number | null;
}

/** One day of the registry file's git history (core.registry_history): the Overview's trends. */
export interface HistoryPoint {
  at: string;
  commit: string;
  attention?: number | null;
  harnesses_graded?: number | null;
  harnesses_conformant?: number | null;
  baseline_ok?: number | null;
  ai_projected_monthly?: number | null;
  actions_projected_monthly?: number | null;
}

/** The decision index's counts (/api/decisions?limit=0): what waits on the maintainer, by kind. */
export interface DecisionsDoc {
  status: string;
  complete?: boolean;
  source?: string;
  age_s?: number | null;
  counts: Dict<number>;
  total: number;
  warnings?: string[];
}

export interface Throughput {
  est_scheduled_ai_per_day?: number | null;
  observed_ai_runs_per_day?: number | null;
  cap_fleet?: number | null;
  cap_per_repo?: number | null;
  cap_per_utc_hour?: number | null;
  repos_over_cap?: { repo: string; est_per_day: number }[];
  /** One per UTC hour where more AI crons than the cap can fire on ONE day.
   *  `utc_hour` names the hour bucket ("06:00" is 06:00–06:59), `count` and
   *  `entries` are the worst day's, `days` the weekdays over the cap, and
   *  `same_minute` the exact minutes two or more of the entries share. */
  hour_collisions?: {
    utc_hour: string; count: number; entries: string[];
    days?: string[]; same_minute?: { at: string; count: number }[];
  }[];
}

export interface HarnessControl {
  title: string;
  rule?: string;
  applies?: string[];
}

export interface HarnessStandard {
  version?: number;
  allowed_models?: string[];
  routes?: Dict<{ standard?: boolean; title?: string }>;
  controls?: Dict<HarnessControl>;
}

/** The index over every live harness: counts by kind, route and lever. */
export interface HarnessCatalog {
  harnesses?: number;
  graded?: number;
  conformant?: number;
  /** Harnesses in retired projects (lever: retire). */
  retired?: number;
  /** …of which GitHub has archived the repo, so they cannot run. */
  dormant?: number;
  by_kind?: Dict<{ harnesses: number; conformant: number }>;
  by_route?: Dict<number>;
  by_lever?: Dict<number>;
  missing_by_control?: Dict<number>;
  levers?: Dict<{ title: string; action: string }>;
}

export interface HarnessRegistry {
  generated_at?: string;
  scan?: { mode?: string; scanned_at?: string | null };
  contract?: { kit?: string; kit_version?: string; baseline?: Dict<boolean>; exempt?: string[]; standard?: HarnessStandard };
  totals?: Dict<number>;
  catalog?: HarnessCatalog;
  trends?: Dict<Trend>;
  throughput?: Throughput;
  attention?: Attention[];
  schedule?: ScheduleEntry[];
  repos?: HarnessRepo[];
}

export interface TripWire {
  id: string;
  tripped: boolean;
  summary: string;
}

export interface ScoreMetric {
  value: number | null;
  direction?: string;
  threshold?: number;
  status?: string;
}

/** One agent step of a loop that the JEV loop runner can run on this machine (a step spec under tools/jev/steps/ with a `local:` block). */
export interface AgentStep {
  id: string;
  loop: string;
  step: string;
  call_site: string;
  spec: string;
  adapter: string;
  model: string;
  max_turns: number;
  cap_usd: number;
  /** Always "API-equivalent (estimate)": a throughput ceiling under OAuth, not an invoice. */
  cost_label: string;
  switch?: { config: string; variable: string; default: boolean | string | null; config_value?: unknown } | null;
  publish_tier?: string | null;
  on_budget_hit?: string;
  /** whether the step's filer files under apply today (spec.PUBLISH_CAN_APPLY); false = apply is refused, naming #488 */
  can_apply?: boolean;
}

export interface Loop {
  id: string;
  title: string;
  workflow: string;
  doc: string;
  outputs: string[];
  local_ops: string[];
  /** The loop's agent steps that also run locally (`loop-run`). */
  agent_steps: AgentStep[];
  cron?: string | null;
  cron_human: string;
  freshest_output_days?: number | null;
  stalest_output_days?: number | null;
  missing_outputs: string[];
}

export interface StateDoc {
  generated_at: string;
  repo_root: string;
  sources: Dict<SourceMeta>;
  contract: { hub?: Dict<unknown>; harnesses?: Dict<unknown>; schedule?: Dict<string> };
  tokens: { name: string; scope: string; required: boolean; deprecated: boolean; used_by: string[] }[];
  registry: {
    count: number;
    projects: { name: string; category?: string; status?: string; submodule: boolean; repo_url?: string; auto_evolve: boolean }[];
  };
  harnesses: HarnessRegistry;
  health: { generated_at?: string; scorecard?: Dict<ScoreMetric>; trip_wires?: TripWire[]; note?: string };
  /** `inbox` is the top of the list; `inbox_total` counts all of it. */
  triage: { generated_at?: string; repos_scanned?: number | null; totals: Dict<number>; inbox: Dict<unknown>[]; inbox_total?: number };
  pipeline: { generated_at?: string; totals: Dict<unknown> };
  /** The registry file's git history, one point per committed day, oldest first; `source` is git or none. */
  history?: { source: string; points: HistoryPoint[]; days?: number; note?: string; reason?: string };
  rotation: {
    generated_at?: string;
    tokens: { name: string; scope?: string; oldest_age_days?: number; max_age_days?: number; counts?: Dict<number> }[];
  };
  usage: {
    actions: { window_days?: number; by_day?: { date: string; runs?: number; total_min?: number }[] };
    ai: { window_days?: number; by_day?: { day: string; runs?: number; cost_usd?: number }[] };
  };
  subscription?: SubscriptionModel;
  loops: Loop[];
  git: { available?: boolean; branch?: string; head?: string; dirty_count?: number };
}

export interface Capabilities {
  tools: Dict<boolean>;
  gh_authenticated: boolean | null;
  env_tokens: Dict<boolean>;
  config_editing: boolean;
  auth_writes: boolean;
  console_token_required: boolean;
  python: string;
  lake_present: boolean;
  otel_exporter: boolean;
  phoenix: { collector: string; ui: string };
}

export interface Op {
  id: string;
  title: string;
  group: string;
  desc: string;
  needs_token: boolean;
  params: string[];
  remote_write: boolean;
  /** What the confirm gate guards: a GitHub write (the default for a remote op) or Claude spend. */
  confirm?: 'write' | 'spend' | null;
  /** Ops sharing this key never run at once (e.g. every writer of the lake); `loop` = one run per loop. */
  exclusive?: string | null;
  /** Why this op cannot run in this console process at all (e.g. no Docker, no claude CLI), or null. */
  unavailable?: string | null;
  /** loop-run only: the agent steps the form offers. */
  agent_steps?: AgentStep[];
  /** A parameter with a fixed set of values (pm's view, conflicts' action): the form offers a select. */
  choices?: Record<string, string[]>;
}

export interface Job {
  id: string;
  op: string;
  title: string;
  argv: string[];
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | string;
  remote_write?: boolean;
  params?: Dict<unknown>;
  created?: string | null;
  started?: string | null;
  finished?: string | null;
  exit_code?: number | null;
  /** The operation's group: observe, plan, verify, lake, content, deploy. */
  group?: string | null;
  /** What its confirm guarded: a GitHub write or Claude spend. */
  confirm?: 'write' | 'spend' | null;
  /** The key it holds while queued or running (`lake`, `loop:<loop>`), or null. */
  exclusive?: string | null;
  // Derived each time the console reads the job (HUB-064, tools/console/docs/job-status.md);
  // absent on the published page, whose jobs are workflow runs read from GitHub.
  /** queued, running, stalled (running, its log quiet past stall_s), done or failed (the exact outcome stays in status). */
  state?: 'queued' | 'running' | 'stalled' | 'done' | 'failed' | string;
  /** Seconds since the job was sent. */
  age_s?: number | null;
  /** Seconds since its log last grew; null once it finished. */
  idle_s?: number | null;
  /** Seconds without log growth before a running job of this op reads as stalled. */
  stall_s?: number | null;
  /** Why it may be slow, each a code and a sentence. */
  diagnostics?: JobDiagnostic[];
}

/** One reason a job may be slow: queue_wait, collector_lag, long_step or no_heartbeat. */
export interface JobDiagnostic {
  code: 'queue_wait' | 'collector_lag' | 'long_step' | 'no_heartbeat' | string;
  detail: string;
}

/** One item of a loop-run job (tools/fleetcore/loopjob.py). */
export interface LoopJobItem {
  key: string;
  status: string;
  decision?: string | null;
  reason: string;
  outcome?: string | null;
  cost_usd?: number | null;
  cost_source?: string | null;
  turns?: number | null;
  flags: string[];
  urls: string[];
  context?: string;
}

/** The structured view of a loop-run job's log, parsed once on the server. */
export interface LoopJob {
  schema: string;
  record: boolean;
  run_id?: string | null;
  status?: string | null;
  exit_code?: number | null;
  mode?: string | null;
  loop?: string | null;
  step?: string | null;
  target?: string | null;
  model?: string | null;
  max_turns?: number | null;
  cap_usd?: number | null;
  spent_usd?: number | null;
  estimated_usd?: number | null;
  cost_label: string;
  attempts?: number | null;
  published?: number | null;
  usage_limited?: boolean | null;
  finished?: string | null;
  items: LoopJobItem[];
  run_dir?: string | null;
  notes: string[];
}

/** One line of an assistant session's condensed tee (core.assist_activity): a tool call, something it said, a denial. */
export interface AssistActivity {
  kind: 'tool' | 'said' | 'denied';
  name: string;
  detail: string;
}

/** The `assist` job's structured view (core.assist_job_fields). */
export interface AssistJob {
  schema: string;
  question: string;
  context: string;
  answer: string | null;
  turns: number | null;
  cost_usd: number | null;
  cost_source: string | null;
  cost_label: string;
  models: string[];
  outcome: string | null;
  subtype: string | null;
  /** The conversation this message belongs to (the docked assistant sends it back with the next one). */
  conversation: string | null;
  /** True when the person's open page was attached to the session. */
  page: boolean;
  /** What the session did so far, newest last. */
  activity: AssistActivity[];
}

export interface JobTail {
  job: Job;
  text: string;
  offset: number;
  done: boolean;
  /** Present on a loop-run job: its parsed fields. */
  loop?: LoopJob;
  /** The assist job's question and answer, once the session ended. */
  assist?: AssistJob;
}

/** One place a frontend runs: the deployed site, or a service of its local dev stack. */
export interface AppTarget {
  id: string;
  kind: 'live' | 'local';
  label: string;
  url: string;
  service?: string;
  port?: number;
  band?: string;
  /** The command that starts a local target's stack (a devenv-hosted site: the `docker compose exec` that serves it). */
  start?: string | null;
  /** The project a local target belongs to: what `dev-up` and `dev-down` take, for a compose-hosted one. */
  project?: string;
  /** Where a local target runs: its own compose stack (the console can start it), or inside the hub's devenv container (it cannot). */
  host?: 'compose' | 'devenv';
}

/** A registry frontend as the launcher lists it (fleetcore.apps, fleet-launcher/v1). */
export interface FleetApp {
  id: string;
  name: string;
  description?: string;
  type: 'app' | 'console' | 'site' | 'game' | 'ext';
  tier: 'shell' | 'tokens';
  framework?: string | null;
  surfaces: string[];
  shell?: string | null;
  token_version?: string | null;
  enforce?: boolean;
  status?: string | null;
  category?: string | null;
  featured?: boolean;
  repo_url?: string | null;
  url?: string | null;
  deep_link: string;
  targets: AppTarget[];
  /** frame: the console can show it; none: no browser surface or no address. */
  embed: 'frame' | 'none';
  local_host?: string | null;
}

/** A repo's frontend component (ADR 0005): what kind it is and how much of it exists. */
export interface RepoComponent {
  /** own: its own frontend · preview: a web preview of a non-browser surface · terminal: its TUI in a window · generated: the repo app the shell builds. */
  kind: 'own' | 'preview' | 'terminal' | 'generated';
  /** live: the shell shows it at a deployed address · local: only at a dev stack · none: nothing to show yet. */
  state: 'live' | 'local' | 'none';
  next: string;
}

/** Every submodule in the registry, with or without a frontend. */
export interface FleetRepo {
  id: string;
  name: string;
  description?: string;
  category?: string | null;
  status?: string | null;
  repo_url?: string | null;
  type?: string | null;
  framework?: string | null;
  surfaces: string[];
  stack?: string[];
  license?: string | null;
  branch?: string | null;
  docs_url?: string | null;
  /** Where it answers, whether or not the shell can frame it. */
  targets: AppTarget[];
  component: RepoComponent;
  /** The shell can frame it today: it is an app in the launcher. */
  framed: boolean;
}

/** A repo's README from its checkout on the console's machine (never in the public snapshot). */
export interface ProjectReadme {
  present: boolean;
  reason?: string;
  path?: string;
  markdown?: string;
  truncated?: boolean;
}

export interface AppsDoc {
  schema: string;
  source: string;
  apps: FleetApp[];
  repos: FleetRepo[];
  viewports: { id: string; width: number; height: number }[];
  summary: {
    apps: number; embeddable: number; live: number; local: number; repos: number;
    by_type: Dict<number>; by_shell: Dict<number>; by_tier: Dict<number>; components: Dict<number>;
  };
}

export interface FleetRow {
  name: string;
  description?: string;
  category?: string;
  status?: string;
  featured?: boolean;
  stack?: string[];
  repo_url?: string;
  live_url?: string | null;
  docs_url?: string | null;
  submodule_path?: string | null;
  checked_out?: boolean;
  health?: Level | null;
  ci_last?: string | null;
  ci_pass?: number | null;
  last_commit_days?: number | null;
  commits_30d?: number | null;
  issues_open?: number | null;
  prs_open?: number | null;
  security_alerts?: number;
  reasons?: string[];
  stars?: number;
  triage_level?: Level | null;
  triage_score?: number | null;
  triage_reasons?: string[];
  triage_issues?: number | null;
  triage_prs?: number | null;
  failing: { workflow: string; url: string }[];
  /** OpenSSF Scorecard aggregate from conformance.yml `security:` (0-10; -1 inconclusive; null = not swept). */
  scorecard?: number | null;
  scorecard_checks?: Record<string, number>;
  docker_up?: number;
  docker_total?: number;
  docker_status?: string | null;
  worst_level?: Level | null;
}

export interface InboxItem {
  kind: string;
  repo: string;
  title: string;
  why: string;
  priority: number;
  age_days?: number | null;
  url: string;
  ref?: string;
  label: string;
  /** kind `merge` (FF-0036): the red workflow(s), then the PRs red only because of it, that merging this PR clears. */
  clears?: string[];
  /** kind `merge`: the fix evidence, `verified` (its own run passed the failed jobs) or `doctor`. */
  evidence?: string;
}

export interface FleetView {
  kpis: Dict<number>;
  health_present: boolean;
  sources: { name: string; path: string; present: boolean; generated_at?: string | null; age_days?: number | null; stale?: boolean }[];
  inbox: InboxItem[];
  repo?: string | null;
  trip_wires: TripWire[];
  scorecard: Dict<ScoreMetric>;
  sorts: string[];
  rows: FleetRow[];
  query?: { q: string; sort: string; health: string | null };
}

export interface Container {
  host: string;
  name: string;
  state?: string;
  status?: string;
  ports?: string;
  project?: string;
  running: boolean;
  owner?: string | null;
}

export interface DockerView {
  hosts: string[];
  containers: Container[];
  errors: Dict<string>;
  polled_at?: string;
}

/** fleetcore.nodes.status_doc (schema fleet-nodes/v1): GET /api/nodes, `tools/dash node status --json`, MCP fleet_nodes. */
export type NodeState = 'up' | 'unknown' | 'off' | 'unprobed';

export interface NodeCapacity {
  /** engine: `docker info` on the edge (the Docker VM on a Mac); ssh: the probe of a workload node. */
  via: 'engine' | 'ssh';
  cpus: number;
  mem_total?: number;
  mem_available?: number;
  disk_total?: number;
  disk_free?: number;
  containers_running?: number;
  server_version?: string;
}

export interface FleetNode {
  name: string;
  role: string;
  runtime: string;
  docker: string;
  enabled: boolean;
  probed: boolean;
  status: NodeState;
  reachable: boolean | null;
  detail: string;
  docker_error: string | null;
  capacity: NodeCapacity | null;
  /** What _data/fleet.yml says the box has (cpus, mem_gb, disk_gb). */
  declared: Dict<number> | null;
  /** Hub services running there now; null when not read. */
  containers: number | null;
  placed: string[];
  deferred: string[];
}

export interface NodePlanRow {
  service: string;
  wants: string;
  runs_on: string[];
  now: string[];
  action: string;
  reason: string;
  deferred: boolean;
}

export interface NodesDoc {
  schema: string;
  generated_at: string;
  edge: string;
  probed: boolean;
  nodes: FleetNode[];
  services: NodePlanRow[];
  /** Services running somewhere other than where they are placed, on the nodes in
   * drift_read; null when no node's containers were read (the public build, or a
   * console with no Docker socket) — not read, never a zero. */
  drift: { service: string; now: string[]; runs_on: string[] }[] | null;
  /** The nodes whose containers were read, which the drift covers. */
  drift_read: string[];
  problems: string[];
}

export interface LakeRun {
  id: number;
  nwo: string;
  workflow_name: string;
  workflow_path?: string;
  event?: string;
  status?: string;
  conclusion?: string | null;
  created_at?: string;
  html_url?: string;
  ai?: number;
  model?: string | null;
  num_turns?: number | null;
  cost_usd?: number | null;
  duration_ms?: number | null;
  trace_id?: string | null;
  exported_at?: string | null;
}

export interface LakeLine {
  nwo: string;
  path: string;
  name?: string;
  ai?: number;
  kind?: string | null;
  triggers?: string | null;
  crons?: string | null;
  switch?: string | null;
  factory_blueprint?: string | null;
  factory_hash?: string | null;
  model?: string | null;
  max_turns?: number | null;
  auth?: string | null;
  last_conclusion?: string | null;
  runs?: number;
  blueprint_in_lake?: number | null;
}

export interface ProjectDetail {
  name: string;
  registry: Dict<unknown>;
  harness: HarnessRepo | null;
  schedule: ScheduleEntry[];
  attention: Attention[];
  lake_runs: LakeRun[];
  lake_lines: LakeLine[];
  row: FleetRow | null;
  inbox: InboxItem[];
}

export interface ConfigField {
  key: string;
  path: string;
  kind: string;
  help: string;
  present: boolean;
  value: unknown;
  choices?: string[];
}

export interface ConfigSection {
  key: string;
  title: string;
  blurb: string;
  doc: string;
  present: boolean;
  fields: ConfigField[];
}

export interface ConfigDoc {
  path: string;
  sections: ConfigSection[];
}

export interface Credential {
  name: string;
  label: string;
  help: string;
  url: string;
  present: boolean;
  source?: string | null;
  in_env_file?: boolean;
}

export interface AuthDoc {
  writes_enabled: boolean;
  console_token_required: boolean;
  github: { cli?: boolean; authenticated?: boolean; account?: string; host?: string; scopes?: string[]; protocol?: string; env_token?: string | null; message?: string };
  claude: { oauth?: boolean; api_key?: boolean; cli?: boolean };
  env_file: { path: string; exists?: boolean; tracked_by_git?: boolean; names?: string[] };
  credentials: Credential[];
  push: { name: string; scope?: string; in_env_file?: boolean }[];
}

export interface TuiStatus {
  available: boolean;
  active: number;
  max: number;
  app: string;
}

// --- GitHub (tools/console/github_link.py) --------------------------------
export interface GithubStatus {
  connected: boolean;
  source: string | null;
  kind: string | null;
  login: string | null;
  name: string | null;
  avatar_url: string | null;
  scopes: string[];
  rate: { limit: number | null; remaining: number | null; reset: number | null } | null;
  error: string | null;
  session_set: boolean;
  writes_enabled: boolean;
  auth_writes: boolean;
  fleet_owner: string;
  oauth: {
    client_id_set: boolean; client_secret_set: boolean; device_flow: boolean; web_flow: boolean;
    default_scopes: string; callback_url: string; new_app_url: string; authorized_apps_url: string;
  };
}

export interface GhRepo {
  full_name: string; name: string; owner: string; private: boolean; archived: boolean; fork: boolean;
  description: string | null; pushed_at: string | null; open_issues: number; stars: number;
  default_branch: string; html_url: string; language: string | null;
  permissions: Record<string, boolean>; fleet_name: string | null; writable: boolean;
}

export interface GhIssue {
  number: number; title: string; state: string; state_reason?: string | null; user: string | null;
  labels: string[]; comments: number; created_at: string; updated_at: string; html_url: string;
  assignees: string[]; draft?: boolean | null; body?: string; is_pr?: boolean;
}

export interface GhRepoDetail {
  nwo: string; fleet_name: string | null; writable: boolean;
  repo: Record<string, any> & { permissions: Record<string, boolean> };
  issues: GhIssue[];
  pulls: { number: number; title: string; user: string | null; draft: boolean; head: string; base: string; updated_at: string; html_url: string; labels: string[] }[];
  runs: { id: number; name: string; display_title: string; event: string; status: string; conclusion: string | null; branch: string; created_at: string; html_url: string; run_attempt: number; workflow_id: number }[];
  workflows: { id: number; name: string; path: string; state: string; html_url: string }[];
  labels: { name: string; color: string; description: string | null }[];
  errors: Record<string, string>;
}

export interface GhAction {
  at: string; action: string; label: string; repo: string; target: string; ok: boolean; url: string | null; error: string | null;
}

// --- The site (tools/console/site_docs.py) ---------------------------------
/**
 * The site this build renders (_data/profile.yml `site:`; in a site build,
 * with its `sites.<key>` entry laid over it by site_docs.site_settings).
 */
export interface SiteSettings {
  title?: string; url?: string; description?: string; image?: string | null;
  /** Who the site is by, where that is not the profile's own name. */
  name?: string;
  /** The tab icon and header mark, a file the app ships. */
  mark?: string;
  /** What `/` is in this build. */
  front_door?: 'home' | 'desktop';
  desktop?: {
    /** `repos`: an icon for every repo (its frontend, else the repo app); `apps`: the framed frontends only. */
    icons?: 'apps' | 'repos';
    /** Registry ids shown first and offered on Welcome. */
    pinned?: string[];
    welcome?: string;
  };
}
export interface Profile {
  name?: string; handle?: string; title?: string; tagline?: string; location?: string; email?: string; avatar?: string; summary?: string;
  site?: SiteSettings;
  links?: { label: string; icon?: string; url: string }[];
}
export interface SitePageMeta { slug: string; title: string; description: string; order: number; icon: string }
export interface SitePage extends SitePageMeta { markdown: string }
export interface SitePostMeta { slug: string; date: string; title: string; excerpt: string; categories: string[]; tags: string[]; draft: boolean; words: number }
export interface SitePost extends SitePostMeta { markdown: string }
export interface SiteIndex { profile: Profile; pages: SitePageMeta[]; posts: SitePostMeta[] }

export interface GithubFleet {
  owner: string;
  hub: { repo?: string; shared?: string; default_branch?: string };
  repos: Record<string, string>;
  dispatchable: Record<string, string[]>;
}

// --- The Work board (/api/work — dash-gen work_board.py) -------------------
export type WorkKind = 'issue' | 'pr' | 'roadmap' | 'spec' | 'backlog';
export type WorkLaneId = 'triage' | 'ready' | 'doing' | 'review' | 'blocked' | 'hold';
export type WorkLoopId = 't1' | 't2' | 't3' | 'evolve' | 'human' | 'none';

export interface WorkItem {
  key: string;
  kind: WorkKind;
  ref: string;
  title: string;
  url: string | null;
  repo: string;
  nwo: string | null;
  lane: WorkLaneId;
  stage: string;
  priority: string;
  priority_auto: string;
  priority_source: 'override' | 'computed' | 'label' | 'default' | 'derived' | 'roadmap' | 'severity';
  rank: number | null;
  size: string | null;
  age_days: number | null;
  idle_days: number | null;
  readiness: number | null;
  autonomy: string | null;
  autonomy_reason: string | null;
  labels: string[];
  movable: WorkLaneId[];
  moved: { lane: WorkLaneId; at: string | null; pending: boolean } | null;
  progress: { done: number; total: number } | null;
  note: string | null;
  loop: WorkLoopId;
  next_run: number | null;
  detail: Dict<any>;
}

export interface WorkLane {
  id: WorkLaneId;
  label: string;
  hint: string;
  count: number;
  pinned: number;
  loops: WorkLoopId[];
}

export interface WorkLoop {
  id: WorkLoopId;
  label: string;
  lane: WorkLaneId;
  kind: WorkKind | null;
  schedule: string | null;
  runs_per_week: number | null;
  cap: number | null;
  sub_cap: { label: string; value: number } | null;
  eligible: number;
  next_run: number;
  drain_runs: number | null;
  drain_days: number | null;
  by_repo: { repo: string; eligible: number; picked: number }[];
  config: string | null;
  on_demand?: boolean;
  note?: string;
  breakdown?: Dict<number>;
}

export interface WorkHint {
  tone: 'good' | 'warn' | 'crit' | 'info';
  lever: string | null;
  text: string;
}

export interface WorkChange {
  key: string | null;
  target: 'github' | 'roadmap' | 'work_queue';
  what: string;
}

export interface WorkBoard {
  schema: string;
  generated_at: string;
  preview: boolean;
  lanes: WorkLane[];
  items: WorkItem[];
  loops: WorkLoop[];
  repos: (Dict<number> & { repo: string; total: number; next_run: number })[];
  totals: { items: number; next_run: number; by_kind: Record<WorkKind, number>; by_priority: Dict<number> };
  sources: {
    issue_pipeline: { generated_at: string | null; full: boolean; age_days: number | null; private_omitted: number };
    fleet_triage: { generated_at: string | null };
    roadmap: { entries: number };
    local: { scanned: boolean; repos: Dict<any>[]; reason?: string };
    work_queue: { updated_at: string | null; pinned: number; priority_overrides: number; stale_keys: string[] };
  };
  labels: Dict<string>;
  priorities: string[];
  roadmap_statuses: string[];
  hints: WorkHint[];
  changes?: WorkChange[];
  queue_path?: string;
}

/** What a drag or a drill-down stages; POST /api/work/preview | /apply. */
export interface WorkPlan {
  stage?: Record<string, WorkLaneId>;
  priority?: Record<string, string | null>;
  pins?: Partial<Record<WorkLaneId, string[]>>;
  unpin?: string[];
  notes?: Record<string, string | null>;
  roadmap_status?: Record<string, string>;
  roadmap_reason?: Record<string, string>;
}

export interface WorkApplyResult {
  results: (WorkChange & { ok: boolean; error: string | null })[];
  pruned: string[];
  diff: string;
  board: WorkBoard;
}

export interface WorkItemDetail {
  item: WorkItem;
  loop: WorkLoop | null;
  entry?: Dict<any> | null;
  spec?: Dict<any> & { task_list: { id: string; title: string; state: 'done' | 'doing' | 'todo' }[]; markdown: string; open_question_lines: string[] };
  backlog?: Dict<any> | null;
  mentions?: string[];
}

export interface PullSpecs {
  pr: Dict<any>;
  specs: (Dict<any> & { slug: string; title: string; status: string; tasks: { total: number; done: number; doing: number };
    open_questions: string[]; requirements: { FR: number; NFR: number; AC: number; uncovered: string[] }; changed: string[]; url: string | null })[];
  specs_truncated: number;
  mentioned: string[];
  backlog: { added: Dict<string>[]; removed: Dict<string>[]; moved: string[] };
  files: { total: number; by_area: Dict<number> };
}

// --- The workflow atlas (dash-gen workflow_atlas.py; /api/workflows) ---------
export type Severity = 'error' | 'warn' | 'info';
export type FailureClass = 'capacity' | 'config' | 'transient' | 'dependency' | 'defect';
export interface WfInput { name: string; type: string; default: unknown; required: boolean; description: string; options: string[] }
export interface WfCron { cron: string; human: string; per_day: number | null; on_hour: boolean; schedule_key: string | null }
export interface WfEvent { name: string; branches?: string[]; paths?: string[]; types?: string[]; tags?: string[]; workflows?: string[] }
export interface WfJob {
  id: string; name: string; line: number | null; runs_on: string | null; timeout: number | string | null; needs: string[];
  if: string | null; uses: string | null; permissions: Record<string, string> | string | null; concurrency: boolean; steps: number; matrix: boolean;
}
export interface WfRef { ref: string; kind: 'action' | 'workflow' | 'external' | 'docker' | 'unknown'; target: string; version: string | null; owner?: string | null; jobs: string[] }
export interface WfAiSite {
  site: string; job: string; kind: string; step: string; continue_on_error: boolean | 'expression'; max_budget_usd: number | null; budget_from_input?: boolean; max_turns: number | null;
  model: string | null; cost_step: boolean; usage_limit: string | null; declared_usd: number | null;
}
export interface Tally { error: number; warn: number; info: number }
export interface Workflow {
  id: string; file: string; name: string; lines: number; parse_error: string | null; header: string; group: string;
  when: string | null; purpose: string | null; purpose_text: string | null; documented: boolean;
  triggers: string[]; events: WfEvent[]; crons: WfCron[]; dispatch_inputs: WfInput[]; call_inputs: WfInput[]; call_secrets: string[];
  permissions: Record<string, string> | string | null; concurrency: { group: string; cancel_in_progress: unknown } | null;
  jobs: WfJob[]; uses: WfRef[]; secrets: string[]; vars: string[]; switch: string | null; switches: string[];
  ai_sites: WfAiSite[]; publishes: string[]; opens_prs: boolean; findings: Tally; loop: string | null; dispatchable: boolean;
}
export interface WfAction {
  id: string; file: string; name: string | null; description: string; using: string | null; inputs: WfInput[]; outputs: string[];
  steps: number; uses: string[]; lines: number; parse_error: string | null; used_by: string[]; documented: boolean; readme: boolean; findings: Tally; description_exprs?: string[];
}
export interface Finding { rule: string; severity: Severity; kind: 'workflow' | 'action'; target: string; file: string; line: number | null; job: string | null; message: string }
export interface Rule { id: string; severity: Severity; title: string; why: string; fix: string; doc: string; gate: string | null }
export interface Retired { date: string; removed: string; why: string; files: string[] }
export interface WorkflowAtlas {
  schema: string; hub: string; workflows: Workflow[]; actions: WfAction[]; retired: Retired[]; rules: Rule[]; findings: Finding[];
  readme_orphans: string[]; edges: { from: string; to: string; kind: string }[]; kinds: Record<string, string>;
  summary: {
    workflows: number; actions: number; lines: number; action_lines: number; groups: Record<string, number>; scheduled: number; ai: number;
    ai_sites: number; kill_switches: number; dispatchable: number; jobs: number; findings: Tally; retired: number;
    external_actions: { action: string; versions: string[] }[]; secrets: string[]; vars: string[];
  };
}
export interface RunBrief { id: number; event: string; conclusion: string | null; status: string; created_at: string; html_url: string; head_branch: string | null }
export interface RunFailure extends RunBrief { cause: string; class: FailureClass; evidence: string; hint: string; failed_step: string | null }
export interface WfHealthRow {
  path: string; runs: number; success: number; failure: number; cancelled: number; skipped: number; other: number;
  events: Record<string, number>; causes: Record<string, number>; classes: Record<string, number>; capacity_skips: number;
  last: RunBrief | null; last_failure: RunFailure | null; failures: RunFailure[]; p50_min: number | null; success_rate: number | null;
  verdict: string; ghost: boolean;
}
export interface WorkflowHealth {
  present: boolean; snapshot?: boolean; error?: string; nwo?: string; days?: number; synced_at?: string | null; logs?: number;
  workflows: WfHealthRow[]; totals: Partial<Record<'runs' | 'success' | 'failure' | 'cancelled' | 'skipped' | 'capacity_skips', number>>;
  classes: Record<string, number>; ghosts: string[]; class_hints: Record<string, string>;
}
export interface Scaffold {
  kind: string; id: string; name: string; file: string; exists: boolean; cron: string | null; cron_human: string | null; switch: string | null;
  text: string; companion: { file: string; where: string; snippet: string; why: string }[]; findings: Finding[]; kinds: Record<string, string>;
}
export interface DraftLint { workflow: Workflow; findings: Finding[]; tally: Tally }

// --- Harness refinement (JEV capability three, docs/HARNESS-REFINEMENT.md) ---
export interface SurfaceCensus {
  surface: string;
  always_on: { files: string[]; chars: number; max_chars: number; pct_of_cap: number | null };
  components: Dict<{ files: number; chars: number; hooks?: number; mcp_servers?: number }>;
  skills: { name: string; path: string; chars: number; triggered: boolean; paths: boolean; description_chars: number; resources: number }[];
  subagents: { name: string; path: string; chars: number; tools?: unknown; model?: unknown }[];
  commands: { name: string; path: string; chars: number }[];
  policy_as_data: { settings: boolean; allow_rules: number; deny_rules: number; hook_events: string[]; hook_commands: number; mcp_servers: string[] };
  script_refs_checked: number;
  files: number;
}
export interface SurfaceReport {
  root?: string;
  ok: boolean;
  errors: string[];
  warnings: string[];
  notes: string[];
  census: SurfaceCensus;
}
export interface FleetSurfaceRow {
  name: string;
  nwo: string | null;
  path: string | null;
  category: string;
  checked_out: boolean;
  ok: boolean | null;
  errors: number;
  warnings: number;
  notes: number;
  always_on_chars: number | null;
  skills: number | null;
  subagents: number | null;
  hooks: number | null;
  mcp_servers: number | null;
  context_files: string[];
  problems: string[];
}
export interface FleetSurface {
  schema?: string;
  generated_at?: string;
  always_on_max_chars?: number;
  repos: FleetSurfaceRow[];
  totals: Dict<number>;
  error?: string;
}
export interface RefineStep { kind: 'rollout' | 'session'; label: string; dim: string; harness: string; evidence: string[]; round: number }
export interface RefinePlan {
  loop: string;
  step?: string;
  call_site?: string;
  k?: number;
  mode?: string;
  identity?: { R: number; P: number };
  cost?: { ceiling_usd: number; rollouts: { count: number; cap_usd_each: number; ceiling_usd: number }; sessions: { count: number; cap_usd_each: number; ceiling_usd: number } };
  budget?: { available: boolean; month?: string; spent_usd?: number; cap_usd?: number; stop_usd?: number; affordable?: boolean; reason?: string };
  tunable?: { path: string; exists: boolean; chars: number }[];
  hard_rules?: { prompt: string; template_sha256: string; allowed_tools: number; model: string; max_turns: number; timeout_minutes: number; gated: string };
  library?: { root: string; domain: string; entries: number; cues: string[] };
  proposer?: { model: string; max_turns: number };
  model_backed?: { enabled: boolean; status: string };
  steps?: RefineStep[];
  finals?: string[];
  error?: string | null;
}
export interface LibraryEdit { component: string; candidates: string[]; change: string; observed: string; verdict: string }
export interface LibraryEntry {
  loop: string;
  domain: string;
  id: string;
  step: string;
  item: string;
  run_id: string;
  adopted: string;
  date: string;
  source: string;
  cue: string;
  lesson: string;
  evidence: string;
  confidence: string;
  edits: LibraryEdit[];
  components?: Dict<unknown>;
  notes?: string;
  has_diff?: boolean;
}
export interface EvidenceTree {
  stamp: string;
  loop: string | null;
  step: string | null;
  item: string | null;
  domain: string | null;
  stage: string | null;
  k: number | null;
  generated_at: string | null;
  files: number;
  rollouts: string[];
  library_entries: number | null;
  redacted: boolean | null;
}
export interface EvidenceDoc { stamp: string; manifest: Dict<unknown>; files: string[]; bytes: Dict<number | null> }
export interface TextFile { path: string; text: string; truncated: boolean; stamp?: string; run_id?: string }
export interface ReviewItem {
  run_id: string;
  loop: string;
  step: string;
  item: string;
  name?: string | null;
  dir: string;
  status: string;
  reason?: string | null;
  would_file?: number | null;
  plan_id?: string | null;
  cost_usd?: number | null;
  cost_label: string;
  finished?: string | null;
  head_sha?: string | null;
  can_apply: boolean;
  publish_tier?: string | null;
  bodies: { file: string; title: string }[];
  preview: string | null;
}
export interface RefineDoc {
  schema: string;
  generated_at: string;
  local: boolean;
  config: Dict<unknown> | null;
  config_error: string | null;
  surface: SurfaceReport;
  fleet_surface: FleetSurface;
  plans: RefinePlan[];
  library: { root: string; entries: LibraryEntry[]; count: number; problems: string[]; uncommitted: string[]; schema: string };
  evidence: EvidenceTree[];
  reviews: ReviewItem[];
  missions: Dict<string>;
  stages: string[];
  modes: string[];
  cost_label: string;
}
export interface AssistDoc {
  schema: string;
  config: {
    enabled: boolean; model: string; max_turns: number; budget_usd: number; timeout_s: number;
    conversation_messages: number; page_access: 'off' | 'look' | 'act';
  } | null;
  config_error: string | null;
  cost_label: string;
  unavailable: string | null;
  /** Why no session starts here: no claude CLI (the Docker console), a broken config, or switched off. */
  unavailable_kind: 'no_cli' | 'config' | 'off' | null;
  /** The command that starts a console on the host, where the CLI is. */
  host_command: string;
  mcp_server: string;
  allowed_tools: string[];
  denied_tools: string[];
  prompt_sha256: string | null;
  max_question_chars: number;
  local: boolean;
  /** The page bridge: the fleet.yml ceiling on what a session may do to an open page, and its two tiers of tools. */
  page: { access: 'off' | 'look' | 'act'; look: string[]; act: string[]; modes: string[]; approval_s: number };
}

// --- How the assistant is observed (tools/fleetcore/assistlog.py, /api/assist/activity) ---
/** One line of the page bridge's audit: what a session did to a page. Never typed text, never a session id. */
export interface PageAuditRow {
  id: string;
  at: string;
  /** The first eight characters of the page session. */
  session: string;
  /** `dock` (the console started the session), `paired` (a person's own Claude Code session) or `operator` (an End). */
  client: string;
  kind: 'console' | 'fleet';
  origin: string | null;
  repo: string | null;
  action: string;
  target: string;
  mode: string;
  outcome: string;
  ms: number;
}
/** One assistant message, from the AI ledger. */
export interface AssistRunRow {
  at: string;
  session_id: string | null;
  model: string | null;
  outcome: string;
  cost_usd: number | null;
  cost_source: string | null;
  cap_usd: number | null;
  turns: number | null;
  duration_s: number | null;
  cli_version: string | null;
}
/** A fleet page sharing itself with this console right now. `id` is what End sends back. */
export interface SharedPage {
  id: string;
  kind: 'fleet' | 'console';
  origin: string | null;
  page: Partial<Record<'repo' | 'branch' | 'source' | 'route' | 'framework' | 'env' | 'version' | 'base' | 'title' | 'path' | 'kit', string>>;
  mode: 'look' | 'ask' | 'act';
  live: boolean;
  paired: number;
  commands: number;
  created: string;
}
/** The assistant's entry in the agent inventory (_data/agents.yml, constitution § 29). */
export interface AssistAgentEntry {
  id: string;
  kind: string | null;
  category: string | null;
  owner: string | null;
  trigger: string | null;
  switch: Record<string, string> | null;
  budget: { per_run_usd?: number; monthly_usd?: number } | null;
  model: string | null;
  kpis: Record<string, number | null> | null;
  reads: Record<string, string | null> | null;
  run_record: string | null;
  feeds_reflector: boolean | null;
  local_entry: string | null;
  gaps: string[] | null;
}
export interface AssistActivity {
  schema: string;
  agent: string;
  window_days: number;
  cost_label: string;
  generated_at: string | null;
  local: boolean;
  page_audit: {
    path: string | null; exists: boolean; recent: PageAuditRow[];
    summary: {
      lines: number; commands: number; attaches: number; ended_by_operator: number; sessions: number;
      by_outcome: Record<string, number>; by_action: Record<string, number>; by_client: Record<string, number>;
      by_kind: Record<string, number>; by_mode: Record<string, number>; origins: Record<string, number>;
      no: number; no_pct: number | null; ok_ms_p50: number | null; ok_ms_p95: number | null;
      first: string | null; last: string | null;
    };
  };
  messages: {
    ledger: string | null; exists: boolean; source: string; recent: AssistRunRow[];
    summary: {
      messages: number; cost_usd: number | null; cost_label: string; by_outcome: Record<string, number>;
      by_model: Record<string, number>; by_cost_source: Record<string, number>; cost_unreported: number;
      not_ok: number; not_ok_pct: number | null; budget_hits: number; turns: number | null;
      max_cost_usd: number | null; first: string | null; last: string | null;
    };
  };
  shared_pages: { access: 'off' | 'look' | 'act'; setting: string; cap: number; sessions: SharedPage[] };
  agent_entry: AssistAgentEntry | null;
  note: string;
}

// --- The fleet voice model (tools/voices.py, /api/voices; constitution § 23 rule 7) ---
export type VoiceStyle = Partial<Record<'formality' | 'length' | 'humor' | 'reading_level', string>>;
export interface VoiceTopics { cover?: string[]; exclude?: string[] }
/** A profile layer (defaults, a site's profile) — persona fields ride on top. Unknown keys round-trip untouched. */
export interface VoiceProfile {
  summary?: string; audience?: string; voice?: string; tone?: string; style?: VoiceStyle;
  guidance?: string; avoid?: string; claims?: string; topics?: VoiceTopics;
  name?: string; role?: string; enabled?: boolean; perspective?: string; beats?: string[]; repos?: string[];
  [key: string]: unknown;
}
export interface VoiceRule { activity?: string[]; repos?: string[]; cadence?: string; persona?: string; default?: string }
export interface VoiceSite { profile: VoiceProfile; personas?: Record<string, VoiceProfile>; assignment?: VoiceRule[]; [key: string]: unknown }
export interface VoicesData { schema: string; defaults: VoiceProfile; sites: Record<string, VoiceSite>; [key: string]: unknown }
export interface VoicesDrift { ref: string; available: boolean; differs: boolean; diff: string; changes: string[] }
export interface VoicesDoc {
  schema: string;
  path: string;
  schema_path: string;
  text: string;
  data: VoicesData | null;
  errors: string[];
  ok: boolean;
  canonical: boolean;
  drift: VoicesDrift;
  enums: { style: Record<string, string[]>; cadence: string[] };
  field_order: string[];
  quoted: string[];
}
export interface VoicesPreview {
  ok: boolean; errors: string[]; text: string; base: string; changed: boolean; diff: string; changes: string[]; plan_id: string; drift: VoicesDrift;
}
export interface VoicesStaged { plan_id: string; staged: boolean; base: string; changes: string[]; diff: string }
// --- The live expedite-sprint records (tools/sprint_record.py, `sprint-records/v1`) ---
export interface SprintGate {
  by: string;
  at: string;
  ref: string;
}
export interface SprintItem {
  ref: string;
  kind: 'issue' | 'pr';
  title?: string;
  state?: string;
  phase?: number;
}
export interface SprintTripWire {
  id: string;
  rule: string;
  state: 'armed' | 'tripped' | 'cleared';
  at?: string | null;
}
export interface Sprint {
  slug: string;
  title: string;
  path: string;
  /** A record that failed the secret check (or did not parse): only its findings are served. */
  withheld: boolean;
  findings: string[];
  warnings: string[];
  item?: string;
  target_repo?: string | null;
  state?: 'proposed' | 'active' | 'stopped' | 'demoted' | 'done';
  phase?: number;
  phase_name?: string | null;
  updated_at?: string | null;
  appetite?: { hours: number; usd: number; label: string; ends_at?: string | null };
  gates?: { declaration: SprintGate | null; spec: SprintGate | null; merge: SprintGate | null };
  gates_passed?: number;
  spend?: { usd: number; cap_usd: number; label: string; updated_at?: string | null; source?: string | null };
  spend_ratio?: number | null;
  items?: SprintItem[] | null;
  trip_wires?: SprintTripWire[] | null;
  dora?: Dict<unknown> | null;
  retro?: { lessons?: string[]; debt?: string[] } | null;
  stop?: { at: string; reason: string; by?: string | null; filed?: string[] | null; note?: string | null } | null;
  notes?: string | null;
}
export interface SprintsDoc {
  schema: string;
  generated_at: string;
  dir: string;
  standard: string;
  cost_label: string;
  maintainer: string;
  phases: string[];
  gates: string[];
  active: string | null;
  count: number;
  sprints: Sprint[];
  errors: string[];
  warnings: string[];
}
// --- GitHub Projects (v2), read-only (gh_projects.py; /api/gh-projects*) ----
export type GhProjectsStatus = 'fresh' | 'partial' | 'scope_missing' | 'unavailable';
export interface GhProjectField {
  id: string | null;
  name: string | null;
  type: string | null;
  options: string[];
}
export interface GhProject {
  owner: string;
  id: string;
  number: number;
  title: string;
  url: string;
  closed: boolean;
  fields: GhProjectField[];
}
export interface GhProjectOwner {
  login: string;
  kind: 'user' | 'organization';
  status: 'ok' | 'scope_missing' | 'error' | 'skipped';
  projects?: number;
  error?: string;
}
export interface GhProjectsBudget {
  limit: number;
  window_s: number;
  used: number;
  left: number;
  budget_s: number;
  elapsed_s: number;
}
export interface GhProjectsDoc {
  schema: string;
  generated_at: string;
  status: GhProjectsStatus;
  complete: boolean;
  source: 'live' | 'cache' | 'none';
  age_s: number;
  ttl_s: number;
  token_source: string | null;
  scope_missing: boolean;
  read_only: boolean;
  owners: GhProjectOwner[];
  projects: GhProject[];
  counts: { owners: number; read: number; projects: number; open: number };
  budget: GhProjectsBudget;
  hint: string | null;
}
export interface GhProjectItem {
  item_id: string;
  archived: boolean;
  kind: 'issue' | 'pr' | 'draft' | 'unknown';
  content_id: string | null;
  repo: string | null;
  number: number | null;
  title: string;
  state: string | null;
  url: string | null;
  fields: Dict<string | number | null>;
  refs: string[];
  closes: string[];
  commits: { sha: string; headline: string; refs: string[] }[];
}
export interface GhProjectItemsDoc {
  schema: string;
  project_id: string;
  generated_at: string;
  status: GhProjectsStatus;
  complete: boolean;
  source: 'live' | 'cache' | 'none';
  age_s: number;
  token_source: string | null;
  total: number;
  matched: number;
  limit: number;
  offset: number;
  next_offset: number | null;
  capped: boolean;
  max_items: number;
  statuses: string[];
  counts: { by_status: Dict<number>; by_kind: Dict<number> };
  items: GhProjectItem[];
  errors: string[];
  budget: GhProjectsBudget;
  hint: string | null;
}
// The PR queue (/api/prs; tools/fleetcore/prqueue.py, docs/PR-QUEUE.md).
export type PrWho = 'amr' | 'agent' | 'loop' | 'author';
export type PrCheckState = 'failing' | 'action_required' | 'cancelled' | 'pending' | 'green' | 'skipped' | 'none';
export interface PrCheckRun {
  name: string; workflow?: string; kind: 'check' | 'status'; state: PrCheckState; conclusion?: string; status?: string;
  url?: string; run_id?: number; superseded?: number; at?: string;
}
export interface PrRow {
  key: string; repo: string; number: number; title: string; url: string; author: string; bot: boolean; draft: boolean;
  private: boolean; labels: string[]; age_days?: number; idle_days?: number; head?: string; base?: string; head_sha?: string;
  mergeable?: string; merge_state?: string; review?: string; files?: number;
  checks: { state: PrCheckState; rollup?: string | null; total: number; superseded: number; failing: string[]; cancelled: string[];
    pending: string[]; action_required: string[]; green: number; skipped: number; false_red: boolean; unread?: boolean };
  check_runs: PrCheckRun[];
  kinds: string[]; batch?: string;
  gate: { gated: boolean; reason: string };
  merge_method?: string | null;
  agent_merge: { ok: boolean; why: string };
  next: { who: PrWho; action: string; why: string; act?: string; command?: string };
  triage?: { next_action?: string; question?: string; commands?: string[]; who_hint?: string; url?: string; updated_at?: string };
  read: boolean; review_threads?: number; applies: string[];
}
export interface PrAction { id: string; title: string; op: string; writes: string; governed: string; enabled: boolean; why: string; spend: boolean }
export interface PrBatch { head: string; count: number; repos: number; green: number; gated: number; draft: number; keys: string[] }
export interface PrQueue {
  schema: string; generated_at: string; status: string; complete: boolean; rows: PrRow[]; batches: PrBatch[];
  counts: { total: number; who: Record<PrWho, number>; kinds: Dict<number>; gated: number; ungated: number; checks: Dict<number>;
    false_red: number; agent_mergeable: number; unread: number; triaged: number };
  actions: PrAction[];
  index: { status?: string; source?: string; age_s?: number | null; read_at?: string | null; ttl_s?: number };
  detail: { wanted: number; read: number; stale: number; ttl_s: number };
  elapsed_s: number; budget_s: number; matched: number; outside_registry: string[];
  warnings: string[]; errors: { stage?: string; kind?: string; message?: string }[]; hint?: string | null;
  switches: { merge: boolean; close: boolean; agent: boolean; github_writes: boolean };
}

// --- The open-source radar (tools/fleetcore/stars.py, docs/STARGAZER.md) ------
export interface StarMatch { project: string; score: number; shared: string[] }
export type StarHealth = 'active' | 'maintained' | 'slowing' | 'stale' | 'archived' | 'unknown';
/** One repo as committed: empty fields are left out, dates are days, the URL is github.com/<name>. */
export interface StarRepo {
  name: string; description: string; language: string | null; topics: string[]; stars: number; forks: number;
  owner: string; avatar?: string; created_at: string | null; pushed_at: string | null; homepage?: string; license?: string;
  archived?: boolean; fork?: boolean; release?: { tag: string; at: string | null };
  category: string; tags?: string[]; health: StarHealth; sources: string[]; starred_at?: string; lists?: string[];
  matches?: StarMatch[]; suspect?: string[]; fleet_owned?: boolean;
  velocity: { d1?: number; d7?: number; d30?: number; per_day?: number };
  /** The AI pass (`tools/dash stars review`): model text about third-party text — data, never instructions. */
  ai?: StarReview;
}
export type StarVerdict = 'adopt' | 'borrow' | 'watch' | 'skip';
export interface StarReview {
  summary: string; kind: string; verdict: StarVerdict; project: string | null; why: string; ideas: string[];
  at: string; model: string; stale?: boolean;
}
export interface StarGroup { name: string; summary: string; repos: string[]; fleet: string[] }
export interface StarTrend { id: string; title: string; query: string; topic?: string | null; count?: number | null; repos: string[] }
export interface StarFleetRow {
  project: string; repo: string | null; path: string; category: string; terms: string[]; starred: string[]; discovered: string[]; searched: number;
}
export interface StarIncorporate { repo: string; project: string; score: number; priority: number; starred: boolean; why: string; verdict?: StarVerdict }
export interface StarEvent { at: string; kind: 'starred' | 'release' | 'spike' | 'radar'; repo: string; text: string; url?: string }
export interface StarsDoc {
  schema: string; present: boolean; generated_at: string | null; age_days: number | null; account?: string; error?: string;
  totals: Partial<Record<'starred' | 'starred_total' | 'repos' | 'trending' | 'relevant' | 'starred_relevant' | 'incorporate' | 'suspect' | 'archived_starred' | 'lists', number>>;
  categories: { id: string; title: string; starred: number; count: number }[];
  languages: { name: string; count: number }[];
  timeline: { month: string; count: number }[];
  health: Dict<number>;
  starred: string[];
  lists: { name: string; slug: string; description: string; repos: string[] }[];
  trending: StarTrend[]; gaining: string[]; fleet: StarFleetRow[]; incorporate: StarIncorporate[]; feed: StarEvent[]; errors: string[];
  repos: Dict<StarRepo>;
  groups?: StarGroup[];
  ai?: { reviewed: number; stale: number; verdicts: Dict<number>; updated_at: string | null; groups_at: string | null;
    groups_current: boolean; models: string[]; cost_label: string };
}
export interface PrPlanItem {
  key: string; repo: string; number: number; title?: string; url?: string; head_sha?: string; do: boolean; skip?: string;
  preview?: string; warnings: string[]; next?: PrRow['next']; gate?: PrRow['gate'];
}
export interface PrPlan {
  schema: string; plan_id: string; action: string; title: string; op: string; params: Dict<unknown>; created_at: string;
  enabled: boolean; why: string; governed: string; writes: string; items: PrPlanItem[]; counts: { do: number; skip: number };
  ceiling_usd?: number; cost_label?: string; warning?: string;
}

// The loop switches (constitution § 17; tools/console/switches.py): GET /api/switches and
// POST /api/switches/preview. Never in the public snapshot: the live values are read with the
// operator's token.
export type SwitchTarget = 'on' | 'off';
export type SwitchScope = 'loop' | 'repo' | 'group' | 'all';
export interface SwitchHold { kind?: string; name?: string; value?: string; source?: string; lift?: string }
export interface SwitchRow {
  key: string; repo: string; workflow: string | null; group: string | null; owner?: string | null; scope?: string | null;
  gate: string | null; variable: string | null; semantics: 'opt_in' | 'opt_out' | null; default: string | null;
  live: { value: string | null; state: 'set' | 'unset' | 'unreadable' | 'n/a'; updated_at: string | null; on: boolean | null };
  effective: { on: boolean | null; why: string; verified: boolean };
  map: {
    state: string; verified: boolean; says: SwitchTarget | null; level_off: string | null; reason: string | null;
    set_by: string | null; set_at: string | null; expires: string | null;
  };
  drift: boolean | null; hold: SwitchHold | null; note: string | null; flippable: boolean; not_flippable: string | null;
}
export interface SwitchRepo {
  repo: string; writable: boolean; readable: boolean; error: string | null; loops: SwitchRow[];
  counts: { loops: number; on: number; off: number; unknown: number; drift: number; flippable: number };
}
export interface SwitchesDoc {
  schema: string; map_schema: string; generated_at: string; writes: { enabled: boolean; why: string | null }; login: string | null;
  global: { state?: string; reason?: string | null } | null; groups: Dict<{ state?: string; reason?: string | null }>;
  repos: SwitchRepo[];
  counts: { repos: number; loops: number; drift: number; on: number; off: number; unreadable: number; flippable: number };
  commit: string;
}
export interface SwitchPlanItem {
  key: string; repo: string; workflow: string | null; variable: string | null; semantics: string | null;
  current: string | null; current_state: string; current_on: boolean | null; new: string | null;
  write_variable: boolean; write_map: boolean; map_before: { state: string; verified: boolean };
  map_after: { state: string; verified: boolean } | null; do: boolean; skip: string | null; warnings: string[];
}
export interface SwitchPlan {
  schema: string; plan_id: string; scope: SwitchScope; key: string; target: SwitchTarget; reason: string;
  set_by: string | null; set_at: string; created_at: string; op: string; writes: { enabled: boolean; why: string | null };
  login_known: boolean; items: SwitchPlanItem[]; diff: string; diff_error: string | null;
  counts: { do: number; skip: number; variables: number; records: number }; commit: string;
}
