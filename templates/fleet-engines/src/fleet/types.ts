// Observe-mode data model. A "fleet" is a read-only reverse-import of a repo's
// .github/workflows/*.yml — one node per workflow, belts for workflow_run chains and
// cross-repo `--repo` emissions. This is how GitFactory plugs into ANY repo (including
// hand-built ones like lifehacker.dev) without shoehorning them into the authoring
// machine types. Nothing here writes to the target repo.

import type { RepoRef } from '../github/types.js';
import type { FleetLane, FleetManifest } from '../harness/lanes.js';

/** Coarse classification of what a workflow writes. */
export type SinkKind =
  | 'pr'
  | 'issue'
  | 'comment'
  | 'label'
  | 'commit'
  | 'merge'
  | 'deploy'
  | 'cross_repo_issue'
  | 'dispatch';

/** One entry from a workflow's `on:` block, summarized for display. */
export interface TriggerSummary {
  /** e.g. push | pull_request | issues | issue_comment | schedule | workflow_dispatch | workflow_run | repository_dispatch */
  kind: string;
  /** cron string, workflow_run source names, event types, etc. */
  detail?: string;
}

/** The AI step a workflow runs, if any. */
export interface AgentInfo {
  runner: 'claude-run' | 'claude-code-action' | 'run-sh' | 'unknown';
  /** named role from .claude/agents/<name> when passed via the `agent:` input. */
  agentName?: string;
  model?: string;
  /** --allowedTools string, when discoverable. */
  tools?: string;
}

/** One workflow file, reverse-imported. Node id on the canvas === `path`. */
export interface ImportedWorkflow {
  path: string; // .github/workflows/content-factory.yml
  name: string; // `name:` field, or the filename
  slug: string; // basename without extension
  triggers: TriggerSummary[];
  hasAgent: boolean;
  agent?: AgentInfo;
  sinks: SinkKind[];
  /** workflow NAMES this runs after (on.workflow_run.workflows); resolved to edges by buildFleet. */
  runAfterNames: string[];
  /** owner/name repos this workflow writes to via `gh … --repo`. */
  crossRepoTargets: string[];
  /** a `*_ENABLED`-style kill-switch variable, if the workflow gates on one. */
  gate?: string;
  /** The `fleet/v1` lane the repo's committed `fleet.manifest.yml` records for this file (specs/014). */
  lane?: FleetLane;
}

export type FleetEdgeKind = 'workflow_run' | 'cross_repo';

/** A belt between two fleet nodes. `to` is a workflow path or an external repo id `ext:owner/name`. */
export interface FleetEdge {
  id: string;
  from: string;
  to: string;
  kind: FleetEdgeKind;
  label?: string;
}

/** The full reverse-imported picture of one repo's automation. */
export interface Fleet {
  repo: RepoRef;
  workflows: ImportedWorkflow[];
  /** external repos targeted cross-repo, as `owner/name`. Canvas node id === `ext:owner/name`. */
  externalRepos: string[];
  edges: FleetEdge[];
  /** non-fatal parse notes (e.g. a workflow whose YAML could not be parsed). */
  warnings: string[];
  /** The repo's committed `fleet.manifest.yml` — the hub's interchange contract — when it has one. */
  manifest?: FleetManifest | null;
}

/** Stable canvas node id for an external repo target. */
export const externalNodeId = (ownerName: string): string => `ext:${ownerName}`;

// ── Fleet Ops: deep workflow facts (the "machine inspection report") ─────────
//
// WorkflowFacts is the full reverse-engineered picture of ONE workflow file —
// everything the audit rules, the metrics labeler, and the cockpit UI need.
// Extracted by fleet/facts.ts (pure, total, never throws), grounded in the real
// bamr87 fleet: signals live in `env:`/`run:` blocks and prompt strings as often
// as in the YAML structure, so extraction mixes parsed YAML with raw-text scans.

/** Coarse cost-grouping type — port of the dash's ordered-substring classifier. */
export type DashType =
  | 'dependencies'
  | 'security'
  | 'ai'
  | 'release'
  | 'deploy'
  | 'docs'
  | 'automation'
  | 'ci'
  | 'other';

