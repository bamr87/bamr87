/**
 * FeedbackCapture — the Next.js half of the feedback adapter.
 * Spec: bamr87/bamr87 specs/FEEDBACK.md (UPS-FB-04, UPS-FB-32).
 *
 * The console/error ring buffer only earns its keep if it is installed BEFORE
 * the app runs. A widget that loads after hydration reports a clean console for
 * every failure that happened during the initial render — the exact failures
 * worth reporting. `beforeInteractive` is how the App Router says "before the
 * framework", and it is only honoured in the ROOT layout.
 *
 *   // app/layout.tsx
 *   import FeedbackCapture from '@/components/FeedbackCapture'
 *   export default function RootLayout({ children }) {
 *     return (
 *       <html lang="en">
 *         <head><FeedbackCapture /></head>
 *         <body>{children}</body>
 *       </html>
 *     )
 *   }
 *
 * Then mount <FeedbackButton> once inside the app shell (adapters/FeedbackButton.tsx).
 * Vendor both files from the kit into `public/`; never hot-link the hub.
 */
import Script from 'next/script';

export interface FeedbackCaptureProps {
  /** Served from `public/`. Vendor it from templates/feedback/capture.js. */
  src?: string;
}

export function FeedbackCapture({ src = '/fleet-feedback-capture.js' }: FeedbackCaptureProps) {
  return <Script src={src} strategy="beforeInteractive" />;
}

export default FeedbackCapture;
