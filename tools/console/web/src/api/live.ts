// The /live page's feed: an SSE stream of /api/live snapshots (app.py
// live_stream), read with fetch + ReadableStream because EventSource cannot send
// the console's Authorization header. Any stream failure falls back to polling
// /api/live every 5 s, and retries the stream after 30 s.
import { useEffect, useState } from 'react';
import { consoleOrigin, hasConsole } from './backend';
import { api, currentToken } from './client';

export type LiveDoc = Record<string, any>;
export type Transport = 'connecting' | 'sse' | 'polling' | 'unavailable';

export function useLive(intervalS = 5) {
  const [doc, setDoc] = useState<LiveDoc | null>(null);
  const [transport, setTransport] = useState<Transport>('connecting');
  const [error, setError] = useState<string | null>(null);
  const [ticks, setTicks] = useState(0);

  useEffect(() => {
    if (!hasConsole()) { setTransport('unavailable'); return undefined; }
    let stopped = false;
    let ctrl: AbortController | null = null;
    let pollTimer: number | undefined;
    let retryTimer: number | undefined;
    const got = (d: LiveDoc) => { setDoc(d); setError(null); setTicks((n) => n + 1); };

    const poll = async () => {
      if (stopped) return;
      try { got(await api<LiveDoc>('/api/live')); } catch (e) { setError((e as Error).message); }
      pollTimer = window.setTimeout(poll, intervalS * 1000);
    };

    const stream = async () => {
      ctrl = new AbortController();
      const headers: Record<string, string> = { Accept: 'text/event-stream' };
      const tok = currentToken();
      if (tok) headers.Authorization = `Bearer ${tok}`;
      try {
        const res = await fetch(`${consoleOrigin()}/api/live/stream?interval=${intervalS}`, { headers, signal: ctrl.signal });
        if (!res.ok || !res.body) throw new Error(`stream HTTP ${res.status}`);
        setTransport('sse');
        const reader = res.body.getReader();
        const dec = new TextDecoder();
        let buf = '';
        for (;;) {
          const { value, done } = await reader.read();
          if (done) throw new Error('stream closed');
          buf += dec.decode(value, { stream: true });
          let i: number;
          while ((i = buf.indexOf('\n\n')) >= 0) {
            const evt = buf.slice(0, i);
            buf = buf.slice(i + 2);
            const data = evt.split('\n').filter((l) => l.startsWith('data:')).map((l) => l.slice(5).trimStart()).join('\n');
            if (data) got(JSON.parse(data));
          }
        }
      } catch (e) {
        if (stopped) return;
        setTransport('polling');
        void poll();
        retryTimer = window.setTimeout(() => { window.clearTimeout(pollTimer); if (!stopped) void stream(); }, 30_000);
      }
    };
    void stream();
    return () => { stopped = true; ctrl?.abort(); window.clearTimeout(pollTimer); window.clearTimeout(retryTimer); };
  }, [intervalS]);

  return { doc, transport, error, ticks };
}
