import type { TableHTMLAttributes } from 'react';
import { cx } from './cx';

export interface TableProps extends TableHTMLAttributes<HTMLTableElement> {
  /** Let long unbreakable values (cron strings, serialised config) wrap instead of scrolling. */
  reference?: boolean;
}

/**
 * Bordered data table inside a horizontal scroller. Pass normal `<thead>/<tbody>`
 * children; add `className="hc-num"` to numeric `th`/`td` (right-aligned, tabular figures)
 * and `hc-flag` / `hc-bad` / `hc-sel` on a `tr` to tint a warning, failing or selected row.
 */
export function Table({ reference, className, ...rest }: TableProps) {
  return (
    <div className="hc-wrap">
      <table {...rest} className={cx('hc-table', reference && 'hc-ref', className)} />
    </div>
  );
}
