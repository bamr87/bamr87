import { describe, expect, it } from 'vitest';
import { AUDIT_RULES, auditRepo, auditWorkflow, gradeFor } from './audit.js';
import type { AuditFinding, AuditSeverity, AuthMode, WorkflowFacts } from './types.js';

// ── fixtures: hand-built facts (facts.ts is a separate module; not imported) ──

/** WorkflowFacts with quiet defaults: no triggers, no AI, no crons, nothing declared. */
function makeFacts(over: Partial<WorkflowFacts> = {}): WorkflowFacts {
  return {
    path: '.github/workflows/wf.yml',
    name: 'wf',
    dashType: 'ci',
    archetype: 'other',
    triggers: [],
    crons: [],
    dormantCrons: [],
    isReusable: false,
    reusableCalls: [],
    jobCount: 1,
    hasMatrix: false,
    matrixDynamic: false,
    localWorkflowCalls: [],
    waitBound: false,
    timeoutMinutes: null,
    runners: ['ubuntu-latest'],
    concurrency: { present: false, group: null, cancelInProgress: 'unset' },
    permissions: { declared: false, topLevelRead: false, topLevelWrite: false, writeScopes: [] },
    actions: [],
    compositeLocals: [],
    ai: { present: false, runners: [], models: [], maxTurns: null, maxCostUsd: null, authMode: 'none', agents: [] },
    killSwitches: [],
    planApply: false,
    guards: [],
    tokenChain: [],
    secretsUsed: [],
    varsUsed: [],
    sinks: [],
    crossRepoTargets: [],
    generated: null,
    manualEditMarkers: 0,
    ...over,
  };
}

/** AiFacts for a present claude-code-action step in the given auth mode. */
function aiIn(authMode: AuthMode): WorkflowFacts['ai'] {
  return {
    present: true,
    runners: ['claude-code-action'],
    models: [],
    maxTurns: null,
    maxCostUsd: null,
    authMode,
    agents: [],
  };
}

/** Findings for one rule id. */
function ofRule(findings: AuditFinding[], id: string): AuditFinding[] {
  return findings.filter((x) => x.ruleId === id);
}

/** A minimal finding of a given severity, for exercising gradeFor directly. */
function sev(severity: AuditSeverity): AuditFinding {
  return { ruleId: 'x', severity, path: null, message: 'm', fix: 'f' };
}

// ── the rulebook ─────────────────────────────────────────────────────────────

describe('AUDIT_RULES', () => {
  it('lists every rule once with the spec severities', () => {
    const ids = AUDIT_RULES.map((r) => r.id);
    expect(new Set(ids).size).toBe(ids.length);
    const sevOf = Object.fromEntries(AUDIT_RULES.map((r) => [r.id, r.severity]));
    expect(sevOf['kill-switch']).toBe('fail');
    expect(sevOf['loop-safety']).toBe('fail');
    expect(sevOf['auth-oauth-first']).toBe('warn');
    expect(sevOf['pin-branch']).toBe('warn');
    expect(sevOf['standard-trio']).toBe('warn');
    expect(sevOf['pin-sha']).toBe('info');
    expect(sevOf['plan-apply']).toBe('info');
    expect(sevOf['sticky-marker']).toBe('info');
    expect(sevOf['disabled-workflow']).toBe('info');
  });
});

// ── workflow-scoped rules ────────────────────────────────────────────────────

describe('auth-oauth-first', () => {
  it('fires on api-key-only auth and passes on oauth-first', () => {
    const hit = ofRule(auditWorkflow(makeFacts({ ai: aiIn('api-key-only') })), 'auth-oauth-first');
    expect(hit).toHaveLength(1);
    expect(hit[0].severity).toBe('warn');
    expect(hit[0].message).toContain('ANTHROPIC_API_KEY only');
    expect(hit[0].message).toContain('OAuth-first');
    expect(hit[0].fix).toContain('CLAUDE_CODE_OAUTH_TOKEN');

    const ok = auditWorkflow(makeFacts({ ai: aiIn('oauth-first') }));
    expect(ofRule(ok, 'auth-oauth-first')).toHaveLength(0);
  });
});

