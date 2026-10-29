// Charts: the column chart is @mantine/charts (Recharts) in Columns.tsx, loaded
// lazily; the ranked horizontal bars are Mantine Progress meters. Both draw in
// the console's validated series roles (--series-1 / --series-2, declared per
// colour scheme in src/theme.ts), keep a tooltip on every mark, and the column
// chart keeps a table view of the same rows — identity is never colour alone.
import { lazy, Suspense, useState, type ReactNode } from 'react';
import { Group, Progress, SegmentedControl, Skeleton, Table, Text, Tooltip, UnstyledButton } from '@mantine/core';
import { fmt } from '../lib/format';
import classes from './Charts.module.css';

const Columns = lazy(() => import('./Columns'));

export interface Series {
  key: string;
  label: string;
  /** Second-series colouring (`s2`); the first series is the default. */
  cls?: string;
}

type Row = Record<string, unknown>;

/**
 * Columns per category (days, hours, months). Two series stack. `tone` may
 * mark a row critical (it draws in the critical role); the table view shows
 * the same numbers.
 */
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
  const data = rows.map((r) => {
    const out: Record<string, unknown> = { [label]: fmtLabel(r[label]) };
    for (const s of series) out[s.label] = Number(r[s.key]) || 0;
    out.__crit = tone?.(r) === 'crit';
    return out;
  });
  const every = Math.max(1, Math.ceil(rows.length / 8));

  return (
    <div>
      <Group justify="space-between" mb={6} gap="xs" wrap="wrap">
        <div>{title}</div>
        <SegmentedControl size="xs" value={view} onChange={(v) => setView(v as 'chart' | 'table')} data={[{ label: 'Chart', value: 'chart' }, { label: 'Table', value: 'table' }]} />
      </Group>
      {view === 'table' ? (
        <Table verticalSpacing={3}>
          <Table.Thead>
            <Table.Tr><Table.Th>{label}</Table.Th>{series.map((s) => <Table.Th key={s.key} data-num>{s.label}</Table.Th>)}</Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((r, i) => (
              <Table.Tr key={i}><Table.Td>{fmtLabel(r[label])}</Table.Td>{series.map((s) => <Table.Td key={s.key} data-num>{fmt(r[s.key] ?? 0, 2)}</Table.Td>)}</Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      ) : (
        <Suspense fallback={<Skeleton h={height} />}>
          <Columns data={data} dataKey={label} series={series.map((s) => ({ name: s.label, s2: s.cls === 's2' }))} height={height} every={every}
            critical={Boolean(tone)} valueFormatter={(v) => fmt(v, 2)} />
        </Suspense>
      )}
    </div>
  );
}

/**
 * A ranked list as horizontal meters: label, bar, value. Rows are buttons when
 * `onPick` is given (the keyboard reaches them; the TUI has the same list).
 */
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
      {rows.map((r, i) => {
        const v = Number(r[value]) || 0;
        const body = (
          <>
            <span className={classes.label} title={String(r[label])}>{String(r[label])}</span>
            <Tooltip label={`${String(r[label])}: ${fmt(r[value])}`}>
              <Progress value={(100 * v) / max} color="var(--series-1)" size="md" radius="sm" aria-label={`${String(r[label])}: ${fmt(r[value])}`} />
            </Tooltip>
            <Text span size="xs" c="dimmed">{fmt(r[value])}{extra?.(r)}</Text>
          </>
        );
        return onPick ? (
          <UnstyledButton key={i} className={classes.rowButton} onClick={() => onPick(r)}>{body}</UnstyledButton>
        ) : (
          <div key={i} className={classes.row}>{body}</div>
        );
      })}
    </div>
  );
}
