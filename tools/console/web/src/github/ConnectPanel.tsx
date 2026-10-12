// Connect the console to GitHub through its own OAuth App: the device flow
// (client ID alone — a code typed at github.com/login/device, polled here) or
// the browser flow (ID + secret, state + PKCE, back through the callback).
// The token never reaches this page: it goes to the session's GH_TOKEN, gh's
// store, or .env (confirmed), and the page only ever sees the status document.
import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router';
import {
  Avatar, Button, Code, CopyButton, Group, Paper, PasswordInput, SegmentedControl, Stack, Text, TextInput,
} from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { useQueryClient } from '@tanstack/react-query';
import { api, post, put } from '../api/client';
import type { GithubStatus } from '../api/types';
import { Banner, External, Mono, Spinner, Status } from '../components/ui';
import { when } from '../lib/format';

type Store = 'session' | 'gh' | 'env';
type Flow = 'device' | 'web';
interface DeviceStart { flow_id: string; user_code: string; verification_uri: string; expires_in: number; interval: number }
interface FlowState { status: string; message: string | null; login: string | null; store: string | null; scopes: string | null }

const STORE_HELP: Record<Store, string> = {
  session: 'this console session (GH_TOKEN, inherited by every job, gone when the console stops)',
  gh: "the gh CLI's login (gh auth login --with-token over stdin)",
  env: 'this session plus the gitignored .env (mode 600)',
};

const ask = (title: string, body: string, label: string, danger = false) =>
  new Promise<boolean>((resolve) =>
    modals.openConfirmModal({
      title, children: <Text size="sm">{body}</Text>, labels: { confirm: label, cancel: 'Cancel' },
      confirmProps: { color: danger ? 'red' : undefined }, onConfirm: () => resolve(true), onCancel: () => resolve(false), onClose: () => resolve(false),
    }));

const fail = (e: unknown) => notifications.show({ color: 'red', message: (e as Error).message, autoClose: 9000 });

/** Client ID / secret → PUT /api/auth/credential (the Credentials page's path); values never come back. */
function AppSetup({ s }: { s: GithubStatus }) {
  const [id, setId] = useState('');
  const [secret, setSecret] = useState('');
  const qc = useQueryClient();
  const save = async () => {
    try {
      if (id.trim()) await put('/api/auth/credential', { name: 'GITHUB_OAUTH_CLIENT_ID', value: id.trim(), persist: false, confirm: false });
      if (secret.trim()) await put('/api/auth/credential', { name: 'GITHUB_OAUTH_CLIENT_SECRET', value: secret.trim(), persist: false, confirm: false });
      setId('');
      setSecret('');
      notifications.show({ color: 'teal', message: 'OAuth App set for this console session' });
      await Promise.all([qc.invalidateQueries({ queryKey: ['github', 'status'] }), qc.invalidateQueries({ queryKey: ['auth'] })]);
    } catch (e) {
      fail(e);
    }
  };
  return (
    <Stack gap={6} mt="sm">
      <Text size="xs" c="dimmed">
        Register an OAuth App once at <External href={s.oauth.new_app_url} size="xs">github.com/settings/applications/new</External> with
        the callback <Code>{s.oauth.callback_url}</Code> and <b>Enable Device Flow</b> ticked. The client ID alone enables the device
        flow; the secret adds the browser flow. Values set here live in this console process (persist them from the Credentials page).
      </Text>
      <Group gap="xs" wrap="wrap">
        <TextInput size="xs" w={240} placeholder={s.oauth.client_id_set ? 'client ID (set)' : 'client ID'} value={id} onChange={(e) => setId(e.currentTarget.value)} autoComplete="off" spellCheck={false} aria-label="OAuth App client ID" disabled={!s.auth_writes} />
        <PasswordInput size="xs" w={240} placeholder={s.oauth.client_secret_set ? 'client secret (set)' : 'client secret (optional)'} value={secret} onChange={(e) => setSecret(e.currentTarget.value)} autoComplete="off" aria-label="OAuth App client secret" disabled={!s.auth_writes} />
        <Button size="xs" variant="light" onClick={() => void save()} disabled={!s.auth_writes || (!id.trim() && !secret.trim())}>Save</Button>
      </Group>
    </Stack>
  );
}