describe('kill-switch', () => {
  it('fails a scheduled AI line with no *_ENABLED variable, citing the cron', () => {
    const hit = ofRule(
      auditWorkflow(makeFacts({ ai: aiIn('oauth-first'), crons: ['0 9 * * *'] })),
      'kill-switch',
    );
    expect(hit).toHaveLength(1);
    expect(hit[0].severity).toBe('fail');
    expect(hit[0].message).toContain('vars.*_ENABLED');
    expect(hit[0].message).toContain('0 9 * * *');
  });

  it('passes with a kill switch and does not apply to unscheduled AI', () => {
    const armed = makeFacts({
      ai: aiIn('oauth-first'),
      crons: ['0 9 * * *'],
      killSwitches: ['CONTENT_FACTORY_ENABLED'],
    });
    expect(ofRule(auditWorkflow(armed), 'kill-switch')).toHaveLength(0);

    const unscheduled = makeFacts({ ai: aiIn('api-key-only') });
    expect(ofRule(auditWorkflow(unscheduled), 'kill-switch')).toHaveLength(0);
  });
});

describe('loop-safety', () => {
  it('fails an unguarded event-triggered writer, citing trigger and sink', () => {
    const hit = ofRule(
      auditWorkflow(
        makeFacts({ triggers: [{ kind: 'issue_comment' }], sinks: ['comment'] }),
      ),
      'loop-safety',
    );
    expect(hit).toHaveLength(1);
    expect(hit[0].severity).toBe('fail');
    expect(hit[0].message).toContain('no loop guard');
    expect(hit[0].message).toContain('issue_comment');
    expect(hit[0].message).toContain('comment');
  });

  it('passes when any guard is present', () => {
    const guarded = makeFacts({
      triggers: [{ kind: 'issues' }],
      sinks: ['issue', 'commit'],
      guards: ['attempt-limit'],
    });
    expect(ofRule(auditWorkflow(guarded), 'loop-safety')).toHaveLength(0);
  });

  it('does not apply without both an event trigger and a write sink', () => {
    const readOnly = makeFacts({ triggers: [{ kind: 'pull_request' }], sinks: ['deploy'] });
    expect(ofRule(auditWorkflow(readOnly), 'loop-safety')).toHaveLength(0);
    const cronWriter = makeFacts({ triggers: [{ kind: 'schedule' }], sinks: ['pr'] });
    expect(ofRule(auditWorkflow(cronWriter), 'loop-safety')).toHaveLength(0);
  });

  // ── self-retrigger matrix: an unguarded writer only fails when its sink re-emits
  //    an event it subscribes to; otherwise it is safe and passes with no guard.
  it('passes an unguarded PR writer whose only sink is a comment (comment emits issue_comment, not pull_request)', () => {
    const safe = makeFacts({ triggers: [{ kind: 'pull_request', detail: 'opened' }], sinks: ['comment'] });
    expect(ofRule(auditWorkflow(safe), 'loop-safety')).toHaveLength(0);
  });

  it('passes a loopy issue_comment commenter guarded by a gate job', () => {
    const gated = makeFacts({
      triggers: [{ kind: 'issue_comment' }],
      sinks: ['comment'],
      guards: ['gate-job'],
    });
    expect(ofRule(auditWorkflow(gated), 'loop-safety')).toHaveLength(0);
  });

  it('passes a loopy issue_comment commenter serialized by a singleton concurrency group', () => {
    const gated = makeFacts({
      triggers: [{ kind: 'issue_comment' }],
      sinks: ['comment'],
      guards: ['concurrency-singleton'],
    });
    expect(ofRule(auditWorkflow(gated), 'loop-safety')).toHaveLength(0);
  });

  it('fails an unguarded commit writer on a pull_request that subscribes to synchronize', () => {
    const loopy = makeFacts({
      triggers: [{ kind: 'pull_request', detail: 'opened, synchronize' }],
      sinks: ['commit'],
    });
    const hit = ofRule(auditWorkflow(loopy), 'loop-safety');
    expect(hit).toHaveLength(1);
    expect(hit[0].severity).toBe('fail');
    expect(hit[0].message).toContain('commit');
    expect(hit[0].message).toContain('pull_request');
  });

  it('passes an unguarded commit writer on a pull_request WITHOUT synchronize (its own push cannot retrigger it)', () => {
    const safe = makeFacts({
      triggers: [{ kind: 'pull_request', detail: 'opened, reopened' }],
      sinks: ['commit'],
    });
    expect(ofRule(auditWorkflow(safe), 'loop-safety')).toHaveLength(0);
  });

  it('credits a repo whose event-triggered writers are all safe: loop-safety passes with no fail finding', () => {
    const audit = auditRepo([
      makeFacts({ path: '.github/workflows/content-quality.yml', triggers: [{ kind: 'pull_request', detail: 'opened' }], sinks: ['comment'] }),
      makeFacts({ path: '.github/workflows/content-review.yml', triggers: [{ kind: 'pull_request', detail: 'opened, reopened' }], sinks: ['commit'] }),
    ]);
    expect(ofRule(audit.findings, 'loop-safety')).toHaveLength(0);
    expect(audit.passedRules).toContain('loop-safety');
  });

  // A bare `on: pull_request` (no types:) defaults to [opened, synchronize, reopened], so a
  // self-push IS loopy — the default-set case the emission model must not miss.
  it('fails a bare pull_request (no types:) commit writer — the default set includes synchronize', () => {
    const loopy = makeFacts({ triggers: [{ kind: 'pull_request' }], sinks: ['commit'] });
    const hit = ofRule(auditWorkflow(loopy), 'loop-safety');
    expect(hit).toHaveLength(1);
    expect(hit[0].severity).toBe('fail');
  });

  // A PR-labeler on pull_request:[labeled] re-emits pull_request(labeled): a real self-loop.
  it('fails an unguarded PR labeler on pull_request:[labeled] (label re-emits pull_request labeled)', () => {
    const loopy = makeFacts({
      triggers: [{ kind: 'pull_request', detail: 'labeled' }],
      sinks: ['label'],
    });
    const hit = ofRule(auditWorkflow(loopy), 'loop-safety');
    expect(hit).toHaveLength(1);
    expect(hit[0].severity).toBe('fail');
  });

  // synchronize-skip only covers the commit→synchronize path; it must NOT bless a label loop
  // (a types:[labeled] trigger incidentally carries synchronize-skip from omitting synchronize).
  it('does not let synchronize-skip bless a non-commit (label) loop', () => {
    const loopy = makeFacts({
      triggers: [{ kind: 'pull_request', detail: 'labeled' }],
      sinks: ['label'],
      guards: ['synchronize-skip'],
    });
    expect(ofRule(auditWorkflow(loopy), 'loop-safety')).toHaveLength(1);
  });

  // …but a synchronize-subscribed commit writer with the `event.action != synchronize`
  // expression guard (synchronize-skip) IS correctly covered for the commit path.
  it('lets synchronize-skip cover a commit-only synchronize loop', () => {
    const covered = makeFacts({
      triggers: [{ kind: 'pull_request', detail: 'opened, synchronize' }],
      sinks: ['commit'],
      guards: ['synchronize-skip'],
    });
    expect(ofRule(auditWorkflow(covered), 'loop-safety')).toHaveLength(0);
  });
});

