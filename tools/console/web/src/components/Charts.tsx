// Column and bar charts as plain HTML. Thin marks, a 4px rounded data end on
// the baseline, a 2px gap between stacked segments; a tooltip on every mark,
// a legend only when there are two series, and a table view of the same rows
// (identity is never colour alone). Series colours are validated tokens
// (--series-1 / --series-2 in styles.css).
import { useState, type ReactNode } from 'react';
import { Group, SegmentedControl, Table, Text, Tooltip } from '@mantine/core';
import { fmt } from '../lib/format';

export interface Series {
  key: string;
  label: string;
  cls?: string;
}

type Row = Record<string, unknown>;

export function ColumnChart({
  rows, label, series, fmtLabel = (x) => String(x), height = 120, tone, title,
}: {
  rows: Row[];
  label: string;
  series: Series[];
  fmtLabel?: (x: unknown) => string;
  height?: number;
  tone?: (row: Row) => string | undefined;
  title?: ReactNode;
}) {
  const [view, setView] = useState<'chart' | 'table'>('chart');
  const total = (r: Row) => series.reduce((a, s) => a + (Number(r[s.key]) || 0), 0);
  const max = Math.max(1, ...rows.map(total));
  const cols = { gridTemplateColumns: `repeat(${rows.length}, minmax(6px, 1fr))` };
  const every = Math.max(1, Math.ceil(rows.length / 8));

  return (
    <div>
      <Group justify="space-between" mb={6} gap="xs" wrap="wrap">
        <div>{title}</div>
        <SegmentedControl size="xs" value={view} onChange={(v) => setView(v as 'chart' | 'table')} data={[{ label: 'Chart', value: 'chart' }, { label: 'Table', value: 'table' }]} />
      </Group>
      {view === 'table' ? (
        <Table className="dt" verticalSpacing={3} fz="sm">
          <Table.Thead>
            <Table.Tr><Table.Th>{label}</Table.Th>{series.map((s) => <Table.Th key={s.key} className="num">{s.label}</Table.Th>)}</Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((r, i) => (
              <Table.Tr key={i}><Table.Td>{fmtLabel(r[label])}</Table.Td>{series.map((s) => <Table.Td key={s.key} className="num">{fmt(r[s.key] ?? 0, 2)}</Table.Td>)}</Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      ) : (
        <>
          {series.length > 1 ? (
            <div className="legend" style={{ marginBottom: 4 }}>
              {series.map((s) => <span key={s.key}><i className={s.cls ?? ''} />{s.label}</span>)}
            </div>
          ) : null}
          <div className="cols" style={{ ...cols, height }} role="img" aria-label={series.map((s) => s.label).join(', ')}>
            {rows.map((r, i) => {
              const tip = `${fmtLabel(r[label])}\n${series.map((s) => `${s.label}: ${fmt(r[s.key] ?? 0, 2)}`).join('\n')}`;
              const extra = tone?.(r);
              return (
                <Tooltip key={i} label={<span style={{ whiteSpace: 'pre' }}>{tip}</span>} position="top" withArrow transitionProps={{ duration: 0 }}>
                  <div className="c">
                    {series.map((s) => {
                      const v = Number(r[s.key]) || 0;
                      return v ? <i key={s.key} className={`${s.cls ?? ''} ${extra ?? ''}`} style={{ height: `${(100 * v) / max}%` }} /> : null;
                    })}
                    {total(r) ? null : <i style={{ height: 1, background: 'var(--grid)' }} />}
                  </div>
                </Tooltip>
              );
            })}
          </div>
          <div className="axis" style={cols}>
            {rows.map((r, i) => <span key={i}>{i % every === 0 ? fmtLabel(r[label]) : ''}</span>)}
          </div>
        </>
      )}
    </div>
  );
}

export function HBars({ rows, label, value, extra, onPick }: {
  rows: Row[];
  label: string;
  value: string;
  extra?: (r: Row) => ReactNode;
  onPick?: (r: Row) => void;
}) {
  if (!rows.length) return <Text size="sm" c="dimmed">none</Text>;
  const max = Math.max(1, ...rows.map((r) => Number(r[value]) || 0));
  return (
    <div>
      {rows.map((r, i) => (
        <div className="hbar" key={i} style={{ cursor: onPick ? 'pointer' : undefined }} onClick={onPick ? () => onPick(r) : undefined}>
          <span title={String(r[label])}>{String(r[label])}</span>
          <Tooltip label={`${String(r[label])}: ${fmt(r[value])}`}>
            <div className="track"><i style={{ width: `${(100 * (Number(r[value]) || 0)) / max}%` }} /></div>
          </Tooltip>
          <Text span size="xs" c="dimmed">{fmt(r[value])}{extra?.(r)}</Text>
        </div>
      ))}
    </div>
  );
}
