export interface BarListRow {
  label: string;
  value: number;
  /** Optional text after the number, e.g. a unit. */
  suffix?: string;
}

export interface BarListProps {
  rows: BarListRow[];
}

/** Ranked horizontal bars: ellipsised label, proportional track, muted value. Scales to the largest row. */
export function BarList({ rows }: BarListProps) {
  const max = Math.max(1, ...rows.map(r => r.value || 0));
  if (!rows.length) return <div className="hc-muted">none</div>;
  return (
    <div>
      {rows.map(r => (
        <div className="hc-hbar" key={r.label}>
          <span title={r.label}>{r.label}</span>
          <div className="hc-track"><i style={{ width: `${(100 * (r.value || 0)) / max}%` }} /></div>
          <span className="hc-muted">{r.value.toLocaleString()}{r.suffix ?? ''}</span>
        </div>
      ))}
    </div>
  );
}
