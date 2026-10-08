// GitHub: connect the console through its OAuth App, then every repo the
// account can see — the fleet's own marked and managed — and the log of every
// write the console made.
import { Link, useParams } from 'react-router';
import { Anchor, Checkbox, Group, Text, TextInput } from '@mantine/core';
import { IconSearch } from '@tabler/icons-react';
import { useState } from 'react';
import { useGithubLog, useGithubRepos, useGithubStatus } from '../api/hooks';
import type { GhAction, GhRepo } from '../api/types';
import { DataTable } from '../components/DataTable';
import { External, Load, Mono, PageHeader, Section, Status } from '../components/ui';
import { ConnectPanel } from '../github/ConnectPanel';
import { RepoManager } from '../github/RepoManager';
import { includesText, when } from '../lib/format';
import { gh, to } from '../lib/links';

export function ActionLog() {
  const log = useGithubLog();
  return (
    <Load q={log}>
      {(rows) => (
        <DataTable<GhAction>
          rows={rows}
          rowKey={(a, i) => `${a.at}:${i}`}
          onActivate={(a) => a.url && window.open(a.url, '_blank', 'noopener')}
          tone={(a) => (a.ok ? undefined : 'crit')}
          empty="No writes yet in this console session."
          columns={[
            { key: 'ok', header: '', render: (a) => (a.ok ? <Status tone="good">done</Status> : <Status tone="crit">refused</Status>), width: 90 },
            { key: 'at', header: 'when', render: (a) => <Text size="xs" c="dimmed">{when(a.at)}</Text> },
            { key: 'a', header: 'action', render: (a) => <Text size="sm">{a.label}</Text> },
            { key: 'r', header: 'repo', render: (a) => <Anchor component={Link} to={to.ghRepo(a.repo)} ff="monospace" fz="sm">{a.repo}</Anchor> },
            { key: 't', header: 'target', render: (a) => (a.url ? <External href={a.url} size="sm">{a.target}</External> : <Text size="sm">{a.target}</Text>) },
            { key: 'e', header: 'error', render: (a) => <Text size="xs" c="dimmed">{a.error ?? ''}</Text> },
          ]}
        />
      )}
    </Load>
  );
}

function Repos() {
  const repos = useGithubRepos(true);
  const [q, setQ] = useState('');
  const [fleetOnly, setFleetOnly] = useState(true);
  const [archived, setArchived] = useState(false);
  return (
    <Load q={repos} rows={8}>
      {(all) => {
        const rows = all.filter((r) => (!fleetOnly || r.writable) && (archived || !r.archived) && includesText([r.full_name, r.description, r.language, r.fleet_name], q));
        return (
          <>
            <Group gap="sm" mb="sm" wrap="wrap">
              <TextInput data-page-search leftSection={<IconSearch size={15} />} placeholder="Filter repos…  ( / )" value={q} onChange={(e) => setQ(e.currentTarget.value)} w={280} />
              <Checkbox label="Fleet repos only" checked={fleetOnly} onChange={(e) => setFleetOnly(e.currentTarget.checked)} />
              <Checkbox label="Include archived" checked={archived} onChange={(e) => setArchived(e.currentTarget.checked)} />
              <Text size="sm" c="dimmed">{rows.length} of {all.length}</Text>
            </Group>
            <DataTable<GhRepo>
              rows={rows}
              keys
              rowKey={(r) => r.full_name}
              href={(r) => to.ghRepo(r.full_name)}
              open={(r) => r.html_url}
              copy={(r) => r.html_url}
              tone={(r) => (r.archived ? 'muted' : undefined)}
              empty="no repos match"
              minWidth={900}
              columns={[
                {
                  key: 'n', header: 'repository', sort: (r) => r.full_name, render: (r) => (
                    <div>
                      <Group gap={6}><Text size="sm" fw={600} ff="monospace">{r.full_name}</Text>{r.private ? <Text size="xs" c="dimmed">private</Text> : null}{r.fork ? <Text size="xs" c="dimmed">fork</Text> : null}{r.archived ? <Text size="xs" c="dimmed">archived</Text> : null}</Group>
                      <Text size="xs" c="dimmed" lineClamp={1}>{r.description}</Text>
                    </div>
                  ),
                },
                { key: 'f', header: 'fleet', sort: (r) => (r.writable ? 0 : 1), render: (r) => (r.fleet_name ? <Anchor component={Link} to={to.project(r.fleet_name)} size="sm">{r.fleet_name}</Anchor> : <Text size="xs" c="dimmed">—</Text>) },
                { key: 'l', header: 'language', sort: (r) => r.language ?? '', render: (r) => <Text size="sm">{r.language ?? ''}</Text> },
                { key: 'i', header: 'open issues', num: true, sort: (r) => r.open_issues, render: (r) => r.open_issues },
                { key: 's', header: 'stars', num: true, sort: (r) => r.stars, render: (r) => r.stars },
                { key: 'p', header: 'pushed', sort: (r) => r.pushed_at ?? '', render: (r) => <Text size="xs" c="dimmed">{when(r.pushed_at)}</Text> },
                { key: 'w', header: '', render: (r) => (r.writable ? <Status tone="good">managed</Status> : <Text size="xs" c="dimmed">read-only</Text>) },
              ]}
            />
          </>
        );
      }}
    </Load>
  );
}

export function GithubPage() {
  const status = useGithubStatus();
  return (
    <>
      <PageHeader
        title="GitHub"
        description={<>Connect the console to GitHub through its own OAuth App, then manage the fleet's repos from here: issues, pull-request conversations, workflow runs and workflows. Writes go only to repos the hub owns, each one confirmed and logged. Nothing here merges, deletes or pushes. See <External href={gh.hubFile('tools/console/README.md')} size="sm">the console README</External>.</>}
      />
      <Load q={status} rows={4}>
        {(s) => (
          <>
            <ConnectPanel s={s} />
            {s.connected ? (
              <>
                <Section title="Repositories" description={`What ${s.login} can see, newest push first. Fleet repos (owned by ${s.fleet_owner} and in the registry, plus the hub) are managed here; everything else is read-only.`}>
                  <Repos />
                </Section>
                <Section title="Action log" description="Every write this console process made to GitHub, newest first. Kept for the life of the process.">
                  <ActionLog />
                </Section>
              </>
            ) : null}
          </>
        )}
      </Load>
    </>
  );
}

export function GithubRepoPage() {
  const { owner = '', repo = '' } = useParams();
  const nwo = `${owner}/${repo}`;
  return (
    <>
      <PageHeader crumbs={[{ label: 'GitHub', to: to.github() }, { label: nwo }]} title={<Mono>{nwo}</Mono>} />
      <RepoManager nwo={nwo} />
    </>
  );
}
