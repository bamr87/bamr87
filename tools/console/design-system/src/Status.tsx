import type { HTMLAttributes } from 'react';
import { cx } from './cx';

export interface StatusProps extends HTMLAttributes<HTMLSpanElement> {
  /** Semantic state; a glyph (✓ ⚠ ✖ ●) is prefixed so colour is never the only signal. */
  tone?: 'good' | 'warn' | 'crit' | 'info';
}

const GLYPH = { good: '✓', warn: '⚠', crit: '✖', info: '●' } as const;

/** Nowrap pill for a short state word ("in the environment", "absent", "P1"). Use Banner for sentences. */
export function Status({ tone = 'info', className, children, ...rest }: StatusProps) {
  return (
    <span {...rest} className={cx('hc-status', `hc-${tone}`, className)}>
      {GLYPH[tone]} {children}
    </span>
  );
}