describe('concurrency', () => {
  it('warns on a push workflow without a concurrency block, passes with one', () => {
    const bare = makeFacts({ triggers: [{ kind: 'push' }] });
    const hit = ofRule(auditWorkflow(bare), 'concurrency');
    expect(hit).toHaveLength(1);
    expect(hit[0].severity).toBe('warn');
    expect(hit[0].message).toContain('pile up or race');
    expect(hit[0].message).toContain('push');

    const grouped = makeFacts({
      triggers: [{ kind: 'push' }],
      concurrency: { present: true, group: 'ci-${{ github.ref }}', cancelInProgress: 'always' },
    });
    expect(ofRule(auditWorkflow(grouped), 'concurrency')).toHaveLength(0);
  });

  it('exempts reusable workflows from concurrency and permissions', () => {
    const reusable = makeFacts({ isReusable: true, triggers: [{ kind: 'push' }] });
    const findings = auditWorkflow(reusable);
    expect(ofRule(findings, 'concurrency')).toHaveLength(0);
    expect(ofRule(findings, 'permissions')).toHaveLength(0);
  });
});

describe('permissions + top-level-write', () => {
  it('warns when no permissions block is declared, passes when one is', () => {
    const hit = ofRule(auditWorkflow(makeFacts()), 'permissions');
    expect(hit).toHaveLength(1);
    expect(hit[0].severity).toBe('warn');
    expect(hit[0].message).toContain('default token grants');

    const declared = makeFacts({
      permissions: { declared: true, topLevelRead: true, topLevelWrite: false, writeScopes: [] },
    });
    expect(ofRule(auditWorkflow(declared), 'permissions')).toHaveLength(0);
  });

  it('flags top-level write scopes (info) but not job-scoped ones', () => {
    const topLevel = makeFacts({
      permissions: {
        declared: true,
        topLevelRead: false,
        topLevelWrite: true,
        writeScopes: ['contents', 'issues'],
      },
    });
    const hit = ofRule(auditWorkflow(topLevel), 'top-level-write');
    expect(hit).toHaveLength(1);
    expect(hit[0].severity).toBe('info');
    expect(hit[0].message).toContain('top level');
    expect(hit[0].message).toContain('contents');

    const jobScoped = makeFacts({
      permissions: { declared: true, topLevelRead: true, topLevelWrite: false, writeScopes: ['contents'] },
    });
    expect(ofRule(auditWorkflow(jobScoped), 'top-level-write')).toHaveLength(0);
  });
});

