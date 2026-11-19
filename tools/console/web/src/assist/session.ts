// The docked assistant's state, outside React: whether the dock is open, this
// tab's page-bridge session and its long poll, the mode the person chose, the
// yes/no prompts waiting on them, what was done to the page, and the
// conversation (a list of jobs — every message is one, see core._assist).
//
// It lives in a module, not a component, because the poll must outlive every
// route change and the Shell re-rendering; components read it through
// useDock() (useSyncExternalStore) and call the functions below.
//
// Sharing is tied to the dock being open, on purpose: the assistant can see
// and use this page exactly while the panel that says so is on screen.
import { useSyncExternalStore } from 'react';
import type { QueryClient } from '@tanstack/react-query';
import { api, del, post, put } from '../api/client';
import { ApiError } from '../api/errors';
import { hasConsole } from '../api/backend';
import type { Job } from '../api/types';
import { readPref, writePref } from '../lib/prefs';
import { Refusal, run, watchErrors, type Approval, type Command, type Mode } from './pageBridge';

export type { Approval, Mode } from './pageBridge';

/** The console's view of this tab's session (page_bridge.PageBridge._view). */
export interface PageSession {
  sid: string;
  mode: Mode;
  ceiling: 'off' | 'look' | 'act';
  live: boolean;
  commands: number;
  paired: number;
  pairing: boolean;
  code?: string;
  code_ttl_s?: number;
  poll_s: number;
  approval_s: number;
}

/** One thing a session did, or was not allowed to do, on this page. */
export interface PageEvent {
  id: string;
  at: number;
  action: string;
  what: string;
  outcome: 'ok' | 'declined' | 'refused' | 'failed';
  client: string;
}

export interface AssistState {
  open: boolean;
  mode: Mode;
  session: PageSession | null;
  /** Why this page is not shared, when it is not: the ceiling is off, the console refused, the link dropped. */
  sessionError: string | null;
  approvals: (Approval & { until: number })[];
  events: PageEvent[];
  conversation: string | null;
  jobs: string[];
}

const PREF = 'console_assist';
interface Saved { open?: boolean; mode?: Mode; conversation?: string | null; jobs?: string[] }
const saved = readPref<Saved>(PREF, {});
// Look and Ask are remembered; Act is not. Letting a session use the page unasked is a choice for the
// conversation in front of you, so a reload goes back to asking.
const REMEMBERED: Mode[] = ['look', 'ask'];

let state: AssistState = {
  open: false, // a reload starts closed: sharing a page is something the person does, not something that resumes
  mode: REMEMBERED.includes(saved.mode as Mode) ? (saved.mode as Mode) : 'ask',
  session: null,
  sessionError: null,
  approvals: [],
  events: [],
  conversation: typeof saved.conversation === 'string' ? saved.conversation : null,
  jobs: Array.isArray(saved.jobs) ? saved.jobs.filter((j) => typeof j === 'string').slice(-40) : [],
};

const listeners = new Set<() => void>();
function set(patch: Partial<AssistState>): void {
  state = { ...state, ...patch };
  writePref(PREF, { mode: state.mode === 'act' ? 'ask' : state.mode, conversation: state.conversation, jobs: state.jobs } satisfies Saved);
  listeners.forEach((l) => l());
}
const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};

export const useDock = (): AssistState => useSyncExternalStore(subscribe, () => state);
export const assistState = (): AssistState => state;

// --- what React lends the bridge ---------------------------------------------
let navigateFn: ((path: string) => void) | null = null;
let queryClient: QueryClient | null = null;

/** The Shell hands over the router's navigate and the query cache once it is mounted. */
export function bindPage(navigate: (path: string) => void, qc: QueryClient): void {
  navigateFn = navigate;
  queryClient = qc;
}

// --- approvals ---------------------------------------------------------------
const waiting = new Map<string, (allowed: boolean) => void>();

function approve(a: Approval): Promise<boolean> {
  const ms = (state.session?.approval_s ?? 90) * 1000;
  return new Promise<boolean>((resolve) => {
    const timer = window.setTimeout(() => decide(a.id, false), ms);
    waiting.set(a.id, (allowed) => {
      window.clearTimeout(timer);
      resolve(allowed);
    });
    set({ approvals: [...state.approvals, { ...a, until: Date.now() + ms }] });
  });
}

/** The person's answer to one prompt. */
export function decide(id: string, allowed: boolean): void {
  const done = waiting.get(id);
  waiting.delete(id);
  set({ approvals: state.approvals.filter((a) => a.id !== id) });
  done?.(allowed);
}

function declineAll(): void {
  [...waiting.keys()].forEach((id) => decide(id, false));
}

// --- the page session and its poll -------------------------------------------
function record(cmd: Command, outcome: PageEvent['outcome'], what: string): void {
  if (cmd.action === 'snapshot' || cmd.action === 'data' || cmd.action === 'read') {
    // Reads are frequent and change nothing; the list keeps what a person would want to have noticed.
    if (outcome === 'ok') return;
  }
  set({ events: [...state.events, { id: cmd.id, at: Date.now(), action: cmd.action, what, outcome, client: cmd.client }].slice(-30) });
}

function describe(cmd: Command): string {
  const a = cmd.args;
  switch (cmd.action) {
    case 'navigate': return `went to ${String(a.path)}`;
    case 'highlight': return `pointed at ${String(a.ref)}${a.note ? `: ${String(a.note)}` : ''}`;
    case 'press': return `pressed ${String(a.key)}`;
    default: return cmd.action;
  }
}

