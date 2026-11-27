// The Switches page's rules, apart from React so they are tested (switchPlan.test.ts):
// what a toggle asks for, how a variable's value reads, when a previewed flip may be
// applied, and why a lever is off. The server holds the same rules (tools/console/
// switches.py); these only decide what the page offers, never what is written.
import type { SwitchPlan, SwitchRepo, SwitchRow, SwitchScope, SwitchTarget, SwitchesDoc } from '../api/switchTypes';

export const REASON_MIN = 3;
export const REASON_MAX = 300;

/** One flip the page asks the console to preview: a scope, what it names, and the target. */
export interface FlipRequest {
  scope: SwitchScope;
  key: string;
  target: SwitchTarget;
}

/** Whether the loop runs now as far as its switch says: the variable when it was read, else the map. */
export function isOn(row: SwitchRow): boolean | null {
  if (row.live.on !== null) return row.live.on;
  if (row.map.state === 'on' || row.map.state === 'off') return row.map.state === 'on';
  return row.effective.on;
}

/** A loop's toggle asks for the opposite of what its switch says now. */
export function loopFlip(row: SwitchRow): FlipRequest {
  return { scope: 'loop', key: row.key, target: isOn(row) ? 'off' : 'on' };
}

export function repoFlip(repo: string, target: SwitchTarget): FlipRequest {
  return { scope: 'repo', key: repo, target };
}

/** A variable's value as the page shows it: unreadable is never shown as unset. */
export function shown(value: string | null | undefined): string {
  if (value === null || value === undefined) return 'unreadable';
  return value === '' ? 'unset' : `'${value}'`;
}

export function semanticsLabel(semantics: string | null): string {
  if (semantics === 'opt_in') return "opt-in: on only when 'true'";
  if (semantics === 'opt_out') return "opt-out: on unless 'false'";
  return 'no variable';
}

/** Why the console will not write this repository's switches, or null when it will. */
export function repoBlocked(doc: Pick<SwitchesDoc, 'writes'>, repo: Pick<SwitchRepo, 'writable' | 'readable' | 'error' | 'repo'>): string | null {
  if (!doc.writes.enabled) return doc.writes.why ?? 'GitHub writes are off in this console';
  if (!repo.writable) return `${repo.repo} is not a repository the hub owns: the console reads it but will not write to it`;
  if (!repo.readable) return `its variables could not be read (${repo.error ?? 'no read'}): nothing is written blind`;
  return null;
}

/** Why this loop's toggle is off, or null when it can be flipped. */
export function rowBlocked(doc: Pick<SwitchesDoc, 'writes'>, row: SwitchRow): string | null {
  if (!doc.writes.enabled) return doc.writes.why ?? 'GitHub writes are off in this console';
  return row.flippable ? null : row.not_flippable ?? 'not flippable from the console';
}

export function reasonOk(reason: string): boolean {
  const n = reason.trim().replace(/\s+/g, ' ').length;
  return n >= REASON_MIN && n <= REASON_MAX;
}

/** Why a previewed plan cannot be applied, or null when Apply may be offered. */
export function applyBlocked(plan: SwitchPlan | null, reason: string): string | null {
  if (!plan) return 'preview it first';
  if (plan.reason !== reason.trim().replace(/\s+/g, ' ')) return 'the reason changed since the preview: preview it again';
  if (plan.counts.do === 0) return 'nothing to apply: every loop is skipped or already there';
  if (plan.diff_error) return `the fleet.yml change could not be made: ${plan.diff_error}`;
  if (plan.counts.variables > 0 && !plan.writes.enabled) return plan.writes.why ?? 'GitHub writes are off in this console';
  if (!plan.login_known) return 'no GitHub login: the flip could not record who made it';
  return null;
}

export function flipTitle(req: FlipRequest): string {
  const what = req.scope === 'loop' ? `loop ${req.key}` : req.scope === 'repo' ? `every loop of ${req.key}`
    : req.scope === 'group' ? `every loop in group ${req.key}` : 'every loop in the map';
  return `Turn ${what} ${req.target}`;
}

/** The table row's one-line summary of a plan item, for the preview. */
export function itemChange(item: SwitchPlan['items'][number]): string {
  if (!item.do) return `skip: ${item.skip ?? ''}`;
  const variable = item.write_variable ? `${item.variable} ${shown(item.current)} → ${shown(item.new)}` : `${item.variable} stays ${shown(item.current)}`;
  return `${variable}; map ${item.map_before.state} → ${item.map_after?.state ?? item.map_before.state}`;
}
