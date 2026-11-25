// Which origins a public build's CSP `frame-src` may name (vite.config.ts,
// CONSOLE_FRAME_SRC from ../build-pages.sh). An origin is admitted only when it
// is https, or plain http to this machine's loopback (a console or dev server
// on 127.0.0.1 / localhost): a cleartext frame of another host could be
// rewritten on the wire, so a registry entry that names one is dropped, and
// the build says so. Scheme, host and an optional port only; no path, no
// wildcard (docs/CONSOLE-PAGES.md, ADR 0005 decision 4).
const HTTPS = /^https:\/\/[A-Za-z0-9.-]+(:\d{1,5})?$/;
const LOOPBACK = /^http:\/\/(127\.0\.0\.1|localhost)(:\d{1,5})?$/;

/** True when `origin` may appear in the public page's `frame-src`. */
export function allowedFrameOrigin(origin: string): boolean {
  return HTTPS.test(origin) || LOOPBACK.test(origin);
}

/** Split a space-separated origin list into the admitted and the dropped. */
export function frameOrigins(list: string): { kept: string[]; dropped: string[] } {
  const kept: string[] = [];
  const dropped: string[] = [];
  for (const o of list.split(/\s+/).filter(Boolean)) (allowedFrameOrigin(o) ? kept : dropped).push(o);
  return { kept, dropped };
}