/** Fleet workflow archetype — the design-pattern taxonomy observed across the fleet. */
export type Archetype =
  | 'standard-ci-caller' // thin `uses: …/standard-ci.yml@main` wrapper
  | 'mention-handler' // the @claude comment/issue handler
  | 'prose-kit' // seeded markdown-oneline enforcer
  | 'ci-gate' // repo-local CI pipeline (push+PR, no writes)
  | 'pr-gate' // PR-only deterministic gate (lint/validate → comment/label)
  | 'pr-editor' // PR-triggered AI reviewer/editor (no merge)
  | 'reusable-library' // `on: workflow_call` — called by others
  | 'content-factory' // cron agent producing content PRs
  | 'issue-to-content' // issue-triggered AI that opens a content PR (e.g. quest-forge)
  | 'agent-gatekeeper' // issue-triggered AI reviewer that labels/comments, no PR
  | 'agentic-validator' // agent that plays/validates content end-to-end (agentic_validate)
  | 'perfection-loop' // scheduled plan→fan-out→fix AI content loop
  | 'auto-merge-bot' // merges green bot PRs under policy
  | 'self-repair' // workflow_run-on-failure fixer loop
  | 'issue-autopilot' // triage→verify→resolve issue pipeline
  | 'nightly-audit' // scheduled sweep → sticky issue
  | 'autonomy-loop' // scheduled self-audit/evolve that opens an improvement PR
  | 'cross-repo-filer' // writes issues/PRs to another repo
  | 'scout' // web-reading discovery agent
  | 'meta-loop' // measures/improves the automation itself
  | 'ledger' // sweeps artifacts/API into committed data
  | 'dispatch-hub' // plans + fans out role agents
  | 'generated-line' // ⚙ GENERATED BY GITFACTORY output
  | 'release' // release-please pipeline
  | 'security-gate' // codeql / secret-scan / policy gate
  | 'deploy' // pushes to Pages/worker/registry
  | 'data-sync' // normalizes/synchronizes committed data
  | 'dependency-bot' // dependency update/merge automation
  | 'other';

/** How a `uses:` reference is pinned. */
export type PinStyle = 'sha' | 'tag' | 'branch' | 'local' | 'unpinned';

/** One `uses:` reference (marketplace action, local composite, or reusable workflow). */
export interface ActionUse {
  /** e.g. `actions/checkout`, `./.github/actions/claude-run`, `bamr87/bamr87/.github/workflows/standard-ci.yml`. */
  action: string;
  /** The `@ref` part, or null for local `./` uses. */
  ref: string | null;
  pin: PinStyle;
}

/** The Claude-auth wiring convention an AI workflow follows. */
export type AuthMode = 'oauth-first' | 'oauth-only' | 'api-key-only' | 'none';

/** Loop-safety / governance guard mechanisms actually used in the fleet. */
export type GuardKind =
  | 'attempt-limit' // MAX_ATTEMPTS counter (comments or git log)
  | 'label-opt-in' // requires an opt-in label before acting
  | 'actor-guard' // actor/author_association/bot-login check
  | 'rate-limiter' // counts today's runs, refuses past a cap
  | 'synchronize-skip' // skips its own push-triggered re-run
  | 'smuggle-guard' // re-classifies the diff before merging
  | 'sticky-marker' // marker OR stable-title dedup for idempotent issue/comment upsert
  | 'same-repo-only' // refuses fork/other-repo heads
  | 'mention-phrase' // only fires on an explicit @mention phrase
  | 'gate-job' // a `gate` job gating the line on a vars.*_ENABLED switch
  | 'concurrency-singleton'; // a per-entity concurrency group serializes the line

/** AI usage found in one workflow (per-file rollup; a file can mix runners). */
export interface AiFacts {
  present: boolean;
  /**
   * Which invocation shapes appear (a workflow can use several).
   * `agentic-engine` = a bare `@anthropic-ai/claude-code` CLI / `agentic_validate.py`
   * driver — the it-journey quest engine, the fleet's single biggest AI cost center.
   */
  runners: ('claude-code-action' | 'claude-cli' | 'claude-run' | 'run-sh' | 'agentic-engine' | 'other')[];
  /** Models named in the file; empty when the model lives in a composite/config (common). */
  models: string[];
  /** Largest --max-turns found, or null. */
  maxTurns: number | null;
  /** Hard dollar spend cap (`--max-cost-usd N`) — the fleet's only per-run cost ceiling, or null. */
  maxCostUsd: number | null;
  authMode: AuthMode;
  /** Named agent roles (`agent: x` / `--agent x`). */
  agents: string[];
}

/** Everything the cockpit knows about one workflow file. */
export interface WorkflowFacts {
  path: string;
  name: string;
  dashType: DashType;
  archetype: Archetype;

  // triggers & scheduling
  triggers: TriggerSummary[];
  /** Active cron strings from parsed `on.schedule`. */
  crons: string[];
  /** Cron strings present only in comments — dormant/disabled automation. */
  dormantCrons: string[];
  /** True when `on:` includes `workflow_call` (a reusable library). */
  isReusable: boolean;
  /** Reusable workflows this one calls (`uses: owner/repo/.github/workflows/x.yml@ref`). */
  reusableCalls: string[];

