import { describe, expect, it } from 'vitest';
import { buildFleet, parseWorkflow } from './parse.js';
import type { ImportedWorkflow } from './types.js';
import type { RepoRef } from '../github/types.js';

// ── fixtures: small inline YAML strings mirroring real repo patterns ─────────

/** Scheduled + manual content agent that opens a PR via ./.github/actions/claude-run. */
const CONTENT_FACTORY = `name: content-factory
on:
  schedule:
    - cron: '0 9 * * *'
  workflow_dispatch:
jobs:
  grow:
    runs-on: ubuntu-latest
    steps:
      - uses: ./.github/actions/claude-run
        with:
          agent: grow-lifehacker
          model: claude-sonnet-4
          tools: "Bash,Read"
      - name: Open PR
        run: gh pr create --title "Daily drop" --body "See changes"
`;

/** Non-agent housekeeping workflow that fires after `pipeline` completes. */
const AUTO_MERGE = `name: auto-merge
on:
  workflow_run:
    workflows: [pipeline]
    types: [completed]
  schedule:
    - cron: '*/30 * * * *'
jobs:
  merge:
    runs-on: ubuntu-latest
    steps:
      - run: gh pr merge --squash --auto
`;

/** Files issues into ANOTHER repo — the cross-repo signal. */
const THEME_SCOUT = `name: theme-scout
on:
  schedule:
    - cron: '0 6 * * 1'
jobs:
  scout:
    runs-on: ubuntu-latest
    steps:
      - run: gh issue create --repo bamr87/zer0-mistakes --title "Theme idea" --body "..."
`;

// ── parseWorkflow ─────────────────────────────────────────────────────────────

describe('parseWorkflow — content-factory shape', () => {
  const wf = parseWorkflow('.github/workflows/content-factory.yml', CONTENT_FACTORY);

  it('reads the doc name and derives the slug', () => {
    expect(wf.name).toBe('content-factory');
    expect(wf.slug).toBe('content-factory');
  });

  it('summarizes schedule + workflow_dispatch (2 triggers)', () => {
    expect(wf.triggers).toHaveLength(2);
    expect(wf.triggers).toContainEqual({ kind: 'schedule', detail: '0 9 * * *' });
    expect(wf.triggers).toContainEqual({ kind: 'workflow_dispatch' });
  });

  it('detects the claude-run agent with role, model, and tools', () => {
    expect(wf.hasAgent).toBe(true);
    expect(wf.agent?.runner).toBe('claude-run');
    expect(wf.agent?.agentName).toBe('grow-lifehacker');
    expect(wf.agent?.model).toBe('claude-sonnet-4');
    expect(wf.agent?.tools).toBe('Bash,Read');
  });

  it('detects the pr sink', () => {
    expect(wf.sinks).toContain('pr');
  });
});

describe('parseWorkflow — auto-merge shape', () => {
  const wf = parseWorkflow('.github/workflows/auto-merge.yml', AUTO_MERGE);

  it('summarizes both workflow_run and schedule triggers', () => {
    const kinds = wf.triggers.map((t) => t.kind);
    expect(kinds).toContain('workflow_run');
    expect(kinds).toContain('schedule');
  });

  it('records the upstream workflow name it runs after', () => {
    expect(wf.runAfterNames).toEqual(['pipeline']);
  });

  it('has no agent', () => {
    expect(wf.hasAgent).toBe(false);
    expect(wf.agent).toBeUndefined();
  });
});

describe('parseWorkflow — theme-scout shape (cross-repo)', () => {
  const wf = parseWorkflow('.github/workflows/theme-scout.yml', THEME_SCOUT);

  it('captures the external cross-repo target', () => {
    expect(wf.crossRepoTargets).toContain('bamr87/zer0-mistakes');
  });

  it('flags a cross_repo_issue sink (alongside the plain issue sink)', () => {
    expect(wf.sinks).toContain('cross_repo_issue');
    expect(wf.sinks).toContain('issue');
  });
});

describe('parseWorkflow — `on` scalar shapes', () => {
  it('parses `on` as a bare string', () => {
    const wf = parseWorkflow('.github/workflows/ci.yml', 'name: ci\non: push\n');
    expect(wf.triggers).toEqual([{ kind: 'push' }]);
  });

  it('parses `on` as an array of event names', () => {
    const wf = parseWorkflow('.github/workflows/ci.yml', 'name: ci\non: [push, pull_request]\n');
    expect(wf.triggers.map((t) => t.kind)).toEqual(['push', 'pull_request']);
  });
});

