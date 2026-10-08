// The terminal dash, inside the console. Not a re-implementation: the console
// runs the real Textual app (tools/tui/app.py) on a pseudo-terminal and relays
// it over /api/tui (tools/console/tui_bridge.py); xterm.js draws it here in the
// TUI's own bashOS dark palette. It joins this console's runtime, so a job its
// `:` palette starts shows on the Jobs page, and the same allowlist and
// confirm gate apply. Links its `o` / `l` keys open arrive as a private OSC and
// open in a new tab of THIS browser.
import '@xterm/xterm/css/xterm.css';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { Anchor, Badge, Button, Group, Kbd, SegmentedControl, Text } from '@mantine/core';
import { IconExternalLink, IconRefresh } from '@tabler/icons-react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { WebLinksAddon } from '@xterm/addon-web-links';
import { Unicode11Addon } from '@xterm/addon-unicode11';
import { api, askToken, currentToken } from '../api/client';
import { useTuiStatus } from '../api/hooks';
import { Banner, PageHeader, Status } from '../components/ui';
import { to } from '../lib/links';

type Phase = 'connecting' | 'ready' | 'exited' | 'error';
interface Palette { tokens: Record<'dark' | 'light', Record<string, string>> }

const OSC_OPEN = 7777; // tools/tui/app.py — "open this URL in the page"

function xtermTheme(t: Record<string, string>) {
  return {
    background: t.background, foreground: t.foreground, cursor: t.primary, cursorAccent: t.background,
    selectionBackground: `${t.primary}55`,
    black: t.background, brightBlack: t.muted,
    red: t.error, brightRed: t.error, green: t.success, brightGreen: t.secondary,
    yellow: t.warning, brightYellow: t.warning, blue: t.primary, brightBlue: t.primary,
    magenta: t.accent, brightMagenta: t.accent, cyan: t.primary, brightCyan: t.secondary,
    white: t.ink2, brightWhite: t.foreground,
  };
}

