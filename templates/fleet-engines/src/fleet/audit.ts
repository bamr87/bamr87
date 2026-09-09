// Alignment-audit rules engine — Fleet Ops' "certification" pass. Grades one repo's
// reverse-engineered WorkflowFacts against the real bamr87 fleet conventions
// (ground-truthed by survey): OAuth-first Claude auth, default-OFF vars.*_ENABLED
// kill switches on scheduled AI, loop guards on event-triggered writers, near-universal
// concurrency blocks, least-privilege permissions, plan/apply duality on mutating
// crons, sticky-marker dedup on issue-filing crons, and the standard trio (a CI
// workflow + the @claude mention handler + the markdown-oneline prose kit).
//
// Every rule is ONE entry in a single data-driven list (meta + applies + violations),
// so the published rulebook (AUDIT_RULES) and the checkers cannot drift — there is no
// parallel switch statement. `applies` is deliberately separate from the violation
// check: a rule only counts as *passed* when it actually applied and stayed silent;
// silence from an inapplicable rule is neither pass nor fail. Pure and total: no I/O,
// no globals, no clock, never throws.

import type {
  ActionUse,
  Archetype,
  AuditFinding,
  AuditRuleMeta,
  Grade,
  RepoAudit,
  SinkKind,
  WorkflowFacts,
} from './types.js';

// ── rule plumbing ─────────────────────────────────────────────────────────────

/** Everything repo-scoped rules see: the facts plus the optional live workflow states. */
interface RepoContext {
  facts: WorkflowFacts[];
  /** path → Actions API `state` (e.g. `active`, `disabled_manually`), when polled. */
  workflowStates: Record<string, string> | undefined;
}

/** A violation from a workflow-scoped rule; the runner supplies ruleId/severity/path. */
interface WorkflowViolation {
  message: string;
  fix: string;
}

/** A violation from a repo-scoped rule; carries its own path (null = repo-wide). */
interface RepoViolation extends WorkflowViolation {
  path: string | null;
}

interface WorkflowRule {
  scope: 'workflow';
  meta: AuditRuleMeta;
  applies: (f: WorkflowFacts) => boolean;
  violations: (f: WorkflowFacts) => WorkflowViolation[];
}

interface RepoRule {
  scope: 'repo';
  meta: AuditRuleMeta;
  applies: (ctx: RepoContext) => boolean;
  violations: (ctx: RepoContext) => RepoViolation[];
}

type AuditRule = WorkflowRule | RepoRule;

function wfRule(
  meta: AuditRuleMeta,
  applies: WorkflowRule['applies'],
  violations: WorkflowRule['violations'],
): WorkflowRule {
  return { scope: 'workflow', meta, applies, violations };
}

function repoRule(
  meta: AuditRuleMeta,
  applies: RepoRule['applies'],
  violations: RepoRule['violations'],
): RepoRule {
  return { scope: 'repo', meta, applies, violations };
}

// ── shared predicates ─────────────────────────────────────────────────────────

/** Events whose payloads a writer can retrigger — the feedback-loop surface. */
const LOOP_EVENT_TRIGGERS = ['issue_comment', 'issues', 'pull_request', 'pull_request_target'];

/** Sinks that can feed one of those events back. */
const LOOP_WRITE_SINKS: SinkKind[] = ['comment', 'issue', 'label', 'pr', 'commit'];

/** Triggers where parallel runs pile up or race without a concurrency group. */
const PILE_UP_TRIGGERS = ['push', 'pull_request', 'schedule'];

/** Sinks that mutate repo state — the plan/apply-duality surface. */
const MUTATING_SINKS: SinkKind[] = ['commit', 'pr', 'issue', 'merge'];

function hasTrigger(f: WorkflowFacts, kinds: string[]): boolean {
  return f.triggers.some((t) => kinds.includes(t.kind));
}

/** Deduped trigger kinds of `f` that fall in `kinds`, for citing evidence. */
function triggersIn(f: WorkflowFacts, kinds: string[]): string[] {
  return Array.from(new Set(f.triggers.map((t) => t.kind).filter((k) => kinds.includes(k))));
}

