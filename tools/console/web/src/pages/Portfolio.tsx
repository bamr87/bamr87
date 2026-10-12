// The portfolio: every registry project as a card, featured first, filtered by
// category or text, each a link to its project page. Health is the same Apps
// row the Projects table and the terminal dash show (fleetcore).
import { useSearchParams } from 'react-router';
import { Group, SegmentedControl, SimpleGrid, Text, TextInput } from '@mantine/core';
import { IconSearch } from '@tabler/icons-react';
import { useFleet } from '../api/hooks';
import { Load, PageHeader } from '../components/ui';
import { ProjectCard } from './Home';

const CATEGORIES: Record<string, string> = { all: 'All', 'full-stack-ai': 'Full-stack / AI', 'dev-tools': 'Dev tools', docs: 'Docs', dash: 'Dash' };

export function Portfolio() {
  const [sp, setSp] = useSearchParams();
  const q = sp.get('q') ?? '';
  const category = sp.get('category') ?? 'all';
  const fleet = useFleet({ sort: 'featured', q });
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(sp);
    if (v && v !== 'all') next.set(k, v);
    else next.delete(k);
    setSp(next, { replace: true });
  };
  return (
    <>
      <PageHeader title="Portfolio" description="Every project in the fleet, featured first. The registry these cards are drawn from is the same one the dash, the drift gate and the profile README read; the dot is each project's live health." />
      <Group gap="sm" mb="md" wrap="wrap">
        <TextInput data-page-search leftSection={<IconSearch size={15} />} placeholder="Filter…  ( / )" value={q} onChange={(e) => set('q', e.currentTarget.value)} w={260} />
        <SegmentedControl size="xs" data={Object.entries(CATEGORIES).map(([value, label]) => ({ value, label }))} value={category} onChange={(v) => set('category', v)} />
      </Group>
      <Load q={fleet} rows={6}>
        {(v) => {
          const rows = v.rows.filter((r) => category === 'all' || r.category === category);
          return (
            <>
              <Text size="sm" c="dimmed" mb="sm">{rows.length} project{rows.length === 1 ? '' : 's'}</Text>
              <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="sm">
                {rows.map((r) => <ProjectCard key={r.name} r={r} />)}
              </SimpleGrid>
            </>
          );
        }}
      </Load>
    </>
  );
}