export function TerminalPage() {
  const host = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const [phase, setPhase] = useState<Phase>('connecting');
  const [message, setMessage] = useState('');
  const [generation, setGeneration] = useState(0);
  const [fontSize, setFontSize] = useState(() => {
    try { return Number(localStorage.getItem('console_term_font')) || 13; } catch { return 13; }
  });
  const [bg, setBg] = useState('var(--page)');
  const status = useTuiStatus();

  const restart = useCallback(() => setGeneration((g) => g + 1), []);

  useEffect(() => {
    let disposed = false;
    const el = host.current;
    if (!el) return undefined;
    setPhase('connecting');
    setMessage('');

    const term = new Terminal({
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace', fontSize, cursorBlink: true,
      allowProposedApi: true, scrollback: 2000, macOptionIsMeta: true,
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    // Textual measures emoji (the health dots) as two cells; xterm's default
    // Unicode 6 tables say one, which shears every row after the first dot.
    term.loadAddon(new Unicode11Addon());
    term.unicode.activeVersion = '11';
    term.loadAddon(new WebLinksAddon((_e, uri) => window.open(uri, '_blank', 'noopener')));
    term.parser.registerOscHandler(OSC_OPEN, (data) => {
      if (/^https?:\/\//.test(data)) window.open(data, '_blank', 'noopener');
      return true;
    });
    term.open(el);
    termRef.current = term;
    fitRef.current = fit;

    void api<Palette>('/api/theme').then((p) => {
      if (disposed) return;
      term.options.theme = xtermTheme(p.tokens.dark);
      setBg(p.tokens.dark.background);
    }).catch(() => undefined);

    try { fit.fit(); } catch { /* not laid out yet */ }

    const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${scheme}://${window.location.host}/api/tui`);
    ws.binaryType = 'arraybuffer';
    wsRef.current = ws;
    const enc = new TextEncoder();

    ws.onopen = () => ws.send(JSON.stringify({ type: 'hello', token: currentToken(), cols: term.cols, rows: term.rows }));
    ws.onmessage = (ev) => {
      if (typeof ev.data === 'string') {
        try {
          const m = JSON.parse(ev.data) as { type: string; message?: string; code?: number | null };
          if (m.type === 'ready') { setPhase('ready'); term.focus(); }
          else if (m.type === 'exit') { setPhase('exited'); setMessage(`The terminal dash exited${m.code != null ? ` (code ${m.code})` : ''}.`); }
          else if (m.type === 'error') { setPhase('error'); setMessage(m.message ?? 'error'); }
        } catch { /* not a control frame */ }
        return;
      }
      term.write(new Uint8Array(ev.data as ArrayBuffer));
    };
    ws.onclose = (ev) => {
      if (disposed) return;
      if (ev.code === 4401) {
        void askToken(Boolean(currentToken())).then((t) => { if (t) restart(); });
        setPhase('error');
        setMessage('The console token is required.');
        return;
      }
      setPhase((p) => (p === 'ready' || p === 'connecting' ? (ev.code === 4403 ? 'error' : 'exited') : p));
      if (ev.code === 4403) setMessage(`Refused: ${ev.reason || 'this page is not the console origin'}`);
      else setMessage((m) => m || (ev.reason ? `Disconnected: ${ev.reason}` : 'Disconnected.'));
    };

    const send = (d: string) => { if (ws.readyState === WebSocket.OPEN) ws.send(enc.encode(d)); };
    const dataSub = term.onData(send);
    const binSub = term.onBinary((d) => {
      if (ws.readyState !== WebSocket.OPEN) return;
      const buf = new Uint8Array(d.length);
      for (let i = 0; i < d.length; i++) buf[i] = d.charCodeAt(i) & 0xff;
      ws.send(buf);
    });
    const resizeSub = term.onResize(({ cols, rows }) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'resize', cols, rows }));
    });
    const ro = new ResizeObserver(() => { try { fit.fit(); } catch { /* hidden */ } });
    ro.observe(el);

    return () => {
      disposed = true;
      ro.disconnect();
      dataSub.dispose();
      binSub.dispose();
      resizeSub.dispose();
      ws.close();
      term.dispose();
      termRef.current = null;
      wsRef.current = null;
    };
    // fontSize is applied live below; a new session only on restart.
  }, [generation, restart]);

  useEffect(() => {
    const t = termRef.current;
    if (!t) return;
    t.options.fontSize = fontSize;
    try { fitRef.current?.fit(); } catch { /* hidden */ }
    try { localStorage.setItem('console_term_font', String(fontSize)); } catch { /* private window */ }
  }, [fontSize]);

  const s = status.data;
  return (
    <>
      <PageHeader
        title="Terminal"
        badges={
          <>
            {phase === 'ready' ? <Status tone="good">connected</Status> : phase === 'connecting' ? <Status tone="info">connecting…</Status> : phase === 'exited' ? <Status tone="warn">ended</Status> : <Status tone="crit">not connected</Status>}
            {s ? <Badge variant="default">{s.active}/{s.max} sessions</Badge> : null}
          </>
        }
        description={<>The terminal dash (<code>tools/tui</code>) running inside this console, on the same runtime: a job its <Kbd size="xs">:</Kbd> palette starts appears on <Anchor component={Link} to={to.jobs()}>Jobs</Anchor>. Keys go to the terminal while it has focus — click outside it to use the console's own keys. <Kbd size="xs">q</Kbd> quits the session.</>}
        actions={
          <>
            <SegmentedControl size="xs" value={String(fontSize)} onChange={(v) => setFontSize(Number(v))} data={['11', '13', '15', '17'].map((v) => ({ value: v, label: `${v}px` }))} aria-label="Font size" />
            <Button size="xs" variant="default" leftSection={<IconRefresh size={14} />} onClick={restart}>{phase === 'ready' ? 'Restart' : 'Start'}</Button>
            <Button size="xs" variant="default" leftSection={<IconExternalLink size={14} />} component="a" href={to.terminal()} target="_blank" rel="noopener">Pop out</Button>
          </>
        }
      />
      {s && !s.available ? <Banner tone="warn" title="Textual is not installed here">The console's environment cannot start the terminal dash. Restart the console with <code>tools/dash console</code>, which installs requirements.txt (it includes the TUI's).</Banner> : null}
      {phase === 'error' || phase === 'exited' ? (
        <Banner tone={phase === 'error' ? 'crit' : 'info'}>
          <Group gap="sm"><Text size="sm">{message || 'The session ended.'}</Text><Button size="compact-xs" onClick={restart}>Start a new session</Button></Group>
        </Banner>
      ) : null}
      <div className="term-host" style={{ background: bg }} onClick={() => termRef.current?.focus()}>
        <div ref={host} style={{ height: '100%', width: '100%' }} />
      </div>
      <Text size="xs" c="dimmed" mt="xs">
        In Docker the console has no Docker socket, so the terminal dash's Docker tab reports each host's error; <code>tools/dash tui --docker</code> runs the TUI with the socket.
      </Text>
    </>
  );
}