/** The subset of `f.sinks` in `kinds` — intersection test and evidence in one. */
function sinksIn(f: WorkflowFacts, kinds: SinkKind[]): SinkKind[] {
  return f.sinks.filter((s) => kinds.includes(s));
}

/**
 * Reusable-workflow refs (`…/x.yml@main`) may float on a branch by fleet convention —
 * the hub's standard-ci.yml callers all track @main — so the pin rules exclude them.
 */
function isReusableWorkflowRef(a: ActionUse): boolean {
  return /\.ya?ml$/i.test(a.action);
}

/** A marketplace action `uses:` — excludes reusable-workflow refs (`…/*.yml`) and local composites. */
function isMarketplaceAction(a: ActionUse): boolean {
  return !isReusableWorkflowRef(a) && a.pin !== 'local';
}

/**
 * Whether a `pull_request`/`pull_request_target` trigger subscribes to a given activity.
 * facts.ts surfaces the explicit `types:` in the trigger `detail`; a MISSING detail means
 * the `types:` block was omitted, so GitHub's DEFAULT PR activity set — [opened, synchronize,
 * reopened] — applies. So `synchronize`/`opened`/`reopened` count when the detail is absent
 * (the default includes them), while non-default activities like `labeled` count only when
 * an explicit `detail` names them.
 */
function prSubscribes(f: WorkflowFacts, activity: string, inDefaultSet: boolean): boolean {
  return f.triggers.some((t) => {
    if (t.kind !== 'pull_request' && t.kind !== 'pull_request_target') return false;
    if (t.detail === undefined) return inDefaultSet; // no types: → GitHub default set
    return t.detail.includes(activity);
  });
}

/** A self-push (`commit` to the PR branch) re-emits `synchronize`, which is in the default set. */
function subscribesSynchronize(f: WorkflowFacts): boolean {
  return prSubscribes(f, 'synchronize', true);
}

/**
 * The write sinks that can retrigger this workflow: a sink is loopy only when the event it
 * emits is one the workflow already subscribes to. Emission map — comment→issue_comment;
 * issue→issues; label→issues(labeled) for an issue label OR pull_request(labeled) for a PR
 * label; pr→pull_request(opened); merge→nothing (terminal); commit→push (always) plus
 * pull_request(synchronize) when the PR trigger subscribes to synchronize. A writer whose
 * sinks emit nothing it listens for cannot feed itself and needs no guard.
 */
function selfRetriggerSinks(f: WorkflowFacts): SinkKind[] {
  const subscribed = new Set(f.triggers.map((t) => t.kind));
  const prFamily = subscribed.has('pull_request') || subscribed.has('pull_request_target');
  const sync = subscribesSynchronize(f);
  // `labeled` is NOT in the default PR set, so it only counts with an explicit `types:`.
  const prLabeled = prFamily && prSubscribes(f, 'labeled', false);
  const loops = (s: SinkKind): boolean => {
    switch (s) {
      case 'comment':
        return subscribed.has('issue_comment');
      case 'issue':
        return subscribed.has('issues');
      case 'label':
        // the `label` sink can be an issue label (→issues) or a PR label (→pull_request labeled)
        return subscribed.has('issues') || prLabeled;
      case 'pr':
        return prFamily;
      case 'commit':
        return subscribed.has('push') || (prFamily && sync);
      default:
        return false; // merge (terminal), deploy, cross_repo_issue, dispatch — emit nothing we listen for
    }
  };
  return f.sinks.filter(loops);
}

// ── the rulebook ──────────────────────────────────────────────────────────────

