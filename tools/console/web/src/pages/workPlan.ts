// The Work board's staged plan: what a drag, a menu pick or a drill-down
// control turns into before anything is written. Pure functions over the plan
// and the two boards — `base` (as committed) and `shown` (the preview of the
// plan so far) — so the server stays the one place a plan is validated
// (dash-gen work_board.resolve_plan) and the page only says what was asked.
//
// Order is a pin: a lane's pinned keys come first, in order, and everything
// else follows by its loop's own ranking. Dropping a card at a position pins
// it and every card above it (that is what "put it third" has to mean when
// the rest are ranked by a formula). Dropping it in the empty space at the end
// of a lane changes only its lane, never the order.
import { useCallback, useMemo, useState } from 'react';
import type { WorkBoard, WorkItem, WorkLaneId, WorkPlan } from '../api/types';

export const LANE_ORDER: WorkLaneId[] = ['triage', 'ready', 'doing', 'review', 'blocked', 'hold'];

const clone = (p: WorkPlan): WorkPlan => JSON.parse(JSON.stringify(p)) as WorkPlan;

export function planSize(p: WorkPlan): number {
  return Object.keys(p.stage ?? {}).length + Object.keys(p.priority ?? {}).length + Object.keys(p.pins ?? {}).length
    + (p.unpin ?? []).length + Object.keys(p.notes ?? {}).length + Object.keys(p.roadmap_status ?? {}).length;
}

/** Drop empty sections so an undone change leaves no trace in the request. */
function tidy(p: WorkPlan): WorkPlan {
  const out: WorkPlan = {};
  for (const [k, v] of Object.entries(p)) {
    if (Array.isArray(v) ? v.length : v && Object.keys(v).length) (out as Record<string, unknown>)[k] = v;
  }
  return out;
}

export function byKey(doc: WorkBoard | undefined): Map<string, WorkItem> {
  return new Map((doc?.items ?? []).map((it) => [it.key, it]));
}

export function laneKeys(doc: WorkBoard, lane: WorkLaneId): string[] {
  return doc.items.filter((it) => it.lane === lane).map((it) => it.key);
}

/** May `it` be dropped into `lane`? Its own lane always (reorder); another only if its source can move it. */
export function canDrop(base: WorkItem | undefined, lane: WorkLaneId): boolean {
  return Boolean(base && (base.lane === lane || base.movable.includes(lane)));
}

export function dropInLane(plan: WorkPlan, base: WorkBoard, shown: WorkBoard, key: string, lane: WorkLaneId,
  before: string | null): WorkPlan {
  const b = byKey(base).get(key);
  if (!b || !canDrop(b, lane)) return plan;
  const next = clone(plan);
  next.stage = { ...(next.stage ?? {}) };
  if (lane === b.lane) delete next.stage[key];
  else next.stage[key] = lane;
  const pins = { ...(next.pins ?? {}) };
  for (const l of Object.keys(pins) as WorkLaneId[]) {
    if (l !== lane && pins[l]?.includes(key)) pins[l] = pins[l]!.filter((k) => k !== key);
  }
  const shownItems = byKey(shown);
  const order = laneKeys(shown, lane).filter((k) => k !== key);
  const pinned = new Set(order.filter((k) => shownItems.get(k)?.rank != null));
  if (before == null) {
    pins[lane] = order.filter((k) => pinned.has(k));
  } else {
    const at = Math.max(0, order.indexOf(before));
    order.splice(at, 0, key);
    pins[lane] = order.filter((k, i) => i <= at || pinned.has(k));
  }
  const was = laneKeys(base, lane).filter((k) => byKey(base).get(k)?.rank != null);
  if (JSON.stringify(was) === JSON.stringify(pins[lane])) delete pins[lane];
  next.pins = pins;
  return tidy(next);
}

