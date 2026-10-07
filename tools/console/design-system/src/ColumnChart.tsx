export interface ColumnSeries {
  /** Legend label. */
  label: string;
  /** One value per column. */
  values: number[];
}

export interface ColumnChartProps {
  /** One or two series; the second stacks on the first in the secondary hue. */
  series: ColumnSeries[];
  /** Axis labels, one per column (only every few are shown if crowded). */
  labels: string[];
  /** Plot height in px. */
  height?: number;
}

/** Stacked column chart: thin bars on a baseline with 4px-rounded tops, a legend when there are two series and a sparse x axis. */
export function ColumnChart({ series, labels, height = 120 }: ColumnChartProps) {
  const n = labels.length;
  const totals = labels.map((_, i) => series.reduce((a, s) => a + (s.values[i] || 0), 0));
  const max = Math.max(1, ...totals);
  const cols = { gridTemplateColumns: `repeat(${n}, minmax(6px, 1fr))` };
  const step = Math.max(1, Math.ceil(n / 12));
  return (
    <div>
      {series.length > 1 && (
        <div className="hc-legend">
          {series.map((s, i) => (
            <span key={s.label}><i className={i === 1 ? 'hc-s2' : ''} />{s.label}</span>
          ))}
        </div>
      )}
      <div className="hc-cols" style={{ ...cols, height }} role="img" aria-label={series.map(s => s.label).join(', ')}>
        {labels.map((l, i) => (
          <div className="hc-c" key={l + i} title={`${l}: ${totals[i]}`}>
            {series.map((s, k) => (s.values[i] ? <i key={k} className={k === 1 ? 'hc-s2' : ''} style={{ height: `${(100 * s.values[i]) / max}%` }} /> : null))}
          </div>
        ))}
      </div>
      <div className="hc-axis" style={cols}>
        {labels.map((l, i) => <span key={l + i}>{i % step === 0 ? l : ''}</span>)}
      </div>
    </div>
  );
}
