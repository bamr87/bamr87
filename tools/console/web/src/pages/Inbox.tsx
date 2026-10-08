// The fleet inbox: every flagged issue, PR and failing workflow, highest
// priority first (fleet_triage.yml through fleetcore — the TUI's Inbox tab).
import { useSearchParams } from 'react-router';
import { Group, SegmentedControl, Text, TextInput } from '@mantine/core';
import { IconSearch } from '@tabler/icons-react';
import { useFleet } from '../api/hooks';
import { Load, PageHeader } from '../components/ui';
import { RunButton } from '../jobs/RunButton';
import { includesText } from '../lib/format';
import { InboxTable } from './ProjectPage';

export function Inbox() {
  const [sp, setSp] = useSearchParams();
  const kind = sp.get('kind') ?? 'all';
  const q = sp.get('q') ?? '';
  const fleet = useFleet({});
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(sp);
    if (v && v !== 'all') next.set(k, v); else next.delete(k);
    setSp(next, { replace: true });
  };
  return (
    <>
      <PageHeader
        title="Inbox"
        description="Flagged items across the fleet, ranked. A project's page lists every open item it carries, flagged or not. Refreshed daily by fleet-pulse; refresh it here with the triage snapshot."
        actions={<RunButton op="triage">Triage snapshot</RunButton>}
      />
      <Load q={fleet}>
        {(v) => {
          const kinds = ['all', ...new Set(v.inbox.map((i) => i.kind))];
          const rows = v.inbox.filter((i) => (kind === 'all' || i.kind === kind) && includesText([i.repo, i.title, i.why, i.ref], q));
          return (
            <>
              <Group gap="sm" mb="sm" wrap="wrap">
                <TextInput data-page-search leftSection={<IconSearch size={15} />} placeholder="Filter…  ( / )" value={q} onChange={(e) => set('q', e.currentTarget.value)} w={260} />
                <SegmentedControl size="xs" data={kinds} value={kinds.includes(kind) ? kind : 'all'} onChange={(x) => set('kind', x)} />
                <Text size="sm" c="dimmed">{rows.length} of {v.inbox.length}</Text>
              </Group>
              <InboxTable rows={rows} showRepo />
            </>
          );
        }}
      </Load>
    </>
  );
}
