// switchPlan.ts decides what the Switches page offers: a toggle asks for the
// opposite of what the loop's switch says now, an unreadable variable is never
// shown as unset, writes that are off or a repository the hub does not own
// disable the lever with the reason, and Apply is offered only for the exact
// plan that was previewed with this reason, with something to do and a diff.
import { describe, expect, it } from 'vitest';
import type { SwitchPlan, SwitchRow, SwitchesDoc } from '../api/switchTypes';
import {
  applyBlocked, flipTitle, isOn, itemChange, loopFlip, reasonOk, repoBlocked, repoFlip, rowBlocked, semanticsLabel, shown,
} from './switchPlan';

function row(more: Partial<SwitchRow> = {}): SwitchRow {
  return {
    key: 'it-journey/theme-scout', repo: 'bamr87/it-journey', workflow: '.github/workflows/theme-scout.yml', group: 'it-journey-loops',
    gate: 'repo_variable', variable: 'THEME_SCOUT_ENABLED', semantics: 'opt_in', default: 'off',
    live: { value: 'true', state: 'set', updated_at: '2026-11-23T21:38:32Z', on: true },
    effective: { on: true, why: "THEME_SCOUT_ENABLED is 'true'", verified: true },
    map: { state: 'on', verified: true, says: 'on', level_off: null, reason: null, set_by: 'bamr87', set_at: '2026-11-23', expires: null },
    drift: false, hold: null, note: null, flippable: true, not_flippable: null, ...more,
  };
}

const on = { writes: { enabled: true, why: null } } as Pick<SwitchesDoc, 'writes'>;
const off = { writes: { enabled: false, why: 'GitHub writes are switched off in this console (DASH_CONSOLE_GITHUB_WRITES / DASH_CONSOLE_AUTH)' } } as Pick<SwitchesDoc, 'writes'>;

function plan(more: Partial<SwitchPlan> = {}): SwitchPlan {
  return {
    schema: 'switches-plan/v1', plan_id: '0123456789abcdef', scope: 'loop', key: 'it-journey/theme-scout', target: 'off',
    reason: 'pause for the audit', set_by: 'bamr87', set_at: '2026-11-25', created_at: '2026-11-25T20:00:00Z', op: 'switches-apply',
    writes: { enabled: true, why: null }, login_known: true, diff: '--- a/_data/fleet.yml\n', diff_error: null, commit: '',
    items: [{
      key: 'it-journey/theme-scout', repo: 'bamr87/it-journey', workflow: null, variable: 'THEME_SCOUT_ENABLED', semantics: 'opt_in',
      current: 'true', current_state: 'set', current_on: true, new: 'false', write_variable: true, write_map: true,
      map_before: { state: 'on', verified: true }, map_after: { state: 'off', verified: true }, do: true, skip: null, warnings: [],
    }],
    counts: { do: 1, skip: 0, variables: 1, records: 1 }, ...more,
  };
}

describe('a toggle', () => {
  it('asks for the opposite of what the variable says', () => {
    expect(loopFlip(row())).toEqual({ scope: 'loop', key: 'it-journey/theme-scout', target: 'off' });
    expect(loopFlip(row({ live: { value: 'false', state: 'set', updated_at: null, on: false } })).target).toBe('on');
  });

  it('reads an unset opt-out variable as on, and an unreadable one from the map', () => {
    const optOut = row({ semantics: 'opt_out', live: { value: '', state: 'unset', updated_at: null, on: true } });
    expect(isOn(optOut)).toBe(true);
    const blind = row({ live: { value: null, state: 'unreadable', updated_at: null, on: null }, map: { ...row().map, state: 'off' } });
    expect(isOn(blind)).toBe(false);
    expect(loopFlip(blind).target).toBe('on');
  });

  it('names its scope in the dialog title', () => {
    expect(flipTitle(loopFlip(row()))).toBe('Turn loop it-journey/theme-scout off');
    expect(flipTitle(repoFlip('bamr87/it-journey', 'on'))).toBe('Turn every loop of bamr87/it-journey on');
    expect(flipTitle({ scope: 'all', key: '', target: 'off' })).toBe('Turn every loop in the map off');
  });
});

describe('what the page shows', () => {
  it('never shows an unreadable variable as unset', () => {
    expect(shown(null)).toBe('unreadable');
    expect(shown('')).toBe('unset');
    expect(shown('true')).toBe("'true'");
  });

  it('spells out the semantics', () => {
    expect(semanticsLabel('opt_in')).toContain("only when 'true'");
    expect(semanticsLabel('opt_out')).toContain("unless 'false'");
    expect(semanticsLabel(null)).toBe('no variable');
  });

  it('summarises a plan item: current → new, or why it is skipped', () => {
    expect(itemChange(plan().items[0])).toBe("THEME_SCOUT_ENABLED 'true' → 'false'; map on → off");
    expect(itemChange({ ...plan().items[0], do: false, skip: 'held' })).toBe('skip: held');
    expect(itemChange({ ...plan().items[0], write_variable: false, new: 'true' })).toBe("THEME_SCOUT_ENABLED stays 'true'; map on → off");
  });
});

describe('the levers', () => {
  it('are off, with the reason, while the console writes nothing to GitHub', () => {
    expect(rowBlocked(off, row())).toContain('DASH_CONSOLE_GITHUB_WRITES');
    expect(repoBlocked(off, { repo: 'bamr87/it-journey', writable: true, readable: true, error: null })).toContain('switched off');
  });

  it('are off for a repository the hub does not own, or whose variables could not be read', () => {
    expect(repoBlocked(on, { repo: 'bash-365/bash-365.com', writable: false, readable: true, error: null })).toContain('not a repository the hub owns');
    expect(repoBlocked(on, { repo: 'bamr87/x', writable: true, readable: false, error: 'GitHub 403' })).toContain('GitHub 403');
    expect(rowBlocked(on, row({ flippable: false, not_flippable: 'held' }))).toBe('held');
    expect(rowBlocked(on, row())).toBeNull();
  });

  it('need a reason of 3–300 characters', () => {
    expect(reasonOk('  ')).toBe(false);
    expect(reasonOk('ok')).toBe(false);
    expect(reasonOk('pause it')).toBe(true);
    expect(reasonOk('x'.repeat(301))).toBe(false);
  });
});

describe('Apply', () => {
  it('is offered only for the plan previewed with this reason', () => {
    expect(applyBlocked(null, 'pause for the audit')).toBe('preview it first');
    expect(applyBlocked(plan(), 'pause for the audit')).toBeNull();
    expect(applyBlocked(plan(), '  pause   for the audit ')).toBeNull();
    expect(applyBlocked(plan(), 'another reason')).toContain('preview it again');
  });

  it('is refused with nothing to do, no diff, writes off or no login', () => {
    expect(applyBlocked(plan({ counts: { do: 0, skip: 1, variables: 0, records: 0 } }), 'pause for the audit')).toContain('nothing to apply');
    expect(applyBlocked(plan({ diff_error: 'needs ruamel.yaml' }), 'pause for the audit')).toContain('ruamel');
    expect(applyBlocked(plan({ writes: off.writes }), 'pause for the audit')).toContain('switched off');
    expect(applyBlocked(plan({ login_known: false }), 'pause for the audit')).toContain('no GitHub login');
  });

  it('records the map alone when writes are off and no variable needs writing', () => {
    expect(applyBlocked(plan({ writes: off.writes, counts: { do: 1, skip: 0, variables: 0, records: 1 } }), 'pause for the audit')).toBeNull();
  });
});
