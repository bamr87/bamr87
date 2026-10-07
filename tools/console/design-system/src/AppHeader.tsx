import type { ReactNode } from 'react';

export interface AppHeaderProps {
  /** Product title, e.g. "🛠️ Harness Console". */
  title: ReactNode;
  /** Metadata chips/text shown after the title. */
  meta?: ReactNode;
  /** Right-aligned buttons (refresh, theme toggle, API link). */
  actions?: ReactNode;
}

/** Top bar: title, metadata chips and right-aligned actions on a surface with a bottom hairline. */
export function AppHeader({ title, meta, actions }: AppHeaderProps) {
  return (
    <header className="hc-header">
      <h1>{title}</h1>
      {meta && <div className="hc-meta">{meta}</div>}
      {actions && <div className="hc-actions">{actions}</div>}
    </header>
  );
}