/** A running device flow: show the code, poll until GitHub answers. */
function DeviceCode({ d, onDone }: { d: DeviceStart; onDone: (f: FlowState | null) => void }) {
  const [state, setState] = useState<FlowState | null>(null);
  const done = useRef(onDone);
  done.current = onDone;
  useEffect(() => {
    let live = true;
    // The server calls GitHub at most once per its interval however often we ask.
    const tick = async () => {
      try {
        const f = await api<FlowState>(`/api/github/oauth/device/${encodeURIComponent(d.flow_id)}`);
        if (!live) return;
        setState(f);
        if (f.status !== 'pending' && f.status !== 'delivering') done.current(f);
      } catch (e) {
        if (live) { fail(e); done.current(null); }
      }
    };
    const t = window.setInterval(() => void tick(), Math.max(2, d.interval) * 1000);
    return () => { live = false; window.clearInterval(t); };
  }, [d]);
  return (
    <Paper p="sm" mt="sm" withBorder>
      <Group gap="sm" wrap="wrap" align="center">
        <Text size="sm">Enter</Text>
        <CopyButton value={d.user_code}>
          {({ copied, copy }) => <Button size="xs" variant="light" ff="monospace" onClick={copy}>{copied ? 'copied' : d.user_code}</Button>}
        </CopyButton>
        <Text size="sm">at</Text>
        <External href={d.verification_uri} size="sm">{d.verification_uri}</External>
        <Button size="xs" variant="subtle" color="gray" onClick={() => onDone(null)}>Cancel</Button>
      </Group>
      <Group mt="xs"><Spinner label={state?.message ?? `waiting for GitHub — the code expires in ${Math.round(d.expires_in / 60)} min`} /></Group>
    </Paper>
  );
}

