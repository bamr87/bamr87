'use client';
/**
 * AssistBridgeNext — the Next.js (App Router) half of the page-bridge adapter.
 * Spec: bamr87/bamr87 specs/ASSIST.md (UPS-AST). Kit: templates/assistant.
 *
 *   // app/layout.tsx — inside <body>, once
 *   import AssistBridgeNext from '@/components/AssistBridgeNext'
 *   <AssistBridgeNext enabled={process.env.NODE_ENV !== 'production'} repo="bamr87/law-ai" />
 *
 * It hands the App Router over (`router.push`), so a session moves between
 * routes without a page load, and names the current pathname as the route.
 * Vendor fleet-assist.js into `public/`; never hot-link the hub. With a
 * `basePath` in next.config, pass it as `base`.
 */
import { usePathname, useRouter } from 'next/navigation';
import { useCallback } from 'react';
import { AssistBridge, type AssistBridgeProps } from './AssistBridge';

export type AssistBridgeNextProps = Omit<AssistBridgeProps, 'navigate' | 'route' | 'framework'>;

export function AssistBridgeNext(props: AssistBridgeNextProps) {
  const router = useRouter();
  const pathname = usePathname();
  const navigate = useCallback((path: string) => router.push(path), [router]);
  return <AssistBridge {...props} navigate={navigate} route={pathname ?? undefined} framework="nextjs" />;
}

export default AssistBridgeNext;
