/**
 * FeedbackButton — React adapter for the universal <fleet-feedback> widget.
 * Spec: bamr87/bamr87 specs/FEEDBACK.md (UPS-FB-32). Kit: templates/feedback.
 *
 * Mount ONCE in the AppShell. Loads the vendored script on first render and
 * renders the custom element; `openFeedback()` lets the error boundary, the
 * 404 route, and "Suggest an edit" links open it pre-typed.
 *
 *   <FeedbackButton repo="bamr87/aieo" branch="main" source={route.sourcePath} />
 *   openFeedback({ type: 'fix-page', extra: `Missing route: ${pathname}` })
 */
import { useEffect } from 'react';

declare global {
  interface Window {
    FleetFeedback?: { open: (o?: OpenOptions) => void; logs: unknown[]; version: string };
  }
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace JSX {
    interface IntrinsicElements {
      'fleet-feedback': React.DetailedHTMLProps<React.HTMLAttributes<HTMLElement>, HTMLElement> & Record<string, string | undefined>;
    }
  }
}

export interface OpenOptions {
  type?: string;
  description?: string;
  extra?: string;
}

export interface FeedbackButtonProps {
  repo: string;
  branch?: string;
  source?: string;
  pageTitle?: string;
  labels?: string;
  assignee?: string;
  mode?: 'url' | 'proxy';
  endpoint?: string;
  fab?: boolean;
  label?: string;
  scriptSrc?: string;
  typesUrl?: string;
}

const DEFAULT_SRC = '/fleet-feedback.js';

export function openFeedback(opts?: OpenOptions): void {
  window.FleetFeedback?.open(opts);
}

export function FeedbackButton(p: FeedbackButtonProps) {
  const src = p.scriptSrc ?? DEFAULT_SRC;
  useEffect(() => {
    if (document.querySelector(`script[src="${src}"]`)) return;
    const s = document.createElement('script');
    s.src = src;
    s.async = true;
    document.head.appendChild(s);
  }, [src]);

  return (
    <fleet-feedback
      repo={p.repo}
      branch={p.branch ?? 'main'}
      source={p.source}
      page-title={p.pageTitle}
      labels={p.labels ?? 'page-feedback'}
      assignee={p.assignee ?? 'copilot'}
      mode={p.mode ?? 'url'}
      endpoint={p.endpoint}
      fab={p.fab === false ? 'false' : 'true'}
      label={p.label ?? 'Improve this page'}
      env={import.meta.env?.MODE}
      types={p.typesUrl}
    />
  );
}

export default FeedbackButton;