describe('ai-timeout', () => {
  it('warns on an AI job without timeout-minutes, passes with one', () => {
    const hit = ofRule(auditWorkflow(makeFacts({ ai: aiIn('oauth-first') })), 'ai-timeout');
    expect(hit).toHaveLength(1);
    expect(hit[0].severity).toBe('warn');
    expect(hit[0].message).toContain('timeout-minutes');

    const bounded = makeFacts({ ai: aiIn('oauth-first'), timeoutMinutes: 30 });
    expect(ofRule(auditWorkflow(bounded), 'ai-timeout')).toHaveLength(0);
  });

  it('warns on an agentic-engine AI job (agentic_validate quest engine) with no timeout', () => {
    const agentic = makeFacts({
      path: '.github/workflows/quest-walkthrough.yml',
      archetype: 'agentic-validator',
      ai: {
        present: true,
        runners: ['agentic-engine'],
        models: [],
        maxTurns: 40,
        maxCostUsd: null,
        authMode: 'oauth-first',
        agents: [],
      },
    });
    const hit = ofRule(auditWorkflow(agentic), 'ai-timeout');
    expect(hit).toHaveLength(1);
    expect(hit[0].severity).toBe('warn');
    expect(hit[0].message).toContain('timeout-minutes');
  });
});

describe('pin rules', () => {
  it('warns once per branch-pinned action, citing action@ref', () => {
    const f = makeFacts({
      actions: [
        { action: 'actions/checkout', ref: 'main', pin: 'branch' },
        { action: 'actions/setup-node', ref: 'master', pin: 'branch' },
        { action: 'actions/cache', ref: 'v4', pin: 'tag' },
      ],
    });
    const hits = ofRule(auditWorkflow(f), 'pin-branch');
    expect(hits).toHaveLength(2);
    expect(hits[0].message).toContain('actions/checkout@main');
    expect(hits[0].message).toContain('moving branch');
    expect(hits[1].message).toContain('actions/setup-node@master');
  });

  it('excludes reusable-workflow refs (…/x.yml@main floats by convention)', () => {
    const f = makeFacts({
      actions: [
        { action: 'bamr87/bamr87/.github/workflows/standard-ci.yml', ref: 'main', pin: 'branch' },
      ],
      reusableCalls: ['bamr87/bamr87/.github/workflows/standard-ci.yml@main'],
    });
    expect(ofRule(auditWorkflow(f), 'pin-branch')).toHaveLength(0);
  });

  it('warns on unpinned non-local actions; local-only usage does not apply', () => {
    const unpinned = makeFacts({
      actions: [{ action: 'some/action', ref: null, pin: 'unpinned' }],
    });
    const hit = ofRule(auditWorkflow(unpinned), 'pin-unpinned');
    expect(hit).toHaveLength(1);
    expect(hit[0].message).toContain('some/action');

    const localOnly = makeFacts({
      actions: [{ action: './.github/actions/claude-run', ref: null, pin: 'local' }],
    });
    expect(ofRule(auditWorkflow(localOnly), 'pin-unpinned')).toHaveLength(0);
  });
});

