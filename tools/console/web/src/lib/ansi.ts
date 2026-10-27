// SGR → HTML for job logs. The tools/ scripts colour their findings; printed
// raw, the escapes show as "[33m!" noise and the signal the colour carried is
// lost. Decode the subset the scripts use, drop every other escape (cursor
// moves, erase-line, OSC hyperlinks). Run over the WHOLE log, never per poll
// chunk: a sequence can straddle two chunks.

const COLOUR: Record<number, string> = {
  30: 'grey', 31: 'red', 32: 'green', 33: 'yellow', 34: 'blue', 35: 'magenta', 36: 'cyan', 37: '',
  90: 'grey', 91: 'red', 92: 'green', 93: 'yellow', 94: 'blue', 95: 'magenta', 96: 'cyan', 97: '',
};
const STYLE: Record<number, string> = { 1: 'bold', 2: 'dim', 4: 'under' };

const escapeHtml = (s: string) =>
  s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] as string);

/** Roles the decoder emits; the caller maps each to its own class (a CSS module). */
export type AnsiRole = 'grey' | 'red' | 'green' | 'yellow' | 'blue' | 'magenta' | 'cyan' | 'bold' | 'dim' | 'under';

export function ansiToHtml(input: string, cls: (role: AnsiRole) => string = (r) => r): string {
  const text = input.replace(/\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/g, '');
  const csi = /\x1b\[([0-9;]*)([A-Za-z])/g;
  let out = '';
  let last = 0;
  let open = 0;
  let m: RegExpExecArray | null;
  while ((m = csi.exec(text)) !== null) {
    out += escapeHtml(text.slice(last, m.index));
    last = csi.lastIndex;
    if (m[2] !== 'm') continue;
    for (const part of (m[1] === '' ? '0' : m[1]).split(';')) {
      const code = parseInt(part || '0', 10);
      if (code === 0) {
        out += '</span>'.repeat(open);
        open = 0;
        continue;
      }
      const cls_ = STYLE[code] ?? COLOUR[code];
      if (cls_) {
        out += `<span class="${cls(cls_ as AnsiRole)}">`;
        open++;
      }
    }
  }
  return out + escapeHtml(text.slice(last)) + '</span>'.repeat(open);
}
