// How the public page gets its hands back. The published snapshot is a
// read-only view; this page gives it what a local console has, two ways:
//
//   GitHub — a token kept in this browser. The page then reads GitHub live and
//            makes the console's GitHub writes itself (issues, runs, workflows,
//            and dispatching the control-plane workflows), with the same rules.
//   Console — the URL of a running console and its bearer token. Every page
//            then talks to that console: jobs, config, credentials, the lake,
//            the terminal. The console must be started with DASH_CONSOLE_TOKEN,
//            or it refuses the page (app.py, remote_page).
//
// From a console itself there is nothing to connect: it already is one.
import { useState } from 'react';
import { Link } from 'react-router';
import {
  Anchor, Avatar, Button, Checkbox, Code, Group, List, Paper, PasswordInput, SimpleGrid, Stack, Text, TextInput, Title,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconBrandGithub, IconPlugConnected, IconServer } from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import { consoleOrigin, githubRemembered, githubToken, mode, setGithubToken, setRemoteConsole } from '../api/backend';
import { setConsoleToken } from '../api/client';
import { useGithubStatus, useManifest } from '../api/hooks';
import { Banner, External, Mono, PageHeader, Status } from '../components/ui';
import { when } from '../lib/format';
import { gh, to } from '../lib/links';

const PAT_URL = 'https://github.com/settings/personal-access-tokens/new';

function GithubCard() {
  const status = useGithubStatus();
  const qc = useQueryClient();
  const [value, setValue] = useState('');
  const [remember, setRemember] = useState(false);
  const [busy, setBusy] = useState(false);
  const s = status.data;
  const connect = async () => {
    setBusy(true);
    setGithubToken(value, remember);
    setValue('');
    await qc.invalidateQueries();
    setBusy(false);
  };
  const disconnect = async () => {
    setGithubToken(null);
    await qc.invalidateQueries();
    notifications.show({ message: 'GitHub token removed from this browser' });
  };
  return (
    <Paper p="lg">
      <Group gap="sm" mb="xs"><IconBrandGithub size={20} /><Title order={3} fz={16}>GitHub, from this browser</Title></Group>
      {s?.connected ? (
        <Stack gap="sm">
          <Group gap="sm">
            <Avatar src={s.avatar_url} size={36} radius={36} />
            <div>
              <Text fw={600}>{s.login}</Text>
              <Text size="xs" c="dimmed">{s.kind} · kept {githubRemembered() ? 'on this device' : 'in this tab only'}{s.rate ? ` · ${s.rate.remaining}/${s.rate.limit} requests left this hour` : ''}</Text>
            </div>
          </Group>
          <Text size="sm">Live repo views and the console's GitHub writes now run from this page, and so does dispatching the control-plane workflows (Operations → Dispatch). Writes go only to repos the hub owns, each one confirmed first.</Text>
          <Group gap="xs">
            <Button component={Link} to={to.github()} size="xs" variant="light">Open GitHub</Button>
            <Button component={Link} to={to.op('dispatch')} size="xs" variant="light">Dispatch a workflow</Button>
            <Button onClick={() => void disconnect()} size="xs" variant="default" color="red">Forget the token</Button>
          </Group>
        </Stack>
      ) : (
        <form onSubmit={(e) => { e.preventDefault(); void connect(); }}>
          <Stack gap="sm">
            {s?.error ? <Banner tone="crit" title="GitHub refused the token">{s.error}</Banner> : null}
            <Text size="sm">Paste a token and this page reads GitHub live and acts on it directly: issues and pull-request conversations, re-running and cancelling runs, enabling workflows, and dispatching the control-plane loops — the same actions, rules and confirmations as the console.</Text>
            <List size="sm" spacing={2}>
              <List.Item>Create a <External href={PAT_URL} size="sm">fine-grained token</External> for the fleet's repos with <b>Actions</b>, <b>Issues</b> and <b>Pull requests</b> read and write, plus <b>Contents</b> and <b>Metadata</b> read.</List.Item>
              <List.Item>It is sent only to api.github.com. It stays in this tab unless you tick the box, and <b>Forget the token</b> removes it.</List.Item>
            </List>
            <PasswordInput value={value} onChange={(e) => setValue(e.currentTarget.value)} placeholder="github_pat_…" aria-label="GitHub token" autoComplete="off" spellCheck={false} />
            <Group justify="space-between" wrap="wrap">
              <Checkbox label="Remember on this device" checked={remember} onChange={(e) => setRemember(e.currentTarget.checked)} />
              <Button type="submit" loading={busy} disabled={!value.trim()} leftSection={<IconPlugConnected size={16} />}>Connect GitHub</Button>
            </Group>
          </Stack>
        </form>
      )}
    </Paper>
  );
}

