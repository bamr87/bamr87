// Number, money, age and cron formatting — one set of rules for every page.

export const dash = '—';

export function fmt(n: unknown, digits = 1): string {
  if (n === null || n === undefined || n === '') return dash;
  if (typeof n === 'number') return Number.isInteger(n) ? n.toLocaleString() : n.toFixed(digits);
  return String(n);
}

export const usd = (n: unknown): string => (n === null || n === undefined || n === '' ? dash : `$${Number(n).toFixed(2)}`);
export const pct = (a: number, b: number): number => (b ? Math.round((100 * a) / b) : 0);
export const sharePct = (x: number | null | undefined): string => (x == null ? dash : `${Math.round(100 * x)}%`);
export const ago = (d: number | null | undefined): string => (d == null ? dash : d === 0 ? 'today' : `${d}d`);

/** Age in days → "now" / "5h" / "2.1d" / "14d". */
export function age(days: number | null | undefined): string {
  if (days == null) return dash;
  if (days < 1 / 24) return 'now';
  if (days < 1) return `${Math.round(days * 24)}h`;
  return days >= 10 ? `${Math.round(days)}d` : `${days.toFixed(1)}d`;
}

export function when(iso: string | null | undefined): string {
  if (!iso) return dash;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

export function duration(ms: number | null | undefined): string {
  if (ms == null) return dash;
  const s = Math.round(ms / 1000);
  return s < 90 ? `${s}s` : `${(s / 60).toFixed(1)}m`;
}

/** The UTC hours a 5-field cron fires in; hourly-ish crons count in every hour. */
export function cronHours(cron: string | null | undefined): number[] {
  const f = String(cron ?? '').trim().split(/\s+/);
  if (f.length !== 5) return [];
  const h = f[1];
  if (h === '*' || h.startsWith('*/')) return [...Array(24).keys()];
  const out: number[] = [];
  for (const part of h.split(',')) {
    const m = part.match(/^(\d+)(?:-(\d+))?$/);
    if (!m) continue;
    const a = Number(m[1]);
    const b = m[2] ? Number(m[2]) : a;
    for (let i = a; i <= b && i < 24; i++) out.push(i);
  }
  return out;
}

/** "owner/name" → "name". */
export const repoName = (nwo: string | null | undefined): string => String(nwo ?? '').split('/').pop() ?? '';

export function parseList(s: string | null | undefined): string[] {
  try {
    const v = JSON.parse(s || '[]');
    return Array.isArray(v) ? v.map(String) : [];
  } catch {
    return [];
  }
}

export const includesText = (hay: unknown[], q: string): boolean =>
  !q || hay.map((x) => String(x ?? '')).join(' ').toLowerCase().includes(q.toLowerCase());
