// ansiToHtml turns a job log's SGR colours into spans and drops every other
// escape. Its output is set as HTML (JobLog), so two properties matter beyond
// the colours: nothing from the log reaches the page as markup, and every span
// it opens is closed.
import { describe, expect, it } from 'vitest';
import { ansiToHtml, type AnsiRole } from './ansi';

const ESC = '\x1b';
const BEL = '\x07';

/** Spans opened minus spans closed. */
const depth = (html: string) => (html.match(/<span /g) ?? []).length - (html.match(/<\/span>/g) ?? []).length;

describe('ansiToHtml: text', () => {
  it('leaves plain text as it is, line breaks included', () => {
    expect(ansiToHtml('checking 3 repos\n  ok\n')).toBe('checking 3 repos\n  ok\n');
    expect(ansiToHtml('')).toBe('');
  });

  it('escapes every character HTML would read as markup', () => {
    expect(ansiToHtml(`<img src=x onerror="alert(1)"> & 'q'`)).toBe('&lt;img src=x onerror=&quot;alert(1)&quot;&gt; &amp; &#39;q&#39;');
  });

  it('escapes the text inside a coloured run too', () => {
    expect(ansiToHtml(`${ESC}[31m<b>fail</b>${ESC}[0m`)).toBe('<span class="red">&lt;b&gt;fail&lt;/b&gt;</span>');
  });
});

describe('ansiToHtml: colours and styles', () => {
  it('wraps a coloured run in a span of that role and ends it at the reset', () => {
    expect(ansiToHtml(`${ESC}[33m!${ESC}[0m 2 warnings`)).toBe('<span class="yellow">!</span> 2 warnings');
  });

  it.each<[number, AnsiRole]>([
    [30, 'grey'], [31, 'red'], [32, 'green'], [33, 'yellow'], [34, 'blue'], [35, 'magenta'], [36, 'cyan'],
    [90, 'grey'], [91, 'red'], [92, 'green'], [93, 'yellow'], [94, 'blue'], [95, 'magenta'], [96, 'cyan'],
  ])('reads SGR %i as %s', (code, role) => {
    expect(ansiToHtml(`${ESC}[${code}mx${ESC}[0m`)).toBe(`<span class="${role}">x</span>`);
  });

  it.each<[number, AnsiRole]>([[1, 'bold'], [2, 'dim'], [4, 'under']])('reads SGR %i as %s', (code, role) => {
    expect(ansiToHtml(`${ESC}[${code}mx${ESC}[0m`)).toBe(`<span class="${role}">x</span>`);
  });

  it('gives white no span: it is the log’s own text colour', () => {
    expect(ansiToHtml(`${ESC}[37mx${ESC}[0m`)).toBe('x');
    expect(ansiToHtml(`${ESC}[97mx${ESC}[0m`)).toBe('x');
  });

  it('reads several codes in one sequence, and one reset ends them all', () => {
    const html = ansiToHtml(`${ESC}[1;31mFAIL${ESC}[0m done`);
    expect(html).toBe('<span class="bold"><span class="red">FAIL</span></span> done');
  });

  it('reads an empty sequence as a reset', () => {
    expect(ansiToHtml(`${ESC}[32mok${ESC}[m after`)).toBe('<span class="green">ok</span> after');
  });

  it('reads a reset and a colour in the same sequence, in order', () => {
    expect(ansiToHtml(`${ESC}[31ma${ESC}[0;32mb${ESC}[0m`)).toBe('<span class="red">a</span><span class="green">b</span>');
  });

  it('closes what the log left open, so a colour never runs into the page', () => {
    const html = ansiToHtml(`${ESC}[31mnever reset`);
    expect(html).toBe('<span class="red">never reset</span>');
    expect(depth(ansiToHtml(`${ESC}[1m${ESC}[31ma${ESC}[32mb`))).toBe(0);
  });

  it('does not close a span it never opened', () => {
    expect(ansiToHtml(`plain${ESC}[0m text${ESC}[0m`)).toBe('plain text');
  });

  it('lets the caller map each role to its own class', () => {
    const cls = (role: AnsiRole) => `log_${role}_x1`;
    expect(ansiToHtml(`${ESC}[32m✓${ESC}[0m ${ESC}[90m3s${ESC}[0m`, cls)).toBe('<span class="log_green_x1">✓</span> <span class="log_grey_x1">3s</span>');
  });
});

describe('ansiToHtml: every other escape is dropped', () => {
  it('drops cursor moves and erase-line, keeping the text around them', () => {
    expect(ansiToHtml(`a${ESC}[2Kb${ESC}[1Ac${ESC}[10;20Hd`)).toBe('abcd');
  });

  it('drops an OSC hyperlink and keeps its label', () => {
    expect(ansiToHtml(`${ESC}]8;;https://example.test/run/1${BEL}run 1${ESC}]8;;${BEL}`)).toBe('run 1');
    expect(ansiToHtml(`${ESC}]8;;https://example.test/run/1${ESC}\\run 1${ESC}]8;;${ESC}\\`)).toBe('run 1');
  });

  it('drops a window-title sequence whole', () => {
    expect(ansiToHtml(`${ESC}]0;build${BEL}compiling`)).toBe('compiling');
  });

  it('keeps colours working next to the escapes it drops', () => {
    expect(ansiToHtml(`${ESC}[2K${ESC}[32m✓${ESC}[0m built${ESC}[1A`)).toBe('<span class="green">✓</span> built');
  });
});

describe('ansiToHtml: a whole log', () => {
  it('decodes the lines a drift report prints', () => {
    const log = [
      `${ESC}[1mRegistry parity${ESC}[0m`,
      `  ${ESC}[32m✓${ESC}[0m registry ↔ .gitmodules`,
      `  ${ESC}[31m✗${ESC}[0m 1 project <unregistered>`,
      `${ESC}[90m3 checks${ESC}[0m`,
    ].join('\n');
    const html = ansiToHtml(log);
    expect(html).toBe([
      '<span class="bold">Registry parity</span>',
      '  <span class="green">✓</span> registry ↔ .gitmodules',
      '  <span class="red">✗</span> 1 project &lt;unregistered&gt;',
      '<span class="grey">3 checks</span>',
    ].join('\n'));
    expect(depth(html)).toBe(0);
  });
});
