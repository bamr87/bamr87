// format.ts is the one set of number, money, age and cron rules every page
// shares, so each rule is held here once. The machine's locale and time zone
// are not the test's business: where the code formats for "the reader's
// locale", the test reads it as en-US in UTC (pinLocale).
import { describe, expect, it, vi } from 'vitest';
import {
  age, ago, cronDays, cronHours, dash, duration, fmt, includesText, parseList, pct, repoName, seconds, sharePct, usd, when,
} from './format';

function pinLocale(): void {
  const num = Number.prototype.toLocaleString;
  const date = Date.prototype.toLocaleString;
  vi.spyOn(Number.prototype, 'toLocaleString').mockImplementation(function pinned(this: number, _locales?: unknown, options?: Intl.NumberFormatOptions) {
    return num.call(this, 'en-US', options);
  });
  vi.spyOn(Date.prototype, 'toLocaleString').mockImplementation(function pinned(this: Date, _locales?: unknown, options?: Intl.DateTimeFormatOptions) {
    return date.call(this, 'en-US', { ...options, timeZone: 'UTC' });
  });
}

const ALL_HOURS = Array.from({ length: 24 }, (_, i) => i);
const ALL_DAYS = [0, 1, 2, 3, 4, 5, 6];

describe('fmt', () => {
  it('shows a dash for a value that is absent, never for a zero', () => {
    expect(fmt(null)).toBe(dash);
    expect(fmt(undefined)).toBe(dash);
    expect(fmt('')).toBe(dash);
    expect(fmt(0)).toBe('0');
  });

  it('gives integers thousands separators', () => {
    pinLocale();
    expect(fmt(34913)).toBe('34,913');
    expect(fmt(40000)).toBe('40,000');
    expect(fmt(999)).toBe('999');
    expect(fmt(-1200)).toBe('-1,200');
  });

  it('rounds a fraction to the asked digits and keeps the separators', () => {
    pinLocale();
    expect(fmt(34913.37)).toBe('34,913.4');
    expect(fmt(1.26, 1)).toBe('1.3');
    expect(fmt(1234.5678, 2)).toBe('1,234.57');
    expect(fmt(2.3, 0)).toBe('2');
  });

  it('pads a fraction to the asked digits, so a column lines up', () => {
    pinLocale();
    expect(fmt(1.5, 2)).toBe('1.50');
    expect(fmt(0.25, 3)).toBe('0.250');
  });

  it('passes anything that is not a number through as text', () => {
    expect(fmt('n/a')).toBe('n/a');
    expect(fmt('12')).toBe('12');
    expect(fmt(true)).toBe('true');
  });
});

describe('usd', () => {
  it('shows a dash for an absent amount, and $0.00 for none spent', () => {
    expect(usd(null)).toBe(dash);
    expect(usd(undefined)).toBe(dash);
    expect(usd('')).toBe(dash);
    expect(usd(0)).toBe('$0.00');
  });

  it('always shows two decimals', () => {
    expect(usd(3)).toBe('$3.00');
    expect(usd(2.5)).toBe('$2.50');
    expect(usd(0.126)).toBe('$0.13');
    expect(usd(12.994)).toBe('$12.99');
  });

  it('reads a numeric string the way the API sometimes sends it', () => {
    expect(usd('2.5')).toBe('$2.50');
  });
});

describe('pct', () => {
  it('is a whole percentage of the total', () => {
    expect(pct(1, 4)).toBe(25);
    expect(pct(1, 3)).toBe(33);
    expect(pct(2, 3)).toBe(67);
    expect(pct(5, 5)).toBe(100);
    expect(pct(0, 5)).toBe(0);
  });

  it('is 0 of nothing rather than a division by zero', () => {
    expect(pct(3, 0)).toBe(0);
    expect(pct(0, 0)).toBe(0);
  });

  it('can exceed 100 when the part is over the total (spend over a budget)', () => {
    expect(pct(15, 10)).toBe(150);
  });
});

describe('sharePct', () => {
  it('turns a 0..1 share into a whole percentage', () => {
    expect(sharePct(0.256)).toBe('26%');
    expect(sharePct(0)).toBe('0%');
    expect(sharePct(1)).toBe('100%');
  });

  it('shows a dash when there is no share', () => {
    expect(sharePct(null)).toBe(dash);
    expect(sharePct(undefined)).toBe(dash);
  });
});

describe('ago', () => {
  it('names whole days, and says today for none', () => {
    expect(ago(0)).toBe('today');
    expect(ago(1)).toBe('1d');
    expect(ago(14)).toBe('14d');
  });

  it('shows a dash when the day is unknown', () => {
    expect(ago(null)).toBe(dash);
    expect(ago(undefined)).toBe(dash);
  });
});

