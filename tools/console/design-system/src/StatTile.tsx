import type { ReactNode } from 'react';
import { Card } from './Card';

export interface StatTileProps {
  /** Small caption above the number. */
  label: ReactNode;
  /** The headline figure, already formatted (e.g. "$12.40", "87%"). */
  value: ReactNode;
  /** Optional muted line below, such as a comparison or cap. */
  delta?: ReactNode;
  /** Optional extra content under the delta, typically a Meter. */
  children?: ReactNode;
}

/** KPI tile: caption, 26px value, optional delta line and optional Meter. Place several in a CardGrid. */
export function StatTile({ label, value, delta, children }: StatTileProps) {
  return (
    <Card className="hc-tile">
      <div className="hc-label">{label}</div>
      <div className="hc-value">{value}</div>
      {delta != null && <div className="hc-delta">{delta}</div>}
      {children}
    </Card>
  );
}