export function ConnectPanel({ s }: { s: GithubStatus }) {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [flow, setFlow] = useState<Flow>('device');
  const [store, setStore] = useState<Store>('session');
  const [scopes, setScopes] = useState('');
  const [device, setDevice] = useState<DeviceStart | null>(null);
  const [busy, setBusy] = useState(false);
  const refresh = () => qc.invalidateQueries({ queryKey: ['github'] });

  // Back from the browser flow: the callback redirects with a status word only.
  const oauth = params.get('oauth');
  useEffect(() => {
    if (!oauth) return;
    const message = params.get('message');
    notifications.show({ color: oauth === 'connected' ? 'teal' : 'red', title: `GitHub sign-in: ${oauth}`, message: message || (oauth === 'connected' ? 'connected' : 'not connected'), autoClose: 9000 });
    const next = new URLSearchParams(params);
    next.delete('oauth');
    next.delete('message');
    setParams(next, { replace: true });
    void refresh();
  }, [oauth]);

  const connect = async () => {
    if (store === 'env' && !(await ask('Write the token to .env?', 'It is gitignored and written mode 600, but it IS a credential on disk.', 'Write it'))) return;
    setBusy(true);
    try {
      const body = { flow, store, scopes: scopes.trim(), confirm: store === 'env' };
      if (flow === 'device') {
        setDevice(await post<DeviceStart>('/api/github/oauth/start', body));
      } else {
        const r = await post<{ authorize_url: string }>('/api/github/oauth/start', body);
        window.location.assign(r.authorize_url);
      }
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const deviceDone = (f: FlowState | null) => {
    setDevice(null);
    if (f) notifications.show({ color: f.status === 'connected' ? 'teal' : 'red', title: `GitHub sign-in: ${f.status}`, message: f.message ?? '', autoClose: 9000 });
    void refresh();
  };

  const disconnect = async (target: 'session' | 'gh') => {
    const what = target === 'session'
      ? 'Clear GH_TOKEN from this console session (and revoke it at GitHub when it is this app’s token and the secret is known).'
      : 'Sign the gh CLI out of github.com on this machine.';
    if (!(await ask('Disconnect GitHub?', what, 'Disconnect', true))) return;
    try {
      const r = await post<{ ok: boolean; revoked: boolean }>('/api/github/disconnect', { target });
      notifications.show({ message: r.revoked ? 'disconnected and revoked at GitHub' : 'disconnected' });
    } catch (e) {
      fail(e);
    }
    void refresh();
  };

  const canConnect = s.auth_writes && (flow === 'device' ? s.oauth.device_flow : s.oauth.web_flow);

  return (
    <Paper p="md">
      <Group justify="space-between" wrap="wrap" gap="xs">
        <Group gap="sm">
          {s.avatar_url ? <Avatar src={s.avatar_url} size={36} radius="xl" alt="" /> : null}
          <div>
            <Group gap={6} wrap="wrap">
              <Text fw={600}>{s.connected ? (s.name || s.login) : 'GitHub'}</Text>
              {s.connected ? <Status tone="good">connected as {s.login}</Status> : <Status tone="warn">not connected</Status>}
              {s.source ? <Text size="xs" c="dimmed">via {s.source}{s.kind ? ` · ${s.kind}` : ''}</Text> : null}
              {s.connected && !s.writes_enabled ? <Status tone="info" title="DASH_CONSOLE_GITHUB_WRITES / DASH_CONSOLE_AUTH">read-only</Status> : null}
            </Group>
            {s.connected ? (
              <Text size="xs" c="dimmed">
                scopes: {s.scopes.length ? s.scopes.join(', ') : '—'}
                {s.rate ? ` · rate ${s.rate.remaining ?? '?'}/${s.rate.limit ?? '?'}${s.rate.reset ? `, resets ${when(new Date(s.rate.reset * 1000).toISOString())}` : ''}` : ''}
              </Text>
            ) : null}
          </div>
        </Group>
        {s.connected ? (
          <Group gap="xs">
            {s.session_set ? <Button size="xs" color="red" variant="light" onClick={() => void disconnect('session')} disabled={!s.auth_writes}>Disconnect session</Button> : null}
            {s.source === 'gh' ? <Button size="xs" color="red" variant="light" onClick={() => void disconnect('gh')} disabled={!s.auth_writes}>Sign gh out</Button> : null}
            <External href={s.oauth.authorized_apps_url} size="xs">authorized apps</External>
          </Group>
        ) : null}
      </Group>

      {s.error ? <Banner tone="crit" title="GitHub refused the current token">{s.error}</Banner> : null}
      {!s.auth_writes ? <Banner tone="info">DASH_CONSOLE_AUTH=off — connecting and credential writes are refused.</Banner> : null}

      {!s.connected || !s.session_set ? (
        <>
          <Group gap="sm" mt="md" wrap="wrap" align="flex-end">
            <SegmentedControl size="xs" value={flow} onChange={(v) => setFlow(v as Flow)} data={[
              { value: 'device', label: 'Device code' },
              { value: 'web', label: 'Browser redirect', disabled: !s.oauth.web_flow },
            ]} />
            <SegmentedControl size="xs" value={store} onChange={(v) => setStore(v as Store)} data={[
              { value: 'session', label: 'Session' }, { value: 'gh', label: 'gh CLI' }, { value: 'env', label: 'Session + .env' },
            ]} />
            <TextInput size="xs" w={240} placeholder={s.oauth.default_scopes} value={scopes} onChange={(e) => setScopes(e.currentTarget.value)} aria-label="scopes" spellCheck={false} />
            <Button size="xs" onClick={() => void connect()} loading={busy} disabled={!canConnect || device !== null}>{s.connected ? 'Connect this app' : 'Connect'}</Button>
          </Group>
          <Text size="xs" c="dimmed" mt={6}>The token goes to {STORE_HELP[store]} — never to this page. Scopes default to <Mono>{s.oauth.default_scopes}</Mono>.</Text>
          {device ? <DeviceCode d={device} onDone={deviceDone} /> : null}
          {!s.oauth.client_id_set || !s.oauth.client_secret_set ? <AppSetup s={s} /> : null}
        </>
      ) : null}
    </Paper>
  );
}
