// A job's log, tailed live. Follows the tail only while the reader is already
// at the bottom, so a streaming job never yanks the view away from what you
// scrolled back to. A job that SUCCEEDS refreshes every console document: its
// output is new data in the working tree.
import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import type { JobTail } from '../api/types';
import { ansiToHtml } from '../lib/ansi';

export function useJobTail(jobId: string | null) {
  const qc = useQueryClient();
  const [raw, setRaw] = useState('');
  const [tail, setTail] = useState<JobTail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId) return undefined;
    let offset = 0;
    let stopped = false;
    let timer: number | undefined;
    setRaw('');
    setTail(null);
    setError(null);
    const tick = async () => {
      try {
        const t = await api<JobTail>(`/api/jobs/${jobId}?offset=${offset}`);
        if (stopped) return;
        if (t.text) setRaw((r) => r + t.text);
        offset = t.offset;
        setTail(t);
        if (t.done) {
          void qc.invalidateQueries({ queryKey: ['jobs'] });
          if (t.job.status === 'succeeded') void qc.invalidateQueries();
          return;
        }
      } catch (e) {
        if (!stopped) setError((e as Error).message);
        return;
      }
      timer = window.setTimeout(tick, 1000);
    };
    void tick();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [jobId, qc]);

  return { raw, tail, error };
}

export function LogView({ raw, height = 480, placeholder }: { raw: string; height?: number | string; placeholder?: string }) {
  const ref = useRef<HTMLPreElement>(null);
  const pinned = useRef(true);
  useEffect(() => {
    const el = ref.current;
    if (el && pinned.current) el.scrollTop = el.scrollHeight;
  }, [raw]);
  return (
    <pre
      ref={ref}
      className="log"
      style={{ height, maxHeight: height }}
      onScroll={(e) => {
        const el = e.currentTarget;
        pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
      }}
      dangerouslySetInnerHTML={{ __html: raw ? ansiToHtml(raw) : `<span class="a-grey">${placeholder ?? 'waiting for output…'}</span>` }}
    />
  );
}
