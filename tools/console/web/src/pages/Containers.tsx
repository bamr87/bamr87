// Containers on every DASH_DOCKER_HOST, attributed to registry projects. The
// compose console holds no Docker socket on purpose (a write-capable service
// holding one would be root on the Docker host); the terminal dash does.
import { Link } from 'react-router';
import { Anchor, Group, Stack, Text } from '@mantine/core';
import { useDocker } from '../api/hooks';
import type { Container } from '../api/types';
import { DataTable } from '../components/DataTable';
import { Banner, Load, Mono, PageHeader, Status } from '../components/ui';
import { to } from '../lib/links';

export function Containers() {
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
    </>
  );
}
