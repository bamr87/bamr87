// The fleet contract (_data/fleet.yml), one top-level block per page
// (/config/:section — the Overview and Costs links land on the right block).
// Saving rewrites only that block in the working tree, comments intact, and
// shows the git diff; the commit and the PR stay with you. A key the file
// does not declare is read-only: the console never invents contract structure.
import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import {
  Anchor, Button, Checkbox, Grid, Group, NavLink, NumberInput, Paper, ScrollArea, Select, Stack, Table, Text, TextInput,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useQueryClient } from '@tanstack/react-query';
import { put } from '../api/client';
import { useCaps, useConfig, useStateDoc } from '../api/hooks';
import type { ConfigField, ConfigSection } from '../api/types';
import { Banner, External, Load, Mono, PageHeader, Section, Status } from '../components/ui';
import { LogView } from '../jobs/JobLog';
import { RunButton } from '../jobs/RunButton';
import { gh, to } from '../lib/links';

type Values = Record<string, unknown>;

function initial(s: ConfigSection): Values {
  return Object.fromEntries(s.fields.filter((f) => f.present).map((f) => [f.key, f.kind === 'list' ? ((f.value as string[]) ?? []).join(',') : f.value]));
}

function FieldInput({ f, value, onChange }: { f: ConfigField; value: unknown; onChange: (v: unknown) => void }) {
  if (!f.present) return <Status tone="info" title="Not declared in fleet.yml — add the key by hand first, then it becomes editable here.">not declared</Status>;
  switch (f.kind) {
    case 'bool': return <Checkbox checked={Boolean(value)} onChange={(e) => onChange(e.currentTarget.checked)} aria-label={f.path} />;
    case 'choice': return <Select data={f.choices ?? []} value={String(value ?? '')} onChange={(v) => onChange(v)} allowDeselect={false} w={180} aria-label={f.path} />;
    case 'int':
    case 'float': return <NumberInput value={value as number} onChange={(v) => onChange(v)} w={140} aria-label={f.path} decimalScale={f.kind === 'int' ? 0 : undefined} />;
    case 'list': return <TextInput value={String(value ?? '')} onChange={(e) => onChange(e.currentTarget.value)} placeholder="comma-separated" w={240} aria-label={f.path} />;
    case 'cron': return <TextInput value={String(value ?? '')} onChange={(e) => onChange(e.currentTarget.value)} placeholder="m h dom mon dow" ff="monospace" w={180} aria-label={f.path} />;
    default: return <TextInput value={String(value ?? '')} onChange={(e) => onChange(e.currentTarget.value)} w={240} aria-label={f.path} />;
  }
}