async function handle(sid: string, cmd: Command): Promise<void> {
  let body: Record<string, unknown>;
  if (!navigateFn || !queryClient) {
    body = { id: cmd.id, ok: false, kind: 'page', error: 'the page is still starting — try again in a moment' };
  } else {
    try {
      const result = await run(cmd, { mode: () => state.mode, navigate: navigateFn, queryClient, approve });
      const r = result as { clicked?: string; filled?: string; highlighted?: string };
      record(cmd, 'ok', r.clicked ? `clicked "${r.clicked}"` : r.filled ? `typed into "${r.filled}"` : r.highlighted ? `pointed at ${r.highlighted}` : describe(cmd));
      body = { id: cmd.id, ok: true, result };
    } catch (e) {
      const kind = e instanceof Refusal ? e.kind : 'page';
      const message = e instanceof Error ? e.message : String(e);
      record(cmd, kind === 'declined' ? 'declined' : kind === 'refused' ? 'refused' : 'failed', `${describe(cmd)} — ${message.split(' — ')[0].slice(0, 140)}`);
      body = { id: cmd.id, ok: false, kind, error: message };
    }
  }
  try {
    await post(`/api/assist/page/${sid}/result`, body);
  } catch {
    /* the session that asked has gone (the dock closed, the console restarted): nobody is waiting on this */
  }
}

let epoch = 0;

async function poll(sid: string, mine: number): Promise<void> {
  let failures = 0;
  while (mine === epoch && state.session?.sid === sid) {
    try {
      const r = await api<{ command: Command | null; session: PageSession }>(`/api/assist/page/${sid}/next`);
      failures = 0;
      if (mine !== epoch) return;
      set({ session: r.session });
      if (r.command) await handle(sid, r.command);
    } catch (e) {
      if (mine !== epoch) return;
      const status = e instanceof ApiError ? e.status : 0;
      if (status === 404 || status === 403) {
        // The console dropped the session (a restart, the idle sweep, the ceiling switched off).
        declineAll();
        set({ session: null, sessionError: status === 403 ? (e as Error).message : 'The console dropped this page\'s session (it restarted, or the page sat idle). Close and reopen the assistant to share it again.' });
        return;
      }
      failures += 1;
      await new Promise((done) => { window.setTimeout(done, Math.min(15_000, 1000 * 2 ** failures)); });
    }
  }
}

async function share(): Promise<void> {
  if (!hasConsole() || state.session) return;
  epoch += 1;
  const mine = epoch;
  try {
    const session = await post<PageSession>('/api/assist/page', { mode: state.mode });
    if (mine !== epoch || !state.open) {
      void del(`/api/assist/page/${session.sid}`).catch(() => undefined);
      return;
    }
    set({ session, sessionError: null, mode: session.mode });
    void poll(session.sid, mine);
  } catch (e) {
    if (mine === epoch) set({ session: null, sessionError: (e as Error).message });
  }
}

function unshare(): void {
  epoch += 1;
  declineAll();
  const sid = state.session?.sid;
  set({ session: null });
  if (sid) void del(`/api/assist/page/${sid}`).catch(() => undefined);
}

/** Open or close the dock. Open shares this page with the assistant; closed, nothing can see or use it. */
export function setOpen(open: boolean): void {
  if (open === state.open) return;
  set({ open, sessionError: null });
  if (open) {
    watchErrors();
    void share();
  } else {
    unshare();
  }
}
export const toggleOpen = () => setOpen(!state.open);

/** The person's choice for this page: look, ask or act. */
export async function setMode(mode: Mode): Promise<void> {
  const before = state.mode;
  set({ mode });
  if (mode === 'look') declineAll(); // a prompt for an action is moot once actions are off
  const sid = state.session?.sid;
  if (!sid) return;
  try {
    set({ session: await put<PageSession>(`/api/assist/page/${sid}/mode`, { mode }) });
  } catch (e) {
    set({ mode: before, sessionError: (e as Error).message });
  }
}

/** Switch pairing on (a fresh single-use code) or off. */
export async function setPairing(on: boolean): Promise<void> {
  const sid = state.session?.sid;
  if (!sid) return;
  try {
    set({ session: await put<PageSession>(`/api/assist/page/${sid}/pair`, { on }) });
  } catch (e) {
    set({ sessionError: (e as Error).message });
  }
}

// --- the conversation --------------------------------------------------------
/**
 * The `assist` op's parameters for one message: the question, where the person
 * is, the conversation it continues and, while the page is shared, this page.
 * The dock hands them to runOp (jobs/JobRunner.tsx), the console's one gate,
 * and never starts a job itself.
 */
export function messageParams(question: string): Record<string, unknown> {
  const params: Record<string, unknown> = {
    question,
    context: `${window.location.pathname}${window.location.search} — ${document.title}`.slice(0, 300),
  };
  if (state.conversation) params.conversation = state.conversation;
  if (state.session) params.page = state.session.sid;
  return params;
}

/** A message was started: remember its job and the conversation the console put it in. */
export function sent(job: Job): void {
  const conversation = typeof job.params?.conversation === 'string' ? job.params.conversation : state.conversation;
  set({ conversation, jobs: [...state.jobs, job.id] });
}

/** True when a start failed because the console no longer holds the conversation this browser remembers. */
export const conversationGone = (e: unknown): boolean => e instanceof ApiError && e.status === 400 && /no such conversation/.test(e.message);

/** Forget the conversation in this browser. Its jobs keep their logs on the Jobs page. */
export function newConversation(): void {
  set({ conversation: null, jobs: [], events: [] });
}

/** Drop a job this browser remembers but the console no longer has (its history was cleared). */
export function forgetJob(id: string): void {
  if (!state.jobs.includes(id)) return;
  const jobs = state.jobs.filter((j) => j !== id);
  // With none of its messages left there is no conversation to continue.
  set({ jobs, conversation: jobs.length ? state.conversation : null });
}