describe('age', () => {
  it('shows a dash when the age is unknown', () => {
    expect(age(null)).toBe(dash);
    expect(age(undefined)).toBe(dash);
  });

  it('says now for under an hour', () => {
    expect(age(0)).toBe('now');
    expect(age(0.5 / 24)).toBe('now');
  });

  it('counts hours under a day', () => {
    expect(age(1 / 24)).toBe('1h');
    expect(age(5 / 24)).toBe('5h');
    expect(age(0.5)).toBe('12h');
  });

  it('keeps one decimal for the first days, where a tenth still matters', () => {
    expect(age(1)).toBe('1.0d');
    expect(age(2.1)).toBe('2.1d');
    expect(age(9.5)).toBe('9.5d');
  });

  it('rounds to whole days from ten on', () => {
    expect(age(10)).toBe('10d');
    expect(age(14)).toBe('14d');
    expect(age(13.6)).toBe('14d');
  });
});

describe('when', () => {
  it('shows a dash for no timestamp', () => {
    expect(when(null)).toBe(dash);
    expect(when(undefined)).toBe(dash);
    expect(when('')).toBe(dash);
  });

  it('shows text it cannot read as a date unchanged, rather than "Invalid Date"', () => {
    expect(when('yesterday-ish')).toBe('yesterday-ish');
  });

  it('shows a date and a time to the minute', () => {
    pinLocale();
    const text = when('2026-11-07T15:04:59Z');
    expect(text).toContain('Nov 7, 2026');
    expect(text).toMatch(/3:04\sPM/);
    expect(text).not.toContain(':59');
  });
});

describe('duration (milliseconds)', () => {
  it('shows a dash when there is none', () => {
    expect(duration(null)).toBe(dash);
    expect(duration(undefined)).toBe(dash);
  });

  it('counts seconds up to a minute and a half', () => {
    expect(duration(0)).toBe('0s');
    expect(duration(1400)).toBe('1s');
    expect(duration(45_000)).toBe('45s');
    expect(duration(89_000)).toBe('89s');
  });

  it('counts minutes with one decimal from there', () => {
    expect(duration(90_000)).toBe('1.5m');
    expect(duration(600_000)).toBe('10.0m');
  });
});

describe('seconds', () => {
  it('shows a dash for nothing and for what is not a finite number', () => {
    expect(seconds(null)).toBe(dash);
    expect(seconds(undefined)).toBe(dash);
    expect(seconds(Number.NaN)).toBe(dash);
    expect(seconds(Number.POSITIVE_INFINITY)).toBe(dash);
  });

  it('picks the unit a span reads best in', () => {
    expect(seconds(0)).toBe('0s');
    expect(seconds(45)).toBe('45s');
    expect(seconds(12 * 60)).toBe('12m');
    expect(seconds(3.4 * 3600)).toBe('3.4h');
    expect(seconds(2 * 86400)).toBe('2d');
  });

  it('changes unit at 90 seconds, 90 minutes and 48 hours', () => {
    expect(seconds(89)).toBe('89s');
    expect(seconds(100)).toBe('2m');
    expect(seconds(89 * 60)).toBe('89m');
    expect(seconds(90 * 60)).toBe('1.5h');
    expect(seconds(47 * 3600)).toBe('47.0h');
    expect(seconds(48 * 3600)).toBe('2d');
  });
});

describe('cronHours', () => {
  it('reads nothing from what is not a 5-field cron', () => {
    expect(cronHours(null)).toEqual([]);
    expect(cronHours(undefined)).toEqual([]);
    expect(cronHours('')).toEqual([]);
    expect(cronHours('7 11 * *')).toEqual([]);
    expect(cronHours('0 7 11 * * *')).toEqual([]);
  });

  it('reads one hour', () => {
    expect(cronHours('7 11 * * *')).toEqual([11]);
    expect(cronHours('37 0 * * 1')).toEqual([0]);
  });

  it('reads a list, a range, and both together', () => {
    expect(cronHours('0 9,17 * * *')).toEqual([9, 17]);
    expect(cronHours('0 9-11 * * *')).toEqual([9, 10, 11]);
    expect(cronHours('37 6,12-14 * * 1')).toEqual([6, 12, 13, 14]);
  });

  it('counts an hourly or every-n-hours cron in every hour', () => {
    expect(cronHours('7 * * * *')).toEqual(ALL_HOURS);
    expect(cronHours('7 */6 * * *')).toEqual(ALL_HOURS);
  });

  it('ignores the spacing around and between fields', () => {
    expect(cronHours('  7   11 *  * *  ')).toEqual([11]);
  });

  it('never names an hour a day does not have', () => {
    expect(cronHours('0 22-30 * * *')).toEqual([22, 23]);
    expect(cronHours('0 24 * * *')).toEqual([]);
  });

  it('skips a part it cannot read and keeps the rest', () => {
    expect(cronHours('0 x,5 * * *')).toEqual([5]);
  });
});