function SectionForm({ s, path, editable }: { s: ConfigSection; path: string; editable: boolean }) {
  const qc = useQueryClient();
  const [values, setValues] = useState<Values>(() => initial(s));
  const [diff, setDiff] = useState('');
  const [saving, setSaving] = useState(false);
  useEffect(() => { setValues(initial(s)); setDiff(''); }, [s]);
  const base = initial(s);
  const dirty = Object.keys(values).filter((k) => JSON.stringify(values[k]) !== JSON.stringify(base[k]));

  const save = async () => {
    setSaving(true);
    try {
      const changes = Object.fromEntries(dirty.map((k) => [k, values[k]]));
      const r = await put<{ applied: Record<string, unknown>; diff?: string }>('/api/config', { changes });
      const keys = Object.keys(r.applied ?? {});
      setDiff(keys.length ? r.diff || '(no diff — already saved?)' : 'nothing changed');
      notifications.show({ color: 'teal', title: keys.length ? 'Saved to the working tree' : 'No changes', message: keys.join(', ') || s.key });
      await qc.invalidateQueries({ queryKey: ['config'] });
      await qc.invalidateQueries({ queryKey: ['state'] });
    } catch (e) {
      notifications.show({ color: 'red', title: 'Not saved', message: (e as Error).message, autoClose: 9000 });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Stack gap="md">
      <PageHeader
        crumbs={[{ label: 'Config', to: to.config() }, { label: `${s.key}:` }]}
        title={<><Mono>{s.key}:</Mono> {s.title}</>}
        description={<>{s.blurb} <External href={gh.hubFile(s.doc)} size="sm">{s.doc}</External></>}
      />
      {!s.present ? <Banner tone="warn">There is no <Mono>{s.key}:</Mono> block in {path}.</Banner> : null}
      <Paper p="md">
        <Stack gap={0}>
          {s.fields.map((f) => (
            <Group key={f.key} justify="space-between" align="center" wrap="wrap" gap="xs" py={9} style={{ borderBottom: '1px solid var(--grid)' }}>
              <div style={{ flex: '1 1 260px', minWidth: 0 }}>
                <Text ff="monospace" fz={12.5} style={{ overflowWrap: 'anywhere' }}>{f.path}{dirty.includes(f.key) ? <Text span c="var(--warning)"> ●</Text> : null}</Text>
                <Text size="xs" c="dimmed">{f.help}</Text>
              </div>
              <FieldInput f={f} value={values[f.key]} onChange={(v) => setValues((x) => ({ ...x, [f.key]: v }))} />
            </Group>
          ))}
        </Stack>
        <Group gap="xs" mt="md">
          <Button onClick={() => void save()} loading={saving} disabled={!editable || !dirty.length}>Save <Mono>&nbsp;{s.key}:</Mono>{dirty.length ? ` (${dirty.length})` : ''}</Button>
          <Button variant="default" disabled={!dirty.length} onClick={() => setValues(base)}>Discard</Button>
          {s.key === 'harnesses' ? <RunButton op="harnesses-offline">Then recompute (offline)</RunButton> : null}
          {s.key === 'variables' ? <RunButton op="config-sync">Project onto the fleet (dry run)</RunButton> : null}
          {s.key === 'schedule' ? <Anchor component={Link} to={to.schedules()} size="sm">See the calendar</Anchor> : null}
        </Group>
      </Paper>
      {diff ? <Section mt={0} title="git diff — the working tree"><LogView raw={diff} height={320} /></Section> : null}
    </Stack>
  );
}

export function ConfigPage() {
  const { section } = useParams();
  const navigate = useNavigate();
  const config = useConfig();
  const caps = useCaps();
  const state = useStateDoc();
  return (
    <Load q={config} rows={8}>
      {(c) => {
        const current = c.sections.find((s) => s.key === (section ?? 'harnesses')) ?? c.sections[0];
        const editable = caps.data?.config_editing !== false;
        return (
          <Grid gap="lg">
            <Grid.Col span={{ base: 12, md: 3 }}>
              <Select hiddenFrom="md" label="Block" data={c.sections.map((x) => ({ value: x.key, label: `${x.key}: ${x.title}` }))}
                value={current?.key ?? null} onChange={(v) => v && navigate(to.config(v))} allowDeselect={false} mb="sm" />
              <Paper p={6} visibleFrom="md">
                <Text size="xs" fw={700} c="dimmed" tt="uppercase" px={8} pt={6}>{c.path}</Text>
                <ScrollArea.Autosize mah="70vh">
                  {c.sections.map((s) => (
                    <NavLink key={s.key} component={Link} to={to.config(s.key)} active={s.key === current?.key}
                      label={<Mono>{s.key}:</Mono>} description={s.title} rightSection={s.present ? null : <Status tone="warn">absent</Status>} styles={{ root: { borderRadius: 6 } }} />
                  ))}
                </ScrollArea.Autosize>
              </Paper>
              <Paper p="md" mt="md" visibleFrom="md">
                <Text fw={600} size="sm" mb={4}>The working tree</Text>
                <Text size="xs" c="dimmed" mb="sm">Saved edits land in {c.path} and nowhere else. The drift gate and the fixture tests verify a contract change; they run on the PR.</Text>
                <Stack gap={6}>
                  <RunButton op="tests">Fixture tests</RunButton>
                  <RunButton op="drift">Drift gate</RunButton>
                  <RunButton op="config-show">dash config show</RunButton>
                </Stack>
              </Paper>
              <Paper p="md" mt="md" visibleFrom="md">
                <Text fw={600} size="sm" mb={4}>Read-only here</Text>
                <Table className="dt" verticalSpacing={2}>
                  <Table.Tbody>
                    {Object.entries(state.data?.contract.hub ?? {}).map(([k, v]) => (
                      <Table.Tr key={k}><Table.Td><Mono dim>{k}</Mono></Table.Td><Table.Td className="wrap-anywhere"><Text size="xs">{String(v)}</Text></Table.Td></Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
                <Text size="xs" c="dimmed" mt="xs">Also read-only: the dependency policy, the token contract (Credentials), and every policy key fleet.yml calls non-negotiable — rotation.hub_first, issue_pipeline.autonomy.never_merge. Those change in an editor, with the comment that explains why.</Text>
              </Paper>
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 9 }}>
              {!editable ? <Banner tone="warn">ruamel.yaml is missing — editing is disabled (pip install ruamel.yaml).</Banner> : null}
              {current ? <SectionForm s={current} path={c.path} editable={editable} /> : <Banner tone="warn">No sections.</Banner>}
            </Grid.Col>
          </Grid>
        );
      }}
    </Load>
  );
}