const RULES: readonly AuditRule[] = [
  wfRule(
    {
      id: 'auth-oauth-first',
      title: 'OAuth-first Claude auth',
      severity: 'warn',
      standard:
        'AI workflows authenticate with CLAUDE_CODE_OAUTH_TOKEN first and keep ANTHROPIC_API_KEY only as the fallback.',
    },
    (f) => f.ai.present,
    (f) =>
      f.ai.authMode === 'api-key-only'
        ? [
            {
              message:
                'uses ANTHROPIC_API_KEY only; fleet convention is OAuth-first (CLAUDE_CODE_OAUTH_TOKEN with API-key fallback)',
              fix: 'Pass claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }} first and keep anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }} as the fallback.',
            },
          ]
        : [],
  ),

  wfRule(
    {
      id: 'kill-switch',
      title: 'Kill switch on scheduled AI',
      severity: 'fail',
      standard:
        'Scheduled AI lines gate on a default-OFF vars.*_ENABLED repo variable so they can be disarmed without a redeploy.',
    },
    (f) => f.ai.present && f.crons.length > 0,
    (f) =>
      f.killSwitches.length === 0
        ? [
            {
              message: `scheduled AI line with no vars.*_ENABLED kill switch — cannot be disarmed without a redeploy (crons: ${f.crons.join(', ')})`,
              fix: "Gate the job with if: vars.<LINE>_ENABLED == 'true' (a default-OFF repo variable) so the schedule can be disarmed from repo settings.",
            },
          ]
        : [],
  ),

  wfRule(
    {
      id: 'loop-safety',
      title: 'Loop guard on self-retriggering writers',
      severity: 'fail',
      standard:
        'A workflow whose write sink can re-emit an event it subscribes to carries at least one loop guard; a writer that cannot retrigger itself (its sink emits nothing it listens for) needs none.',
    },
    (f) => hasTrigger(f, LOOP_EVENT_TRIGGERS) && sinksIn(f, LOOP_WRITE_SINKS).length > 0,
    (f) => {
      const loopy = selfRetriggerSinks(f);
      if (loopy.length === 0) return [];
      // A GENERAL guard (attempt limit, label opt-in, actor guard, rate limiter, gate job,
      // singleton concurrency, sticky marker, …) breaks any loop. `synchronize-skip` is
      // narrower: it neutralizes ONLY the commit→synchronize path, so it counts only when
      // every loopy sink is `commit` — never for a label/comment/pr self-retrigger.
      const generalGuards = f.guards.filter((g) => g !== 'synchronize-skip');
      if (generalGuards.length > 0) return [];
      if (f.guards.includes('synchronize-skip') && loopy.every((s) => s === 'commit')) return [];
      return [
        {
          message: `event-triggered writer with no loop guard — writing ${loopy.join(', ')} re-emits an event its own trigger subscribes to (${triggersIn(f, LOOP_EVENT_TRIGGERS).join(', ')})`,
          fix: 'Add a loop guard (attempt-limit counter, label opt-in, actor/bot guard, rate limiter, sticky marker, gate job, or singleton concurrency), or stop subscribing to the activity the sink emits (e.g. drop pull_request synchronize).',
        },
      ];
    },
  ),

  wfRule(
    {
      id: 'concurrency',
      title: 'Concurrency block',
      severity: 'warn',
      standard:
        'Push, pull_request, and scheduled workflows declare a concurrency group so runs cannot pile up or race.',
    },
    (f) => !f.isReusable && hasTrigger(f, PILE_UP_TRIGGERS),
    (f) =>
      f.concurrency.present
        ? []
        : [
            {
              message: `no concurrency block; parallel runs can pile up or race (triggers: ${triggersIn(f, PILE_UP_TRIGGERS).join(', ')})`,
              fix: 'Add a top-level concurrency block, e.g. concurrency: { group: "<line>-${{ github.ref }}", cancel-in-progress: true }.',
            },
          ],
  ),

  wfRule(
    {
      id: 'permissions',
      title: 'Least-privilege permissions',
      severity: 'warn',
      standard:
        'Every non-reusable workflow declares an explicit permissions block instead of inheriting the repo default token grants.',
    },
    (f) => !f.isReusable,
    (f) =>
      f.permissions.declared
        ? []
        : [
            {
              message: "no permissions block — the job runs with the repo's default token grants",
              fix: 'Declare a permissions: block with the minimal scopes each job needs (start from contents: read).',
            },
          ],
  ),

  wfRule(
    {
      id: 'top-level-write',
      title: 'Job-scoped write grants',
      severity: 'info',
      standard: 'Write scopes are escalated per job, never granted at the workflow top level.',
    },
    (f) => f.permissions.declared,
    (f) =>
      f.permissions.topLevelWrite
        ? [
            {
              message: `write scopes granted at the top level; prefer per-job escalation${
                f.permissions.writeScopes.length > 0
                  ? ` (write scopes in file: ${f.permissions.writeScopes.join(', ')})`
                  : ''
              }`,
              fix: 'Move write scopes down to the jobs that need them and keep the top level read-only.',
            },
          ]
        : [],
  ),

  wfRule(
    {
      id: 'ai-timeout',
      title: 'Timeout on AI jobs',
      severity: 'warn',
      standard: 'AI jobs declare timeout-minutes so a wedged agent cannot burn unbounded minutes.',
    },
    (f) => f.ai.present,
    (f) =>
      f.timeoutMinutes === null
        ? [
            {
              message: 'AI job without timeout-minutes — an unbounded cost risk',
              fix: 'Set timeout-minutes on the AI job (e.g. timeout-minutes: 30).',
            },
          ]
        : [],
  ),

  wfRule(
    {
      id: 'pin-branch',
      title: 'No branch-pinned actions',
      severity: 'warn',
      standard:
        'Actions are pinned to a tag or SHA; only reusable fleet-hub workflow refs may float on a branch.',
    },
    (f) => f.actions.some((a) => !isReusableWorkflowRef(a)),
    (f) =>
      f.actions
        .filter((a) => !isReusableWorkflowRef(a) && a.pin === 'branch')
        .map((a) => ({
          message: `${a.action}@${a.ref ?? '?'} — action pinned to a moving branch`,
          fix: `Pin ${a.action} to a release tag or commit SHA instead of @${a.ref ?? '?'}.`,
        })),
  ),

  wfRule(
    {
      id: 'pin-unpinned',
      title: 'No unpinned actions',
      severity: 'warn',
      standard: 'Every non-local uses: reference carries an explicit @ref pin.',
    },
    (f) => f.actions.some((a) => a.pin !== 'local'),
    (f) =>
      f.actions
        .filter((a) => a.pin === 'unpinned')
        .map((a) => ({
          message: `${a.action} has no @ref — it resolves to whatever the default branch holds`,
          fix: `Add an explicit pin: ${a.action}@<tag-or-sha>.`,
        })),
  ),

  repoRule(
    {
      id: 'pin-sha',
      title: 'SHA-pin marketplace actions',
      severity: 'info',
      standard:
        'In repos that pin marketplace actions to commit SHAs by convention (SHA-pins outnumber tag-pins), every marketplace action is SHA-pinned rather than left tag-pinned.',
    },
    ({ facts }) => {
      let sha = 0;
      let tag = 0;
      for (const f of facts) {
        for (const a of f.actions) {
          if (!isMarketplaceAction(a)) continue;
          if (a.pin === 'sha') sha += 1;
          else if (a.pin === 'tag') tag += 1;
        }
      }
      return sha > tag;
    },
    ({ facts }) => {
      const out: RepoViolation[] = [];
      for (const f of facts) {
        for (const a of f.actions) {
          if (!isMarketplaceAction(a) || a.pin !== 'tag') continue;
          out.push({
            path: f.path,
            message: `${a.action}@${a.ref ?? '?'} is tag-pinned while this repo SHA-pins marketplace actions by convention`,
            fix: `Pin ${a.action} to a full commit SHA (${a.action}@<sha>) to match the repo's SHA-pinning convention.`,
          });
        }
      }
      return out;
    },
  ),

  wfRule(
    {
      id: 'plan-apply',
      title: 'Plan/apply duality on mutating crons',
      severity: 'info',
      standard:
        'Mutating scheduled lines expose a plan-first (dry-run) apply input so a human can preview before the line writes.',
    },
    (f) => f.crons.length > 0 && sinksIn(f, MUTATING_SINKS).length > 0,
    (f) =>
      f.planApply
        ? []
        : [
            {
              message: `mutating scheduled line without a plan-first apply input (dry-run duality) — writes ${sinksIn(f, MUTATING_SINKS).join(', ')}`,
              fix: 'Add a workflow_dispatch apply input (default false) and keep the scheduled path plan-only.',
            },
          ],
  ),

  wfRule(
    {
      id: 'dormant-cron',
      title: 'No dormant schedules',
      severity: 'info',
      standard:
        'Commented-out cron lines are re-armed or removed rather than left as dead automation.',
    },
    (f) => f.crons.length > 0 || f.dormantCrons.length > 0,
    (f) =>
      f.dormantCrons.length > 0
        ? [
            {
              message: `schedule is commented out — dormant automation; re-arm or remove it (${f.dormantCrons.join(', ')})`,
              fix: 'Uncomment the cron to re-arm the schedule, or delete the commented-out block.',
            },
          ]
        : [],
  ),

  wfRule(
    {
      id: 'sticky-marker',
      title: 'Sticky-marker dedup on issue-filing crons',
      severity: 'info',
      standard:
        'Scheduled issue-filers upsert against an HTML-comment marker instead of filing duplicates.',
    },
    (f) => f.crons.length > 0 && f.sinks.includes('issue'),
    (f) =>
      f.guards.includes('sticky-marker')
        ? []
        : [
            {
              message:
                'scheduled issue-filer without an HTML-comment dedup marker — risks duplicate issues',
              fix: 'Embed an HTML-comment marker (e.g. <!-- fleet:rule-id -->) in the issue body and update the marked issue when it already exists.',
            },
          ],
  ),

  repoRule(
    {
      id: 'standard-trio',
      title: 'Standard trio',
      severity: 'warn',
      standard:
        'Every fleet repo carries a CI workflow, the @claude mention handler, and the markdown-oneline prose kit.',
    },
    () => true,
    ({ facts }) => {
      const has = (...kinds: Archetype[]): boolean => facts.some((f) => kinds.includes(f.archetype));
      const out: RepoViolation[] = [];
      if (!has('standard-ci-caller', 'ci-gate')) {
        out.push({
          path: null,
          message:
            "standard trio: no CI workflow — nothing with archetype 'standard-ci-caller' or 'ci-gate'",
          fix: 'Add the thin caller of the hub reusable standard-ci.yml (or a repo-local CI gate).',
        });
      }
      if (!has('mention-handler')) {
        out.push({
          path: null,
          message: "standard trio: no @claude mention handler — nothing with archetype 'mention-handler'",
          fix: 'Seed the @claude mention workflow from the agent-context kit (standardize fan-out).',
        });
      }
      if (!has('prose-kit')) {
        out.push({
          path: null,
          message:
            "standard trio: no markdown-oneline prose kit — nothing with archetype 'prose-kit'",
          fix: 'Seed the markdown-oneline prose workflow (fan-out kit: prose).',
        });
      }
      return out;
    },
  ),

  repoRule(
    {
      id: 'disabled-workflow',
      title: 'No disabled workflows',
      severity: 'info',
      standard: 'Disabled workflows are dead weight — re-enabled or deleted, never left lingering.',
    },
    ({ workflowStates }) =>
      workflowStates !== undefined && Object.keys(workflowStates).length > 0,
    ({ workflowStates }) =>
      Object.entries(workflowStates ?? {})
        .filter(([, state]) => typeof state === 'string' && state.startsWith('disabled'))
        .map(([path, state]) => ({
          path,
          message: `workflow is disabled (${state}) — dead weight; remove it or re-enable it`,
          fix: 'Re-enable the workflow from the Actions tab, or delete the file if the line is retired.',
        })),
  ),
];

