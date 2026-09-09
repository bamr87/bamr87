// Shared contract for the GitHub I/O layer (seed 03).
// This file is the seam between the transport client, the crypto helper, and the
// deploy planner — each is implemented against these types. No I/O here; pure types
// + a couple of tiny pure helpers so the modules agree on shapes.
//
// Security (CLAUDE.md golden rule #7): the PAT lives in sessionStorage at most and is
// held in a closure by the client; it never appears in these types, in the blueprint,
// or in any persisted state. The Claude auth secret (CLAUDE_CODE_OAUTH_TOKEN or the
// ANTHROPIC_API_KEY fallback) plaintext is passed straight into sealSecret and never stored.

/** An `owner/repo` pair. */
export interface RepoRef {
  owner: string;
  repo: string;
}

/** Parse `"owner/repo"` (tolerating a full GitHub URL or surrounding whitespace). */
export function parseRepo(input: string): RepoRef | null {
  const cleaned = input
    .trim()
    .replace(/^https?:\/\/github\.com\//i, '')
    .replace(/\.git$/i, '')
    .replace(/\/$/, '');
  const m = /^([A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)\/([A-Za-z0-9._-]+)$/.exec(cleaned);
  if (!m) return null;
  return { owner: m[1], repo: m[2] };
}

/** `owner/repo` string form. */
export function repoSlug(r: RepoRef): string {
  return `${r.owner}/${r.repo}`;
}

/** Per-permission preflight state. `unknown` = we could not determine it. */
export type PermState = 'ok' | 'missing' | 'unknown';

/**
 * Result of checking a fine-grained PAT against a specific repo. The app needs, at a
 * minimum, Contents (RW) + Workflows (RW) to deploy; the rest gate optional features.
 */
export interface Preflight {
  repo: RepoRef;
  contents: PermState; // RW — blueprint + prompt files
  workflows: PermState; // RW — pushing .github/workflows/factory--*.yml
  issues: PermState; // RW — issue-writing sinks at runtime
  pullRequests: PermState; // RW — PR-mode deploys + PR sinks
  actions: PermState; // R — telemetry (seed 04)
  secrets: PermState; // RW — in-app power hookup
  /** True when the minimum-to-deploy permissions (contents + workflows) are present. */
  canDeploy: boolean;
}

/** A file read from the repo. `sha` is the blob sha required to update or delete it. */
export interface RepoFile {
  path: string;
  /** Decoded UTF-8 text. */
  content: string;
  sha: string;
}

/** One entry in a directory listing. */
export interface RepoDirEntry {
  path: string;
  name: string;
  sha: string;
  type: 'file' | 'dir';
}

/** GitHub Actions repo public key for sealed-box secret encryption. */
export interface ActionsPublicKey {
  key: string; // base64 libsodium public key
  keyId: string;
}

/** Where a deploy commit lands. `commit` = default branch; `pr` = new branch + PR. */
export type DeployMode = 'commit' | 'pr';

/** A single file the deploy will create or update. */
export interface DeployWrite {
  path: string;
  content: string;
  /** Blob sha of the existing file, when updating; omitted when creating. */
  sha?: string;
  reason: 'blueprint' | 'workflow' | 'prompt';
}

/** A file the deploy will delete (an assembly line that no longer exists). */
export interface DeployDelete {
  path: string;
  sha: string;
  reason: 'stale-workflow';
}

/**
 * The full set of changes a deploy will make, computed by diffing freshly compiled
 * output against what is currently in the repo. Rendered as a review diff before commit.
 */
export interface DeployPlan {
  writes: DeployWrite[];
  deletes: DeployDelete[];
  /** Non-fatal notes, e.g. a referenced prompt file that is missing from the repo. */
  warnings: string[];
}

/**
 * Drift for one deployed workflow: the blueprint hash embedded in its generated header
 * versus the hash of the current blueprint's freshly compiled output.
 */
export interface DriftItem {
  path: string;
  /** Hash parsed from the deployed file's header, or null if unparseable/absent. */
  deployedHash: string | null;
  compiledHash: string;
  drifted: boolean;
}

// ── telemetry (seed 04) ────────────────────────────────────────────────

/** Machine/line LED semantics (ARCHITECTURE §6): success / running / failed / never-ran. */
export type LedState = 'on' | 'warn' | 'bad' | 'idle';

/** A conclusion string from the Actions API, or null while a run is still in progress. */
export type RunConclusion =
  | 'success'
  | 'failure'
  | 'cancelled'
  | 'timed_out'
  | 'skipped'
  | 'action_required'
  | 'neutral'
  | 'stale'
  | 'startup_failure'
  | null;

/** One GitHub Actions run of a `factory--*` workflow. */
export interface FactoryRun {
  /** Workflow file path, e.g. `.github/workflows/factory--issue-triage-line.yml`. */
  path: string;
  /** Slug parsed from the path, e.g. `issue-triage-line`. */
  slug: string;
  runId: number;
  runNumber: number;
  status: 'queued' | 'in_progress' | 'completed' | (string & {});
  conclusion: RunConclusion;
  event: string;
  htmlUrl: string;
  /** ISO timestamps; runStartedAt is null before the run actually starts. */
  runStartedAt: string | null;
  updatedAt: string;
  createdAt: string;
  /** 1 for a first attempt; >1 means the run was re-run (the rework signal). */
  runAttempt: number;
}

/** One registered workflow from the Actions workflows API (id needed to enable/disable). */
export interface RepoWorkflow {
  id: number;
  name: string;
  /** `.github/workflows/<file>.yml`, or `dynamic/…` for GitHub-injected workflows. */
  path: string;
  /** `active` | `disabled_manually` | `disabled_inactivity` | … */
  state: string;
  htmlUrl: string;
}

/** Result of a conditional (ETag) runs poll. A 304 sets `notModified` and empty `runs`. */
export interface RunsPoll {
  runs: FactoryRun[];
  etag: string | null;
  notModified: boolean;
  /** `x-ratelimit-remaining` header value when present, for polite backoff. */
  rateRemaining: number | null;
}

/** One step of a run job (drill-down detail). */
export interface RunJobStep {
  number: number;
  name: string;
  status: string;
  conclusion: RunConclusion;
}

/** One job of a workflow run — the Monitor tab's drill-down unit. */
export interface RunJob {
  jobId: number;
  name: string;
  status: 'queued' | 'in_progress' | 'completed' | (string & {});
  conclusion: RunConclusion;
  startedAt: string | null;
  completedAt: string | null;
  htmlUrl: string;
  steps: RunJobStep[];
}

/**
 * Transport surface. Implemented by a thin fetch-based client (no Octokit dep — keeps
 * the static bundle lean and trivially mockable via `globalThis.fetch`). Every method
 * rejects with a {@link GithubError} on non-2xx.
 */
export interface GithubClient {
  /** Authenticated login (from GET /user at connect time). */
  readonly login: string;

  /** Best-effort permission check for a repo. Never throws for permission gaps; maps them to `missing`. */
  preflight(repo: RepoRef): Promise<Preflight>;

  /** Read a file, or `null` if it does not exist (404). Throws on other errors. */
  getFile(repo: RepoRef, path: string, ref?: string): Promise<RepoFile | null>;

  /** List a directory, or `[]` if it does not exist. */
  listDir(repo: RepoRef, path: string, ref?: string): Promise<RepoDirEntry[]>;

  /** Create or update a file (Contents API). Pass `sha` to update, `branch` to target a branch. */
  putFile(
    repo: RepoRef,
    path: string,
    content: string,
    message: string,
    opts?: { sha?: string; branch?: string },
  ): Promise<void>;

  /** Delete a file (Contents API). */
  deleteFile(
    repo: RepoRef,
    path: string,
    sha: string,
    message: string,
    opts?: { branch?: string },
  ): Promise<void>;

  /** Default branch name (e.g. `main`). */
  getDefaultBranch(repo: RepoRef): Promise<string>;

  /** Create a new branch `newBranch` pointing at the tip of `fromBranch`. */
  createBranch(repo: RepoRef, newBranch: string, fromBranch: string): Promise<void>;

  /** Open a pull request; returns the html_url. */
  createPullRequest(
    repo: RepoRef,
    args: { title: string; head: string; base: string; body?: string },
  ): Promise<string>;

  /** Repo public key for sealed-box secret encryption. */
  getActionsPublicKey(repo: RepoRef): Promise<ActionsPublicKey>;

  /** Whether an Actions secret with this name exists (metadata only; value never returned). */
  hasSecret(repo: RepoRef, name: string): Promise<boolean>;

  /** Create/update an Actions secret with an already sealed-box-encrypted value. */
  putSecret(repo: RepoRef, name: string, encryptedValue: string, keyId: string): Promise<void>;

  /**
   * List recent runs of `factory--*` workflows, newest first. Pass a prior `etag` for a
   * conditional request — a 304 returns `{ notModified: true, runs: [] }` and costs no
   * rate quota. Never throws for an empty/absent Actions history.
   */
  listFactoryRuns(
    repo: RepoRef,
    opts?: { etag?: string | null; perPage?: number; pathPrefix?: string },
  ): Promise<RunsPoll>;

  /** Jobs (with steps) for one run — the Monitor drill-down. */
  listRunJobs(repo: RepoRef, runId: number): Promise<RunJob[]>;

  /** Fire a workflow_dispatch for a workflow file (e.g. `factory--x.yml`). Defaults to the default branch. */
  dispatchWorkflow(repo: RepoRef, workflowFile: string, ref?: string): Promise<void>;

  /** Cancel an in-progress run. */
  cancelRun(repo: RepoRef, runId: number): Promise<void>;

  /**
   * Registered workflows for a repo (id, path, `state` — the disable/enable handle).
   * Never throws for a repo without Actions — returns `[]` on 403/404.
   */
  listRepoWorkflows(repo: RepoRef): Promise<RepoWorkflow[]>;

  /** Re-run a completed run (all jobs) — the "clear the jam" maintain action. */
  rerunRun(repo: RepoRef, runId: number): Promise<void>;

  /** Enable or disable a workflow by id — powering a machine on/off from the cockpit. */
  setWorkflowEnabled(repo: RepoRef, workflowId: number, enabled: boolean): Promise<void>;

  /** Open an issue (the audit's "file a work order" action); returns the html_url. */
  createIssue(
    repo: RepoRef,
    args: { title: string; body: string; labels?: string[] },
  ): Promise<string>;

  /**
   * List repository Actions variables (the enablement-gate kill switches). Never throws for
   * an empty/absent list or missing permission — returns `[]`. Values are readable (unlike
   * secrets), which is exactly what lets the app show a line as armed or idle.
   */
  /**
   * Repo Actions variables, or `null` when they could not be read (no permission,
   * no Actions). `null` is NOT the same as `[]`: an empty list means the repo really
   * has no variables, so a kill switch is genuinely off, while `null` means we do not
   * know — and a cockpit must not draw a running loop as stopped.
   */
  listVariables(repo: RepoRef): Promise<RepoVariable[] | null>;

  /** Read one Actions variable, or `null` if unset. */
  getVariable(repo: RepoRef, name: string): Promise<RepoVariable | null>;

  /** Create or update an Actions variable (PATCH if it exists, else POST). */
  setVariable(repo: RepoRef, name: string, value: string): Promise<void>;
}

/** A repository Actions variable — an enablement-gate kill switch. Values are plaintext. */
export interface RepoVariable {
  name: string;
  value: string;
}

/** Error carrying the HTTP status so callers can branch on 401/403/404/422. */
export class GithubError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly url: string,
  ) {
    super(message);
    this.name = 'GithubError';
  }
}