describe('pin-sha', () => {
  it('flags tag-pinned marketplace actions in a SHA-majority repo, exempting reusable and local refs', () => {
    const shaLine = makeFacts({
      path: '.github/workflows/ci.yml',
      actions: [
        { action: 'actions/checkout', ref: 'a1b2c3d', pin: 'sha' },
        { action: 'actions/setup-node', ref: 'e4f5a6b', pin: 'sha' },
      ],
    });
    const tagLine = makeFacts({
      path: '.github/workflows/quest.yml',
      actions: [
        { action: 'actions/cache', ref: 'v4', pin: 'tag' },
        // reusable-workflow ref (…/*.yml) — exempt even when tag-pinned
        { action: 'bamr87/bamr87/.github/workflows/standard-ci.yml', ref: 'v1', pin: 'tag' },
        // local composite — exempt
        { action: './.github/actions/claude-run', ref: null, pin: 'local' },
      ],
    });
    const audit = auditRepo([shaLine, tagLine]);
    const hits = ofRule(audit.findings, 'pin-sha');
    expect(hits).toHaveLength(1);
    expect(hits[0].severity).toBe('info');
    expect(hits[0].path).toBe('.github/workflows/quest.yml');
    expect(hits[0].message).toContain('actions/cache@v4');
    expect(hits[0].message).toContain('SHA-pin');
    expect(hits[0].fix).toContain('actions/cache');
  });

  it('does not nag a tag-majority repo (edgar/law-style): rule never applies', () => {
    const tagHeavy = makeFacts({
      path: '.github/workflows/ci.yml',
      actions: [
        { action: 'actions/checkout', ref: 'v4', pin: 'tag' },
        { action: 'actions/setup-node', ref: 'v4', pin: 'tag' },
      ],
    });
    const onlySha = makeFacts({
      path: '.github/workflows/build.yml',
      actions: [{ action: 'actions/cache', ref: 'a1b2c3d', pin: 'sha' }],
    });
    const audit = auditRepo([tagHeavy, onlySha]);
    expect(ofRule(audit.findings, 'pin-sha')).toHaveLength(0);
    expect(audit.passedRules).not.toContain('pin-sha');
  });
});

