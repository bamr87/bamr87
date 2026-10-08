// Shapes of the console API documents (tools/console/core.py and
// tools/fleetcore/views.py). Every field is optional where the source file can
// be absent: the console renders a degraded page rather than failing.

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
}

export interface HarnessWorkflow {
  path: string;
  kind: string;
  model?: string | null;
  max_turns?: number | null;
  auth?: string | null;
  kit?: string | null;
  kit_status?: string | null;
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
  last7?: number | null;
  prior7?: number | null;
  wow_delta_pct?: number | null;
  projected_monthly?: number | null;
  budget_monthly?: number | null;
}

export interface Throughput {
  est_scheduled_ai_per_day?: number | null;
  observed_ai_runs_per_day?: number | null;
  cap_fleet?: number | null;
  cap_per_repo?: number | null;
  cap_per_utc_hour?: number | null;
  repos_over_cap?: { repo: string; est_per_day: number }[];
  hour_collisions?: { utc_hour: string; count: number; entries: string[] }[];
}

export interface HarnessRegistry {
  generated_at?: string;
  scan?: { mode?: string };
  contract?: { kit?: string; kit_version?: string; baseline?: Dict<boolean>; exempt?: string[] };
  totals?: Dict<number>;
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

export interface Loop {
  id: string;
  title: string;
  workflow: string;
  doc: string;
  outputs: string[];
  local_ops: string[];
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
  triage: { generated_at?: string; totals: Dict<number>; inbox: Dict<unknown>[] };
  pipeline: { generated_at?: string; totals: Dict<unknown> };
  rotation: {
    generated_at?: string;
    tokens: { name: string; scope?: string; oldest_age_days?: number; max_age_days?: number; counts?: Dict<number> }[];
  };
  usage: {
    actions: { window_days?: number; by_day?: { date: string; runs?: number; total_min?: number }[] };
    ai: { window_days?: number; by_day?: { day: string; runs?: number; cost_usd?: number }[] };
  };
  loops: Loop[];
  git: { branch?: string; head?: string; dirty_count?: number };
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
}

export interface Job {
  id: string;
  op: string;
  title: string;
  argv: string[];
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | string;
  remote_write?: boolean;
  params?: Dict<unknown>;
  started?: string | null;
  finished?: string | null;
  exit_code?: number | null;
}

export interface JobTail {
  job: Job;
  text: string;
  offset: number;
  done: boolean;
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
