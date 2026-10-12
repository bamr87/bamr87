// GitHub, straight from the browser — the public build's write path.
//
// With no console behind the page, a GitHub token pasted on the Connect page
// makes the page act on GitHub itself. This module answers the console's own
// /api/github/* and /api/jobs routes with the SAME document shapes
// github_link.py and core.py return, so the GitHub page, the repo manager and
// the job drawer work unchanged:
//
//   /api/github/status, /repos, /repos/:o/:r, /repos/:o/:r/issues/:n  — reads
//   /api/github/repos/:o/:r/actions — github_link.act's writes, with its rules:
//       the same nine actions, the same validation, fleet repos the hub owns
//       only, confirm required, every write in an action log (this tab's)
//   /api/jobs (POST op=dispatch)   — `gh workflow run` for the allowlisted
//       control-plane workflows (core.DISPATCHABLE) and their allowed inputs
//   /api/jobs, /api/jobs/:id       — the hub's workflow_dispatch runs as jobs,
//       their steps as the live log
//
// The rules (which repos are the fleet's, what may be dispatched) come from the
// snapshot (github/fleet.json), written by the same Python the console uses.
// The token goes to api.github.com and nowhere else, and is never logged.
import { ApiError } from './errors';
import { githubToken } from './backend';
import { staticGet } from './static';
import type { GhAction, GhIssue, GhRepo, GhRepoDetail, GithubStatus, Job, JobTail } from './types';

const API = 'https://api.github.com';
const NWO_RX = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})\/[A-Za-z0-9._-]{1,100}$/;
const LABEL_RX = /^[^\x00-\x1f]{1,50}$/;
const FIELD_RX = /^[A-Za-z0-9._,/: -]{0,120}$/;

interface FleetRules {
  owner: string;
  hub: { repo?: string; shared?: string; default_branch?: string };
  repos: Record<string, string>;
  dispatchable: Record<string, string[]>;
}

const rules = () => staticGet<FleetRules>('/api/github/fleet');
const hubRepo = async () => (await rules()).hub.repo ?? 'bamr87/bamr87';

type Json = Record<string, any>;

async function gh<T = any>(method: string, path: string, body?: unknown): Promise<{ data: T; headers: Headers; status: number }> {
  const token = githubToken();
  if (!token) throw new ApiError(401, 'Connect a GitHub token first (the Connect page)');
  const res = await fetch(`${API}${path}`, {
    method,
    headers: {
      Accept: 'application/vnd.github+json',
      Authorization: `Bearer ${token}`,
      'X-GitHub-Api-Version': '2022-11-28',
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
    cache: 'no-store',
  });
  const text = await res.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const msg = (data && typeof data === 'object' && data.message) || `${res.status} ${res.statusText}`;
    throw new ApiError(res.status, res.status === 401 ? `GitHub rejected the token: ${msg}` : `GitHub: ${msg}`);
  }
  return { data, headers: res.headers, status: res.status };
}

const get = async <T = any>(path: string) => (await gh<T>('GET', path)).data;

function tokenKind(t: string): string | null {
  if (!t) return null;
  if (t.startsWith('github_pat_')) return 'fine-grained PAT';
  if (t.startsWith('ghp_')) return 'classic PAT';
  if (t.startsWith('gho_')) return 'OAuth token';
  if (t.startsWith('ghu_')) return 'GitHub App user token';
  return 'token';
}

const num = (v: string | null) => (v == null || v === '' ? null : Number(v));

