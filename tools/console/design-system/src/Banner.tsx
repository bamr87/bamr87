import type { HTMLAttributes } from 'react';
import { cx } from './cx';

export interface BannerProps extends HTMLAttributes<HTMLDivElement> {
  /** Severity of the notice. */
  tone?: 'info' | 'warn' | 'crit';
}

/** Full-width notice block for sentence-length messages; wraps instead of widening the page like a Status pill would. */
export function Banner({ tone = 'info', className, ...rest }: BannerProps) {
  return <div {...rest} role="note" className={cx('hc-banner', `hc-${tone}`, className)} />;
}
