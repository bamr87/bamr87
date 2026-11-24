// workPlan.ts turns a drag, a menu pick or a drill-down control on the Work
// board into a staged plan. Its header states the rules, and they are held
// here: order is a pin (a drop at a position pins the card and every card
// above it), a drop in the empty space at the end of a lane changes only the
// lane, an undone change leaves no trace in the request, and nothing here
// edits the plan or the boards it was given.
import { describe, expect, it } from 'vitest';
import type { WorkBoard, WorkItem, WorkLaneId, WorkPlan } from '../api/types';
import {
  byKey, canDrop, dropInLane, laneKeys, nudge, pinTop, planSize, setNote, setPriority, setRoadmapStatus, unpin,
} from './workPlan';

function card(key: string, lane: WorkLaneId, more: Partial<WorkItem> = {}): WorkItem {
  return {
    key, kind: 'issue', ref: key, title: key, url: null, repo: 'scripts', nwo: 'bamr87/scripts', lane, stage: lane,
    priority: 'P2', priority_auto: 'P2', priority_source: 'computed', rank: null, size: null, age_days: null, idle_days: null,
    readiness: null, autonomy: null, autonomy_reason: null, labels: [], movable: [], moved: null, progress: null, note: null,
    loop: 'none', next_run: null, detail: {}, ...more,
  };
}

/** A board with these cards, in this order. The plan functions read only its items. */
const board = (...items: WorkItem[]) => ({ items }) as unknown as WorkBoard;

/** A pinned card: `rank` is its place among its lane's pins. */
const pinned = (key: string, lane: WorkLaneId, rank: number, more: Partial<WorkItem> = {}) => card(key, lane, { rank, ...more });