describe('plan-apply', () => {
  it('notes a mutating cron without a plan-first input, passes with planApply', () => {
    const bare = makeFacts({ crons: ['0 4 * * *'], sinks: ['commit', 'pr'] });
    const hit = ofRule(auditWorkflow(bare), 'plan-apply');
    expect(hit).toHaveLength(1);
    expect(hit[0].severity).toBe('info');
    expect(hit[0].message).toContain('dry-run duality');

    const dual = makeFacts({ crons: ['0 4 * * *'], sinks: ['commit'], planApply: true });
    expect(ofRule(auditWorkflow(dual), 'plan-apply')).toHaveLength(0);
  });

  it('does not apply to a non-mutating cron', () => {
    const readOnly = makeFacts({ crons: ['0 4 * * *'], sinks: ['deploy'] });
    expect(ofRule(auditWorkflow(readOnly), 'plan-apply')).toHaveLength(0);
  });
});

describe('dormant-cron', () => {
  it('notes commented-out schedules citing the cron; active-only schedules pass', () => {
    const dormant = makeFacts({ dormantCrons: ['0 3 * * *'] });
    const hit = ofRule(auditWorkflow(dormant), 'dormant-cron');
    expect(hit).toHaveLength(1);
    expect(hit[0].severity).toBe('info');
    expect(hit[0].message).toContain('commented out');
    expect(hit[0].message).toContain('0 3 * * *');

    const active = makeFacts({ crons: ['0 3 * * *'] });
    expect(ofRule(auditWorkflow(active), 'dormant-cron')).toHaveLength(0);
  });
});

describe('sticky-marker', () => {
  it('notes a scheduled issue-filer without a marker, passes with the guard', () => {
    const bare = makeFacts({ crons: ['0 5 * * *'], sinks: ['issue'], planApply: true });
    const hit = ofRule(auditWorkflow(bare), 'sticky-marker');
    expect(hit).toHaveLength(1);
    expect(hit[0].severity).toBe('info');
    expect(hit[0].message).toContain('duplicate issues');

    const marked = makeFacts({
      crons: ['0 5 * * *'],
      sinks: ['issue'],
      planApply: true,
      guards: ['sticky-marker'],
    });
    expect(ofRule(auditWorkflow(marked), 'sticky-marker')).toHaveLength(0);
  });
});

describe('plan-apply + sticky-marker stay silent given corrected facts', () => {
  it('a plan/apply issue-filing cron with a sticky-marker guard fires neither rule', () => {
    // A nightly-audit line: facts.planApply true and the widened sticky-marker guard both set.
    const disciplined = makeFacts({
      path: '.github/workflows/nightly-audit.yml',
      archetype: 'nightly-audit',
      triggers: [{ kind: 'schedule', detail: '0 6 * * *' }, { kind: 'workflow_dispatch' }],
      crons: ['0 6 * * *'],
      sinks: ['issue'],
      planApply: true,
      guards: ['sticky-marker'],
    });
    const findings = auditWorkflow(disciplined);
    expect(ofRule(findings, 'plan-apply')).toHaveLength(0);
    expect(ofRule(findings, 'sticky-marker')).toHaveLength(0);

    const audit = auditRepo([disciplined]);
    expect(audit.passedRules).toContain('plan-apply');
    expect(audit.passedRules).toContain('sticky-marker');
  });
});

describe('exemplary workflow', () => {
  it('a fully conventional scheduled AI line yields zero findings', () => {
    const exemplary = makeFacts({
      path: '.github/workflows/content-factory.yml',
      name: 'content-factory',
      archetype: 'content-factory',
      triggers: [{ kind: 'schedule', detail: '0 9 * * *' }, { kind: 'workflow_dispatch' }],
      crons: ['0 9 * * *'],
      timeoutMinutes: 30,
      concurrency: { present: true, group: 'content-factory', cancelInProgress: 'never' },
      permissions: {
        declared: true,
        topLevelRead: true,
        topLevelWrite: false,
        writeScopes: ['contents', 'pull-requests'],
      },
      actions: [
        { action: 'actions/checkout', ref: 'v4', pin: 'tag' },
        { action: './.github/actions/claude-run', ref: null, pin: 'local' },
        { action: 'bamr87/bamr87/.github/workflows/standard-ci.yml', ref: 'main', pin: 'branch' },
      ],
      ai: {
        present: true,
        runners: ['claude-run'],
        models: ['claude-sonnet-4'],
        maxTurns: 30,
        maxCostUsd: null,
        authMode: 'oauth-first',
        agents: ['grow-lifehacker'],
      },
      killSwitches: ['CONTENT_FACTORY_ENABLED'],
      planApply: true,
      guards: ['rate-limiter'],
      sinks: ['pr', 'commit'],
    });
    expect(auditWorkflow(exemplary)).toEqual([]);
  });
});