describe('cronDays (Monday 0 … Sunday 6)', () => {
  it('reads nothing from what is not a 5-field cron', () => {
    expect(cronDays(null)).toEqual([]);
    expect(cronDays(undefined)).toEqual([]);
    expect(cronDays('0 9 * *')).toEqual([]);
  });

  it('counts every day when no weekday is named, a day-of-month rule included', () => {
    expect(cronDays('0 9 * * *')).toEqual(ALL_DAYS);
    expect(cronDays('0 9 * * ?')).toEqual(ALL_DAYS);
    expect(cronDays('0 9 * * */2')).toEqual(ALL_DAYS);
    expect(cronDays('0 9 1 * *')).toEqual(ALL_DAYS);
  });

  it("moves cron's Sunday-first numbers to a Monday-first week", () => {
    expect(cronDays('0 9 * * 1')).toEqual([0]);
    expect(cronDays('0 9 * * 5')).toEqual([4]);
    expect(cronDays('0 9 * * 6')).toEqual([5]);
  });

  it("reads cron's 0 and 7 both as Sunday", () => {
    expect(cronDays('0 9 * * 0')).toEqual([6]);
    expect(cronDays('0 9 * * 7')).toEqual([6]);
    expect(cronDays('0 9 * * 0,7')).toEqual([6]);
  });

  it('reads names in either case', () => {
    expect(cronDays('0 9 * * MON')).toEqual([0]);
    expect(cronDays('0 9 * * sun')).toEqual([6]);
    expect(cronDays('0 9 * * Sat,SUN')).toEqual([5, 6]);
  });

  it('reads ranges of numbers and of names', () => {
    expect(cronDays('0 9 * * MON-FRI')).toEqual([0, 1, 2, 3, 4]);
    expect(cronDays('0 9 * * 1-5')).toEqual([0, 1, 2, 3, 4]);
    expect(cronDays('0 9 * * 5-7')).toEqual([4, 5, 6]);
    expect(cronDays('0 9 * * 0-6')).toEqual(ALL_DAYS);
  });

  it('reads a list in week order, each day once', () => {
    expect(cronDays('0 9 * * 5,1,3')).toEqual([0, 2, 4]);
    expect(cronDays('0 9 * * 1,MON,1-2')).toEqual([0, 1]);
  });

  it('skips a day it cannot read and keeps the rest', () => {
    expect(cronDays('0 9 * * xyz')).toEqual([]);
    expect(cronDays('0 9 * * xyz,2')).toEqual([1]);
  });
});

describe('repoName', () => {
  it('is the name half of owner/name', () => {
    expect(repoName('bamr87/zer0-mistakes')).toBe('zer0-mistakes');
  });

  it('leaves a bare name alone and gives nothing for nothing', () => {
    expect(repoName('scripts')).toBe('scripts');
    expect(repoName(null)).toBe('');
    expect(repoName(undefined)).toBe('');
    expect(repoName('')).toBe('');
  });
});

describe('parseList', () => {
  it('reads a JSON array as a list of strings', () => {
    expect(parseList('["a","b"]')).toEqual(['a', 'b']);
    expect(parseList('[1, 2, true]')).toEqual(['1', '2', 'true']);
    expect(parseList('[]')).toEqual([]);
  });

  it('gives an empty list for nothing, for broken JSON and for JSON that is not a list', () => {
    expect(parseList(null)).toEqual([]);
    expect(parseList(undefined)).toEqual([]);
    expect(parseList('')).toEqual([]);
    expect(parseList('[a, b')).toEqual([]);
    expect(parseList('{"a": 1}')).toEqual([]);
    expect(parseList('"a"')).toEqual([]);
  });
});

describe('includesText', () => {
  it('matches everything while the search box is empty', () => {
    expect(includesText(['a'], '')).toBe(true);
    expect(includesText([], '')).toBe(true);
  });

  it('ignores case on both sides', () => {
    expect(includesText(['Fleet Pulse'], 'pulse')).toBe(true);
    expect(includesText(['fleet pulse'], 'PULSE')).toBe(true);
  });

  it('searches every field of the row, numbers included', () => {
    expect(includesText(['zer0-mistakes', 'jekyll', 42], 'jekyll')).toBe(true);
    expect(includesText(['zer0-mistakes', 'jekyll', 42], '42')).toBe(true);
  });

  it('treats an absent field as empty rather than as the word "null"', () => {
    expect(includesText([null, undefined, 'x'], 'null')).toBe(false);
    expect(includesText([null, undefined, 'x'], 'undefined')).toBe(false);
  });

  it('says no when nothing matches', () => {
    expect(includesText(['fleet', 'pulse'], 'doctor')).toBe(false);
    expect(includesText([], 'doctor')).toBe(false);
  });
});
