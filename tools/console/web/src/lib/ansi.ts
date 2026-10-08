// SGR → HTML for job logs. The tools/ scripts colour their findings; printed
// raw, the escapes show as "[33m!" noise and the signal the colour carried is
// lost. Decode the subset the scripts use, drop every other escape (cursor
// moves, erase-line, OSC hyperlinks). Run over the WHOLE log, never per poll
// chunk: a sequence can straddle two chunks.

const COLOUR: Record<number, string> = {
  30: 'a-grey', 31: 'a-red', 32: 'a-green', 33: 'a-yellow', 34: 'a-blue', 35: 'a-magenta', 36: 'a-cyan', 37: '',
  90: 'a-grey', 91: 'a-red', 92: 'a-green', 93: 'a-yellow', 94: 'a-blue', 95: 'a-magenta', 96: 'a-cyan', 97: '',
};
const STYLE: Record<number, string> = { 1: 'a-bold', 2: 'a-dim', 4: 'a-under' };

const escapeHtml = (s: string) =>
  s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] as string);

export function ansiToHtml(input: string): string {
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
      const cls = STYLE[code] ?? COLOUR[code];
      if (cls) {
        out += `<span class="${cls}">`;
        open++;
      }
    }
  }
  return out + escapeHtml(text.slice(last)) + '</span>'.repeat(open);
}
