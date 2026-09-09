// Pure reverse-import parser for GitHub Actions workflow YAML — the engine behind
// GitFactory's observe mode. `parseWorkflow` turns one workflow file into an
// ImportedWorkflow; `buildFleet` stitches a repo's workflows into a Fleet graph
// (workflow_run chains + cross-repo emissions). No I/O, never throws on bad YAML.
//
// Structure (name + the `on:` block) is read via the `yaml` parser when possible, but
// every agent/sink/cross-repo/gate signal comes from a raw-text regex scan. Text
// scanning is far more robust than deep YAML walking across the many shapes real
// workflows take: composite actions, matrices, heredocs, reusable-workflow calls, and
// even syntactically broken files (which the scan still mines for signals).

import { parse } from 'yaml';
import type { RepoRef } from '../github/types.js';
import type {
  AgentInfo,
  Fleet,
  FleetEdge,
  ImportedWorkflow,
  SinkKind,
  TriggerSummary,
} from './types.js';
import { externalNodeId } from './types.js';

// ── path helpers ────────────────────────────────────────────────────────────

/** Basename of a path with a trailing `.yml`/`.yaml` stripped. */
function baseNoExt(path: string): string {
  const base = path.split('/').pop() ?? path;
  return base.replace(/\.ya?ml$/i, '');
}

// ── `on:` → triggers ──────────────────────────────────────────────────────────

/** Join a string/number array field (e.g. `types:`) of an event config into a detail. */
function joinField(value: unknown, field: string): string | undefined {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    const raw = (value as Record<string, unknown>)[field];
    if (Array.isArray(raw)) {
      const parts = (raw as unknown[])
        .filter((x): x is string | number => typeof x === 'string' || typeof x === 'number')
        .map((x) => String(x));
      if (parts.length > 0) return parts.join(', ');
    }
  }
  return undefined;
}

/** Cron strings from a `schedule:` value (`[{ cron: '…' }, …]`). */
function cronsOf(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const out: string[] = [];
  for (const entry of value as unknown[]) {
    if (entry && typeof entry === 'object' && !Array.isArray(entry)) {
      const cron = (entry as Record<string, unknown>).cron;
      if (typeof cron === 'string') out.push(cron);
    } else if (typeof entry === 'string') {
      out.push(entry);
    }
  }
  return out;
}

/** The `workflows:` name list from a `workflow_run:` value. */
function workflowsOf(value: unknown): string[] {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    const raw = (value as Record<string, unknown>).workflows;
    if (Array.isArray(raw)) {
      return (raw as unknown[]).filter((x): x is string => typeof x === 'string');
    }
  }
  return [];
}

/** Map a single `on:` key (not schedule/workflow_run, which fan out) to a summary. */
function triggerForKey(key: string, value: unknown): TriggerSummary {
  switch (key) {
    case 'push':
      return { kind: 'push' };
    case 'pull_request': {
      const detail = joinField(value, 'types');
      return detail ? { kind: 'pull_request', detail } : { kind: 'pull_request' };
    }
    case 'issues': {
      const detail = joinField(value, 'types');
      return detail ? { kind: 'issues', detail } : { kind: 'issues' };
    }
    case 'issue_comment':
      return { kind: 'issue_comment' };
    case 'workflow_dispatch':
      return { kind: 'workflow_dispatch' };
    case 'repository_dispatch':
      return { kind: 'repository_dispatch' };
    default:
      return { kind: key };
  }
}

/** Expand an `on:` block (string | array | object) into triggers + workflow_run names. */
function triggersFromOn(on: unknown): { triggers: TriggerSummary[]; runAfterNames: string[] } {
  const triggers: TriggerSummary[] = [];
  const runAfterNames: string[] = [];

  if (on == null) return { triggers, runAfterNames };

  if (typeof on === 'string') {
    triggers.push(triggerForKey(on, undefined));
    return { triggers, runAfterNames };
  }

  if (Array.isArray(on)) {
    for (const item of on as unknown[]) {
      if (typeof item === 'string') triggers.push(triggerForKey(item, undefined));
    }
    return { triggers, runAfterNames };
  }

  if (typeof on === 'object') {
    for (const [key, value] of Object.entries(on as Record<string, unknown>)) {
      if (key === 'schedule') {
        for (const cron of cronsOf(value)) triggers.push({ kind: 'schedule', detail: cron });
      } else if (key === 'workflow_run') {
        const workflows = workflowsOf(value);
        for (const w of workflows) runAfterNames.push(w);
        triggers.push(
          workflows.length > 0
            ? { kind: 'workflow_run', detail: workflows.join(', ') }
            : { kind: 'workflow_run' },
        );
      } else {
        triggers.push(triggerForKey(key, value));
      }
    }
  }

  return { triggers, runAfterNames };
}

// ── raw-text signal scans ─────────────────────────────────────────────────────

/** First capture group across `patterns`, or undefined. Patterns must be non-global. */
function firstCapture(text: string, patterns: RegExp[]): string | undefined {
  for (const re of patterns) {
    const m = re.exec(text);
    if (m && m[1]) return m[1];
  }
  return undefined;
}

