import type { ButtonHTMLAttributes } from 'react';
import { cx } from './cx';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** `primary` is the single main action of a toolbar; `danger` marks destructive or credential-writing actions. */
  variant?: 'default' | 'primary' | 'danger';
}

/** Compact bordered button used in toolbars, rows and headers. */
export function Button({ variant = 'default', className, type = 'button', ...rest }: ButtonProps) {
  return <button {...rest} type={type} className={cx('hc-btn', variant !== 'default' && `hc-${variant}`, className)} />;
}