// --- READ ------------------------------------------------------------------
async function status(): Promise<GithubStatus> {
  const r = await rules();
  const token = githubToken();
  const out: GithubStatus = {
    connected: false, source: token ? 'browser' : null, kind: tokenKind(token), login: null, name: null, avatar_url: null,
    scopes: [], rate: null, error: null, session_set: false, writes_enabled: Boolean(token), auth_writes: Boolean(token),
    fleet_owner: r.owner,
    oauth: { client_id_set: false, client_secret_set: false, device_flow: false, web_flow: false, default_scopes: '', callback_url: '', new_app_url: '', authorized_apps_url: '' },
  };
  if (!token) return out;
  try {
    const { data: me, headers } = await gh<Json>('GET', '/user');
    out.connected = true;
    out.login = me.login;
    out.name = me.name;
    out.avatar_url = me.avatar_url;
    out.scopes = (headers.get('x-oauth-scopes') ?? '').split(',').map((s) => s.trim()).filter(Boolean);
    out.rate = { limit: num(headers.get('x-ratelimit-limit')), remaining: num(headers.get('x-ratelimit-remaining')), reset: num(headers.get('x-ratelimit-reset')) };
  } catch (e) {
    out.error = (e as Error).message;
  }
  return out;
}

async function listRepos(): Promise<GhRepo[]> {
  const fleet = (await rules()).repos;
  const out: GhRepo[] = [];
  for (let page = 1; page <= 3; page += 1) {
    const batch = await get<Json[]>(`/user/repos?per_page=100&page=${page}&sort=pushed&affiliation=owner,collaborator,organization_member`);
    for (const r of batch) {
      const full = String(r.full_name);
      out.push({
        full_name: full, name: r.name, owner: r.owner?.login, private: r.private, archived: r.archived, fork: r.fork,
        description: r.description, pushed_at: r.pushed_at, open_issues: r.open_issues_count, stars: r.stargazers_count,
        default_branch: r.default_branch, html_url: r.html_url, language: r.language, permissions: r.permissions ?? {},
        fleet_name: fleet[full.toLowerCase()] ?? null, writable: full.toLowerCase() in fleet,
      });
    }
    if (batch.length < 100) break;
  }
  return out;
}

function slimIssue(i: Json): GhIssue {
  return {
    number: i.number, title: i.title, state: i.state, state_reason: i.state_reason, user: i.user?.login ?? null,
    labels: (i.labels ?? []).map((l: Json) => l.name), comments: i.comments, created_at: i.created_at, updated_at: i.updated_at,
    html_url: i.html_url, assignees: (i.assignees ?? []).map((a: Json) => a.login), draft: i.draft, is_pr: 'pull_request' in i,
  };
}

function checkNwo(nwo: string): string {
  if (!NWO_RX.test(nwo)) throw new ApiError(400, 'expected owner/name');
  return nwo;
}

async function repoDetail(nwo: string): Promise<GhRepoDetail> {
  checkNwo(nwo);
  const calls: Record<string, string> = {
    repo: `/repos/${nwo}`,
    issues: `/repos/${nwo}/issues?state=open&per_page=50&sort=updated`,
    pulls: `/repos/${nwo}/pulls?state=open&per_page=30&sort=updated`,
    runs: `/repos/${nwo}/actions/runs?per_page=25`,
    workflows: `/repos/${nwo}/actions/workflows?per_page=100`,
    labels: `/repos/${nwo}/labels?per_page=100`,
  };
  const results: Json = {};
  const errors: Record<string, string> = {};
  await Promise.all(Object.entries(calls).map(async ([k, path]) => {
    try {
      results[k] = await get(path);
    } catch (e) {
      errors[k] = (e as Error).message;
    }
  }));
  if (!results.repo) throw new ApiError(404, errors.repo ?? `cannot read ${nwo}`);
  const r = results.repo;
  const fleet = (await rules()).repos;
  const pick = ['description', 'private', 'archived', 'fork', 'default_branch', 'html_url', 'homepage', 'language', 'stargazers_count', 'forks_count', 'open_issues_count', 'pushed_at', 'visibility', 'topics', 'has_issues'];
  return {
    nwo: r.full_name, fleet_name: fleet[nwo.toLowerCase()] ?? null, writable: nwo.toLowerCase() in fleet,
    repo: { ...Object.fromEntries(pick.map((k) => [k, r[k]])), permissions: r.permissions ?? {} },
    issues: (results.issues ?? []).filter((i: Json) => !('pull_request' in i)).map(slimIssue),
    pulls: (results.pulls ?? []).map((p: Json) => ({
      number: p.number, title: p.title, user: p.user?.login ?? null, draft: p.draft, head: p.head?.ref, base: p.base?.ref,
      updated_at: p.updated_at, html_url: p.html_url, labels: (p.labels ?? []).map((l: Json) => l.name),
    })),
    runs: (results.runs?.workflow_runs ?? []).map((x: Json) => ({
      id: x.id, name: x.name, display_title: x.display_title, event: x.event, status: x.status, conclusion: x.conclusion,
      branch: x.head_branch, created_at: x.created_at, html_url: x.html_url, run_attempt: x.run_attempt, workflow_id: x.workflow_id,
    })),
    workflows: (results.workflows?.workflows ?? []).map((w: Json) => ({ id: w.id, name: w.name, path: w.path, state: w.state, html_url: w.html_url })),
    labels: (results.labels ?? []).map((l: Json) => ({ name: l.name, color: l.color, description: l.description })),
    errors,
  };
}

