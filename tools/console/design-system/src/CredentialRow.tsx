import type { ReactNode } from 'react';

export interface CredentialRowProps {
  /** Variable name, rendered in monospace. */
  name: string;
  /** One-line description of what the credential is for. */
  description?: ReactNode;
  /** Status pills shown after the name (e.g. Status good "in the environment"). */
  status?: ReactNode;
  /** Controls on the right (set / clear buttons). */
  actions?: ReactNode;
}

/** One row of a credential list: name + pills + description on the left, actions on the right. Stack several; the last has no divider. */
export function CredentialRow({ name, description, status, actions }: CredentialRowProps) {
  return (
    <div className="hc-cred">
      <div className="hc-n">
        <code>{name}</code> {status}
        {description && <small>{description}</small>}
      </div>
      {actions && <div className="hc-set">{actions}</div>}
    </div>
  );
}
