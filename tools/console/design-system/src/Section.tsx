import type { ReactNode } from 'react';

export interface SectionProps {
  /** Bold summary line. */
  title: ReactNode;
  /** Muted second line under the title. */
  hint?: ReactNode;
  /** Start expanded. */
  open?: boolean;
  children?: ReactNode;
}

/** Collapsible group (native details/summary) used for config blocks and credential groups. */
export function Section({ title, hint, open, children }: SectionProps) {
  return (
    <details className="hc-sect" open={open}>
      <summary>
        {title}
        {hint && <small>{hint}</small>}
      </summary>
      {children}
    </details>
  );
}
