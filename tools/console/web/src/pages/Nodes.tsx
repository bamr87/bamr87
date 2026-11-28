// Where hub workloads run (tools/fleetcore/nodes.py, docs/PLATFORM.md): a card
// per node — role, on/off, reachability, capacity, the hub services placed on
// and running on it — then the drift and the placement table. The document is
// fleetcore.nodes.status_doc, the one `tools/dash node status --json` prints and
// the MCP's fleet_nodes returns. Read-only: placement changes by a reviewed PR,
// and `enabled: true` in _data/fleet.yml is the deploy step. A node that is off
// is never probed; the published page probes nothing and says so.
import { Link } from 'react-router';
import { Anchor, Badge, Group, Paper, SimpleGrid, Stack, Text } from '@mantine/core';
import { useNodes } from '../api/hooks';
import type { FleetNode, NodePlanRow, NodeState, NodesDoc } from '../api/types';
import { DataTable } from '../components/DataTable';
import { Banner, External, Load, Mono, PageHeader, Section, Status, type Tone } from '../components/ui';
import { to } from '../lib/links';

const DOC = 'https://github.com/bamr87/bamr87/blob/main/docs/PLATFORM.md';

export const NODE_STATE: Record<NodeState, { tone: Tone; label: string; title: string }> = {
  up: { tone: 'good', label: 'up', title: 'reached within the probe time limit' },
  unknown: { tone: 'warn', label: 'unknown', title: 'probed, and it did not answer within the time limit' },
  off: { tone: 'info', label: 'off', title: 'not enabled in _data/fleet.yml — never probed' },
  unprobed: { tone: 'info', label: 'not probed', title: 'read on the operator’s machine, not in the published page' },
};

const gib = (n?: number | null): string => (n == null ? '—' : `${(n / 2 ** 30).toFixed(1)} GiB`);

function Capacity({ n }: { n: FleetNode }) {
  const c = n.capacity;
  const d = n.declared;
  const declared = d ? `${d.cpus ?? '?'} CPUs · ${d.mem_gb ?? '?'} GB RAM · ${d.disk_gb ?? '?'} GB disk` : null;
  return (
    <Stack gap={2}>
      {c?.via === 'engine' ? (
        <Text size="sm">{c.cpus} CPUs · {gib(c.mem_total)} in the Docker engine · {c.containers_running ?? 0} containers running</Text>
      ) : c?.via === 'ssh' ? (
        <Text size="sm">{c.cpus} CPUs · {gib(c.mem_available)} of {gib(c.mem_total)} RAM free · {gib(c.disk_free)} of {gib(c.disk_total)} disk free</Text>
      ) : n.probed ? (
        <Text size="sm" c="dimmed">capacity not measured: the probe did not answer</Text>
      ) : declared ? null : (
        <Text size="sm" c="dimmed">capacity not measured</Text>
      )}
      {declared ? <Text size="xs" c="dimmed">declared in fleet.yml: {declared}</Text> : null}
    </Stack>
  );
}

function NodeCard({ n }: { n: FleetNode }) {
  const st = NODE_STATE[n.status] ?? NODE_STATE.unknown;
  return (
    <Paper p="md" withBorder>
      <Stack gap="xs">
        <Group justify="space-between" wrap="wrap" gap="xs">
          <Group gap="xs" wrap="wrap">
            <Text fw={600} ff="monospace">{n.name}</Text>
            <Badge variant="default" size="sm">{n.role}</Badge>
            <Badge variant={n.enabled ? 'light' : 'default'} color={n.enabled ? 'teal' : 'gray'} size="sm">{n.enabled ? 'on' : 'off'}</Badge>
          </Group>
          <Status tone={st.tone} title={st.title}>{st.label}</Status>
        </Group>
        <Group gap={6} wrap="wrap">
          <Text size="xs" c="dimmed">docker</Text><Mono dim>{n.docker}</Mono>
          <Text size="xs" c="dimmed">· {n.runtime}</Text>
        </Group>
        <Text size="sm" c={n.status === 'unknown' ? 'var(--warning)' : 'dimmed'}>{n.detail}</Text>
        {n.docker_error ? <Text size="xs" c="var(--warning)">containers unread: {n.docker_error}</Text> : null}
        <Capacity n={n} />
        <Text size="sm">
          hub services: {n.containers == null ? <Text span c="dimmed">running now unknown</Text> : <b>{n.containers} running</b>}
          {' · '}{n.placed.length} placed here
        </Text>
        {n.placed.length ? <Text size="xs" c="dimmed" ff="monospace">{n.placed.join(' · ')}</Text> : null}
        {n.deferred.length ? (
          <Text size="xs" c="dimmed">placed here once it is enabled: <Text span ff="monospace" fz="xs">{n.deferred.join(' · ')}</Text></Text>
        ) : null}
      </Stack>
    </Paper>
  );
}

