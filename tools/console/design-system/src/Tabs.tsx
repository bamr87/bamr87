import { cx } from './cx';

export interface TabItem {
  /** Stable identifier passed back to onChange. */
  id: string;
  label: string;
}

export interface TabsProps {
  items: TabItem[];
  /** id of the active tab. */
  value: string;
  onChange?: (id: string) => void;
  /** `nav` is the full-width sticky-style bar under the header; `panes` is the compact in-page switcher. */
  variant?: 'nav' | 'panes';
}

/** Underlined tab strip. The active tab gets an accent underline and heavier weight. */
export function Tabs({ items, value, onChange, variant = 'nav' }: TabsProps) {
  return (
    <nav className={cx('hc-tabs', variant === 'panes' && 'hc-panes')}>
      {items.map(t => (
        <button key={t.id} type="button" className={cx(t.id === value && 'hc-active')} onClick={() => onChange?.(t.id)}>
          {t.label}
        </button>
      ))}
    </nav>
  );
}
