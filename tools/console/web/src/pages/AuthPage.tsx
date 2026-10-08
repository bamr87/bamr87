// Credentials for THIS console process, and the fleet's. A value set here lives
// in the process environment a job inherits and dies with the process, unless
// you also write it to the gitignored .env (mode 600) on an explicit confirm.
// A GitHub token can instead go to `gh auth login --with-token` over stdin.
// Values are never returned, logged, or put on a command line: this page only
// ever sees which names are present and where they came from.
import { useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import {
  Anchor, Button, Checkbox, Code, Group, Paper, PasswordInput, Select, SimpleGrid, Stack, Table, Tabs, Text,
} from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { useQueryClient } from '@tanstack/react-query';
import { del, post, put } from '../api/client';
import { useAuth, useStateDoc } from '../api/hooks';
import type { AuthDoc, Credential } from '../api/types';
import { DataTable } from '../components/DataTable';
import { Banner, External, Load, Mono, PageHeader, Section, Status } from '../components/ui';
import { RunButton } from '../jobs/RunButton';
import { fmt } from '../lib/format';
import { gh, to } from '../lib/links';

const ask = (title: string, body: string, label: string, danger = false) =>
  new Promise<boolean | null>((resolve) =>
    modals.openConfirmModal({
      title, children: <Text size="sm">{body}</Text>, labels: { confirm: label, cancel: 'Cancel' },
      confirmProps: { color: danger ? 'red' : undefined }, onConfirm: () => resolve(true), onCancel: () => resolve(false), onClose: () => resolve(null),
    }));

function useRefresh() {
  const qc = useQueryClient();
  return () => Promise.all([qc.invalidateQueries({ queryKey: ['auth'] }), qc.invalidateQueries({ queryKey: ['caps'] })]);
}

function CredentialRow({ c, a, age }: { c: Credential; a: AuthDoc; age?: string }) {
  const [value, setValue] = useState('');
  const [persist, setPersist] = useState(false);
  const refresh = useRefresh();
  const set = async () => {
    if (!value.trim()) {
      notifications.show({ color: 'red', message: 'paste a value first' });
      return;
    }
    if (persist && !(await ask(`Write ${c.name} to ${a.env_file.path}?`, 'It is gitignored and written mode 600, but it IS a credential on disk.', 'Write it'))) return;
    try {
      await put('/api/auth/credential', { name: c.name, value: value.trim(), persist, confirm: persist });
      setValue('');
      notifications.show({ color: 'teal', message: `${c.name} set${persist ? ' and written to .env' : ' for this console'}` });
      await refresh();
    } catch (e) {
      notifications.show({ color: 'red', message: (e as Error).message });
    }
  };
  const clear = async () => {
    const purge = await ask(`Clear ${c.name}`, `Remove it from the running console. Also remove it from ${a.env_file.path}?`, `Also remove from .env`, true);
    if (purge === null) return;
    try {
      await del(`/api/auth/credential/${encodeURIComponent(c.name)}?purge=${purge}`);
      notifications.show({ message: `${c.name} cleared` });
      await refresh();
    } catch (e) {
      notifications.show({ color: 'red', message: (e as Error).message });
    }
  };
  return (
    <Paper p="sm">
      <Group justify="space-between" align="flex-start" wrap="wrap" gap="xs">
        <div style={{ minWidth: 0, flex: 1 }}>
          <Group gap={6} wrap="wrap">
            <Mono>{c.name}</Mono>
            {c.present ? <Status tone="good">{c.source === 'session' ? 'set in this console' : 'in the environment'}</Status> : <Status tone="warn">absent</Status>}
            {c.in_env_file ? <Status tone="info">in .env</Status> : null}
            {age ? <Text size="xs" c="dimmed">fleet copies: {age}</Text> : null}
          </Group>
          <Text size="xs" c="dimmed" mt={2}>{c.label} — {c.help} <External href={c.url} size="xs">get one</External></Text>
        </div>
      </Group>
      <Group gap="xs" mt="xs" wrap="wrap">
        <PasswordInput size="xs" w={260} placeholder="paste value…" value={value} onChange={(e) => setValue(e.currentTarget.value)} autoComplete="off" spellCheck={false} aria-label={`value for ${c.name}`} disabled={!a.writes_enabled} />
        <Checkbox size="xs" label="also write to .env" checked={persist} onChange={(e) => setPersist(e.currentTarget.checked)} disabled={!a.writes_enabled} />
        <Button size="xs" onClick={() => void set()} disabled={!a.writes_enabled}>Set</Button>
        {c.present || c.in_env_file ? <Button size="xs" variant="light" color="red" onClick={() => void clear()} disabled={!a.writes_enabled}>Clear</Button> : null}
      </Group>
    </Paper>
  );
}

function GitHubCard({ a }: { a: AuthDoc }) {
  const g = a.github;
  const [token, setToken] = useState('');
  const refresh = useRefresh();
  const login = async () => {
    if (!token.trim()) {
      notifications.show({ color: 'red', message: 'paste a token first' });
      return;
    }
    try {
      const r = await post<{ ok: boolean; message?: string }>('/api/auth/github', { action: 'login', token: token.trim() });
      setToken('');
      notifications.show({ color: r.ok ? 'teal' : 'red', message: r.ok ? 'gh signed in' : r.message ?? 'sign-in failed' });
      await refresh();
    } catch (e) {
      notifications.show({ color: 'red', message: (e as Error).message });
    }
  };
  const logout = async () => {
    if (!(await ask('Sign gh out?', 'Sign the gh CLI out of github.com on this machine.', 'Sign out', true))) return;
    try {
      const r = await post<{ ok: boolean; message?: string }>('/api/auth/github', { action: 'logout' });
      notifications.show({ message: r.ok ? 'gh signed out' : r.message ?? 'failed' });
      await refresh();
    } catch (e) {
      notifications.show({ color: 'red', message: (e as Error).message });
    }
  };
  return (
    <Paper p="md">
      <Group justify="space-between" mb="xs"><Text fw={600}>GitHub</Text>
        {!g.cli ? <Status tone="crit">gh CLI not installed</Status> : g.authenticated ? <Status tone="good">signed in{g.account ? ` as ${g.account}` : ''}{g.host ? ` @ ${g.host}` : ''}</Status> : <Status tone="warn">not signed in</Status>}
      </Group>
      {g.scopes?.length ? <Text size="xs" c="dimmed">scopes: {g.scopes.join(', ')}{g.protocol ? ` · protocol ${g.protocol}` : ''}</Text> : null}
      {g.env_token ? <Banner tone="warn"><Mono>{g.env_token}</Mono> is set in this process's environment — gh prefers it over a stored login, so signing in here does not change which token gh uses until you clear it.</Banner> : null}
      <Text size="xs" c="dimmed" my="xs">A pasted token goes to <Code>gh auth login --with-token</Code> over stdin, never a command line, and the CLI's own store keeps it. Fleet work needs repo, workflow and read:org; cross-repo PRs and secret writes want a FLEET_TOKEN instead.</Text>
      <Group gap="xs" wrap="wrap">
        <PasswordInput size="xs" w={260} placeholder="ghp_… / github_pat_…" value={token} onChange={(e) => setToken(e.currentTarget.value)} autoComplete="off" aria-label="GitHub token" />
        <Button size="xs" onClick={() => void login()} disabled={!a.writes_enabled || !g.cli}>Sign in</Button>
        {g.authenticated ? <Button size="xs" color="red" variant="light" onClick={() => void logout()} disabled={!a.writes_enabled}>Sign out</Button> : null}
        <External href="https://github.com/settings/personal-access-tokens" size="xs">create a token</External>
      </Group>
      {g.message ? <pre className="log" style={{ maxHeight: 120, marginTop: 10 }}>{g.message}</pre> : null}
    </Paper>
  );
}

function PushCard({ a }: { a: AuthDoc }) {
  const [secret, setSecret] = useState('');
  const [hubOnly, setHubOnly] = useState(false);
  const pushable = a.push.filter((t) => t.in_env_file);
  const params = (apply: boolean) => ({ hub_only: hubOnly, apply, ...(secret ? { secret } : {}) });
  return (
    <Paper p="md">
      <Text fw={600} mb={4}>Rotate from <Mono>.env</Mono></Text>
      <Text size="xs" c="dimmed" mb="sm">Put the new value in {a.env_file.path} (or Set it with "also write to .env"), then push. Only the contract's names are read — the file is parsed, never sourced. Every secret goes to the hub first; a fleet-scoped one then fans out, and a hub refusal aborts that secret's fan-out. Hub only stops at the hub and lets the weekly token-rotation propagate it.</Text>
      <Table className="dt" verticalSpacing={3} mb="sm">
        <Table.Tbody>
          {a.push.map((t) => (
            <Table.Tr key={t.name}><Table.Td><Mono>{t.name}</Mono></Table.Td><Table.Td><Text size="xs">{t.scope}</Text></Table.Td><Table.Td>{t.in_env_file ? <Status tone="good">in .env</Status> : <Status tone="warn">not in .env</Status>}</Table.Td></Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      <Group gap="sm" wrap="wrap" align="flex-end">
        <Select size="xs" label="Secret" w={260} data={[{ value: '', label: `every one in .env (${pushable.length})` }, ...pushable.map((t) => ({ value: t.name, label: t.name }))]} value={secret} onChange={(v) => setSecret(v ?? '')} />
        <Checkbox size="xs" label="hub only" checked={hubOnly} onChange={(e) => setHubOnly(e.currentTarget.checked)} />
        <RunButton op="secrets-push" params={params(false)} disabled={!a.env_file.exists}>Preview (dry run)</RunButton>
        <RunButton op="secrets-push" params={params(true)} disabled={!a.env_file.exists || !pushable.length || !a.writes_enabled} variant="filled">Push to GitHub</RunButton>
      </Group>
    </Paper>
  );
}

export function AuthPage() {
  const auth = useAuth();
  const state = useStateDoc();
  const [sp, setSp] = useSearchParams();
  const tab = sp.get('tab') ?? 'console';
  const rot = state.data?.rotation.tokens ?? [];
  return (
    <>
      <PageHeader
        title="Credentials"
        description={<>What this console process holds, the gh login, the fleet's token contract and its rotation. The fleet's own copies live in GitHub Actions secrets and are rotated weekly by <External href={gh.hubFile('docs/TOKEN-ROTATION.md')}>token-rotation.yml</External>.</>}
      />
      <Load q={auth} rows={6}>
        {(a) => (
          <>
            {a.writes_enabled ? null : <Banner tone="warn">Credential writes are disabled (<Mono>DASH_CONSOLE_AUTH=off</Mono>) — this page is read-only.</Banner>}
            {a.console_token_required ? null : <Banner tone="info">No <Mono>DASH_CONSOLE_TOKEN</Mono> is set: this console is protected by the loopback Host guard alone. Set one before serving it anywhere but localhost.</Banner>}
            {a.env_file.tracked_by_git ? <Banner tone="crit"><Mono>{a.env_file.path}</Mono> is TRACKED BY GIT — the console refuses to write a credential into it.</Banner> : null}
            <Tabs value={tab} onChange={(v) => setSp(v && v !== 'console' ? { tab: v } : {}, { replace: true })} keepMounted={false}>
              <Tabs.List mb="md">
                <Tabs.Tab value="console">This console</Tabs.Tab>
                <Tabs.Tab value="fleet">Fleet secrets</Tabs.Tab>
                <Tabs.Tab value="keys">Anthropic API keys</Tabs.Tab>
                <Tabs.Tab value="order">AI auth order</Tabs.Tab>
              </Tabs.List>
              <Tabs.Panel value="console">
                <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="md">
                  <Stack gap="md">
                    <Banner tone="info" title="Connect with the OAuth App">The quickest way to sign the console in to GitHub is the <Anchor component={Link} to={to.github()}>GitHub page</Anchor>: approve a short code on github.com, no token to copy. Pasting a token below still works.</Banner>
                    <GitHubCard a={a} />
                    <Paper p="md">
                      <Group justify="space-between" mb="xs"><Text fw={600}>Claude</Text>
                        {a.claude.oauth ? <Status tone="good">CLAUDE_CODE_OAUTH_TOKEN present</Status> : a.claude.api_key ? <Status tone="warn">API key only</Status> : <Status tone="warn">no Claude credential</Status>}
                      </Group>
                      <Text size="xs" c="dimmed">The OAuth token is minted by a browser flow that cannot run headlessly: run <Code>claude setup-token</Code> in a terminal{a.claude.cli ? '' : ' (the claude CLI is not on this PATH)'} and paste the result into CLAUDE_CODE_OAUTH_TOKEN. It lasts a year; token-rotation.yml propagates the hub's copy to the fleet weekly, and only ever one newer than what a repo has.</Text>
                    </Paper>
                    <Paper p="md">
                      <Text fw={600} mb="xs">Where values live</Text>
                      <Table className="dt" verticalSpacing={4}>
                        <Table.Tbody>
                          <Table.Tr><Table.Td fw={600}>this process</Table.Td><Table.Td><Text size="sm">every credential you Set — inherited by jobs, gone when the console stops</Text></Table.Td></Table.Tr>
                          <Table.Tr><Table.Td><Mono>{a.env_file.path}</Mono></Table.Td><Table.Td><Text size="sm">{a.env_file.exists ? 'exists' : 'absent'}{a.env_file.names?.length ? ` · declares ${a.env_file.names.join(', ')}` : ''} — gitignored, mode 600, written only on an explicit confirm</Text></Table.Td></Table.Tr>
                          <Table.Tr><Table.Td fw={600}>gh CLI store</Table.Td><Table.Td><Text size="sm">the GitHub login (keychain / config file, this machine only)</Text></Table.Td></Table.Tr>
                          <Table.Tr><Table.Td fw={600}>GitHub Actions</Table.Td><Table.Td><Text size="sm">the fleet's copies — audited by dash secrets, rotated weekly, never readable back</Text></Table.Td></Table.Tr>
                        </Table.Tbody>
                      </Table>
                    </Paper>
                  </Stack>
                  <Stack gap="sm">
                    <Text fw={600}>Credentials this console can hold</Text>
                    {a.credentials.map((c) => {
                      const r = rot.find((t) => t.name === c.name);
                      return <CredentialRow key={c.name} c={c} a={a} age={r ? `oldest ${fmt(r.oldest_age_days)}d of ${fmt(r.max_age_days)}d` : undefined} />;
                    })}
                  </Stack>
                </SimpleGrid>
              </Tabs.Panel>
              <Tabs.Panel value="fleet">
                <Group gap="xs" mb="md">
                  <RunButton op="secrets-audit">Audit the fleet's secrets</RunButton>
                  <RunButton op="secrets-plan">Rotation plan</RunButton>
                  <RunButton op="secrets-rotate">Run the rotation loop (dry run)</RunButton>
                </Group>
                <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="md">
                  <Section mt={0} title="The token contract" description="Names and placement from _data/fleet.yml tokens: — never values.">
                    <DataTable
                      rows={state.data?.tokens ?? []}
                      rowKey={(t) => t.name}
                      columns={[
                        { key: 'n', header: 'secret', render: (t) => <Group gap={6}><Mono>{t.name}</Mono>{t.deprecated ? <Status tone="warn">deprecated</Status> : null}</Group> },
                        { key: 's', header: 'scope', render: (t) => <Text size="sm">{t.scope}{t.required ? ' · required' : ''}</Text> },
                        { key: 'u', header: 'used by', render: (t) => <Text size="xs" c="dimmed">{t.used_by.join(', ')}</Text> },
                      ]}
                    />
                  </Section>
                  <Section mt={0} title="Credential ages" description={`From _data/token_rotation.yml · ${state.data?.rotation.generated_at ?? 'no ledger'}`}>
                    <DataTable
                      rows={rot}
                      rowKey={(t) => t.name}
                      tone={(t) => ((t.oldest_age_days ?? 0) > (t.max_age_days ?? Infinity) ? 'warn' : undefined)}
                      empty="no ledger"
                      columns={[
                        { key: 'n', header: 'secret', render: (t) => <Mono>{t.name}</Mono> },
                        { key: 's', header: 'scope', render: (t) => <Text size="sm">{t.scope}</Text> },
                        { key: 'a', header: 'oldest (d)', num: true, render: (t) => fmt(t.oldest_age_days) },
                        { key: 'm', header: 'max age', num: true, render: (t) => fmt(t.max_age_days) },
                        { key: 'c', header: 'counts', render: (t) => <Text size="xs" c="dimmed">{Object.entries(t.counts ?? {}).map(([k, v]) => `${k} ${v}`).join(' · ')}</Text> },
                      ]}
                    />
                  </Section>
                </SimpleGrid>
                <Section title="Push">
                  <PushCard a={a} />
                </Section>
              </Tabs.Panel>
              <Tabs.Panel value="keys">
                <Paper p="md">
                  <Text size="sm" mb="sm">One Console key per workspace, each written to the repos that workspace pays for (<Mono>api_keys:</Mono> in fleet.yml; every other repo gets the Default Workspace's key). The Admin API cannot create keys: create each in the <External href="https://platform.claude.com/settings/keys">Console</External>, scoped to its workspace with a 7-day expiry, and paste it into .env under any ANTHROPIC_API_KEY* name. Rotate tests each key with one cheap call, writes it hub-first, and disables the key it replaced. api-keys.yml files an issue two days before any deployed key expires.</Text>
                  <Group gap="xs">
                    <RunButton op="keys-status">Status</RunButton>
                    <RunButton op="keys-verify">Cheap test</RunButton>
                    <RunButton op="keys-watch">Deployed keys</RunButton>
                    <RunButton op="keys-rotate">Rotate — dry run</RunButton>
                    <RunButton op="keys-rotate" params={{ apply: true }} variant="filled">Rotate keys</RunButton>
                  </Group>
                </Paper>
              </Tabs.Panel>
              <Tabs.Panel value="order">
                <Paper p="md">
                  <Text size="sm" mb="sm">Which Claude credential each repo tries first — oauth (the subscription token) or api_key (metered) — set per repo or group in fleet.yml <Mono>ai_auth:</Mono>. Every call site reads the repo's CLAUDE_AUTH_ORDER variable, and a repo is only pushed the credentials its order uses. One repo's order is also on its project page.</Text>
                  <Group gap="xs">
                    <RunButton op="ai-auth">Resolve per repo</RunButton>
                    <RunButton op="ai-auth-sync">Sync — dry run</RunButton>
                    <RunButton op="ai-auth-sync" params={{ apply: true }} variant="filled">Sync CLAUDE_AUTH_ORDER</RunButton>
                  </Group>
                </Paper>
              </Tabs.Panel>
            </Tabs>
          </>
        )}
      </Load>
    </>
  );
}