async function probe(url: string, token: string): Promise<string | null> {
  try {
    const health = await fetch(`${url}/api/health`);
    if (health.status === 403) return String(((await health.json()) as { detail?: string }).detail ?? 'the console refused this page');
    if (!health.ok) return `the console answered ${health.status}`;
    const caps = await fetch(`${url}/api/capabilities`, { headers: { Authorization: `Bearer ${token}` } });
    if (caps.status === 401) return 'the console rejected that token';
    if (!caps.ok) return `the console answered ${caps.status}`;
    return null;
  } catch (e) {
    return `cannot reach ${url} — is the console running, on that port? (${(e as Error).message})`;
  }
}

function ConsoleCard() {
  const [url, setUrl] = useState('http://127.0.0.1:4001');
  const [token, setToken] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const connect = async () => {
    setBusy(true);
    const clean = url.trim().replace(/\/+$/, '');
    const problem = await probe(clean, token.trim());
    setBusy(false);
    if (problem) {
      setError(problem);
      return;
    }
    setRemoteConsole(clean);
    setConsoleToken(token.trim());
    window.location.reload();
  };
  return (
    <Paper p="lg">
      <Group gap="sm" mb="xs"><IconServer size={20} /><Title order={3} fz={16}>A running console</Title></Group>
      <form onSubmit={(e) => { e.preventDefault(); void connect(); }}>
        <Stack gap="sm">
          <Text size="sm">Point this page at a Harness Console and it becomes that console: run any operation with a live log, edit <Mono>_data/fleet.yml</Mono>, manage credentials, read the data lake and open the terminal dash. Start the console with a token — it refuses a page from another origin without one:</Text>
          <Code block>{'DASH_CONSOLE_TOKEN=$(openssl rand -hex 24) tools/dash console\n# then paste that token here'}</Code>
          {error ? <Banner tone="crit" title="Not connected">{error}</Banner> : null}
          <TextInput label="Console URL" value={url} onChange={(e) => setUrl(e.currentTarget.value)} spellCheck={false} />
          <PasswordInput label="Console token" value={token} onChange={(e) => setToken(e.currentTarget.value)} autoComplete="off" spellCheck={false} />
          <Text size="xs" c="dimmed">The URL and token stay in this browser. Chrome and Firefox let a public page reach a console on 127.0.0.1; Safari blocks it, so use one of those or open the console directly.</Text>
          <Group justify="flex-end"><Button type="submit" loading={busy} disabled={!token.trim()} leftSection={<IconPlugConnected size={16} />}>Connect console</Button></Group>
        </Stack>
      </form>
    </Paper>
  );
}

export function Connect() {
  const m = mode();
  const manifest = useManifest();
  if (m === 'console') {
    return (
      <>
        <PageHeader title="Connect" description="This page is being served by a console, so it already has every capability: there is nothing to connect." />
        <Group gap="xs"><Button component={Link} to={to.auth()} variant="light">Credentials</Button><Button component={Link} to={to.github()} variant="light">GitHub</Button></Group>
      </>
    );
  }
  if (m === 'remote') {
    return (
      <>
        <PageHeader title="Connect" description="This page is connected to a console. Every page reads and acts through it." />
        <Paper p="lg" maw={720}>
          <Stack gap="sm">
            <Status tone="good">connected to <Mono>{consoleOrigin()}</Mono></Status>
            <Group gap="xs">
              <Button component={Link} to={to.jobs()} variant="light" size="xs">Jobs</Button>
              <Button component={Link} to={to.auth()} variant="light" size="xs">Credentials</Button>
              <Button size="xs" variant="default" color="red" onClick={() => { setRemoteConsole(null); setConsoleToken(null); window.location.reload(); }}>Disconnect</Button>
            </Group>
          </Stack>
        </Paper>
      </>
    );
  }
  return (
    <>
      <PageHeader
        title="Connect"
        description={<>You are reading the published snapshot{manifest.data ? <>, built {when(manifest.data.generated_at)} from <Anchor href={`https://github.com/${manifest.data.repo}/commit/${manifest.data.commit}`} target="_blank" rel="noopener" size="sm" ff="monospace">{manifest.data.commit.slice(0, 7)}</Anchor></> : null}. It is rebuilt daily and on every change to the hub. To act on what it shows, connect GitHub, a running console, or both. Nothing you enter here leaves this browser except to the service it is for. How it works: <External href={gh.hubFile('docs/CONSOLE-PAGES.md')} size="sm">docs/CONSOLE-PAGES.md</External>.</>}
      />
      {githubToken() ? null : <Banner tone="info">Without either, every page still works read-only, and every button that would change something says what it needs.</Banner>}
      <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="md">
        <GithubCard />
        <ConsoleCard />
      </SimpleGrid>
    </>
  );
}
