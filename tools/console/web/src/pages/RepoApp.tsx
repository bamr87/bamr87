// The generated repo app (ADR 0005, phase F1): the frontend every repo has
// before it has one of its own. One component, rendered for any repo from
// what the hub already holds about it — the registry entry, its health and
// CI, its open work, its automation, its standards audit — plus its README
// when a console can read the checkout. No change in the repo is needed, so a
// CLI, a library or a kernel is an app on the desktop on the same terms as a
// site.
//
// It is also what a repo with a frontend the shell cannot show yet (an editor
// extension, a terminal UI, an app with no address) opens as, with a line
// saying which component it is owed.
import { useState } from 'react';
import { Link } from 'react-router';
import { ActionIcon, Anchor, Badge, Code, CopyButton, Group, SimpleGrid, Stack, Tabs, Text, Tooltip } from '@mantine/core';
import { IconCopy } from '@tabler/icons-react';
import { hasConsole } from '../api/backend';
import { useData, useProject, useProjectReadme } from '../api/hooks';
import type { AppsDoc, Dict, FleetRepo } from '../api/types';
import { Markdown } from '../components/Markdown';
import { Banner, Empty, External, LevelDot, Load, Spinner, StatTile } from '../components/ui';
import { fmt } from '../lib/format';
import { to } from '../lib/links';
import { HarnessWorkflows, InboxTable, ScheduleTable } from './ProjectPage';
import c from './RepoApp.module.css';

export const KIND_TEXT: Record<FleetRepo['component']['kind'], string> = {
  own: 'its own frontend, mounted in the shell',
  preview: 'a web preview of a surface a browser cannot host',
  terminal: 'its terminal UI in a shell window',
  generated: 'a component of its own in place of this generated one',
};

function Command({ value }: { value: string }) {
  return (
    <Group gap={6} wrap="nowrap">
      <Code className={c.command}>{value}</Code>
      <CopyButton value={value}>
        {({ copied, copy }) => (
          <Tooltip label={copied ? 'copied' : 'copy'}>
            <ActionIcon variant="default" size="sm" onClick={copy} aria-label={`Copy ${value}`}><IconCopy size={13} /></ActionIcon>
          </Tooltip>
        )}
      </CopyButton>
    </Group>
  );
}

interface Audit { checked?: number; passed?: number; must_failed?: number; should_failed?: number }

function Overview({ repo }: { repo: FleetRepo }) {
  const detail = useProject(repo.name);
  const conformance = useData<Dict<any>>('conformance');
  const audit = ((conformance.data?.repos ?? []) as (Audit & { name?: string })[]).find((r) => r.name === repo.name);
  const local = repo.targets.filter((t) => t.kind === 'local');
  const live = repo.targets.find((t) => t.kind === 'live');
  return (
    <Stack gap="md">
      <Text size="sm">{repo.description}</Text>
      <Group gap={6} wrap="wrap">
        {repo.status ? <Badge variant="default">{repo.status}</Badge> : null}
        {repo.category ? <Badge variant="light">{repo.category}</Badge> : null}
        {repo.license ? <Badge variant="outline">{repo.license}</Badge> : null}
        {(repo.stack ?? []).map((s) => <Badge key={s} variant="outline" size="sm">{s}</Badge>)}
      </Group>
      <Load q={detail} rows={3}>
        {(d) => {
          const r = d.row;
          return (
            <SimpleGrid cols={{ base: 2, sm: 3 }} spacing="sm">
              <StatTile label="Health" value={<LevelDot level={r?.health} label={r?.health ?? 'unknown'} />} sub={(r?.reasons ?? []).join(' · ') || 'live monitor signal'} />
              <StatTile label="CI" value={r?.ci_last ?? '—'} sub={r?.ci_pass != null ? `${r.ci_pass}% pass rate` : 'no CI data'} tone={r?.ci_last === 'failure' ? 'crit' : undefined} />
              <StatTile label="Last commit" value={r?.last_commit_days == null ? '—' : `${r.last_commit_days}d ago`} sub={`${fmt(r?.commits_30d)} commits in 30 days`} />
              <StatTile label="Open work" value={`${fmt(r?.triage_issues ?? r?.issues_open)} · ${fmt(r?.triage_prs ?? r?.prs_open)}`} sub="issues · pull requests" />
              <StatTile label="Standards" value={audit?.checked ? `${fmt(audit.passed)}/${fmt(audit.checked)}` : '—'}
                sub={audit?.checked ? `${fmt(audit.must_failed)} required and ${fmt(audit.should_failed)} recommended rows failing` : 'not audited yet'} />
              <StatTile label="Automation" value={fmt(d.harness?.harnesses?.length ?? 0)} sub={d.harness ? `AI workflows · ${fmt(d.harness.workflows_total)} workflows in all` : 'not in the harness inventory'} />
            </SimpleGrid>
          );
        }}
      </Load>
      <Stack gap={6}>
        <Text fw={650} size="sm">Get it</Text>
        {repo.repo_url ? <Command value={`git clone ${repo.repo_url}`} /> : null}
        <Text size="xs" c="dimmed">In the hub it is the submodule <Code>projects/{repo.id}</Code>{repo.branch ? <>, on <Code>{repo.branch}</Code></> : null}.</Text>
        {local.length ? (
          <>
            <Command value={local[0].start ?? `tools/dash dev up ${repo.id}`} />
            <Text size="xs" c="dimmed">
              Its dev stack answers on {local.map((t, i) => <span key={t.id}>{i ? ', ' : ''}<External href={t.url} size="xs">{t.service} :{t.port}</External></span>)}.
            </Text>
          </>
        ) : null}
      </Stack>
      <Group gap="md">
        {repo.repo_url ? <External href={repo.repo_url} size="sm">repository</External> : null}
        {live ? <External href={live.url} size="sm">live site</External> : null}
        {repo.docs_url ? <External href={repo.docs_url} size="sm">docs</External> : null}
        <Anchor component={Link} to={to.project(repo.name)} size="sm">every signal, in the classic console</Anchor>
      </Group>
    </Stack>
  );
}

