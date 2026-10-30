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
  /** Ops sharing this key never run at once (e.g. every writer of the lake). */
  exclusive?: string | null;
  /** Why this op cannot run in this console process at all (e.g. no Docker), or null. */
  unavailable?: string | null;
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
export interface Profile {
  name?: string; handle?: string; title?: string; tagline?: string; location?: string; email?: string; avatar?: string; summary?: string;
  site?: { title?: string; url?: string; description?: string };
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
