// The Overview's story pieces, each in the console's roles: a segmented bar
// (parts of a whole), a bullet (a value against its threshold), a sparkline
// (fifteen days inside a tile), a delta (which way, and is that good), a heat
// strip (a week of UTC hours) and the freshness timeline. Identity is never
// colour alone: every segment has a legend entry, every mark a tooltip, every
// bar an aria label, and a good/bad delta says so in words.
import type { CSSProperties, ReactNode } from 'react';
import { Link } from 'react-router';
import { Anchor, Group, Text, Tooltip, VisuallyHidden } from '@mantine/core';
import { useElementSize } from '@mantine/hooks';
import { IconArrowDownRight, IconArrowUpRight, IconMinus } from '@tabler/icons-react';
import { age, fmt } from '../lib/format';
import { Status, type Tone } from './ui';
import classes from './Viz.module.css';

export type SegTone = Tone | 'muted';

export interface Segment {
  key: string;
  label: string;
  value: number;
  tone: SegTone;
  href?: string;
  /** Said in the tooltip after the count. */
  hint?: string;
}

const vars = (v: Record<string, string | number>) => v as CSSProperties;

/** Parts of one whole as a single bar with 2px of surface between parts, and a legend beneath (swatch, label, value). */
export function SegmentBar({ segments, label, legend = true, height = 10 }: { segments: Segment[]; label: string; legend?: boolean; height?: number }) {
  const shown = segments.filter((s) => s.value > 0);
  const total = shown.reduce((n, s) => n + s.value, 0);
  const text = (s: Segment) => `${s.label}: ${fmt(s.value, 0)}${total ? ` (${Math.round((100 * s.value) / total)}%)` : ''}${s.hint ? ` — ${s.hint}` : ''}`;
  return (
    <div>
      <div className={classes.segments} role="img" aria-label={`${label}: ${segments.map((s) => `${s.label} ${fmt(s.value, 0)}`).join(', ')}`} style={vars({ '--h': `${height}px` })}>
        {shown.map((s) => (
          <Tooltip key={s.key} label={text(s)}>
            {s.href ? (
              <Link to={s.href} className={classes.segment} data-tone={s.tone} style={vars({ '--grow': s.value })} aria-label={text(s)} />
            ) : (
              <span className={classes.segment} data-tone={s.tone} style={vars({ '--grow': s.value })} />
            )}
          </Tooltip>
        ))}
      </div>
      {legend ? (
        <Group gap="sm" mt={6} wrap="wrap">
          {segments.map((s) => (
            <Group key={s.key} gap={5} wrap="nowrap">
              <span className={classes.swatch} data-tone={s.tone} aria-hidden />
              {s.href ? <Anchor component={Link} to={s.href} size="xs">{s.label}</Anchor> : <Text size="xs" c="dimmed">{s.label}</Text>}
              <Text size="xs" fw={600}>{fmt(s.value, 0)}</Text>
            </Group>
          ))}
        </Group>
      ) : null}
    </div>
  );
}

/** A value against its threshold: label, a track with the fill and the threshold's tick, the value, which way is better. */
export function Bullet({
  label, value, max, threshold, tone = 'info', better, format = (v) => fmt(v), sub, href,
}: {
  label: string;
  value: number;
  /** The track's right edge; 0 draws no track (a value with no scale to sit on). */
  max: number;
  threshold?: number | null;
  tone?: SegTone;
  better?: 'up' | 'down' | 'steady';
  format?: (v: number) => string;
  sub?: string;
  href?: string;
}) {
  const pct = max > 0 ? Math.min(100, Math.max(0, (100 * value) / max)) : 0;
  const tick = threshold != null && max > 0 ? Math.min(100, Math.max(0, (100 * threshold) / max)) : null;
  const Arrow = better === 'up' ? IconArrowUpRight : better === 'down' ? IconArrowDownRight : IconMinus;
  return (
    <div className={classes.bullet}>
      <span className={classes.bulletLabel}>
        {href ? <Anchor component={Link} to={href} size="sm">{label}</Anchor> : <Text span size="sm">{label}</Text>}
      </span>
      {max > 0 ? (
        <Tooltip label={`${label}: ${format(value)}${threshold != null ? ` · threshold ${format(threshold)}` : ''}`}>
          <div className={classes.track} role="meter" aria-valuenow={value} aria-valuemin={0} aria-valuemax={max} aria-label={label}>
            <span className={classes.fill} data-tone={tone} style={vars({ '--pct': `${pct}%` })} />
            {tick != null ? <span className={classes.tick} style={vars({ '--pct': `${tick}%` })} aria-hidden /> : null}
          </div>
        </Tooltip>
      ) : <span />}
      <Text span size="sm" fw={600} className={classes.bulletValue}>
        {format(value)}{sub ? <Text span size="xs" c="dimmed" fw={400}> {sub}</Text> : null}
      </Text>
      {better ? <Arrow size={14} className={classes.arrow} aria-label={`better is ${better}`} /> : <span />}
    </div>
  );
}

