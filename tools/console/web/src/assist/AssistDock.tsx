// The docked assistant: Claude Code beside the page, on every console page.
//
// A message is one capped, headless Claude Code session (the `assist` op, the
// same one the Assist page runs) that continues this conversation and has the
// page you are on attached: it can read it, point at things on it and — as far
// as the mode you pick here allows — move around and use it for you. What it
// does on the page is listed here; what it may never do is in pageBridge.ts.
//
// The dock is the consent: the page is shared exactly while this panel is
// open, and in Ask mode every click, fill and key press waits for the Allow
// below. Spend goes through the console's one gate (runOp): the first message
// of a conversation gets the "This spends Claude budget" dialog, which states
// the whole envelope, and later messages in it are sent under that yes. No
// session can see or press anything inside this panel.
import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { Link } from 'react-router';
import {
  ActionIcon, Anchor, Box, Button, Collapse, CopyButton, Group, Loader, ScrollArea, SegmentedControl, Stack, Switch, Text, Textarea, Tooltip,
} from '@mantine/core';
import { IconArrowUp, IconCheck, IconCopy, IconMessagePlus, IconPlayerStopFilled, IconSparkles, IconX } from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import { hasConsole } from '../api/backend';
import { post } from '../api/client';
import { ApiError } from '../api/errors';
import { useAssist as useAssistDoc, useJobTail } from '../api/hooks';
import type { AssistActivity, AssistDoc, Job } from '../api/types';
import { Markdown } from '../components/Markdown';
import { Banner } from '../components/ui';
import { to } from '../lib/links';
import { useRunner } from '../jobs/JobRunner';
import { conversationGone, decide, forgetJob, messageParams, newConversation, sent, setMode, setOpen, setPairing, useDock, type Mode } from './session';
import classes from './AssistDock.module.css';

const MODE_HELP: Record<Mode, string> = {
  look: 'It can read this page and point at things on it. It cannot move or press anything.',
  ask: 'It can read and move between pages. Each click, each thing it types and each key press waits for your yes.',
  act: 'It can use this page without asking. It still cannot answer a confirming dialog or touch a secret field.',
};

const SUGGESTIONS = [
  'What am I looking at, and what needs attention here?',
  'Which repos are red this week, and which operation would clear each one?',
  'Show me where I run the drift check, and take me there.',
];

/** One step of a session, in words a person skims: "went to /loops", not a tool name and a JSON blob. */
function stepText(a: AssistActivity): string {
  if (a.kind !== 'tool') return a.detail;
  let args: Record<string, unknown> = {};
  try {
    args = JSON.parse(a.detail || '{}') as Record<string, unknown>;
  } catch {
    /* the tee cuts long arguments: fall back to the tool's name */
  }
  switch (a.name) {
    case 'page_snapshot': return 'looked at the page';
    case 'page_read': return 'read part of the page';
    case 'page_data': return args.key ? `read the page's ${String(args.key)} document` : 'listed the documents the page loaded';
    case 'page_highlight': return 'pointed at something on the page';
    case 'page_navigate': return `went to ${String(args.path ?? 'another page')}`;
    case 'page_click': return 'clicked a control';
    case 'page_fill': return 'typed into a field';
    case 'page_press': return `pressed ${String(args.key ?? 'a key')}`;
    case 'Read': return `read ${String(args.file_path ?? 'a file').replace(/^.*\/(?=[^/]+\/[^/]+$)/, '')}`;
    case 'Grep': return `searched the hub for ${String(args.pattern ?? '…')}`;
    case 'Glob': return `listed files matching ${String(args.pattern ?? '…')}`;
    default: return a.name.replace(/_/g, ' ');
  }
}

function Steps({ activity, live }: { activity: AssistActivity[]; live: boolean }) {
  const [all, setAll] = useState(false);
  const steps = activity.filter((a) => a.kind !== 'said');
  if (!steps.length) return null;
  const shown = live || all ? steps.slice(-8) : [];
  return (
    <Box>
      {shown.length ? (
        <ul className={classes.steps} data-testid="assist-steps">
          {shown.map((a, i) => <li key={i} data-kind={a.kind}>{stepText(a)}</li>)}
        </ul>
      ) : null}
      {!live ? (
        <Anchor component="button" type="button" size="xs" c="dimmed" onClick={() => setAll((v) => !v)}>
          {all ? 'Hide the steps' : `${steps.length} step${steps.length === 1 ? '' : 's'}`}
        </Anchor>
      ) : null}
    </Box>
  );
}

