export interface PillarMeterProps {
  /** Recent share, 0–1. */
  share: number;
  /** Target share, 0–1; drawn as a vertical tick. */
  target?: number;
}

/** Pill-shaped share bar with an optional target tick, for coverage against a plan. */
export function PillarMeter({ share, target }: PillarMeterProps) {
  return (
    <div className="hc-pillar">
      <i style={{ width: `${Math.min(100, 100 * share)}%` }} />
      {target != null && <b style={{ left: `calc(${Math.min(100, 100 * target)}% - 1px)` }} />}
    </div>
  );
}