function freeze<T>(value: T): T {
  if (value && typeof value === 'object') {
    Object.values(value as object).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}

/** Four unpinned cards in Ready, one in Triage that may move to Ready or Hold. */
const plain = () => board(
  card('a', 'ready'), card('b', 'ready'), card('c', 'ready'), card('d', 'ready'),
  card('t', 'triage', { movable: ['ready', 'hold'] }),
);

describe('planSize', () => {
  it('is 0 for an empty plan', () => {
    expect(planSize({})).toBe(0);
  });

  it('counts each staged change once', () => {
    const plan: WorkPlan = {
      stage: { a: 'doing', b: 'hold' },
      priority: { a: 'P0' },
      pins: { ready: ['c', 'd'], doing: ['a'] },
      unpin: ['e'],
      notes: { a: 'look at this', b: null },
      roadmap_status: { 'FF-12': 'declined' },
      roadmap_reason: { 'FF-12': 'superseded' },
    };
    // A reason travels with its status: it is not a change of its own.
    expect(planSize(plan)).toBe(2 + 1 + 2 + 1 + 2 + 1);
  });
});

describe('reading a board', () => {
  it('finds a card by its key, and nothing on a board that has not loaded', () => {
    const b = plain();
    expect(byKey(b).get('c')?.lane).toBe('ready');
    expect(byKey(b).get('zzz')).toBeUndefined();
    expect(byKey(undefined).size).toBe(0);
  });

  it('lists a lane’s cards in board order', () => {
    const b = board(card('a', 'ready'), card('x', 'doing'), card('b', 'ready'), card('y', 'doing'));
    expect(laneKeys(b, 'ready')).toEqual(['a', 'b']);
    expect(laneKeys(b, 'doing')).toEqual(['x', 'y']);
    expect(laneKeys(b, 'hold')).toEqual([]);
  });
});

describe('canDrop', () => {
  const t = card('t', 'triage', { movable: ['ready', 'hold'] });

  it('always allows a card’s own lane (a reorder)', () => {
    expect(canDrop(t, 'triage')).toBe(true);
    expect(canDrop(card('a', 'ready'), 'ready')).toBe(true);
  });

  it('allows another lane only if the card’s source can move it there', () => {
    expect(canDrop(t, 'ready')).toBe(true);
    expect(canDrop(t, 'hold')).toBe(true);
    expect(canDrop(t, 'doing')).toBe(false);
    expect(canDrop(card('a', 'ready'), 'doing')).toBe(false);
  });

  it('refuses a card the committed board does not have', () => {
    expect(canDrop(undefined, 'ready')).toBe(false);
  });
});

describe('dropInLane: moving between lanes', () => {
  it('stages only the lane for a drop in the empty space at the end', () => {
    const b = plain();
    expect(dropInLane({}, b, b, 't', 'ready', null)).toEqual({ stage: { t: 'ready' } });
  });

  it('keeps the destination lane’s committed pins untouched by such a drop', () => {
    const b = board(pinned('p', 'ready', 0), card('a', 'ready'), card('t', 'triage', { movable: ['ready'] }));
    expect(dropInLane({}, b, b, 't', 'ready', null)).toEqual({ stage: { t: 'ready' } });
  });

  it('stages the lane and pins the card and every card above it for a drop at a position', () => {
    const b = plain();
    expect(dropInLane({}, b, b, 't', 'ready', 'c')).toEqual({ stage: { t: 'ready' }, pins: { ready: ['a', 'b', 't'] } });
    expect(dropInLane({}, b, b, 't', 'ready', 'a')).toEqual({ stage: { t: 'ready' }, pins: { ready: ['t'] } });
  });

  it('leaves the plan as it was for a lane the card may not enter', () => {
    const b = plain();
    const plan: WorkPlan = { notes: { a: 'x' } };
    expect(dropInLane(plan, b, b, 't', 'doing', null)).toBe(plan);
    expect(dropInLane(plan, b, b, 'a', 'hold', null)).toBe(plan);
  });

  it('leaves the plan as it was for a card the committed board does not have', () => {
    const b = plain();
    const plan: WorkPlan = {};
    expect(dropInLane(plan, b, b, 'ghost', 'ready', null)).toBe(plan);
  });

  it('un-stages the move when the card is dropped back in its committed lane', () => {
    const base = plain();
    const moved = dropInLane({}, base, base, 't', 'ready', null);
    const shown = board(...base.items.map((c) => (c.key === 't' ? { ...c, lane: 'ready' as const } : c)));
    expect(dropInLane(moved, base, shown, 't', 'triage', null)).toEqual({});
  });

  it('takes a card out of the pins the plan holds for the lane it leaves', () => {
    const base = board(card('a', 'ready', { movable: ['doing'] }), card('b', 'ready'), card('x', 'doing'));
    const plan: WorkPlan = { pins: { ready: ['a', 'b'] } };
    const shown = board(pinned('a', 'ready', 0, { movable: ['doing'] }), pinned('b', 'ready', 1), card('x', 'doing'));
    const next = dropInLane(plan, base, shown, 'a', 'doing', null);
    expect(next.stage).toEqual({ a: 'doing' });
    expect(next.pins?.ready).toEqual(['b']);
    expect(next.pins?.doing).toBeUndefined();
  });
});

describe('dropInLane: ordering within a lane', () => {
  it('pins the card and every card above it', () => {
    const b = plain();
    expect(dropInLane({}, b, b, 'd', 'ready', 'b')).toEqual({ pins: { ready: ['a', 'd'] } });
    expect(dropInLane({}, b, b, 'd', 'ready', 'c')).toEqual({ pins: { ready: ['a', 'b', 'd'] } });
  });

  it('pins only the card when it is dropped at the top', () => {
    const b = plain();
    expect(dropInLane({}, b, b, 'c', 'ready', 'a')).toEqual({ pins: { ready: ['c'] } });
  });

  it('stages no lane change for a reorder', () => {
    const b = plain();
    expect(dropInLane({}, b, b, 'd', 'ready', 'a').stage).toBeUndefined();
  });

  it('keeps cards below the drop pinned if they already were', () => {
    const b = board(pinned('p1', 'ready', 0), pinned('p2', 'ready', 1), card('a', 'ready'), card('b', 'ready'));
    expect(dropInLane({}, b, b, 'b', 'ready', 'p2')).toEqual({ pins: { ready: ['p1', 'b', 'p2'] } });
  });

  it('changes nothing for a drop in the empty space at the end of the card’s own lane', () => {
    const b = board(pinned('p', 'ready', 0), card('a', 'ready'), card('b', 'ready'));
    expect(dropInLane({}, b, b, 'a', 'ready', null)).toEqual({});
  });

  it('unpins a pinned card dropped in the empty space at the end of its lane', () => {
    const b = board(pinned('p1', 'ready', 0), pinned('p2', 'ready', 1), card('a', 'ready'));
    expect(dropInLane({}, b, b, 'p1', 'ready', null)).toEqual({ pins: { ready: ['p2'] } });
  });

  it('leaves no trace when a drop restores the committed pins', () => {
    const base = board(pinned('p1', 'ready', 0), pinned('p2', 'ready', 1), card('a', 'ready'));
    const swapped = dropInLane({}, base, base, 'p2', 'ready', 'p1');
    expect(swapped).toEqual({ pins: { ready: ['p2', 'p1'] } });
    const shown = board(pinned('p2', 'ready', 0), pinned('p1', 'ready', 1), card('a', 'ready'));
    expect(dropInLane(swapped, base, shown, 'p1', 'ready', 'p2')).toEqual({});
  });

  it('keeps the rest of the plan', () => {
    const b = plain();
    const plan: WorkPlan = { notes: { a: 'x' }, priority: { b: 'P0' } };
    expect(dropInLane(plan, b, b, 'c', 'ready', 'a')).toEqual({ notes: { a: 'x' }, priority: { b: 'P0' }, pins: { ready: ['c'] } });
  });
});

describe('nudge', () => {
  it('moves a card one place up', () => {
    const b = plain();
    // a b c d → a c b d: c is second, so a and c are pinned.
    expect(nudge({}, b, b, 'c', -1)).toEqual({ pins: { ready: ['a', 'c'] } });
  });

  it('moves a card one place down', () => {
    const b = plain();
    // a b c d → a c b d: b is third, so a, c and b are pinned.
    expect(nudge({}, b, b, 'b', 1)).toEqual({ pins: { ready: ['a', 'c', 'b'] } });
  });

  it('does nothing at the top', () => {
    const b = plain();
    const plan: WorkPlan = {};
    expect(nudge(plan, b, b, 'a', -1)).toBe(plan);
  });

  it('stops one short of the last place, which only pinning the whole lane could hold', () => {
    const b = plain();
    const plan: WorkPlan = {};
    expect(nudge(plan, b, b, 'c', 1)).toBe(plan);
    expect(nudge(plan, b, b, 'd', 1)).toBe(plan);
  });

  it('does nothing for a card the shown board does not have', () => {
    const b = plain();
    const plan: WorkPlan = {};
    expect(nudge(plan, b, b, 'ghost', -1)).toBe(plan);
  });

  it('moves within the lane the card is shown in, not the one it was committed to', () => {
    const base = plain();
    const plan: WorkPlan = { stage: { t: 'ready' }, pins: { ready: ['a', 'b', 't'] } };
    const shown = board(
      pinned('a', 'ready', 0), pinned('b', 'ready', 1), pinned('t', 'ready', 2, { movable: ['ready', 'hold'] }), card('c', 'ready'), card('d', 'ready'),
    );
    expect(nudge(plan, base, shown, 't', -1)).toEqual({ stage: { t: 'ready' }, pins: { ready: ['a', 't', 'b'] } });
  });
});

describe('pinTop', () => {
  it('puts the card first in its lane and pins only it', () => {
    const b = plain();
    expect(pinTop({}, b, b, 'c')).toEqual({ pins: { ready: ['c'] } });
  });

  it('puts it above the cards already pinned, which stay pinned', () => {
    const b = board(pinned('p1', 'ready', 0), pinned('p2', 'ready', 1), card('a', 'ready'));
    expect(pinTop({}, b, b, 'a')).toEqual({ pins: { ready: ['a', 'p1', 'p2'] } });
  });

  it('changes nothing for the only card of a lane', () => {
    const b = plain();
    expect(pinTop({}, b, b, 't')).toEqual({});
  });

  it('does nothing for a card the shown board does not have', () => {
    const b = plain();
    const plan: WorkPlan = {};
    expect(pinTop(plan, b, b, 'ghost')).toBe(plan);
  });
});

describe('unpin', () => {
  it('releases one committed pin and keeps the others in order', () => {
    const b = board(pinned('p1', 'ready', 0), pinned('p2', 'ready', 1), pinned('p3', 'ready', 2), card('a', 'ready'));
    expect(unpin({}, b, b, 'p2')).toEqual({ pins: { ready: ['p1', 'p3'] } });
  });

  it('stages an empty pin list when the lane’s last committed pin is released', () => {
    const b = board(pinned('p', 'ready', 0), card('a', 'ready'));
    expect(unpin({}, b, b, 'p')).toEqual({ pins: { ready: [] } });
  });

  it('leaves no trace when it undoes a pin the plan itself made', () => {
    const base = plain();
    const plan = pinTop({}, base, base, 'c');
    const shown = board(pinned('c', 'ready', 0), card('a', 'ready'), card('b', 'ready'), card('d', 'ready'), card('t', 'triage', { movable: ['ready', 'hold'] }));
    expect(unpin(plan, base, shown, 'c')).toEqual({});
  });

  it('touches only the card’s own lane', () => {
    const b = board(pinned('p', 'ready', 0), pinned('q', 'doing', 0), pinned('r', 'doing', 1));
    expect(unpin({ pins: { doing: ['r', 'q'] } }, b, b, 'p')).toEqual({ pins: { doing: ['r', 'q'], ready: [] } });
  });

  it('does nothing for a card the shown board does not have', () => {
    const b = plain();
    const plan: WorkPlan = {};
    expect(unpin(plan, b, b, 'ghost')).toBe(plan);
  });
});

describe('setPriority', () => {
  const computed = () => board(card('a', 'ready', { priority: 'P2', priority_auto: 'P2', priority_source: 'computed' }));
  const overridden = () => board(card('a', 'ready', { priority: 'P0', priority_auto: 'P2', priority_source: 'override' }));

  it('stages a new priority', () => {
    expect(setPriority({}, computed(), 'a', 'P0')).toEqual({ priority: { a: 'P0' } });
  });

  it('replaces an earlier pick for the same card', () => {
    expect(setPriority({ priority: { a: 'P0' } }, computed(), 'a', 'P1')).toEqual({ priority: { a: 'P1' } });
  });

  it('leaves no trace when the pick is what the card already has', () => {
    expect(setPriority({}, computed(), 'a', 'P2')).toEqual({});
    expect(setPriority({ priority: { a: 'P0' } }, computed(), 'a', 'P2')).toEqual({});
  });

  it('clears an override, staged as null, when the pick is what the formula says', () => {
    expect(setPriority({}, overridden(), 'a', 'P2')).toEqual({ priority: { a: null } });
  });

  it('clears an override when asked to reset', () => {
    expect(setPriority({}, overridden(), 'a', null)).toEqual({ priority: { a: null } });
  });

  it('has nothing to reset on a card with no override, and drops an earlier pick', () => {
    expect(setPriority({}, computed(), 'a', null)).toEqual({});
    expect(setPriority({ priority: { a: 'P0' } }, computed(), 'a', null)).toEqual({});
  });

  it('always stages a roadmap entry’s pick as a value: a roadmap spec always has a priority, so there is no override to clear', () => {
    const KEY = 'roadmap:FF-12';
    const entry = (source: WorkItem['priority_source']) => board(card(KEY, 'ready', { kind: 'roadmap', ref: 'FF-12', priority: 'P0', priority_auto: 'P2', priority_source: source }));
    expect(setPriority({}, entry('roadmap'), KEY, 'P1')).toEqual({ priority: { [KEY]: 'P1' } });
    expect(setPriority({}, entry('roadmap'), KEY, 'P2')).toEqual({ priority: { [KEY]: 'P2' } });
    expect(setPriority({}, entry('override'), KEY, 'P2')).toEqual({ priority: { [KEY]: 'P2' } });
    expect(setPriority({}, entry('roadmap'), KEY, 'P0')).toEqual({});
    expect(setPriority({}, entry('roadmap'), KEY, null)).toEqual({});
  });

  it('keeps other cards’ picks and the rest of the plan', () => {
    const b = board(card('a', 'ready'), card('b', 'ready'));
    expect(setPriority({ priority: { b: 'P0' }, notes: { b: 'x' } }, b, 'a', 'P1')).toEqual({ priority: { b: 'P0', a: 'P1' }, notes: { b: 'x' } });
  });

  it('does nothing for a card the committed board does not have', () => {
    const plan: WorkPlan = {};
    expect(setPriority(plan, computed(), 'ghost', 'P0')).toBe(plan);
  });
});

describe('setRoadmapStatus', () => {
  const KEY = 'roadmap:FF-12';
  const roadmap = (more: Partial<WorkItem> = {}) => board(
    card(KEY, 'ready', { kind: 'roadmap', ref: 'FF-12', stage: 'planned', movable: ['doing', 'hold'], ...more }),
    card('a', 'ready'),
  );

  it('stages the status under the entry’s roadmap id', () => {
    expect(setRoadmapStatus({}, roadmap(), KEY, 'in-progress')).toEqual({ roadmap_status: { 'FF-12': 'in-progress' } });
  });

  it('leaves no trace when the status is the one the entry already has', () => {
    expect(setRoadmapStatus({}, roadmap(), KEY, 'planned')).toEqual({});
    expect(setRoadmapStatus({ roadmap_status: { 'FF-12': 'done' } }, roadmap(), KEY, 'planned')).toEqual({});
  });

  it('keeps the reason for a decline, trimmed', () => {
    expect(setRoadmapStatus({}, roadmap(), KEY, 'declined', '  superseded by FF-20 \n')).toEqual({
      roadmap_status: { 'FF-12': 'declined' }, roadmap_reason: { 'FF-12': 'superseded by FF-20' },
    });
  });

  it('stages a decline without a reason when none is given', () => {
    expect(setRoadmapStatus({}, roadmap(), KEY, 'declined')).toEqual({ roadmap_status: { 'FF-12': 'declined' } });
    expect(setRoadmapStatus({}, roadmap(), KEY, 'declined', '   ')).toEqual({ roadmap_status: { 'FF-12': 'declined' } });
  });

  it('drops a reason when the status is no longer a decline', () => {
    const declined: WorkPlan = { roadmap_status: { 'FF-12': 'declined' }, roadmap_reason: { 'FF-12': 'superseded' } };
    expect(setRoadmapStatus(declined, roadmap(), KEY, 'done', 'superseded')).toEqual({ roadmap_status: { 'FF-12': 'done' } });
  });

  it('replaces a staged lane move: the status decides the entry’s lane', () => {
    const plan: WorkPlan = { stage: { [KEY]: 'doing', a: 'hold' } };
    expect(setRoadmapStatus(plan, roadmap(), KEY, 'done')).toEqual({ stage: { a: 'hold' }, roadmap_status: { 'FF-12': 'done' } });
  });

  it('does nothing for a card that is not a roadmap entry, or is not on the board', () => {
    const plan: WorkPlan = {};
    expect(setRoadmapStatus(plan, roadmap(), 'a', 'done')).toBe(plan);
    expect(setRoadmapStatus(plan, roadmap(), 'ghost', 'done')).toBe(plan);
  });
});

describe('setNote', () => {
  const noted = () => board(card('a', 'ready', { note: 'waiting on review' }), card('b', 'ready'));

  it('stages a note, trimmed', () => {
    expect(setNote({}, noted(), 'b', '  ask Amr first \n')).toEqual({ notes: { b: 'ask Amr first' } });
  });

  it('stages a changed note', () => {
    expect(setNote({}, noted(), 'a', 'review done')).toEqual({ notes: { a: 'review done' } });
  });

  it('stages the removal of a note as null', () => {
    expect(setNote({}, noted(), 'a', '')).toEqual({ notes: { a: null } });
    expect(setNote({}, noted(), 'a', '   ')).toEqual({ notes: { a: null } });
  });

  it('leaves no trace when the text is the note the card already has', () => {
    expect(setNote({}, noted(), 'a', 'waiting on review')).toEqual({});
    expect(setNote({ notes: { a: 'draft' } }, noted(), 'a', ' waiting on review ')).toEqual({});
  });

  it('leaves no trace for an empty note on a card that has none', () => {
    expect(setNote({}, noted(), 'b', '')).toEqual({});
    expect(setNote({ notes: { b: 'draft' } }, noted(), 'b', '  ')).toEqual({});
  });

  it('does nothing for a card the committed board does not have', () => {
    const plan: WorkPlan = {};
    expect(setNote(plan, noted(), 'ghost', 'x')).toBe(plan);
  });
});

describe('every plan function', () => {
  it('returns a new plan and edits neither the plan nor the boards it was given', () => {
    const base = freeze(board(
      pinned('p', 'ready', 0), card('a', 'ready', { movable: ['doing'], note: 'n', priority_source: 'override', priority: 'P0' }), card('b', 'ready'),
      card('roadmap:FF-1', 'triage', { kind: 'roadmap', ref: 'FF-1', stage: 'idea', movable: ['ready'] }),
    ));
    const plan = freeze<WorkPlan>({
      stage: { 'roadmap:FF-1': 'ready' }, priority: { b: 'P1' }, pins: { ready: ['p', 'b'], triage: ['roadmap:FF-1'] },
      notes: { b: 'x' }, roadmap_status: { 'FF-1': 'planned' }, roadmap_reason: {},
    });
    const before = JSON.stringify(plan);
    const steps: (() => WorkPlan)[] = [
      () => dropInLane(plan, base, base, 'a', 'doing', null),
      () => dropInLane(plan, base, base, 'b', 'ready', 'p'),
      () => dropInLane(plan, base, base, 'roadmap:FF-1', 'ready', 'p'),
      () => nudge(plan, base, base, 'a', -1),
      () => pinTop(plan, base, base, 'b'),
      () => unpin(plan, base, base, 'p'),
      () => setPriority(plan, base, 'a', null),
      () => setPriority(plan, base, 'b', 'P0'),
      () => setRoadmapStatus(plan, base, 'roadmap:FF-1', 'declined', 'no'),
      () => setNote(plan, base, 'a', ''),
    ];
    for (const step of steps) {
      const next = step();
      expect(next).not.toBe(plan);
      expect(JSON.stringify(plan)).toBe(before);
    }
  });
});
