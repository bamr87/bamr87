import { Fragment, type ReactNode } from 'react';

export interface LogViewProps {
  /** Raw job output. ANSI SGR colour/bold/dim/underline codes are decoded; other escape sequences are dropped. */
  text: string;
}

const COLOUR: Record<number, string> = {
  30: 'a-grey', 31: 'a-red', 32: 'a-green', 33: 'a-yellow', 34: 'a-blue', 35: 'a-magenta', 36: 'a-cyan', 37: '',
  90: 'a-grey', 91: 'a-red', 92: 'a-green', 93: 'a-yellow', 94: 'a-blue', 95: 'a-magenta', 96: 'a-cyan', 97: '',
};
const STYLE: Record<number, string> = { 1: 'a-bold', 2: 'a-dim', 4: 'a-under' };

function decode(input: string): ReactNode[] {
  const text = input.replace(/\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/g, '');
  const csi = /\x1b\[([0-9;]*)([A-Za-z])/g;
  const out: ReactNode[] = [];
  let classes: string[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  const push = (s: string, key: number) => {
    if (s) out.push(classes.length ? <span key={key} className={classes.join(' ')}>{s}</span> : <Fragment key={key}>{s}</Fragment>);
  };
  while ((m = csi.exec(text)) !== null) {
    push(text.slice(last, m.index), out.length);
    last = csi.lastIndex;
    if (m[2] !== 'm') continue;
    for (const part of (m[1] === '' ? '0' : m[1]).split(';')) {
      const code = parseInt(part || '0', 10);
      if (code === 0) classes = [];
      else {
        const cls = STYLE[code] ?? COLOUR[code];
        if (cls) classes = [...classes, cls];
      }
    }
  }
  push(text.slice(last), out.length);
  return out;
}

/** Terminal-style log pane (monospace, max 520px, scrolls) that renders the colours of the tools/ scripts' output. */
export function LogView({ text }: LogViewProps) {
  return <pre className="hc-log">{decode(text)}</pre>;
}