// ── public API ────────────────────────────────────────────────────────────────

/** The rulebook, in check order — what the UI renders as the certification standard. */
export const AUDIT_RULES: AuditRuleMeta[] = RULES.map((r) => r.meta);

/**
 * Run every workflow-scoped rule against one workflow's facts. Repo-scoped rules
 * (standard-trio, disabled-workflow) only run in {@link auditRepo}. PURE and total.
 */
export function auditWorkflow(f: WorkflowFacts): AuditFinding[] {
  const out: AuditFinding[] = [];
  for (const rule of RULES) {
    if (rule.scope !== 'workflow' || !rule.applies(f)) continue;
    for (const v of rule.violations(f)) {
      out.push({
        ruleId: rule.meta.id,
        severity: rule.meta.severity,
        path: f.path,
        message: v.message,
        fix: v.fix,
      });
    }
  }
  return out;
}

/**
 * Certify one repo's whole workflow fleet: all workflow-scoped rules across every
 * workflow, plus the repo-scoped rules. `opts.workflowStates` (path → Actions API
 * state) feeds the disabled-workflow rule when the caller has polled live states.
 *
 * Scoring: 100 − 10·fails − 3·warns − 1·infos, clamped to 0–100. A rule lands in
 * `passedRules` only when it applied to ≥1 workflow (or to the repo) and produced
 * zero findings — a rule that never applied is neither passed nor failed.
 */