/** Detect the AI runner + its role/model/tools, or undefined if the workflow runs none. */
function detectAgent(text: string): AgentInfo | undefined {
  let runner: AgentInfo['runner'] | undefined;
  if (text.includes('./.github/actions/claude-run') || text.includes('actions/claude-run')) {
    runner = 'claude-run';
  } else if (text.includes('anthropics/claude-code-action')) {
    runner = 'claude-code-action';
  } else if (text.includes('scripts/ai/run.sh') || text.includes('claude -p')) {
    runner = 'run-sh';
  }
  if (!runner) return undefined;

  const agent: AgentInfo = { runner };
  const agentName = firstCapture(text, [
    /agent:\s*['"]?([A-Za-z0-9_-]+)/,
    /--agent\s+([A-Za-z0-9_-]+)/,
  ]);
  if (agentName) agent.agentName = agentName;
  const model = firstCapture(text, [
    /--model\s+([A-Za-z0-9_.-]+)/,
    /model:\s*['"]?([A-Za-z0-9_.-]+)/,
  ]);
  if (model) agent.model = model;
  const tools = firstCapture(text, [
    /tools:\s*['"]([^'"]+)['"]/,
    /--allowedTools\s+['"]?([^'"\n]+)/,
  ]);
  if (tools) agent.tools = tools;
  return agent;
}

/** Coarse-classify what a workflow writes, deduped and in a stable order. */
function detectSinks(text: string): SinkKind[] {
  const sinks: SinkKind[] = [];
  const add = (k: SinkKind): void => {
    if (!sinks.includes(k)) sinks.push(k);
  };
  if (/gh pr create/.test(text)) add('pr');
  if (/gh issue create/.test(text)) add('issue');
  if (/gh (pr|issue) comment/.test(text)) add('comment');
  if (/gh (issue|pr) edit[^\n]*--add-label/.test(text)) add('label');
  if (/git push/.test(text)) add('commit');
  if (/deploy-pages|actions\/deploy-pages|environment:\s*\n?\s*name:\s*github-pages/.test(text)) {
    add('deploy');
  }
  if (/gh issue create[^\n]*--repo\s+\S+\/\S+/.test(text)) add('cross_repo_issue');
  if (/repository_dispatch|gh workflow run|gh api[^\n]*dispatches/.test(text)) add('dispatch');
  return sinks;
}

/** Unique `owner/name` repos targeted via `gh … --repo owner/name`. */
function detectCrossRepoTargets(text: string): string[] {
  const out: string[] = [];
  const re = /--repo\s+([A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (!out.includes(m[1])) out.push(m[1]);
  }
  return out;
}

/** A `*_ENABLED`-style kill-switch variable name, if the workflow references one. */
function detectGate(text: string): string | undefined {
  const m = /([A-Z][A-Z0-9_]*_ENABLED)/.exec(text);
  return m ? m[1] : undefined;
}

// ── public API ────────────────────────────────────────────────────────────────

/**
 * Reverse-import one workflow file into an {@link ImportedWorkflow}. PURE and total:
 * never throws. Name + `on:` come from the YAML parser when the file parses; all
 * agent/sink/cross-repo/gate signals come from a raw-text scan, so odd YAML shapes
 * (and even unparseable files) still yield useful data.
 */
export function parseWorkflow(path: string, yamlText: string): ImportedWorkflow {
  const slug = baseNoExt(path);

  let docName: string | undefined;
  let on: unknown;
  try {
    const parsed = parse(yamlText) as unknown;
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      const doc = parsed as Record<string, unknown>;
      const n = doc.name;
      if (typeof n === 'string' && n.trim() !== '') docName = n;
      // The `on:` key round-trips as the string 'on' under YAML 1.2, but a YAML-1.1
      // bool resolver hands it back under the boolean-`true` key. Read it defensively.
      on = doc.on ?? doc[true as unknown as string] ?? doc['on'];
    }
  } catch {
    // Unparseable YAML: fall through to the filename name + text-only signal scan.
  }

  const { triggers, runAfterNames } = triggersFromOn(on);
  const agent = detectAgent(yamlText);
  const gate = detectGate(yamlText);

  const wf: ImportedWorkflow = {
    path,
    name: docName ?? slug,
    slug,
    triggers,
    hasAgent: agent !== undefined,
    sinks: detectSinks(yamlText),
    runAfterNames,
    crossRepoTargets: detectCrossRepoTargets(yamlText),
  };
  if (agent) wf.agent = agent;
  if (gate) wf.gate = gate;
  return wf;
}

/**
 * Stitch a repo's parsed workflows into a {@link Fleet}: workflow_run belts (a workflow
 * whose `on.workflow_run.workflows` names another workflow in the same repo) and
 * cross-repo belts (a `gh … --repo owner/name` targeting a *different* repo). PURE.
 */
export function buildFleet(repo: RepoRef, parsed: ImportedWorkflow[]): Fleet {
  const nameToPath = new Map<string, string>();
  for (const wf of parsed) nameToPath.set(wf.name, wf.path);

  const edges: FleetEdge[] = [];
  const warnings: string[] = [];
  const externalRepos: string[] = [];
  const self = `${repo.owner}/${repo.repo}`.toLowerCase();

  for (const wf of parsed) {
    for (const name of wf.runAfterNames) {
      const sourcePath = nameToPath.get(name);
      if (sourcePath) {
        edges.push({
          id: `wr:${sourcePath}->${wf.path}`,
          from: sourcePath,
          to: wf.path,
          kind: 'workflow_run',
          label: 'after',
        });
      } else {
        warnings.push(`${wf.slug}: runs after unknown workflow '${name}'`);
      }
    }

    for (const target of wf.crossRepoTargets) {
      if (target.toLowerCase() === self) continue;
      if (!externalRepos.includes(target)) externalRepos.push(target);
      edges.push({
        id: `cr:${wf.path}->${target}`,
        from: wf.path,
        to: externalNodeId(target),
        kind: 'cross_repo',
        label: 'files issues',
      });
    }
  }

  return { repo, workflows: parsed, externalRepos, edges, warnings };
}