/** The drift section's title and description. Drift is a number only when some
 * node's containers were read: the published page reads none, and a console
 * without a Docker socket reaches the edge but cannot list it — a zero there
 * would never have been measured. */
function driftText(d: NodesDoc): { title: string; description: string } {
  if (d.drift != null) {
    return {
      title: `Placement drift: ${d.drift.length} service(s)`,
      description: `A hub service running somewhere other than where it is placed, on the nodes whose containers were read: ${d.drift_read.join(', ')}.`,
    };
  }
  return {
    title: 'Placement drift: not read',
    description: d.probed
      ? 'No node’s containers could be read (each card says why), so drift was not measured.'
      : 'Drift compares placement with what runs, which only a console reads.',
  };
}

function Placement({ d }: { d: NodesDoc }) {
  const drifted = new Set((d.drift ?? []).map((r) => r.service));
  return (
    <DataTable<NodePlanRow>
      rows={d.services}
      keys
      rowKey={(r) => r.service}
      tone={(r) => (drifted.has(r.service) ? 'warn' : r.deferred ? 'muted' : undefined)}
      empty="no services in docker-compose.yml"
      columns={[
        { key: 'service', header: 'service', sort: (r) => r.service, render: (r) => <Mono>{r.service}</Mono> },
        { key: 'wants', header: 'placed on', sort: (r) => r.wants, render: (r) => <Text size="sm">{r.wants}</Text> },
        { key: 'runs', header: 'runs on', sort: (r) => r.runs_on.join(','), render: (r) => <Text size="sm">{r.runs_on.join(', ')}</Text> },
        // What runs now, and so what would change, only where some node's containers were read.
        ...(d.drift != null ? [
          { key: 'now', header: 'running now', sort: (r: NodePlanRow) => r.now.join(','), render: (r: NodePlanRow) => <Text size="sm" c={r.now.length ? undefined : 'dimmed'}>{r.now.join(', ') || '—'}</Text> },
          { key: 'action', header: 'what would change', render: (r: NodePlanRow) => <Text size="xs" c={drifted.has(r.service) ? 'var(--warning)' : 'dimmed'}>{r.action}</Text> },
        ] : []),
        { key: 'reason', header: 'why', render: (r) => <Text size="xs" c="dimmed">{r.reason}</Text> },
      ]}
    />
  );
}

export function Nodes() {
  const q = useNodes();
  return (
    <>
      <PageHeader
        title="Nodes"
        description="Where each hub service runs: the Mac is the edge, x870e a workload node, and _data/fleet.yml nodes: places every compose service. A node that is not enabled is never probed. Nothing here changes a machine: placement changes by a reviewed pull request, and enabled: true is the deploy step."
        actions={<Group gap="sm"><Anchor component={Link} to={to.containers()} size="sm">Containers</Anchor><External href={DOC} size="sm">docs/PLATFORM.md</External></Group>}
      />
      <Load q={q}>
        {(d) => (
          <Stack gap="md">
            {!d.probed ? (
              <Banner tone="info" title="The committed model, nothing probed">
                Reachability, measured capacity and running containers are read on the operator’s machine, so this published page shows placement as committed and each node’s declared capacity.{' '}
                <Anchor component={Link} to={to.connect()}>Connect a console</Anchor> to see them live.
              </Banner>
            ) : null}
            {d.problems.map((p) => <Banner key={p} tone="crit" title="Placement problem">{p}</Banner>)}
            {d.nodes.length ? (
              <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
                {d.nodes.map((n) => <NodeCard key={n.name} n={n} />)}
              </SimpleGrid>
            ) : <Text c="dimmed">No nodes: _data/fleet.yml has no nodes: block.</Text>}
            <Text size="xs" c="dimmed">edge: {d.edge || '—'} · {d.probed ? `probed ${d.generated_at.replace('T', ' ').slice(0, 19)} UTC` : `built ${d.generated_at.slice(0, 10)}`} · <Mono dim>tools/dash node status</Mono> prints the same document</Text>
            <Section title={driftText(d).title} mt="md" description={driftText(d).description}>
              {d.drift == null ? (
                d.probed ? <Status tone="info">not measured: no node’s containers were read</Status> : null
              ) : d.drift.length ? (
                <Stack gap={4}>
                  {d.drift.map((r) => <Text key={r.service} size="sm"><Mono>{r.service}</Mono> runs on {r.now.join(', ')}, placed on {r.runs_on.join(', ')}</Text>)}
                </Stack>
              ) : <Status tone="good">every running hub service is where it is placed</Status>}
            </Section>
            <Section title="Placement" description={<>Every compose service, where fleet.yml places it and where it resolves to while each node is on or off. <Mono>tools/dash node plan --assume-enabled</Mono> previews the move.</>}>
              <Placement d={d} />
            </Section>
          </Stack>
        )}
      </Load>
    </>
  );
}