  // structure
  jobCount: number;
  hasMatrix: boolean;
  /** True when a matrix is computed at runtime (`matrix: fromJSON(needs.*.outputs.*)`) — unknown fan-out width. */
  matrixDynamic: boolean;
  /** Same-repo reusable-workflow calls (`uses: ./.github/workflows/x.yml`) — intra-repo belts. */
  localWorkflowCalls: string[];
  /**
   * True when the workflow spends its minutes WAITING (a `sleep` + `gh pr checks` poll
   * loop), not computing — its "cost" is wall-clock, retireable with `--auto` + required checks.
   */
  waitBound: boolean;
  /** Max declared job `timeout-minutes`, or null when none declared anywhere. */
  timeoutMinutes: number | null;
  runners: string[];
  concurrency: {
    present: boolean;
    group: string | null;
    cancelInProgress: 'always' | 'never' | 'conditional' | 'unset';
  };
  permissions: {
    /** True when any permissions block (top or job level) is declared. */
    declared: boolean;
    /** True when the top level declares read-only contents. */
    topLevelRead: boolean;
    /** True when the TOP level grants any write scope (prefer job-level grants). */
    topLevelWrite: boolean;
    /** Union of `scope: write` grants anywhere in the file. */
    writeScopes: string[];
  };
  /** All `uses:` references with pin style. */
  actions: ActionUse[];
  /** Local composite actions used (`./.github/actions/*`). */
  compositeLocals: string[];

  ai: AiFacts;

  // governance
  /** Repo-variable kill switches referenced anywhere (if/env/run), e.g. CONTENT_FACTORY_ENABLED. */
  killSwitches: string[];
  /** True when the workflow exposes a plan/apply (dry-run) dispatch input. */
  planApply: boolean;
  guards: GuardKind[];
  /** Token fallback chain in privilege order, e.g. ['FLEET_TOKEN','github.token']. */
  tokenChain: string[];
  /** All `secrets.*` names referenced. */
  secretsUsed: string[];
  /** All `vars.*` names referenced. */
  varsUsed: string[];

  // outputs
  sinks: SinkKind[];
  crossRepoTargets: string[];

  // provenance
  /** Set when the file carries the ⚙ GENERATED BY GITFACTORY header. */
  generated: { blueprintPath: string | null; hash: string | null } | null;
  /** Count of "MANUAL EDIT" markers in a generated file (blueprint drift risk). */
  manualEditMarkers: number;
}

// ── Fleet Ops: alignment audit (the "certification") ─────────────────────────

export type AuditSeverity = 'fail' | 'warn' | 'info';

/** Rule catalog entry — what the fleet standard is, for the UI's rulebook. */
export interface AuditRuleMeta {
  id: string;
  title: string;
  severity: AuditSeverity;
  /** One-sentence statement of the fleet convention this rule encodes. */
  standard: string;
}

/** One violation found in one workflow (or repo-wide when `path` is null). */
export interface AuditFinding {
  ruleId: string;
  severity: AuditSeverity;
  /** Workflow path, or null for a repo-level finding. */
  path: string | null;
  message: string;
  /** The concrete fix, phrased as an actionable instruction. */
  fix: string;
}

/** Factorio-style certification grade. */
export type Grade = 'S' | 'A' | 'B' | 'C' | 'D';

/** The audit result for one repo's whole workflow fleet. */
export interface RepoAudit {
  /** 0–100 conformance score (weighted: fail 10, warn 3, info 1). */
  score: number;
  grade: Grade;
  findings: AuditFinding[];
  /** Rule ids that were applicable and fully passed. */
  passedRules: string[];
  /** Per-workflow finding counts for the matrix view. */
  byWorkflow: Record<string, { fails: number; warns: number; infos: number }>;
}

// ── Fleet Ops: run metrics (port of the dash's actions_analytics formulas) ───

export type MetricFlag =
  | 'high-cost-low-value'
  | 'failing'
  | 'flaky'
  | 'slow'
  | 'cancel-heavy'
  | 'cron-heavy'
  | 'rework-heavy';

/** Windowed run metrics for one workflow. Cost = wall-clock minutes (shadow price). */
export interface WorkflowMetrics {
  path: string;
  name: string;
  dashType: DashType;
  runs: number;
  totalMin: number;
  avgMin: number;
  p95Min: number;
  wasteMin: number;
  runsPerWeek: number;
  success: number;
  failure: number;
  cancelled: number;
  other: number;
  successRatePct: number;
  effectivenessPct: number;
  schedPct: number;
  /** Runs with runAttempt > 1 — the rework signal (not in the dash; gitorio addition). */
  reworkRuns: number;
  reworkPct: number;
  /** Median queue latency in seconds (createdAt → runStartedAt), or null. */
  queueP50Sec: number | null;
  events: Record<string, number>;
  flags: MetricFlag[];
  /** Triage priority = wasteMin + totalMin × (1 − effectiveness/100). */
  priority: number;
}

/** Rollup across a group of workflows (a repo, a type, or the whole fleet). */
export interface MetricsRollup {
  runs: number;
  totalMin: number;
  wasteMin: number;
  effectivenessPct: number;
  successRatePct: number;
  reworkPct: number;
}

// ── Fleet Ops: roster (which repos make up the fleet) ────────────────────────

/** One repo in the fleet roster. Slugs only — never tokens (golden rule #7). */
export interface RosterEntry {
  /** `owner/name`. */
  slug: string;
  source: 'manual' | 'gitmodules';
  /** Tracked branch when known (from .gitmodules). */
  branch: string | null;
}