/** A small series in a tile: a 2px line, a faint area, the last point marked, an optional cap as a dashed rule, a
 *  tooltip per day. It measures its box, so the drawing is never stretched. */
export function Sparkline({
  values, labels, cap, label, format = (v) => fmt(v), height = 40,
}: { values: number[]; labels?: string[]; cap?: number | null; label: string; format?: (v: number) => string; height?: number }) {
  const { ref, width } = useElementSize();
  const n = values.length;
  if (n < 2) return <Text size="xs" c="dimmed">{n ? 'one day of data' : 'no daily data'}</Text>;
  const w = Math.max(80, Math.round(width || 0));
  const top = Math.max(...values, cap ?? 0, 1e-9);
  const px = (i: number) => 4 + (i / (n - 1)) * (w - 8);
  const py = (v: number) => height - 4 - (Math.max(0, v) / top) * (height - 8);
  const line = values.map((v, i) => `${px(i).toFixed(1)},${py(v).toFixed(1)}`).join(' ');
  const area = `${px(0).toFixed(1)},${height - 4} ${line} ${px(n - 1).toFixed(1)},${height - 4}`;
  const step = (w - 8) / (n - 1);
  const day = (i: number) => labels?.[i] ?? `day ${i + 1}`;
  return (
    <div ref={ref} className={classes.sparkBox}>
      <svg className={classes.spark} width={w} height={height} viewBox={`0 0 ${w} ${height}`} role="img"
        aria-label={`${label}: ${format(values[0])} on ${day(0)}, ${format(values[n - 1])} on ${day(n - 1)}, peak ${format(Math.max(...values))}`}>
        <polygon className={classes.sparkArea} points={area} />
        <polyline className={classes.sparkLine} points={line} />
        {cap != null && cap > 0 && cap <= top ? <line className={classes.sparkCap} x1={0} x2={w} y1={py(cap)} y2={py(cap)} /> : null}
        <circle className={classes.sparkDot} cx={px(n - 1)} cy={py(values[n - 1])} r={4} />
        {values.map((v, i) => (
          <rect key={i} className={classes.sparkHit} x={px(i) - step / 2} y={0} width={step} height={height}>
            <title>{`${day(i)}: ${format(v)}`}</title>
          </rect>
        ))}
      </svg>
    </div>
  );
}

/** A week-over-week turn: the arrow and the sign carry the direction, the word says whether it is better. */
export function Delta({ pct, better, suffix = 'WoW' }: { pct: number | null | undefined; better: 'up' | 'down'; suffix?: string }) {
  if (pct == null) return <Text span size="xs" c="dimmed">no prior week</Text>;
  const good = pct === 0 ? null : (pct < 0) === (better === 'down');
  const tone: Tone = good == null ? 'info' : good ? 'good' : 'crit';
  const Arrow = pct > 0 ? IconArrowUpRight : pct < 0 ? IconArrowDownRight : IconMinus;
  return (
    <Text span size="xs" fw={600} className={classes.delta} data-tone={tone}>
      <Arrow size={13} aria-hidden />
      {pct > 0 ? '+' : ''}{fmt(pct)}% {suffix}{good == null ? '' : good ? ' · better' : ' · worse'}
      <VisuallyHidden>{pct > 0 ? ', up' : pct < 0 ? ', down' : ', unchanged'}</VisuallyHidden>
    </Text>
  );
}

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

/** A week of UTC hours (rows Monday to Sunday, columns 0–23): a stepped ramp of one hue by count, a crowded cell
 *  ringed in the critical role. `crowded` holds `Mon:6`-style keys. */
