// Connecting the console to GitHub through the console's own OAuth App.
//
// Device flow (default): GitHub hands out a short user code, the operator types
// it at github.com/login/device, the console polls for the token. Needs only
// the app's client ID. Browser flow: a redirect to GitHub and back to
// /api/github/oauth/callback; needs the client secret too. Either way the token
// goes where the operator chose — this console session, the gh CLI's store, or
// .env — and never reaches this page.
import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router';
import {
  Avatar, Badge, Button, Checkbox, Code, CopyButton, Group, List, Loader, Modal, Paper, PasswordInput, SegmentedControl,
  Select, SimpleGrid, Stack, Text, TextInput, Title,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { modals } from '@mantine/modals';
import { IconBrandGithub, IconCopy, IconExternalLink, IconPlugConnected, IconPlugConnectedX } from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import { api, post, put } from '../api/client';
import type { GithubStatus } from '../api/types';
import { Banner, External, Mono, Status } from '../components/ui';

type Store = 'session' | 'gh' | 'env';
const STORE_LABEL: Record<Store, string> = {
  session: 'This console session (GH_TOKEN, gone when it stops)',
  gh: 'The gh CLI’s own login (persists on this machine)',
  env: 'This session and .env (gitignored, mode 600)',
};
const SOURCE_LABEL: Record<string, string> = {
  GH_TOKEN: 'GH_TOKEN in the console’s environment', GITHUB_TOKEN: 'GITHUB_TOKEN in the console’s environment', gh: 'the gh CLI’s stored login',
};

function useRefreshGithub() {
  const qc = useQueryClient();
  return () => Promise.all([qc.invalidateQueries({ queryKey: ['github'] }), qc.invalidateQueries({ queryKey: ['caps'] }), qc.invalidateQueries({ queryKey: ['auth'] })]);
}

/** Paste the OAuth App's client ID (and, optionally, secret) without leaving the page. */
function AppSetup({ s }: { s: GithubStatus }) {
  const [cid, setCid] = useState('');
  const [secret, setSecret] = useState('');
  const [persist, setPersist] = useState(true);
  const refresh = useRefreshGithub();
  const save = async () => {
    try {
      for (const [name, value] of [['GITHUB_OAUTH_CLIENT_ID', cid], ['GITHUB_OAUTH_CLIENT_SECRET', secret]] as const) {
        if (value.trim()) await put('/api/auth/credential', { name, value: value.trim(), persist, confirm: persist });
      }
      setCid('');
      setSecret('');
      notifications.show({ color: 'teal', message: `OAuth App saved${persist ? ' to this session and .env' : ' for this session'}` });
      await refresh();
    } catch (e) {
      notifications.show({ color: 'red', message: (e as Error).message });
    }
  };
  return (
    <Paper p="md">
      <Title order={4} fz={15} mb="xs">Set up the console's OAuth App (once)</Title>
      <List size="sm" spacing={4} type="ordered" mb="sm">
        <List.Item>Create an OAuth App: <External href={s.oauth.new_app_url} size="sm">github.com/settings/applications/new</External>. Name it anything (for example “bamr87 Harness Console”); the homepage can be <Code>http://127.0.0.1:4001</Code>.</List.Item>
        <List.Item>Set its callback URL to <Code>{s.oauth.callback_url}</Code>. GitHub accepts a loopback callback on any port.</List.Item>
        <List.Item>Tick <b>Enable Device Flow</b>, so the console can sign in with only the client ID.</List.Item>
        <List.Item>Paste the client ID below. Generate a client secret too only if you want the browser flow, or token revocation on disconnect.</List.Item>
      </List>
      <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
        <TextInput label="Client ID" placeholder="Ov23li…" value={cid} onChange={(e) => setCid(e.currentTarget.value)} autoComplete="off" spellCheck={false} disabled={!s.auth_writes} />
        <PasswordInput label="Client secret (optional)" value={secret} onChange={(e) => setSecret(e.currentTarget.value)} autoComplete="off" disabled={!s.auth_writes} />
      </SimpleGrid>
      <Group mt="sm" gap="sm">
        <Checkbox label="Also write them to .env, so they survive a restart" checked={persist} onChange={(e) => setPersist(e.currentTarget.checked)} disabled={!s.auth_writes} />
        <Button onClick={() => void save()} disabled={!cid.trim() && !secret.trim()}>Save</Button>
      </Group>
      <Text size="xs" c="dimmed" mt="xs">Stored as GITHUB_OAUTH_CLIENT_ID / GITHUB_OAUTH_CLIENT_SECRET, like every credential on the Credentials page: names shown, values never returned.</Text>
    </Paper>
  );
}

function DeviceModal({ flow, onClose }: { flow: { flow_id: string; user_code: string; verification_uri: string; interval: number; expires_in: number } | null; onClose: () => void }) {
  const [state, setState] = useState<{ status: string; message?: string | null; login?: string | null }>({ status: 'pending' });
  const refresh = useRefreshGithub();
  const timer = useRef<number | undefined>(undefined);
  // Held in refs so a re-render (new closures) never restarts the polling loop.
  const done = useRef({ onClose, refresh });
  done.current = { onClose, refresh };
  useEffect(() => {
    if (!flow) return undefined;
    setState({ status: 'pending' });
    let stop = false;
    const tick = async () => {
      try {
        const r = await api<{ status: string; message?: string; login?: string }>(`/api/github/oauth/device/${flow.flow_id}`);
        if (stop) return;
        setState(r);
        if (r.status === 'connected') {
          notifications.show({ color: 'teal', title: 'Connected to GitHub', message: r.message ?? r.login ?? '' });
          await done.current.refresh();
          done.current.onClose();
          return;
        }
        if (r.status !== 'pending' && r.status !== 'delivering') return;
      } catch (e) {
        if (!stop) setState({ status: 'error', message: (e as Error).message });
        return;
      }
      timer.current = window.setTimeout(tick, Math.max(2, flow.interval) * 1000);
    };
    timer.current = window.setTimeout(tick, Math.max(2, flow.interval) * 1000);
    return () => { stop = true; window.clearTimeout(timer.current); };
  }, [flow]);

  return (
    <Modal opened={Boolean(flow)} onClose={onClose} title="Sign in on GitHub" centered size="md">
      {flow ? (
        <Stack gap="md" align="center">
          <Text size="sm" ta="center">Open GitHub's device page and enter this code. The console is waiting for you to approve it.</Text>
          <Group gap="xs">
            <Text ff="monospace" fz={34} fw={700} style={{ letterSpacing: 4 }}>{flow.user_code}</Text>
            <CopyButton value={flow.user_code}>{({ copied, copy }) => <Button size="xs" variant="default" leftSection={<IconCopy size={14} />} onClick={copy}>{copied ? 'Copied' : 'Copy'}</Button>}</CopyButton>
          </Group>
          <Button component="a" href={flow.verification_uri} target="_blank" rel="noopener" leftSection={<IconExternalLink size={16} />}>Open {flow.verification_uri.replace(/^https?:\/\//, '')}</Button>
          {state.status === 'pending' || state.status === 'delivering'
            ? <Group gap="xs"><Loader size="xs" /><Text size="sm" c="dimmed">waiting for approval… (the code expires in {Math.round(flow.expires_in / 60)} minutes)</Text></Group>
            : state.status === 'connected' ? <Status tone="good">connected</Status>
              : <Banner tone="crit" title={state.status === 'denied' ? 'Not approved' : state.status === 'expired' ? 'The code expired' : 'Sign-in failed'}>{state.message ?? ''}</Banner>}
        </Stack>
      ) : null}
    </Modal>
  );
}

export function ConnectPanel({ s }: { s: GithubStatus }) {
  const [sp, setSp] = useSearchParams();
  const [flowKind, setFlowKind] = useState<'device' | 'web'>('device');
  const [store, setStore] = useState<Store>('session');
  const [scopes, setScopes] = useState(s.oauth.default_scopes);
  const [busy, setBusy] = useState(false);
  const [device, setDevice] = useState<{ flow_id: string; user_code: string; verification_uri: string; interval: number; expires_in: number } | null>(null);
  const refresh = useRefreshGithub();

  // Coming back from the browser flow: /github?oauth=connected|denied|error&message=…
  useEffect(() => {
    const result = sp.get('oauth');
    if (!result) return;
    if (result === 'connected') notifications.show({ color: 'teal', title: 'Connected to GitHub', message: 'through the browser flow' });
    else notifications.show({ color: 'red', title: `GitHub sign-in ${result}`, message: sp.get('message') ?? '', autoClose: 12000 });
    void refresh();
    setSp({}, { replace: true });
  }, [sp, setSp, refresh]);

  const connect = async () => {
    if (store === 'env') {
      const ok = await new Promise<boolean>((resolve) => modals.openConfirmModal({
        title: 'Write the token to .env?', children: <Text size="sm">The OAuth token will be written to the hub's gitignored .env (mode 600) as GH_TOKEN, as well as held by this session.</Text>,
        labels: { confirm: 'Write it', cancel: 'Cancel' }, onConfirm: () => resolve(true), onCancel: () => resolve(false), onClose: () => resolve(false),
      }));
      if (!ok) return;
    }
    setBusy(true);
    try {
      const r = await post<Record<string, any>>('/api/github/oauth/start', { flow: flowKind, store, scopes, confirm: store === 'env' });
      if (flowKind === 'web') window.location.assign(String(r.authorize_url));
      else setDevice(r as never);
    } catch (e) {
      notifications.show({ color: 'red', title: 'Could not start', message: (e as Error).message, autoClose: 10000 });
    } finally {
      setBusy(false);
    }
  };

  const disconnect = async (target: 'session' | 'gh') => {
    const ok = await new Promise<boolean>((resolve) => modals.openConfirmModal({
      title: target === 'gh' ? 'Sign the gh CLI out?' : 'Disconnect this session?',
      children: <Text size="sm">{target === 'gh' ? 'gh forgets its github.com login on this machine.' : `GH_TOKEN is cleared from the console.${s.oauth.client_secret_set ? ' An OAuth App token is also revoked at GitHub.' : ' Without the client secret the token cannot be revoked from here — revoke it in GitHub’s authorized apps.'}`}</Text>,
      labels: { confirm: 'Disconnect', cancel: 'Cancel' }, confirmProps: { color: 'red' },
      onConfirm: () => resolve(true), onCancel: () => resolve(false), onClose: () => resolve(false),
    }));
    if (!ok) return;
    try {
      const r = await post<{ revoked: boolean }>('/api/github/disconnect', { target });
      notifications.show({ message: target === 'gh' ? 'gh signed out' : r.revoked ? 'disconnected and revoked at GitHub' : 'disconnected' });
      await refresh();
    } catch (e) {
      notifications.show({ color: 'red', message: (e as Error).message });
    }
  };

  const configured = s.oauth.client_id_set;
  return (
    <Stack gap="md">
      {s.connected ? (
        <Paper p="md">
          <Group justify="space-between" wrap="wrap" gap="md" align="flex-start">
            <Group gap="md" wrap="nowrap">
              <Avatar src={s.avatar_url} size={48} radius="xl"><IconBrandGithub /></Avatar>
              <div>
                <Group gap={8}><Text fw={650} fz={18}>{s.login}</Text>{s.name ? <Text c="dimmed" size="sm">{s.name}</Text> : null}<Status tone="good">connected</Status></Group>
                <Text size="sm" c="dimmed">through {SOURCE_LABEL[s.source ?? ''] ?? s.source}{s.kind ? ` · ${s.kind} token` : ''}{s.session_set ? ' · set in this console' : ''}</Text>
                <Group gap={4} mt={6}>{s.scopes.length ? s.scopes.map((x) => <Badge key={x} size="sm" variant="light">{x}</Badge>) : <Text size="xs" c="dimmed">no classic scopes reported (fine-grained tokens report none)</Text>}</Group>
              </div>
            </Group>
            <Stack gap={6} align="flex-end">
              {s.rate ? <Text size="xs" c="dimmed">API rate: {s.rate.remaining}/{s.rate.limit}{s.rate.reset ? ` · resets ${new Date(s.rate.reset * 1000).toLocaleTimeString()}` : ''}</Text> : null}
              <Group gap="xs">
                {s.source === 'GH_TOKEN' && s.session_set ? <Button size="xs" color="red" variant="light" leftSection={<IconPlugConnectedX size={14} />} onClick={() => void disconnect('session')} disabled={!s.auth_writes}>Disconnect</Button> : null}
                {s.source === 'gh' ? <Button size="xs" color="red" variant="light" leftSection={<IconPlugConnectedX size={14} />} onClick={() => void disconnect('gh')} disabled={!s.auth_writes}>Sign gh out</Button> : null}
                <External href={s.oauth.authorized_apps_url} size="xs">authorized apps</External>
              </Group>
            </Stack>
          </Group>
          {!s.writes_enabled ? <Banner tone="warn">GitHub writes are switched off (DASH_CONSOLE_GITHUB_WRITES or DASH_CONSOLE_AUTH) — repo pages are read-only.</Banner> : null}
        </Paper>
      ) : (
        <Banner tone={s.error ? 'crit' : 'info'} title={s.error ? 'The GitHub token was refused' : 'Not connected to GitHub'}>
          {s.error ?? 'Connect through the console’s OAuth App below — or sign the gh CLI in on the Credentials page.'}
        </Banner>
      )}
      {!configured ? <AppSetup s={s} /> : (
        <Paper p="md">
          <Group justify="space-between" mb="sm"><Title order={4} fz={15}>{s.connected ? 'Connect again (another account or more scopes)' : 'Connect with the OAuth App'}</Title>
            <Text size="xs" c="dimmed">client ID set{s.oauth.client_secret_set ? ' · secret set' : ' · no secret (device flow only)'}</Text></Group>
          <SimpleGrid cols={{ base: 1, md: 3 }} spacing="md">
            <Stack gap={4}>
              <Text size="sm" fw={600}>Flow</Text>
              <SegmentedControl value={flowKind} onChange={(v) => setFlowKind(v as 'device' | 'web')}
                data={[{ value: 'device', label: 'Device code' }, { value: 'web', label: 'Browser redirect', disabled: !s.oauth.web_flow }]} />
              <Text size="xs" c="dimmed">{flowKind === 'device' ? 'Type a short code at github.com/login/device. Works natively, in Docker and over SSH.' : 'Go to GitHub and come back here. Needs the client secret.'}</Text>
            </Stack>
            <Select label="Keep the token in" data={(Object.keys(STORE_LABEL) as Store[]).map((k) => ({ value: k, label: STORE_LABEL[k] }))} value={store} onChange={(v) => setStore((v as Store) ?? 'session')} allowDeselect={false} />
            <TextInput label="Scopes" description="repo · workflow · read:org cover every fleet operation" value={scopes} onChange={(e) => setScopes(e.currentTarget.value)} ff="monospace" />
          </SimpleGrid>
          <Group mt="md" gap="sm">
            <Button leftSection={<IconPlugConnected size={16} />} onClick={() => void connect()} loading={busy} disabled={!s.auth_writes}>Connect to GitHub</Button>
            {store === 'gh' ? <Text size="xs" c="dimmed">gh prefers GH_TOKEN when it is set — clear it on the Credentials page if gh should use this login.</Text> : null}
            {!s.auth_writes ? <Text size="xs" c="dimmed">Credential writes are off (DASH_CONSOLE_AUTH=off).</Text> : null}
          </Group>
          <Text size="xs" c="dimmed" mt="sm">Tokens go server-side only: the console hands them to {store === 'gh' ? <Mono>gh auth login --with-token</Mono> : <Mono>GH_TOKEN</Mono>} and never returns them. Every job the console runs inherits the same identity.</Text>
        </Paper>
      )}
      <DeviceModal flow={device} onClose={() => setDevice(null)} />
    </Stack>
  );
}