function Message({ id, onLive }: { id: string; onLive: (id: string, live: boolean) => void }) {
  const [live, setLive] = useState(true);
  const tail = useJobTail(id, live);
  const job = tail.data?.job;
  const a = tail.data?.assist;
  const running = !tail.data ? !tail.isError : !tail.data.done;
  useEffect(() => {
    setLive(running);
    onLive(id, running);
  }, [id, running, onLive]);
  // The console forgot this job (its history was cleared): drop it rather than show an error forever.
  useEffect(() => {
    if (tail.error instanceof ApiError && tail.error.status === 404) forgetJob(id);
  }, [tail.error, id]);
  if (tail.isError) return null;
  const question = a?.question ?? String(job?.params?.question ?? '');
  const failed = Boolean(tail.data?.done && !a?.answer);
  return (
    <>
      {question ? <div className={classes.you}>{question}</div> : null}
      <Stack gap={6} data-testid="assist-message">
        <Steps activity={a?.activity ?? []} live={running} />
        {running ? <Group gap={6}><Loader size={12} /><Text size="xs" c="dimmed">{job?.status === 'queued' ? 'Waiting for another job to finish…' : 'Working…'}</Text></Group> : null}
        {a?.answer ? <div className={classes.answer}><Markdown source={a.answer} /></div> : null}
        {failed ? (
          <Text size="sm" c="dimmed">
            {a?.outcome === 'usage_limit' ? 'The Claude usage window is spent, so there was no answer. It resets on its own.' : job?.status === 'cancelled' ? 'Stopped.' : 'The session ended without an answer.'}
          </Text>
        ) : null}
        {tail.data?.done ? (
          <div className={classes.meta}>
            {a?.cost_usd != null ? <span>${a.cost_usd.toFixed(4)} ({a.cost_label})</span> : null}
            {a?.turns != null ? <span>{a.turns} turns</span> : null}
            <Anchor component={Link} to={to.job(id)} size="xs" c="dimmed">the session's log</Anchor>
          </div>
        ) : null}
      </Stack>
    </>
  );
}

function Approvals() {
  const { approvals } = useDock();
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!approvals.length) return undefined;
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, [approvals.length]);
  const a = approvals[0];
  if (!a) return null;
  const left = Math.max(0, Math.ceil((a.until - now) / 1000));
  return (
    <div className={classes.approval} role="alertdialog" aria-label="The assistant asks to act on this page" data-testid="assist-approval">
      <Text size="xs" c="dimmed">{a.client === 'paired' ? 'The paired Claude Code session' : 'The assistant'} asks to</Text>
      <Text size="sm" fw={600}>{a.summary}</Text>
      {a.detail !== undefined ? <div className={classes.typed}>{a.detail || '(clear the field)'}</div> : null}
      <Group justify="space-between" mt={8} gap="xs">
        <Text size="xs" c="dimmed">{left}s, then it is not done{approvals.length > 1 ? ` · ${approvals.length - 1} more waiting` : ''}</Text>
        <Group gap={6}>
          <Button size="compact-sm" variant="default" onClick={() => decide(a.id, false)} data-testid="assist-deny">Deny</Button>
          <Button size="compact-sm" onClick={() => decide(a.id, true)} data-testid="assist-allow">Allow</Button>
        </Group>
      </Group>
    </div>
  );
}

function Pairing({ open, setShown }: { open: boolean; setShown: (fn: (v: boolean) => boolean) => void }) {
  const { session, events } = useDock();
  if (!session) return null;
  const code = session.code ? `${session.code.slice(0, 4)}-${session.code.slice(4)}` : null;
  return (
    <div className={classes.foot}>
      <Group justify="space-between" gap="xs">
        <Anchor component="button" type="button" size="xs" c="dimmed" onClick={() => setShown((v) => !v)} aria-expanded={open} data-testid="assist-pairing-toggle">
          {open ? 'Hide' : 'Pair a Claude Code session, and what was done here'}
        </Anchor>
        {session.paired ? <Text size="xs" c="dimmed">{session.paired} paired</Text> : null}
      </Group>
      <Collapse expanded={open}>
        <Stack gap={6} mt={6}>
          <Switch
            size="xs" checked={session.pairing} onChange={(e) => void setPairing(e.currentTarget.checked)} data-testid="assist-pairing"
            label="Let a Claude Code session on this machine use this page"
            description="For a session in your terminal or editor that has the fleet MCP server. It gets the same page tools, under the same mode and the same rules."
          />
          {code ? (
            <Group gap="sm" align="center">
              <span className={classes.code} data-testid="assist-code">{code}</span>
              <CopyButton value={`Pair with my console page: page_attach ${code}`}>
                {({ copied, copy }) => (
                  <Button size="compact-xs" variant="default" leftSection={copied ? <IconCheck size={12} /> : <IconCopy size={12} />} onClick={copy}>
                    {copied ? 'Copied' : 'Copy the ask'}
                  </Button>
                )}
              </CopyButton>
              <Text size="xs" c="dimmed">one use, {Math.max(1, Math.round((session.code_ttl_s ?? 0) / 60))} min</Text>
            </Group>
          ) : null}
          {events.length ? (
            <ul className={classes.events} data-testid="assist-events">
              {events.slice(-6).map((e) => (
                <li key={e.id} data-outcome={e.outcome}>
                  {e.outcome === 'ok' ? '' : e.outcome === 'declined' ? 'you declined: ' : 'not done: '}{e.what}{e.client === 'paired' ? ' (paired session)' : ''}
                </li>
              ))}
            </ul>
          ) : <Text size="xs" c="dimmed">Nothing has been done to this page yet.</Text>}
        </Stack>
      </Collapse>
    </div>
  );
}