export function auditRepo(
  facts: WorkflowFacts[],
  opts?: { workflowStates?: Record<string, string> },
): RepoAudit {
  const ctx: RepoContext = { facts, workflowStates: opts?.workflowStates };
  const findings: AuditFinding[] = [];
  const passedRules: string[] = [];

  for (const rule of RULES) {
    let applied = false;
    const before = findings.length;
    if (rule.scope === 'workflow') {
      for (const f of facts) {
        if (!rule.applies(f)) continue;
        applied = true;
        for (const v of rule.violations(f)) {
          findings.push({
            ruleId: rule.meta.id,
            severity: rule.meta.severity,
            path: f.path,
            message: v.message,
            fix: v.fix,
          });
        }
      }
    } else if (rule.applies(ctx)) {
      applied = true;
      for (const v of rule.violations(ctx)) {
        findings.push({
          ruleId: rule.meta.id,
          severity: rule.meta.severity,
          path: v.path,
          message: v.message,
          fix: v.fix,
        });
      }
    }
    if (applied && findings.length === before) passedRules.push(rule.meta.id);
  }

  let fails = 0;
  let warns = 0;
  let infos = 0;
  const byWorkflow: RepoAudit['byWorkflow'] = {};
  for (const f of facts) byWorkflow[f.path] = { fails: 0, warns: 0, infos: 0 };
  for (const fd of findings) {
    if (fd.severity === 'fail') fails += 1;
    else if (fd.severity === 'warn') warns += 1;
    else infos += 1;
    if (fd.path === null) continue;
    const cell = byWorkflow[fd.path] ?? { fails: 0, warns: 0, infos: 0 };
    byWorkflow[fd.path] = cell;
    if (fd.severity === 'fail') cell.fails += 1;
    else if (fd.severity === 'warn') cell.warns += 1;
    else cell.infos += 1;
  }

  const score = Math.max(0, Math.min(100, 100 - 10 * fails - 3 * warns - infos));
  return { score, grade: gradeFor(score, findings), findings, passedRules, byWorkflow };
}

/**
 * Factorio-style certification grade. 'S' demands a spotless run (no fail, no warn,
 * score ≥ 95 — infos alone can't block it); 'A' tolerates warns at ≥ 85 but no fail;
 * below that only the score matters: 'B' ≥ 70, 'C' ≥ 50, else 'D'.
 */
export function gradeFor(score: number, findings: AuditFinding[]): Grade {
  const hasFail = findings.some((f) => f.severity === 'fail');
  const hasWarn = findings.some((f) => f.severity === 'warn');
  if (!hasFail && !hasWarn && score >= 95) return 'S';
  if (!hasFail && score >= 85) return 'A';
  if (score >= 70) return 'B';
  if (score >= 50) return 'C';
  return 'D';
}
