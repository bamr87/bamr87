import type { HTMLAttributes } from 'react';
import { cx } from './cx';

export interface CardGridProps extends HTMLAttributes<HTMLDivElement> {}

/** Auto-fitting grid (min 190px columns, 12px gap) for rows of StatTile or Card. */
export function CardGrid({ className, ...rest }: CardGridProps) {
  return <div {...rest} className={cx('hc-grid', className)} />;
}