/** Alt+↑ / Alt+↓: one place up or down in the shown lane. */
export function nudge(plan: WorkPlan, base: WorkBoard, shown: WorkBoard, key: string, delta: -1 | 1): WorkPlan {
  const it = byKey(shown).get(key);
  if (!it) return plan;
  const order = laneKeys(shown, it.lane);
  const i = order.indexOf(key);
  const j = i + delta;
  if (i < 0 || j < 0) return plan;
  // The last place is "after everything", which only pinning the whole lane
  // could hold, so a nudge stops one short of it.
  const target = order.filter((k) => k !== key)[j];
  return target === undefined ? plan : dropInLane(plan, base, shown, key, it.lane, target);
}

export function pinTop(plan: WorkPlan, base: WorkBoard, shown: WorkBoard, key: string): WorkPlan {
  const it = byKey(shown).get(key);
  if (!it) return plan;
  const first = laneKeys(shown, it.lane).find((k) => k !== key) ?? null;
  return dropInLane(plan, base, shown, key, it.lane, first);
}

export function unpin(plan: WorkPlan, base: WorkBoard, shown: WorkBoard, key: string): WorkPlan {
  const it = byKey(shown).get(key);
  if (!it) return plan;
  const items = byKey(shown);
  const next = clone(plan);
  next.pins = { ...(next.pins ?? {}), [it.lane]: laneKeys(shown, it.lane).filter((k) => k !== key && items.get(k)?.rank != null) };
  const was = laneKeys(base, it.lane).filter((k) => byKey(base).get(k)?.rank != null);
  if (JSON.stringify(was) === JSON.stringify(next.pins[it.lane])) delete next.pins[it.lane];
  return tidy(next);
}

export function setPriority(plan: WorkPlan, base: WorkBoard, key: string, value: string | null): WorkPlan {
  const b = byKey(base).get(key);
  if (!b) return plan;
  const next = clone(plan);
  next.priority = { ...(next.priority ?? {}) };
  if (value === null) {
    if (b.priority_source === 'override') next.priority[key] = null;
    else delete next.priority[key];
  } else if (value === b.priority) {
    delete next.priority[key];
  } else if (b.kind !== 'roadmap' && b.priority_source === 'override' && value === b.priority_auto) {
    next.priority[key] = null;          // back to what the formula says: clear the override
  } else {
    next.priority[key] = value;
  }
  return tidy(next);
}

export function setRoadmapStatus(plan: WorkPlan, base: WorkBoard, key: string, status: string, reason = ''): WorkPlan {
  const b = byKey(base).get(key);
  if (!b || b.kind !== 'roadmap') return plan;
  const next = clone(plan);
  const ff = b.ref;
  next.roadmap_status = { ...(next.roadmap_status ?? {}) };
  next.roadmap_reason = { ...(next.roadmap_reason ?? {}) };
  if (next.stage) delete next.stage[key];
  if (status === b.stage) delete next.roadmap_status[ff];
  else next.roadmap_status[ff] = status;
  if (status === 'declined' && reason.trim()) next.roadmap_reason[ff] = reason.trim();
  else delete next.roadmap_reason[ff];
  return tidy(next);
}

export function setNote(plan: WorkPlan, base: WorkBoard, key: string, text: string): WorkPlan {
  const b = byKey(base).get(key);
  if (!b) return plan;
  const next = clone(plan);
  next.notes = { ...(next.notes ?? {}) };
  const t = text.trim();
  if (t === (b.note ?? '')) delete next.notes[key];
  else next.notes[key] = t || null;
  return tidy(next);
}

/** The plan with an undo stack. */
export function usePlan() {
  const [stack, setStack] = useState<WorkPlan[]>([{}]);
  const plan = stack[stack.length - 1];
  const push = useCallback((next: WorkPlan) => {
    setStack((s) => (JSON.stringify(next) === JSON.stringify(s[s.length - 1]) ? s : [...s, next]));
  }, []);
  const undo = useCallback(() => setStack((s) => (s.length > 1 ? s.slice(0, -1) : s)), []);
  const reset = useCallback(() => setStack([{}]), []);
  const size = useMemo(() => planSize(plan), [plan]);
  return { plan, size, push, undo, reset, canUndo: stack.length > 1 };
}
