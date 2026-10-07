import { cx } from './cx';

export interface MeterProps {
  /** Current amount. */
  value: number;
  /** Cap the amount is measured against; the bar fills value/max (clamped to 100%). */
  max: number;
}

/** 8px progress bar that turns amber at 70% of the cap and red at 100%, so budgets read at a glance. */
export function Meter({ value, max }: MeterProps) {
  const ratio = max ? value / max : 0;
  const tone = ratio >= 1 ? 'hc-crit' : ratio >= 0.7 ? 'hc-warn' : '';
  return (
    <div className={cx('hc-meter', tone)} role="meter" aria-valuenow={value} aria-valuemin={0} aria-valuemax={max}>
      <i style={{ width: `${Math.min(100, 100 * ratio)}%` }} />
    </div>
  );
}