// ── auditRepo ────────────────────────────────────────────────────────────────

describe('auditRepo — standard trio', () => {
  it('files one repo-level (path null) finding per missing member', () => {
    const audit = auditRepo([makeFacts()]);
    const trio = ofRule(audit.findings, 'standard-trio');
    expect(trio).toHaveLength(3);
    expect(trio.every((x) => x.path === null && x.severity === 'warn')).toBe(true);
    const all = trio.map((x) => x.message).join('\n');
    expect(all).toContain('standard-ci-caller');
    expect(all).toContain('ci-gate');
    expect(all).toContain('mention-handler');
    expect(all).toContain('prose-kit');
  });

  it("accepts 'ci-gate' as the CI member and passes a complete trio", () => {
    const full = auditRepo([
      makeFacts({ path: '.github/workflows/ci.yml', archetype: 'ci-gate' }),
      makeFacts({ path: '.github/workflows/claude.yml', archetype: 'mention-handler' }),
      makeFacts({ path: '.github/workflows/prose.yml', archetype: 'prose-kit' }),
    ]);
    expect(ofRule(full.findings, 'standard-trio')).toHaveLength(0);
    expect(full.passedRules).toContain('standard-trio');

    const partial = auditRepo([
      makeFacts({ path: '.github/workflows/claude.yml', archetype: 'mention-handler' }),
    ]);
    expect(ofRule(partial.findings, 'standard-trio')).toHaveLength(2);
  });
});

describe('auditRepo — disabled workflows', () => {
  it('notes each disabled state with its path and counts it in byWorkflow', () => {
    const audit = auditRepo([makeFacts({ path: '.github/workflows/ci.yml' })], {
      workflowStates: {
        '.github/workflows/ci.yml': 'active',
        '.github/workflows/old.yml': 'disabled_manually',
      },
    });
    const hit = ofRule(audit.findings, 'disabled-workflow');
    expect(hit).toHaveLength(1);
    expect(hit[0].path).toBe('.github/workflows/old.yml');
    expect(hit[0].severity).toBe('info');
    expect(hit[0].message).toContain('disabled (disabled_manually)');
    expect(hit[0].message).toContain('dead weight');
    expect(audit.byWorkflow['.github/workflows/old.yml']).toEqual({ fails: 0, warns: 0, infos: 1 });
  });

  it('passes when all polled states are active, and never applies without states', () => {
    const facts = [makeFacts({ path: '.github/workflows/ci.yml' })];
    const polled = auditRepo(facts, { workflowStates: { '.github/workflows/ci.yml': 'active' } });
    expect(polled.passedRules).toContain('disabled-workflow');

    const unpolled = auditRepo(facts);
    expect(unpolled.passedRules).not.toContain('disabled-workflow');
    expect(ofRule(unpolled.findings, 'disabled-workflow')).toHaveLength(0);
  });
});

describe('auditRepo — applicability and passedRules', () => {
  it('a rule that never applied is neither passed nor failed', () => {
    const audit = auditRepo([
      makeFacts({
        permissions: { declared: true, topLevelRead: true, topLevelWrite: false, writeScopes: [] },
      }),
    ]);
    // Applied and clean → passed.
    expect(audit.passedRules).toContain('permissions');
    expect(audit.passedRules).toContain('top-level-write');
    // No AI, no crons, no actions, no event triggers → these never applied.
    for (const id of ['auth-oauth-first', 'kill-switch', 'ai-timeout', 'loop-safety', 'concurrency', 'pin-branch', 'pin-unpinned', 'pin-sha', 'plan-apply', 'dormant-cron', 'sticky-marker']) {
      expect(audit.passedRules).not.toContain(id);
      expect(ofRule(audit.findings, id)).toHaveLength(0);
    }
  });
});