async function issueThread(nwo: string, n: number) {
  checkNwo(nwo);
  const issue = await get<Json>(`/repos/${nwo}/issues/${n}`);
  const comments = await get<Json[]>(`/repos/${nwo}/issues/${n}/comments?per_page=50`);
  return {
    issue: { ...slimIssue(issue), body: issue.body ?? '' },
    comments: comments.map((c) => ({ id: c.id, user: c.user?.login, body: c.body ?? '', created_at: c.created_at, html_url: c.html_url })),
  };
}

// --- WRITE (github_link.act, in the browser) -------------------------------
const ACTIONS: Record<string, string> = {
  'issue.create': 'Open an issue',
  'issue.comment': 'Comment on an issue or pull request',
  'issue.close': 'Close an issue',
  'issue.reopen': 'Reopen an issue',
  'issue.labels': 'Add / remove labels',
  'run.rerun_failed': "Re-run a run's failed jobs",
  'run.cancel': 'Cancel a run',
  'workflow.enable': 'Enable a workflow',
  'workflow.disable': 'Disable a workflow',
};

const LOG_KEY = 'gh_direct_log';
function readLog(): GhAction[] {
  try {
    return JSON.parse(sessionStorage.getItem(LOG_KEY) ?? '[]') as GhAction[];
  } catch {
    return [];
  }
}
function record(entry: GhAction): void {
  try {
    sessionStorage.setItem(LOG_KEY, JSON.stringify([entry, ...readLog()].slice(0, 200)));
  } catch {
    /* the log is a convenience; the write itself already happened */
  }
}

function n(v: unknown, name: string): number {
  const x = Number(v);
  if (!Number.isInteger(x) || x <= 0 || x > 1e12) throw new ApiError(400, `${name} must be a number`);
  return x;
}
function text(v: unknown, name: string, lo: number, hi: number): string {
  const s = String(v ?? '').trim();
  if (s.length < lo || s.length > hi) throw new ApiError(400, `${name} must be ${lo}-${hi} characters`);
  return s;
}
function labels(v: unknown): string[] {
  const items = Array.isArray(v) ? v : String(v ?? '').split(',');
  const out = items.map((x) => String(x).trim()).filter(Boolean);
  if (out.length > 20 || !out.every((x) => LABEL_RX.test(x))) throw new ApiError(400, 'labels: at most 20 names, 50 characters each');
  return out;
}

