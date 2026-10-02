import type { HTMLAttributes } from 'react';
import { cx } from './cx';

export interface CardProps extends HTMLAttributes<HTMLDivElement> {}

/** Surface container with a hairline border and 10px radius. The base for every panel. */
export function Card({ className, ...rest }: CardProps) {
  return <div {...rest} className={cx('hc-card', className)} />;
}