describe('auditRepo — scoring', () => {
  it('scores 100 − 10·fails − 3·warns − 1·infos and tallies byWorkflow', () => {
    // One workflow firing exactly kill-switch (fail); trio missing mention + prose (2 warns).
    const wf = makeFacts({
      path: '.github/workflows/nightly-ai.yml',
      archetype: 'standard-ci-caller',
      triggers: [{ kind: 'schedule', detail: '0 0 * * *' }],
      crons: ['0 0 * * *'],
      ai: aiIn('oauth-first'),
      timeoutMinutes: 20,
      concurrency: { present: true, group: 'nightly', cancelInProgress: 'never' },
      permissions: { declared: true, topLevelRead: true, topLevelWrite: false, writeScopes: [] },
    });
    const audit = auditRepo([wf]);

    expect(audit.findings.map((x) => x.severity).sort()).toEqual(['fail', 'warn', 'warn']);
    expect(audit.score).toBe(84); // 100 − 10·1 − 3·2
    expect(audit.grade).toBe('B'); // a fail bars A; 84 ≥ 70
    expect(audit.byWorkflow['.github/workflows/nightly-ai.yml']).toEqual({
      fails: 1,
      warns: 0,
      infos: 0,
    });
    expect(audit.passedRules).toContain('ai-timeout');
    expect(audit.passedRules).not.toContain('kill-switch');
    expect(audit.passedRules).not.toContain('standard-trio');
  });

  it('clamps the score at 0', () => {
    // Eleven scheduled AI lines with no kill switch → 11 fails → raw −10.
    const fleet = Array.from({ length: 11 }, (_, i) =>
      makeFacts({
        path: `.github/workflows/line-${i}.yml`,
        archetype: i === 0 ? 'standard-ci-caller' : i === 1 ? 'mention-handler' : i === 2 ? 'prose-kit' : 'other',
        triggers: [{ kind: 'schedule' }],
        crons: ['0 0 * * *'],
        ai: aiIn('oauth-first'),
        timeoutMinutes: 20,
        concurrency: { present: true, group: 'g', cancelInProgress: 'never' },
        permissions: { declared: true, topLevelRead: true, topLevelWrite: false, writeScopes: [] },
      }),
    );
    const audit = auditRepo(fleet);
    expect(audit.findings.filter((x) => x.severity === 'fail')).toHaveLength(11);
    expect(audit.score).toBe(0);
    expect(audit.grade).toBe('D');
  });
});

// ── gradeFor boundaries ──────────────────────────────────────────────────────

describe('gradeFor', () => {
  it('S requires no fail, no warn, and score ≥ 95 (infos alone cannot block it)', () => {
    expect(gradeFor(100, [])).toBe('S');
    expect(gradeFor(95, [sev('info')])).toBe('S');
    expect(gradeFor(94, [])).toBe('A');
    expect(gradeFor(97, [sev('warn')])).toBe('A');
  });

  it('A tolerates warns at ≥ 85 but never a fail', () => {
    expect(gradeFor(85, [sev('warn')])).toBe('A');
    expect(gradeFor(84, [])).toBe('B');
    expect(gradeFor(90, [sev('fail')])).toBe('B');
  });

  it('B ≥ 70, C ≥ 50, D below', () => {
    expect(gradeFor(70, [sev('fail')])).toBe('B');
    expect(gradeFor(69, [sev('fail')])).toBe('C');
    expect(gradeFor(50, [])).toBe('C');
    expect(gradeFor(49, [])).toBe('D');
    expect(gradeFor(0, [sev('fail')])).toBe('D');
  });
});
