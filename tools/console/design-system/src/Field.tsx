import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react';
import { cx } from './cx';

export interface TextInputProps extends InputHTMLAttributes<HTMLInputElement> {}
/** Single-line text, password or number input with the console's border and 7px radius. */
export function TextInput({ className, type = 'text', ...rest }: TextInputProps) {
  return <input {...rest} type={type} className={cx('hc-input', className)} />;
}

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {}
/** Native select styled to match TextInput. Pass `<option>` children. */
export function Select({ className, ...rest }: SelectProps) {
  return <select {...rest} className={cx('hc-select', className)} />;
}

export interface TextAreaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {}
/** Full-width multi-line input for briefs and notes. */
export function TextArea({ className, ...rest }: TextAreaProps) {
  return <textarea {...rest} className={cx('hc-textarea', className)} />;
}

export interface InlineLabelProps {
  /** Caption shown beside the control. */
  label: ReactNode;
  children: ReactNode;
}
/** Muted inline caption wrapping a checkbox, select or input inside a Toolbar. */
export function InlineLabel({ label, children }: InlineLabelProps) {
  return (
    <label className="hc-inl">
      {children}
      {label}
    </label>
  );
}