describe('parseWorkflow — robustness', () => {
  it('never throws on unparseable YAML; falls back to filename + text scan', () => {
    const broken =
      'name: [unterminated\nuses: anthropics/claude-code-action@v1\nrun: gh pr create --title x\n';
    const wf = parseWorkflow('.github/workflows/broken.yml', broken);
    expect(wf.name).toBe('broken'); // filename fallback (no readable doc name)
    expect(wf.triggers).toEqual([]);
    expect(wf.hasAgent).toBe(true);
    expect(wf.agent?.runner).toBe('claude-code-action');
    expect(wf.sinks).toContain('pr');
  });

  it('falls back to the filename when no `name:` is present', () => {
    const wf = parseWorkflow('.github/workflows/no-name.yml', 'on: push\n');
    expect(wf.name).toBe('no-name');
  });

  it('extracts a *_ENABLED kill-switch gate', () => {
    const wf = parseWorkflow(
      '.github/workflows/gated.yml',
      "on: push\njobs:\n  go:\n    if: ${{ vars.CONTENT_FACTORY_ENABLED == 'true' }}\n    runs-on: ubuntu-latest\n",
    );
    expect(wf.gate).toBe('CONTENT_FACTORY_ENABLED');
  });
});

// ── buildFleet ────────────────────────────────────────────────────────────────

/** Terse ImportedWorkflow factory for graph-shaping tests. */
function wf(
  path: string,
  name: string,
  extra: Partial<ImportedWorkflow> = {},
): ImportedWorkflow {
  return {
    path,
    name,
    slug: name,
    triggers: [],
    hasAgent: false,
    sinks: [],
    runAfterNames: [],
    crossRepoTargets: [],
    ...extra,
  };
}

describe('buildFleet', () => {
  it('links a workflow_run belt from the named source to the dependent', () => {
    const pipeline = wf('.github/workflows/pipeline.yml', 'pipeline');
    const autoMerge = wf('.github/workflows/auto-merge.yml', 'auto-merge', {
      runAfterNames: ['pipeline'],
    });
    const fleet = buildFleet({ owner: 'o', repo: 'r' }, [pipeline, autoMerge]);

    const wrEdges = fleet.edges.filter((e) => e.kind === 'workflow_run');
    expect(wrEdges).toHaveLength(1);
    expect(wrEdges[0]).toEqual({
      id: `wr:${pipeline.path}->${autoMerge.path}`,
      from: pipeline.path,
      to: autoMerge.path,
      kind: 'workflow_run',
      label: 'after',
    });
    expect(fleet.warnings).toEqual([]);
  });

  it('warns when a runAfter name resolves to no workflow', () => {
    const orphan = wf('.github/workflows/orphan.yml', 'orphan', { runAfterNames: ['ghost'] });
    const fleet = buildFleet({ owner: 'o', repo: 'r' }, [orphan]);
    expect(fleet.edges).toHaveLength(0);
    expect(fleet.warnings).toEqual(["orphan: runs after unknown workflow 'ghost'"]);
  });

  it('adds a cross_repo belt for externals and filters out the self-repo (case-insensitive)', () => {
    const themeScout = wf('.github/workflows/theme-scout.yml', 'theme-scout', {
      crossRepoTargets: ['bamr87/zer0-mistakes', 'bamr87/lifehacker.dev', 'Bamr87/Lifehacker.dev'],
    });
    const repo: RepoRef = { owner: 'bamr87', repo: 'lifehacker.dev' };
    const fleet = buildFleet(repo, [themeScout]);

    expect(fleet.externalRepos).toContain('bamr87/zer0-mistakes');
    expect(fleet.externalRepos).not.toContain('bamr87/lifehacker.dev');
    expect(fleet.externalRepos).not.toContain('Bamr87/Lifehacker.dev');

    const crEdges = fleet.edges.filter((e) => e.kind === 'cross_repo');
    expect(crEdges).toHaveLength(1);
    expect(crEdges[0]).toEqual({
      id: `cr:${themeScout.path}->bamr87/zer0-mistakes`,
      from: themeScout.path,
      to: 'ext:bamr87/zer0-mistakes',
      kind: 'cross_repo',
      label: 'files issues',
    });
  });
});
