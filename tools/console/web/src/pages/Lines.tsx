// Every workflow in the lake in GitFactory's vocabulary: a line compiled from a
// blueprint (blueprint@hash), its gate (a vars.*_ENABLED kill switch),
// triggers and crons, model and auth, and its latest verdict. Hand-built
// workflows are the adoption candidates (gitorio specs/012).
import { Checkbox, Group, SegmentedControl, Text, TextInput } from '@mantine/core';
import { IconSearch } from '@tabler/icons-react';
import { useSearchParams } from 'react-router';
import { useLakeLines } from '../api/hooks';
import { Load, PageHeader } from '../components/ui';
import { RunButton } from '../jobs/RunButton';
import { includesText } from '../lib/format';
import { LinesTable } from './ProjectPage';

export function Lines() {
  const lines = useLakeLines();
  const [sp, setSp] = useSearchParams();
  const q = sp.get('q') ?? '';
  const aiOnly = sp.get('all') !== '1';
  const filter = sp.get('f') ?? 'all';
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(sp);
    if (v) next.set(k, v); else next.delete(k);
    setSp(next, { replace: true });
  };
  return (
    <>
      <PageHeader
        title="Lines"
        description="Every workflow the lake holds, with its provenance, its kill switch and its last verdict. A scheduled agent with no switch cannot be stopped without a commit — that is the gap to close first."
        actions={<RunButton op="lake-sync">Sync lake</RunButton>}
      />
      <Load q={lines}>
        {(all) => {
          const rows = all.filter((w) => (!aiOnly || w.ai)
            && (filter === 'all' || (filter === 'failing' && w.last_conclusion === 'failure') || (filter === 'noswitch' && w.kind === 'scheduled-agent' && !w.switch) || (filter === 'handbuilt' && !w.factory_blueprint))
            && includesText([w.nwo, w.path, w.kind], q));
          return (
            <>
              <Group gap="sm" mb="sm" wrap="wrap">
                <TextInput data-page-search leftSection={<IconSearch size={15} />} placeholder="Filter repo / path / kind…  ( / )" value={q} onChange={(e) => set('q', e.currentTarget.value)} w={280} />
                <Checkbox label="AI lines only" checked={aiOnly} onChange={(e) => set('all', e.currentTarget.checked ? '' : '1')} />
                <SegmentedControl size="xs" value={filter} onChange={(v) => set('f', v === 'all' ? '' : v)}
                  data={[{ label: 'All', value: 'all' }, { label: 'Failing', value: 'failing' }, { label: 'No kill switch', value: 'noswitch' }, { label: 'Hand-built', value: 'handbuilt' }]} />
                <Text size="sm" c="dimmed">{rows.length} of {all.length}</Text>
              </Group>
              <LinesTable rows={rows} />
            </>
          );
        }}
      </Load>
    </>
  );
}