function shareLine(doc: AssistDoc | undefined, sessionError: string | null, shared: boolean, mode: Mode): string {
  if (!hasConsole()) return 'The published page has no assistant: it runs on a console.';
  if (doc?.page.access === 'off') return 'Page access is off (_data/fleet.yml assistant.page_access), so the assistant answers without seeing this page.';
  if (sessionError) return sessionError;
  if (!shared) return 'Connecting this page…';
  return mode === 'look' ? 'Sharing this page: it can read, not act.' : mode === 'ask' ? 'Sharing this page: it asks before each action.' : 'Sharing this page: it may act without asking.';
}

export function AssistDock() {
  const { mode, session, sessionError, jobs, conversation } = useDock();
  const doc = useAssistDoc();
  const qc = useQueryClient();
  const { runOp } = useRunner();
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState<Record<string, boolean>>({});
  const [pairingOpen, setPairingOpen] = useState(false);
  const viewport = useRef<HTMLDivElement>(null);
  const field = useRef<HTMLTextAreaElement>(null);
  const a = doc.data;
  const ceiling = a?.page.access ?? 'act';
  const unavailable = !hasConsole() ? 'The assistant runs on a console.' : a?.unavailable ?? a?.config_error ?? null;
  const live = jobs.find((id) => running[id]);
  const full = a?.config ? jobs.length >= a.config.conversation_messages : false;
  const onLive = useRef((id: string, isLive: boolean) => setRunning((r) => (r[id] === isLive ? r : { ...r, [id]: isLive }))).current;

  useEffect(() => {
    field.current?.focus();
  }, []);
  // Follow the newest message, the way a chat does.
  useEffect(() => {
    viewport.current?.scrollTo({ top: viewport.current.scrollHeight });
  }, [jobs.length, live]);

  const submit = async () => {
    const question = text.trim();
    if (!question || busy || live || unavailable || full) return;
    setBusy(true);
    setError(null);
    const detail = a?.config
      ? `This conversation can hold ${a.config.conversation_messages} messages. Each is one session capped at $${a.config.budget_usd} (${a.cost_label}). You are asked once for the conversation, not again for each message.`
      : undefined;
    const start = () => runOp('assist', messageParams(question), { quiet: true, detail });
    try {
      let job: Job | null;
      try {
        job = await start();
      } catch (e) {
        // The console no longer holds the conversation this browser remembers (its job history was cleared):
        // the same message starts a new one, which asks again like any new conversation.
        if (!conversationGone(e)) throw e;
        newConversation();
        job = await start();
      }
      if (job) {
        const id = job.id;
        sent(job);
        setText('');
        setRunning((r) => ({ ...r, [id]: true }));
        void qc.invalidateQueries({ queryKey: ['jobs'] });
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void submit();
    }
  };
  const stop = () => {
    if (live) void post(`/api/jobs/${live}/cancel`, {}).catch((e: Error) => setError(e.message));
  };

  return (
    <section className={classes.dock} data-assist-dock aria-label="Assistant">
      <div className={classes.head}>
        <Group justify="space-between" wrap="nowrap" gap="xs">
          <Group gap={6} wrap="nowrap">
            <IconSparkles size={16} color="var(--accent)" />
            <Text fw={650} size="sm">Assistant</Text>
          </Group>
          <Group gap={4} wrap="nowrap">
            <Tooltip label="Start a new conversation">
              <ActionIcon variant="subtle" color="gray" size="md" onClick={() => { newConversation(); setError(null); field.current?.focus(); }} disabled={!jobs.length || Boolean(live)} aria-label="New conversation">
                <IconMessagePlus size={16} />
              </ActionIcon>
            </Tooltip>
            <Tooltip label="Close: the assistant stops seeing this page">
              <ActionIcon variant="subtle" color="gray" size="md" onClick={() => setOpen(false)} aria-label="Close the assistant" data-testid="assist-close">
                <IconX size={16} />
              </ActionIcon>
            </Tooltip>
          </Group>
        </Group>
        <SegmentedControl
          mt={8} fullWidth size="xs" value={mode} onChange={(v) => void setMode(v as Mode)} aria-label="What the assistant may do on this page" data-testid="assist-mode"
          data={[
            { value: 'look', label: 'Look' },
            { value: 'ask', label: 'Ask first', disabled: ceiling !== 'act' },
            { value: 'act', label: 'Act', disabled: ceiling !== 'act' },
          ]}
        />
        <div className={classes.share} data-testid="assist-share">
          <span className={classes.dot} data-on={Boolean(session)} aria-hidden />
          <span>{shareLine(a, sessionError, Boolean(session), mode)}</span>
        </div>
        <Text size="xs" c="dimmed" mt={4}>{MODE_HELP[mode]}</Text>
      </div>

      <ScrollArea className={classes.thread} viewportRef={viewport} type="auto">
        {jobs.length ? (
          <div className={classes.messages} data-testid="assist-thread">
            {jobs.map((id) => <Message key={id} id={id} onLive={onLive} />)}
          </div>
        ) : unavailable ? (
          <Stack className={classes.empty} gap="sm" data-testid="assist-unavailable">
            {a?.unavailable_kind === 'no_cli' ? (
              <>
                <Text size="sm" fw={600}>This console cannot start a session itself</Text>
                <Text size="sm">It has no Claude Code CLI on its PATH, which is how the console's container is built. There are two ways to use the assistant from here.</Text>
                <div className={classes.way}>
                  <Text size="sm" fw={600}>Let a Claude Code session use this page</Text>
                  <Text size="xs" c="dimmed">A session in your terminal or editor that has the fleet MCP server can read this page, point at things and, in the mode above, use it. You give it a code.</Text>
                  <Button mt={8} size="compact-sm" variant="default" disabled={!session} onClick={() => { setPairingOpen(() => true); if (!session?.pairing) void setPairing(true); }} data-testid="assist-pair-now">
                    Show a pairing code
                  </Button>
                </div>
                <div className={classes.way}>
                  <Text size="sm" fw={600}>Run a console on the host</Text>
                  <Text size="xs" c="dimmed">Beside the CLI, the assistant answers here in the dock. Start one, then open it on its port.</Text>
                  <Group gap="xs" mt={8} wrap="nowrap">
                    <code className={classes.command}>{a.host_command}</code>
                    <CopyButton value={a.host_command}>
                      {({ copied, copy }) => <Button size="compact-xs" variant="default" onClick={copy}>{copied ? 'Copied' : 'Copy'}</Button>}
                    </CopyButton>
                  </Group>
                </div>
              </>
            ) : (
              <Banner tone="warn" title="The assistant cannot run here"><Text size="xs">{unavailable}</Text></Banner>
            )}
          </Stack>
        ) : (
          <Stack className={classes.empty} gap="sm">
            <Text size="sm">Ask about the fleet or about what is on this page. It reads the fleet's own data, cites it, and can show you where things are.</Text>
            <Stack gap={6}>
              {SUGGESTIONS.map((s) => (
                <button key={s} type="button" className={classes.suggestion} onClick={() => { setText(s); field.current?.focus(); }}>{s}</button>
              ))}
            </Stack>
          </Stack>
        )}
      </ScrollArea>

      <Approvals />

      {unavailable ? null : (
      <div className={classes.composer}>
        {error ? <Text size="xs" c="red" mb={6} data-testid="assist-error">{error}</Text> : null}
        {full ? <Text size="xs" c="dimmed" mb={6}>This conversation has reached its {a?.config?.conversation_messages} messages. Start a new one.</Text> : null}
        <Textarea
          ref={field} value={text} onChange={(e) => setText(e.currentTarget.value)} onKeyDown={onKey} autosize minRows={2} maxRows={8}
          maxLength={a?.max_question_chars ?? 4000} placeholder={conversation ? 'Reply…' : 'Ask about this page or the fleet…'} aria-label="Message the assistant"
          disabled={Boolean(unavailable)} data-testid="assist-input"
        />
        <Group justify="space-between" mt={6} gap="xs" wrap="nowrap" align="flex-end">
          <Text size="xs" c="dimmed">
            {a?.config ? <>Each message is one capped session: up to ${a.config.budget_usd} ({a.cost_label}), {a.config.model}.</> : a?.config_error ?? ''}
          </Text>
          {live ? (
            <Button className={classes.send} size="compact-sm" variant="default" leftSection={<IconPlayerStopFilled size={12} />} onClick={stop} data-testid="assist-stop">Stop</Button>
          ) : (
            <Button
              className={classes.send} size="compact-sm" rightSection={<IconArrowUp size={14} />} onClick={() => void submit()} loading={busy}
              disabled={!text.trim() || Boolean(unavailable) || full} data-testid="assist-send"
            >
              Send
            </Button>
          )}
        </Group>
      </div>
      )}

      <Pairing open={pairingOpen} setShown={setPairingOpen} />
    </section>
  );
}
