import type { ReactNode } from 'react';
import { Card } from './Card';

export interface HeroProps {
  /** The single big number (52px), already formatted, e.g. a health score. */
  value: ReactNode;
  /** Caption beside the number. */
  label: ReactNode;
  /** Supporting content to the right, such as a Banner list or Status pills. */
  children?: ReactNode;
}

/** Overview headline card: one large figure with a label and supporting content. */
export function Hero({ value, label, children }: HeroProps) {
  return (
    <Card className="hc-hero">
      <div>
        <div className="hc-value">{value}</div>
        <div className="hc-label">{label}</div>
      </div>
      {children && <div>{children}</div>}
    </Card>
  );
}