async function act(nwo: string, action: string, p: Json, confirm: boolean): Promise<GhAction> {
  checkNwo(nwo);
  if (!(action in ACTIONS)) throw new ApiError(400, `unknown action — one of ${Object.keys(ACTIONS).sort().join(', ')}`);
  if (!(nwo.toLowerCase() in (await rules()).repos)) throw new ApiError(403, `${nwo} is not a fleet repo the hub owns — the page reads it but will not write to it`);
  if (!confirm) throw new ApiError(403, `${ACTIONS[action]} writes to GitHub — it needs confirm=true`);
  const entry: GhAction = { at: new Date().toISOString().replace(/\.\d+Z$/, 'Z'), action, label: ACTIONS[action], repo: nwo, target: '', ok: false, url: null, error: null };
  try {
    let result: Json | null = null;
    if (action === 'issue.create') {
      const body: Json = { title: text(p.title, 'title', 1, 256), body: text(p.body, 'body', 0, 65536) };
      if (p.labels) body.labels = labels(p.labels);
      result = (await gh('POST', `/repos/${nwo}/issues`, body)).data;
      entry.target = `#${result?.number}`;
    } else if (action === 'issue.comment') {
      const i = n(p.number, 'number');
      entry.target = `#${i}`;
      result = (await gh('POST', `/repos/${nwo}/issues/${i}/comments`, { body: text(p.body, 'comment', 1, 65536) })).data;
    } else if (action === 'issue.close' || action === 'issue.reopen') {
      const i = n(p.number, 'number');
      entry.target = `#${i}`;
      const body: Json = { state: action === 'issue.close' ? 'closed' : 'open' };
      if (action === 'issue.close') {
        const reason = p.reason || 'completed';
        if (reason !== 'completed' && reason !== 'not_planned') throw new ApiError(400, 'reason must be completed or not_planned');
        body.state_reason = reason;
      }
      result = (await gh('PATCH', `/repos/${nwo}/issues/${i}`, body)).data;
    } else if (action === 'issue.labels') {
      const i = n(p.number, 'number');
      entry.target = `#${i}`;
      const add = labels(p.add);
      const remove = labels(p.remove);
      if (!add.length && !remove.length) throw new ApiError(400, 'nothing to add or remove');
      if (add.length) await gh('POST', `/repos/${nwo}/issues/${i}/labels`, { labels: add });
      for (const name of remove) {
        await gh('DELETE', `/repos/${nwo}/issues/${i}/labels/${encodeURIComponent(name)}`).catch((e: ApiError) => {
          if (e.status !== 404) throw e; // already absent is the goal state
        });
      }
    } else if (action === 'run.rerun_failed' || action === 'run.cancel') {
      const id = n(p.run_id, 'run_id');
      entry.target = `run ${id}`;
      await gh('POST', `/repos/${nwo}/actions/runs/${id}/${action === 'run.cancel' ? 'cancel' : 'rerun-failed-jobs'}`, {});
    } else {
      const id = n(p.workflow_id, 'workflow_id');
      entry.target = `workflow ${id}`;
      await gh('PUT', `/repos/${nwo}/actions/workflows/${id}/${action.split('.')[1]}`);
    }
    entry.ok = true;
    entry.url = result?.html_url ?? null;
  } catch (e) {
    entry.error = (e as Error).message;
    record(entry);
    throw e;
  }
  record(entry);
  return entry;
}

// --- JOBS: control-plane workflows dispatched from the page ----------------
function jobStatus(run: Json): Job['status'] {
  if (run.status !== 'completed') return run.status === 'queued' || run.status === 'requested' || run.status === 'waiting' || run.status === 'pending' ? 'queued' : 'running';
  if (run.conclusion === 'success') return 'succeeded';
  if (run.conclusion === 'cancelled') return 'cancelled';
  return 'failed';
}