function Readme({ repo }: { repo: FleetRepo }) {
  const readme = useProjectReadme(repo.name);
  const onGitHub = repo.repo_url ? <External href={`${repo.repo_url}#readme`} size="sm">Read it in the repository</External> : null;
  if (readme.isError) return <Banner tone="crit" title="Could not read the README">{(readme.error as Error).message}</Banner>;
  if (readme.data === undefined) return <Spinner label="reading the README…" />;
  if (!readme.data.present || !readme.data.markdown) {
    return (
      <Stack gap="xs">
        <Text size="sm" c="dimmed">
          {hasConsole() ? <>The console could not show this README: {readme.data.reason ?? 'it is not available'}.</> : <>The public page carries no README; a console reads it from the repo's checkout.</>}
        </Text>
        {onGitHub}
      </Stack>
    );
  }
  // Relative links in the file point at its neighbours in the repo.
  const base = `${repo.repo_url ?? ''}/blob/${repo.branch ?? 'main'}/`;
  return (
    <Stack gap="xs">
      <Text size="xs" c="dimmed">From <Code>{readme.data.path}</Code> on this machine{readme.data.truncated ? ' (cut: the file is longer than the page shows)' : ''}. Images are shown as links.</Text>
      <Markdown source={readme.data.markdown} foreign={{ base }} />
    </Stack>
  );
}

function Work({ repo }: { repo: FleetRepo }) {
  const detail = useProject(repo.name);
  return (
    <Load q={detail} rows={4}>
      {(d) => (
        <Stack gap="xs">
          <Text size="sm" c="dimmed">Every open issue and pull request this repo carries, in the inbox's order. A row opens it on GitHub.</Text>
          <InboxTable rows={d.inbox} />
        </Stack>
      )}
    </Load>
  );
}

function Automation({ repo }: { repo: FleetRepo }) {
  const detail = useProject(repo.name);
  return (
    <Load q={detail} rows={4}>
      {(d) => (
        <Stack gap="md">
          {d.harness ? <HarnessWorkflows repo={d.harness} /> : <Empty>Not in the harness inventory.</Empty>}
          <div>
            <Text fw={650} size="sm" mb={4}>Schedule</Text>
            <ScheduleTable rows={d.schedule} />
          </div>
        </Stack>
      )}
    </Load>
  );
}

export function RepoApp({ repo, fill = false }: { repo: FleetRepo; doc?: AppsDoc; fill?: boolean }) {
  const [tab, setTab] = useState<string | null>('overview');
  const owed = repo.component.kind !== 'generated';
  return (
    <div className={c.root} data-fill={fill || undefined}>
      <Text size="xs" c="dimmed" mb="sm">
        {owed
          ? <>{repo.name}'s own frontend is not in the shell yet: it is owed {KIND_TEXT[repo.component.kind]}. Next: {repo.component.next}. Until then this is the app the shell generates for any repo.</>
          : <>{repo.name} has no interface of its own, so this app is generated from what the hub holds about it. Next: {KIND_TEXT.generated}.</>}
      </Text>
      <Tabs value={tab} onChange={setTab} keepMounted={false}>
        <Tabs.List mb="md">
          <Tabs.Tab value="overview">Overview</Tabs.Tab>
          <Tabs.Tab value="readme">README</Tabs.Tab>
          <Tabs.Tab value="work">Open work</Tabs.Tab>
          <Tabs.Tab value="automation">Automation</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="overview"><Overview repo={repo} /></Tabs.Panel>
        <Tabs.Panel value="readme"><Readme repo={repo} /></Tabs.Panel>
        <Tabs.Panel value="work"><Work repo={repo} /></Tabs.Panel>
        <Tabs.Panel value="automation"><Automation repo={repo} /></Tabs.Panel>
      </Tabs>
    </div>
  );
}
