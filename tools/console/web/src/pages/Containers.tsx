// Containers on every DASH_DOCKER_HOST, attributed to registry projects. The
// compose console holds no Docker socket on purpose (a write-capable service
// holding one would be root on the Docker host); the terminal dash does.
import { Link } from 'react-router';
import { Anchor, Group, Stack, Text } from '@mantine/core';
import { hasConsole } from '../api/backend';
import { useData, useDocker } from '../api/hooks';
import type { Container, Dict } from '../api/types';
import { DataTable } from '../components/DataTable';
import { Banner, External, Load, Mono, PageHeader, Section, StatTile, Status } from '../components/ui';
import { SimpleGrid } from '@mantine/core';
import { to } from '../lib/links';

type Row = Dict<any>;

/** The committed Docker view (_data/docker.yml, `dash docker view --write`):
 * every allocated endpoint with the state it was last recorded in. What the
 * public page shows in place of live containers; a console shows it too. */
function DockerContract() {
  const d = useData<Row>('docker');
  return (
    <Load q={d}>
      {(v) => (v ? (
        <>
          <SimpleGrid cols={{ base: 2, md: 5 }} spacing="sm">
            <StatTile label="Projects" value={v.summary?.projects} sub={`${v.summary?.stacks} compose stacks`} />
            <StatTile label="Endpoints" value={v.summary?.endpoints} sub={`${v.summary?.ok} ok · ${v.summary?.broken} broken`} />
            <StatTile label="Services" value={v.summary?.services} />
            <StatTile label="Image families behind" value={v.summary?.families_behind} tone={v.summary?.families_behind ? 'crit' : undefined} />
            <StatTile label="Pending changes" value={v.summary?.pending_changes} sub="harmonizer audit" />
          </SimpleGrid>
          <Text size="xs" c="dimmed" mt={6}>Recorded {v.generated_at} on the operator's machine (local-first, like the smoke recording it reads). Contract: <External href="https://github.com/bamr87/bamr87/blob/main/docs/DOCKER.md" size="xs">docs/DOCKER.md</External>.</Text>
          <Section title="Endpoints">
            <DataTable<Row> rows={v.endpoints ?? []} keys rowKey={(e) => `${e.project}:${e.service}:${e.port}`} href={(e) => to.project(e.project)} minWidth={900}
              tone={(e) => (e.verdict === 'broken' ? 'crit' : e.present === false ? 'muted' : undefined)}
              columns={[
                { key: 'p', header: 'project', sort: (e) => e.project, render: (e) => <Anchor component={Link} to={to.project(e.project)} size="sm">{e.project}</Anchor> },
                { key: 's', header: 'service', sort: (e) => e.service, render: (e) => <Mono>{e.service}</Mono> },
                { key: 'port', header: 'port', num: true, sort: (e) => e.port, render: (e) => e.port },
                { key: 'k', header: 'kind', sort: (e) => e.kind, render: (e) => e.kind },
                { key: 'st', header: 'state', sort: (e) => e.state ?? '', render: (e) => (e.state === 'running' ? <Status tone="good">{e.health ?? 'running'}</Status> : <Text size="xs" c="dimmed">{e.state ?? 'absent'}</Text>) },
                { key: 'i', header: 'image', sort: (e) => e.image ?? '', render: (e) => <Mono dim>{e.image ?? ''}</Mono> },
              ]} />
          </Section>
        </>
      ) : <Text c="dimmed">No Docker view recorded yet.</Text>)}
    </Load>
  );
}

export function Containers() {
  if (!hasConsole()) {
    return (
      <>
        <PageHeader title="Containers" description="The fleet dev stack as last recorded: every allocated port, its service, image and state. Live containers are on each Docker host, which a console reads — connect one to see them." />
        <DockerContract />
      </>
    );
  }
  return <LiveContainers />;
}

function LiveContainers() {
  const docker = useDocker();
  return (
    <>
      <PageHeader
        title="Containers"
        description="Every container on each Docker host, attributed to its registry project by the com.bamr87.fleet.project label, then by compose project or name."
        actions={<Anchor component={Link} to={to.terminal()} size="sm">Open the terminal dash's Docker tab</Anchor>}
      />
      <Load q={docker}>
        {(d) => (
          <Stack gap="sm">
            {Object.entries(d.errors ?? {}).map(([h, e]) => (
              <Banner key={h} tone="warn" title={h}>{String(e).slice(0, 300)}</Banner>
            ))}
            <Text size="sm" c="dimmed">hosts: {d.hosts.join(', ') || 'none (DASH_DOCKER_HOST is empty)'} · polled {d.polled_at?.replace('T', ' ').slice(0, 19)}</Text>
            <DataTable<Container>
              rows={d.containers}
              keys
              rowKey={(c) => `${c.host}:${c.name}`}
              href={(c) => (c.owner ? to.project(c.owner) : null)}
              tone={(c) => (c.running ? undefined : 'muted')}
              empty="no containers"
              columns={[
                { key: 'host', header: 'host', sort: (c) => c.host, render: (c) => <Text size="sm">{c.host}</Text> },
                { key: 'state', header: 'state', sort: (c) => (c.running ? 0 : 1), render: (c) => (c.running ? <Status tone="good">up</Status> : <Text size="sm" c="dimmed">{c.state}</Text>) },
                { key: 'name', header: 'name', sort: (c) => c.name, render: (c) => <Mono>{c.name}</Mono> },
                { key: 'ports', header: 'ports', render: (c) => <Mono dim>{c.ports ?? ''}</Mono> },
                { key: 'status', header: 'status', render: (c) => <Text size="xs" c="dimmed">{c.status}</Text> },
                { key: 'owner', header: 'project', sort: (c) => c.owner ?? '', render: (c) => (c.owner ? <Anchor component={Link} to={to.project(c.owner)} size="sm">{c.owner}</Anchor> : <Text size="xs" c="dimmed">unattributed</Text>) },
              ]}
            />
            <Group><Text size="xs" c="dimmed">In the compose service the console has no Docker socket, so each host reports its error here; the terminal dash (Operate → Terminal, or tools/dash tui --docker) holds it.</Text></Group>
          </Stack>
        )}
      </Load>
      <Section title="The recorded contract"><DockerContract /></Section>
    </>
  );
}
