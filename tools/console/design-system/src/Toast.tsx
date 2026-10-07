import type { HTMLAttributes } from 'react';
import { cx } from './cx';

export interface ToastProps extends HTMLAttributes<HTMLDivElement> {
  /** `error` swaps the accent edge to red. */
  tone?: 'info' | 'error';
}

/** Transient message card with a 4px coloured left edge and a soft shadow. Position it yourself (the console fixes it bottom-right). */
export function Toast({ tone = 'info', className, ...rest }: ToastProps) {
  return <div {...rest} role="status" className={cx('hc-toast', tone === 'error' && 'hc-err', className)} />;
}