function asJob(run: Json): Job {
  const wf = String(run.path ?? '').replace(/^.*\//, '').replace(/\.ya?ml(@.*)?$/, '');
  return {
    id: `run-${run.id}`, op: 'dispatch', title: `${run.name} #${run.run_number}${run.actor?.login ? ` · ${run.actor.login}` : ''}`,
    argv: ['gh', 'workflow', 'run', `${wf || run.name}.yml`], status: jobStatus(run), remote_write: true,
    params: { workflow: wf, run_url: run.html_url }, started: run.run_started_at ?? run.created_at,
    finished: run.status === 'completed' ? run.updated_at : null, exit_code: run.status === 'completed' ? (run.conclusion === 'success' ? 0 : 1) : null,
  };
}

async function listJobs(): Promise<Job[]> {
  const hub = await hubRepo();
  const runs = await get<Json>(`/repos/${hub}/actions/runs?event=workflow_dispatch&per_page=25`);
  return (runs.workflow_runs ?? []).map(asJob);
}

async function dispatch(params: Json, confirm: boolean): Promise<Job> {
  const r = await rules();
  const hub = r.hub.repo ?? 'bamr87/bamr87';
  const wf = String(params.workflow ?? '').trim();
  const allowed = r.dispatchable[wf];
  if (!allowed) throw new ApiError(400, `workflow must be one of ${Object.keys(r.dispatchable).sort().join(', ')}`);
  if (!confirm) throw new ApiError(409, `dispatching ${wf} writes to GitHub — it needs confirm=true`);
  const fields = (params.fields ?? {}) as Json;
  if (typeof fields !== 'object' || Array.isArray(fields)) throw new ApiError(400, 'fields must be an object');
  const inputs: Record<string, string> = {};
  for (const [k, v] of Object.entries(fields)) {
    if (!allowed.includes(k)) throw new ApiError(400, `${wf} does not accept input '${k}'`);
    const s = v === true ? 'true' : v === false ? 'false' : String(v);
    if (!FIELD_RX.test(s)) throw new ApiError(400, `input '${k}' has characters the page refuses to pass`);
    inputs[k] = s;
  }
  const since = Date.now() - 5000;
  // return_run_details asks GitHub for the new run's id; an API without it
  // answers 204 and the run is found by polling, below.
  const res = await gh<Json>('POST', `/repos/${hub}/actions/workflows/${wf}.yml/dispatches`, { ref: r.hub.default_branch ?? 'main', inputs, return_run_details: true });
  let runId: number | null = res.data?.workflow_run_id ?? null;
  for (let attempt = 0; !runId && attempt < 8; attempt += 1) {
    await new Promise((ok) => setTimeout(ok, 1500));
    const runs = await get<Json>(`/repos/${hub}/actions/workflows/${wf}.yml/runs?event=workflow_dispatch&per_page=5`);
    runId = (runs.workflow_runs ?? []).find((x: Json) => Date.parse(x.created_at) >= since)?.id ?? null;
  }
  if (!runId) {
    return { id: `pending-${wf}`, op: 'dispatch', title: `${wf} (dispatched — the run has not appeared yet)`, argv: ['gh', 'workflow', 'run', `${wf}.yml`], status: 'queued', remote_write: true, params };
  }
  return asJob(await get<Json>(`/repos/${hub}/actions/runs/${runId}`));
}

// A run's steps, as an append-only log: a line is emitted once, when it is
// final, so an offset into the text stays valid while the run goes on.
const emitted = new Map<string, { keys: Set<string>; lines: string[] }>();
const C = { ok: '\x1b[32m', bad: '\x1b[31m', dim: '\x1b[90m', off: '\x1b[0m' };

function secs(a?: string | null, b?: string | null): string {
  if (!a || !b) return '';
  const s = Math.max(0, Math.round((Date.parse(b) - Date.parse(a)) / 1000));
  return s >= 60 ? ` ${Math.floor(s / 60)}m${s % 60}s` : ` ${s}s`;
}

async function tail(id: string, offset: number): Promise<JobTail> {
  const runId = id.replace(/^run-/, '');
  if (!/^\d+$/.test(runId)) throw new ApiError(404, 'no such job');
  const hub = await hubRepo();
  const run = await get<Json>(`/repos/${hub}/actions/runs/${runId}`);
  const jobs = await get<Json>(`/repos/${hub}/actions/runs/${runId}/jobs?per_page=100`);
  const log = emitted.get(id) ?? { keys: new Set<string>(), lines: [`${C.dim}${run.html_url}${C.off}`] };
  emitted.set(id, log);
  const emit = (key: string, line: string) => {
    if (!log.keys.has(key)) {
      log.keys.add(key);
      log.lines.push(line);
    }
  };
  for (const j of jobs.jobs ?? []) {
    if (!j.started_at && j.status !== 'completed') continue;
    emit(`job:${j.id}`, `▶ ${j.name}`);
    for (const s of j.steps ?? []) {
      if (s.status !== 'completed') break;
      const mark = s.conclusion === 'success' ? `${C.ok}✓` : s.conclusion === 'skipped' ? `${C.dim}–` : `${C.bad}✗`;
      emit(`step:${j.id}:${s.number}`, `  ${mark} ${s.name}${C.off}${C.dim}${secs(s.started_at, s.completed_at)}${C.off}`);
    }
    if (j.status === 'completed') emit(`done:${j.id}`, `${j.conclusion === 'success' ? C.ok : j.conclusion === 'skipped' ? C.dim : C.bad}■ ${j.name} — ${j.conclusion}${C.off}`);
  }
  const done = run.status === 'completed';
  if (done) emit('run', `\n${run.conclusion === 'success' ? C.ok : C.bad}run ${run.conclusion}${C.off} — full logs: ${run.html_url}`);
  const full = `${log.lines.join('\n')}\n`;
  return { job: asJob(run), text: full.slice(offset), offset: full.length, done };
}

// --- the router ------------------------------------------------------------
export async function githubDirect<T>(path: string, init: RequestInit): Promise<T> {
  const url = new URL(path, 'http://github.invalid');
  const p = url.pathname.replace(/\/+$/, '');
  const method = (init.method ?? 'GET').toUpperCase();
  const body = init.body ? (JSON.parse(String(init.body)) as Json) : {};
  let m: RegExpMatchArray | null;

  if (p === '/api/github/status') return (await status()) as T;
  if (p === '/api/github/fleet') return (await rules()) as T;
  if (p === '/api/github/log') return readLog() as T;
  if (p === '/api/github/repos') return (await listRepos()) as T;
  if ((m = p.match(/^\/api\/github\/repos\/([^/]+\/[^/]+)\/issues\/(\d+)$/))) return (await issueThread(m[1], Number(m[2]))) as T;
  if ((m = p.match(/^\/api\/github\/repos\/([^/]+\/[^/]+)\/actions$/)) && method === 'POST') return (await act(m[1], String(body.action ?? ''), body.params ?? {}, Boolean(body.confirm))) as T;
  if ((m = p.match(/^\/api\/github\/repos\/([^/]+\/[^/]+)$/))) return (await repoDetail(m[1])) as T;
  if (p.startsWith('/api/github/oauth') || p === '/api/github/disconnect') {
    throw new ApiError(501, 'The public page does not run the OAuth App flows — paste a token on the Connect page instead');
  }
  if (p === '/api/jobs' && method === 'GET') return (githubToken() ? await listJobs() : []) as T;
  if (p === '/api/jobs' && method === 'POST') {
    if (body.op !== 'dispatch') throw new ApiError(501, `“${body.op}” runs on a console — the public page can only dispatch control-plane workflows. Connect a console to run it.`);
    return (await dispatch(body.params ?? {}, Boolean(body.confirm))) as T;
  }
  if ((m = p.match(/^\/api\/jobs\/([^/]+)\/cancel$/)) && method === 'POST') {
    const runId = m[1].replace(/^run-/, '');
    await gh('POST', `/repos/${await hubRepo()}/actions/runs/${n(runId, 'run id')}/cancel`, {});
    return (await tail(m[1], 0)).job as T;
  }
  if ((m = p.match(/^\/api\/jobs\/([^/]+)$/))) return (await tail(m[1], Number(url.searchParams.get('offset') ?? 0))) as T;
  throw new ApiError(404, `no GitHub route for ${p}`);
}

/** Paths this module answers in the public build (the rest are snapshot files). */
export const isGithubPath = (path: string) => /^\/api\/(github\/(?!fleet)|jobs)/.test(path);
