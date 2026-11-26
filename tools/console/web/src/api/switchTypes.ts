import type { Dict } from './types';

// The loop switches (constitution § 17; tools/console/switches.py): GET /api/switches and
// POST /api/switches/preview. Never in the public snapshot: the live values are read with the
// operator's token.
export type SwitchTarget = 'on' | 'off';
export type SwitchScope = 'loop' | 'repo' | 'group' | 'all';
export interface SwitchHold { kind?: string; name?: string; value?: string; source?: string; lift?: string }
export interface SwitchRow {
  key: string; repo: string; workflow: string | null; group: string | null; owner?: string | null; scope?: string | null;
  gate: string | null; variable: string | null; semantics: 'opt_in' | 'opt_out' | null; default: string | null;
  live: { value: string | null; state: 'set' | 'unset' | 'unreadable' | 'n/a'; updated_at: string | null; on: boolean | null };
  effective: { on: boolean | null; why: string; verified: boolean };
  map: {
    state: string; verified: boolean; says: SwitchTarget | null; level_off: string | null; reason: string | null;
    set_by: string | null; set_at: string | null; expires: string | null;
  };
  drift: boolean | null; hold: SwitchHold | null; note: string | null; flippable: boolean; not_flippable: string | null;
}
export interface SwitchRepo {
  repo: string; writable: boolean; readable: boolean; error: string | null; loops: SwitchRow[];
  counts: { loops: number; on: number; off: number; unknown: number; drift: number; flippable: number };
}
export interface SwitchesDoc {
  schema: string; map_schema: string; generated_at: string; writes: { enabled: boolean; why: string | null }; login: string | null;
  global: { state?: string; reason?: string | null } | null; groups: Dict<{ state?: string; reason?: string | null }>;
  repos: SwitchRepo[];
  counts: { repos: number; loops: number; drift: number; on: number; off: number; unreadable: number; flippable: number };
  commit: string;
}
export interface SwitchPlanItem {
  key: string; repo: string; workflow: string | null; variable: string | null; semantics: string | null;
  current: string | null; current_state: string; current_on: boolean | null; new: string | null;
  write_variable: boolean; write_map: boolean; map_before: { state: string; verified: boolean };
  map_after: { state: string; verified: boolean } | null; do: boolean; skip: string | null; warnings: string[];
}
export interface SwitchPlan {
  schema: string; plan_id: string; scope: SwitchScope; key: string; target: SwitchTarget; reason: string;
  set_by: string | null; set_at: string; created_at: string; op: string; writes: { enabled: boolean; why: string | null };
  login_known: boolean; items: SwitchPlanItem[]; diff: string; diff_error: string | null;
  counts: { do: number; skip: number; variables: number; records: number }; commit: string;
}
