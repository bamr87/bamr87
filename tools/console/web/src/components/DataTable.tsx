// One table for every list in the console: sortable headers, a row that is a
// link to its drill-down, a severity edge, and — with `keys` — the TUI's own
// j/k/g/G/enter/o/l/y navigation (keys v1).
import { useEffect, useId, useMemo, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router';
import { ScrollArea, Table, Text } from '@mantine/core';
import { IconChevronDown, IconChevronUp } from '@tabler/icons-react';
import { useKeyScope } from './keyscope';

export interface Column<T> {
  key: string;
  header: ReactNode;
  render: (row: T) => ReactNode;
  sort?: (row: T) => string | number | null | undefined;
  num?: boolean;
  width?: number | string;
  title?: string;
}

export interface DataTableProps<T> {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T, i: number) => string;
  href?: (row: T) => string | null | undefined;
  onActivate?: (row: T) => void;
  tone?: (row: T) => 'crit' | 'warn' | 'muted' | undefined | null | false;
  empty?: ReactNode;
  initialSort?: { key: string; desc?: boolean };
  keys?: boolean;
  open?: (row: T) => string | null | undefined;
  openLive?: (row: T) => string | null | undefined;
  copy?: (row: T) => string | null | undefined;
  onSortKey?: () => void;
  maxHeight?: number;
  minWidth?: number;
  dense?: boolean;
}

function compare(a: unknown, b: unknown): number {
  const na = a === null || a === undefined || a === '';
  const nb = b === null || b === undefined || b === '';
  if (na && nb) return 0;
  if (na) return 1;
  if (nb) return -1;
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: 'base' });
}

export function DataTable<T>(p: DataTableProps<T>) {
  const navigate = useNavigate();
  const [sort, setSort] = useState(p.initialSort ?? null);
  const [sel, setSel] = useState(0);
  const tid = useId();

  const sorted = useMemo(() => {
    if (!sort) return p.rows;
    const col = p.columns.find((c) => c.key === sort.key);
    if (!col?.sort) return p.rows;
    const out = [...p.rows].sort((a, b) => compare(col.sort!(a), col.sort!(b)));
    return sort.desc ? out.reverse() : out;
  }, [p.rows, p.columns, sort]);

  useEffect(() => {
    setSel((s) => Math.min(s, Math.max(0, sorted.length - 1)));
  }, [sorted.length]);

  const activate = (row: T | undefined) => {
    if (!row) return;
    if (p.onActivate) p.onActivate(row);
    else {
      const h = p.href?.(row);
      if (h) navigate(h);
    }
  };
  const openUrl = (u: string | null | undefined) => {
    if (u) window.open(u, '_blank', 'noopener');
  };
  const scrollTo = (i: number) => {
    document.querySelector(`[data-dt="${CSS.escape(tid)}"][data-dt-row="${i}"]`)?.scrollIntoView({ block: 'nearest' });
  };

  useKeyScope(
    {
      move: (d) => setSel((s) => { const n = Math.max(0, Math.min(sorted.length - 1, s + d)); scrollTo(n); return n; }),
      edge: (e) => { const n = e ? sorted.length - 1 : 0; setSel(n); scrollTo(n); },
      activate: () => activate(sorted[sel]),
      open: p.open ? () => openUrl(p.open!(sorted[sel])) : undefined,
      openLive: p.openLive ? () => openUrl(p.openLive!(sorted[sel])) : undefined,
      copy: p.copy
        ? () => {
            const v = p.copy!(sorted[sel]);
            if (v) void navigator.clipboard?.writeText(v);
          }
        : undefined,
      sort: p.onSortKey,
    },
    Boolean(p.keys) && sorted.length > 0,
  );

  const clickable = Boolean(p.href || p.onActivate);
  const header = (c: Column<T>) => {
    const active = sort?.key === c.key;
    const onClick = c.sort ? () => setSort(active ? { key: c.key, desc: !sort?.desc } : { key: c.key, desc: Boolean(c.num) }) : undefined;
    return (
      <Table.Th key={c.key} className={`${c.num ? 'num' : ''} ${c.sort ? 'sortable' : ''}`} onClick={onClick} style={{ width: c.width }} title={c.title}>
        {c.header}
        {active ? (sort?.desc ? <IconChevronDown size={12} /> : <IconChevronUp size={12} />) : null}
      </Table.Th>
    );
  };

  const table = (
    <Table className="dt" striped={false} highlightOnHover={false} verticalSpacing={p.dense ? 4 : 7} horizontalSpacing="sm" miw={p.minWidth} stickyHeader={Boolean(p.maxHeight)}>
      <Table.Thead>
        <Table.Tr>{p.columns.map(header)}</Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {sorted.length ? (
          sorted.map((row, i) => {
            const t = p.tone?.(row);
            const cls = [
              clickable ? 'clickable' : '',
              p.keys && i === sel ? 'selected' : '',
              t === 'crit' ? 'tone-crit' : t === 'warn' ? 'tone-warn' : t === 'muted' ? 'muted-row' : '',
            ].join(' ');
            return (
              <Table.Tr
                key={p.rowKey(row, i)}
                data-dt={tid}
                data-dt-row={i}
                className={cls}
                onClick={(e) => {
                  if (!clickable) return;
                  // Let real links, buttons and inputs inside the row do their own thing.
                  if ((e.target as HTMLElement).closest('a,button,input,select,textarea,label')) return;
                  setSel(i);
                  activate(row);
                }}
              >
                {p.columns.map((c) => (
                  <Table.Td key={c.key} className={c.num ? 'num' : ''}>{c.render(row)}</Table.Td>
                ))}
              </Table.Tr>
            );
          })
        ) : (
          <Table.Tr>
            <Table.Td colSpan={p.columns.length}>
              <Text size="sm" c="dimmed">{p.empty ?? 'nothing to show'}</Text>
            </Table.Td>
          </Table.Tr>
        )}
      </Table.Tbody>
    </Table>
  );

  return (
    <ScrollArea.Autosize mah={p.maxHeight} type="auto" offsetScrollbars style={{ border: '1px solid var(--grid)', borderRadius: 8, background: 'var(--surface)' }}>
      {table}
    </ScrollArea.Autosize>
  );
}