export function HeatStrip({ cells, crowded, cap, unit = 'AI crons' }: { cells: number[][]; crowded: Set<string>; cap?: number | null; unit?: string }) {
  const max = Math.max(1, ...cells.flat());
  const level = (v: number) => (v <= 0 ? 0 : v >= max * 0.8 ? 4 : v >= max * 0.55 ? 3 : v >= max * 0.3 ? 2 : 1);
  const hh = (h: number) => String(h).padStart(2, '0');
  return (
    <div>
      <div className={classes.heat} role="table" aria-label={`${unit} by weekday and UTC hour`}>
        <div className={classes.heatHead} role="row">
          <span />
          {Array.from({ length: 24 }, (_, h) => (
            <span key={h} className={classes.heatHour} role="columnheader" aria-label={`${hh(h)} UTC`}>{h % 6 === 0 ? hh(h) : ''}</span>
          ))}
        </div>
        {DAYS.map((d, di) => (
          <div key={d} className={classes.heatRow} role="row">
            <span className={classes.heatDay} role="rowheader">{d}</span>
            {(cells[di] ?? []).map((v, h) => {
              const hot = crowded.has(`${d}:${h}`);
              const text = `${d} ${hh(h)} UTC: ${v} ${unit}${hot ? ` — more than ${cap ?? '—'} can fire this hour` : ''}`;
              return (
                <Tooltip key={h} label={text}>
                  <span className={classes.heatCell} role="cell" data-level={level(v)} data-hot={hot || undefined} aria-label={text} />
                </Tooltip>
              );
            })}
          </div>
        ))}
      </div>
      <Group gap={6} mt={6} wrap="wrap">
        <Text size="xs" c="dimmed">fewer</Text>
        {[0, 1, 2, 3, 4].map((l) => <span key={l} className={classes.heatCell} data-level={l} data-key aria-hidden />)}
        <Text size="xs" c="dimmed">more (peak {max}) · ringed: more than {cap ?? '—'} AI crons can fire in that hour on that day</Text>
      </Group>
    </div>
  );
}

export interface FreshnessRow {
  key: string;
  label: ReactNode;
  present: boolean;
  age_days?: number | null;
  stamp?: string | null;
  tone: Tone;
  action?: ReactNode;
}

const TICKS: [number, string][] = [[0, 'now'], [1, '1d'], [3, '3d'], [7, '1w'], [30, '1mo'], [365, '1y']];
const pos = (days: number) => Math.min(100, (100 * Math.log10(1 + Math.max(0, days))) / Math.log10(1 + 365));

/** Every source on one log-scale axis: a lane per source, its dot where its age falls, its state and its refresh. */
export function FreshnessTimeline({ rows }: { rows: FreshnessRow[] }) {
  return (
    <div className={classes.timeline}>
      <div className={classes.tlHead}>
        <span className={classes.tlSpacer} />
        <div className={classes.tlAxis} aria-hidden>
          {TICKS.map(([d, l]) => <span key={l} className={classes.tlTick} style={vars({ '--x': `${pos(d)}%` })}>{l}</span>)}
        </div>
        <span className={classes.tlSpacer} />
      </div>
      {rows.map((r) => {
        const state = r.present ? (r.age_days == null ? 'present' : `${age(r.age_days)} old`) : 'missing';
        return (
          <div key={r.key} className={classes.tlRow}>
            <span className={classes.tlLabel}>{r.label}</span>
            <div className={classes.tlTrack}>
              {r.present && r.age_days != null ? (
                <Tooltip label={`${r.stamp ?? 'no stamp'} · ${state}`}>
                  <span className={classes.tlDot} data-tone={r.tone} style={vars({ '--x': `${pos(r.age_days)}%` })} role="img" aria-label={state} />
                </Tooltip>
              ) : <Text size="xs" c="dimmed" className={classes.tlNote}>{r.present ? 'no stamp' : 'missing'}</Text>}
            </div>
            <Group gap={6} wrap="nowrap" justify="flex-end">
              <Status tone={r.tone} title={r.stamp ?? undefined}>{state}</Status>
              {r.action}
            </Group>
          </div>
        );
      })}
    </div>
  );
}
