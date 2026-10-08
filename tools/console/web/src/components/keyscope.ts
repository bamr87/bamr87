// Where keys v1 land. The global handler (GlobalKeys.tsx) owns the keymap —
// the same table the terminal dash binds, from /api/keys — and dispatches the
// list-shaped actions (down/up/top/bottom/enter/open/copy/sort) to whichever
// list or page registered most recently. A page that registers nothing just
// scrolls.
import { useEffect, useRef } from 'react';

export interface KeyHandlers {
  move?: (delta: number) => void;      // +1 / -1
  edge?: (end: 0 | 1) => void;          // top / bottom
  activate?: () => void;                // enter
  open?: () => void;                    // o
  openLive?: () => void;                // l
  copy?: () => void;                    // y
  sort?: () => void;                    // s
  back?: () => boolean;                 // esc — true when handled
}

const stack: { id: number; get: () => KeyHandlers }[] = [];
let seq = 0;

/** The handlers a key should reach: the newest registration that has it. */
export function handlerFor<K extends keyof KeyHandlers>(name: K): KeyHandlers[K] | undefined {
  for (let i = stack.length - 1; i >= 0; i--) {
    const h = stack[i].get()[name];
    if (h) return h;
  }
  return undefined;
}

/** Register handlers for the lifetime of a component. Always reads the latest closure. */
export function useKeyScope(handlers: KeyHandlers, enabled = true): void {
  const ref = useRef(handlers);
  ref.current = handlers;
  useEffect(() => {
    if (!enabled) return undefined;
    const id = ++seq;
    stack.push({ id, get: () => ref.current });
    return () => {
      const i = stack.findIndex((s) => s.id === id);
      if (i >= 0) stack.splice(i, 1);
    };
  }, [enabled]);
}
