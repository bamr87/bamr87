// The fleet voice model (voices/v1, constitution § 23 rule 7): one editor for
// _data/voices/voices.yml — the only copy. The page loads the file with its
// tools/voices.py check errors and its drift from origin/main, edits it per
// site and persona, previews the exact bytes and diff a PR would carry (the
// preview writes nothing), and files them through the `voices-pr` operation:
// a dry run first, then — behind the confirm — one draft PR that changes that
// file alone. There is no database copy; git is the store and the PR the review.
import { useEffect, useMemo, useState } from 'react';
import {
  ActionIcon, Accordion, Badge, Button, Grid, Group, List, NavLink, Paper, Select, SimpleGrid, Stack, Switch, Table, Tabs, TagsInput, Text,
  TextInput, Textarea,
} from '@mantine/core';
import { IconArrowDown, IconArrowUp, IconPlus, IconTrash } from '@tabler/icons-react';
import { notifications } from '@mantine/notifications';
import { useQueryClient } from '@tanstack/react-query';
import { hasConsole } from '../api/backend';
import { post } from '../api/client';
import { useVoices } from '../api/hooks';
import type { VoiceProfile, VoiceRule, VoicesData, VoicesDoc, VoicesPreview, VoicesStaged, VoiceSite } from '../api/types';
import { Banner, Empty, External, Load, LocalOnly, Mono, PageHeader, Section, Status } from '../components/ui';
import { LogView } from '../jobs/JobLog';
import { useRunner } from '../jobs/JobRunner';
import { gh } from '../lib/links';

type Enums = VoicesDoc['enums'];
const TEXT: [string, string, boolean][] = [
  ['summary', 'Summary', true], ['audience', 'Audience', false], ['voice', 'Voice', false], ['tone', 'Tone', false],
  ['guidance', 'Guidance', true], ['avoid', 'Avoid', true], ['claims', 'Claims', true],
];
/** Fields the form edits; anything else a layer holds (bans, lifts, vocabulary …) round-trips untouched. */
const FORM_KEYS = new Set(['summary', 'audience', 'voice', 'tone', 'style', 'guidance', 'avoid', 'claims', 'topics', 'name', 'role', 'enabled', 'perspective', 'beats', 'repos']);
const KEY_RX = /^[a-z][a-z0-9_-]{0,40}$/;

/** A profile layer's own fields. An emptied text field is removed, so the layer inherits it again. */
function ProfileForm({ p, enums, onChange, readOnly, persona }: {
  p: VoiceProfile; enums: Enums; onChange: (next: VoiceProfile) => void; readOnly: boolean; persona?: boolean;
}) {
  const set = (k: string, v: unknown) => {
    const next: VoiceProfile = { ...p };
    if (v === '' || v === null || v === undefined || (Array.isArray(v) && !v.length && (k === 'beats' || k === 'repos'))) delete next[k];
    else next[k] = v;
    onChange(next);
  };
  const setStyle = (k: string, v: string | null) => {
    const style = { ...(p.style ?? {}) } as Record<string, string>;
    if (v) style[k] = v; else delete style[k];
    set('style', Object.keys(style).length ? style : undefined);
  };
  const setTopics = (k: 'cover' | 'exclude', v: string[]) => set('topics', { ...(p.topics ?? {}), [k]: v });
  const other = Object.keys(p).filter((k) => !FORM_KEYS.has(k));
  return (
    <Stack gap="sm">
      {persona ? (
        <SimpleGrid cols={{ base: 1, sm: 3 }}>
          <TextInput label="Name" required value={String(p.name ?? '')} readOnly={readOnly} onChange={(e) => set('name', e.currentTarget.value)} />
          <TextInput label="Role" description="the SDLC role it writes from" required value={String(p.role ?? '')} readOnly={readOnly} onChange={(e) => set('role', e.currentTarget.value)} />
          <Switch label="Enabled" description="assignment skips a disabled persona" mt="lg" checked={Boolean(p.enabled)} disabled={readOnly} onChange={(e) => onChange({ ...p, enabled: e.currentTarget.checked })} />
        </SimpleGrid>
      ) : null}
      {persona ? <Textarea label="Perspective" autosize minRows={1} value={String(p.perspective ?? '')} readOnly={readOnly} onChange={(e) => set('perspective', e.currentTarget.value)} /> : null}
      <SimpleGrid cols={{ base: 1, sm: 2 }}>
        {TEXT.map(([k, label, long]) => (long
          ? <Textarea key={k} label={label} autosize minRows={1} value={String(p[k] ?? '')} readOnly={readOnly} placeholder="(inherited)" onChange={(e) => set(k, e.currentTarget.value)} />
          : <TextInput key={k} label={label} value={String(p[k] ?? '')} readOnly={readOnly} placeholder="(inherited)" onChange={(e) => set(k, e.currentTarget.value)} />))}
      </SimpleGrid>
      <SimpleGrid cols={{ base: 2, sm: 4 }}>
        {Object.entries(enums.style).map(([k, values]) => (
          <Select key={k} label={`Style: ${k.replace('_', ' ')}`} data={values} value={(p.style as Record<string, string> | undefined)?.[k] ?? null}
            placeholder="(inherited)" clearable disabled={readOnly} onChange={(v) => setStyle(k, v)} />
        ))}
      </SimpleGrid>
      <SimpleGrid cols={{ base: 1, sm: 2 }}>
        <TagsInput label="Topics: cover" value={p.topics?.cover ?? []} disabled={readOnly} onChange={(v) => setTopics('cover', v)} clearable />
        <TagsInput label="Topics: exclude" value={p.topics?.exclude ?? []} disabled={readOnly} onChange={(v) => setTopics('exclude', v)} clearable />
      </SimpleGrid>
      {persona ? (
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <TagsInput label="Beats" description="the activity types it covers" value={p.beats ?? []} disabled={readOnly} onChange={(v) => set('beats', v)} clearable />
          <TagsInput label="Repos" description="the repos it covers; empty = all" value={p.repos ?? []} disabled={readOnly} onChange={(v) => set('repos', v)} clearable />
        </SimpleGrid>
      ) : null}
      {other.length ? <Text size="xs" c="dimmed">Also set on this layer, kept as they are (edit them in the file): {other.map((k) => <Mono key={k}>{k} </Mono>)}</Text> : null}
    </Stack>
  );
}

function Personas({ site, enums, onChange, readOnly }: { site: VoiceSite; enums: Enums; onChange: (s: VoiceSite) => void; readOnly: boolean }) {
  const personas = site.personas ?? {};
  const [key, setKey] = useState('');
  const used = new Set((site.assignment ?? []).flatMap((r) => [r.persona, r.default]).filter(Boolean) as string[]);
  const add = () => {
    onChange({ ...site, personas: { ...personas, [key]: { name: key, role: 'development', enabled: false } } });
    setKey('');
  };
  const remove = (k: string) => {
    const next = { ...personas };
    delete next[k];
    onChange({ ...site, personas: next });
  };
  return (
    <Stack gap="sm">
      <Accordion variant="separated" multiple>
        {Object.entries(personas).map(([k, p]) => (
          <Accordion.Item key={k} value={k}>
            <Accordion.Control>
              <Group gap="xs" wrap="wrap">
                <Mono>{k}</Mono>
                <Text size="sm" fw={600}>{String(p.name ?? '')}</Text>
                <Text size="xs" c="dimmed">{String(p.role ?? '')}</Text>
                {p.enabled ? <Status tone="good">enabled</Status> : <Status tone="info">disabled</Status>}
              </Group>
            </Accordion.Control>
            <Accordion.Panel>
              <ProfileForm p={p} enums={enums} persona readOnly={readOnly} onChange={(next) => onChange({ ...site, personas: { ...personas, [k]: next } })} />
              <Group justify="flex-end" mt="sm">
                <Button size="xs" variant="subtle" color="red" leftSection={<IconTrash size={14} />} disabled={readOnly || used.has(k)}
                  title={used.has(k) ? 'An assignment rule names it — change the rule first' : undefined} onClick={() => remove(k)}>Remove {k}</Button>
              </Group>
            </Accordion.Panel>
          </Accordion.Item>
        ))}
      </Accordion>
      {readOnly ? null : (
        <Group gap="xs" align="flex-end">
          <TextInput label="New persona key" description="lowercase; written to front matter as character:" value={key} onChange={(e) => setKey(e.currentTarget.value.trim())} w={240}
            error={key && (!KEY_RX.test(key) ? 'a-z, 0-9, - or _' : key in personas ? 'already a persona' : null)} />
          <Button size="sm" variant="default" leftSection={<IconPlus size={14} />} disabled={!key || !KEY_RX.test(key) || key in personas} onClick={add}>Add (disabled)</Button>
        </Group>
      )}
    </Stack>
  );
}

function Rules({ site, enums, onChange, readOnly }: { site: VoiceSite; enums: Enums; onChange: (s: VoiceSite) => void; readOnly: boolean }) {
  const rules = site.assignment ?? [];
  const keys = Object.keys(site.personas ?? {});
  const put = (next: VoiceRule[]) => onChange({ ...site, assignment: next });
  const edit = (i: number, fn: (r: VoiceRule) => VoiceRule) => put(rules.map((r, j) => (j === i ? fn({ ...r }) : r)));
  const list = (r: VoiceRule, k: 'activity' | 'repos', v: string[]) => {
    const next = { ...r };
    if (v.length) next[k] = v; else delete next[k];
    return next;
  };
  const move = (i: number, by: number) => {
    const next = [...rules];
    [next[i], next[i + by]] = [next[i + by], next[i]];
    put(next);
  };
  const last = rules.length && 'default' in rules[rules.length - 1] ? rules.length - 1 : rules.length;
  return (
    <Stack gap="xs">
      <Text size="sm" c="dimmed">The first rule that matches wins (activity, repos, cadence); a disabled persona is skipped; the default rule comes last.</Text>
      <Table.ScrollContainer minWidth={760}>
        <Table verticalSpacing={6}>
          <Table.Thead>
            <Table.Tr><Table.Th>#</Table.Th><Table.Th>Persona</Table.Th><Table.Th>Activity</Table.Th><Table.Th>Repos</Table.Th><Table.Th>Cadence</Table.Th><Table.Th /></Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rules.map((r, i) => {
              const isDefault = 'default' in r;
              return (
                <Table.Tr key={i}>
                  <Table.Td><Mono dim>{i}</Mono></Table.Td>
                  <Table.Td>
                    <Group gap={4} wrap="nowrap">
                      {isDefault ? <Badge size="xs" variant="light">default</Badge> : null}
                      <Select size="xs" w={120} data={keys} value={(isDefault ? r.default : r.persona) ?? null} disabled={readOnly} allowDeselect={false}
                        onChange={(v) => edit(i, (x) => (isDefault ? { default: v ?? '' } : { ...x, persona: v ?? '' }))} aria-label={`rule ${i} persona`} />
                    </Group>
                  </Table.Td>
                  <Table.Td>{isDefault ? <Text size="xs" c="dimmed">everything else</Text>
                    : <TagsInput size="xs" value={r.activity ?? []} disabled={readOnly} onChange={(v) => edit(i, (x) => list(x, 'activity', v))} aria-label={`rule ${i} activity`} />}</Table.Td>
                  <Table.Td>{isDefault ? null
                    : <TagsInput size="xs" value={r.repos ?? []} disabled={readOnly} onChange={(v) => edit(i, (x) => list(x, 'repos', v))} aria-label={`rule ${i} repos`} />}</Table.Td>
                  <Table.Td>{isDefault ? null
                    : <Select size="xs" w={110} data={enums.cadence} value={r.cadence ?? null} clearable disabled={readOnly} aria-label={`rule ${i} cadence`}
                      onChange={(v) => edit(i, (x) => { const n = { ...x }; if (v) n.cadence = v; else delete n.cadence; return n; })} />}</Table.Td>
                  <Table.Td>
                    {readOnly || isDefault ? null : (
                      <Group gap={2} wrap="nowrap">
                        <ActionIcon variant="subtle" size="sm" disabled={i === 0} onClick={() => move(i, -1)} aria-label={`move rule ${i} up`}><IconArrowUp size={14} /></ActionIcon>
                        <ActionIcon variant="subtle" size="sm" disabled={i + 1 >= last} onClick={() => move(i, 1)} aria-label={`move rule ${i} down`}><IconArrowDown size={14} /></ActionIcon>
                        <ActionIcon variant="subtle" size="sm" color="red" onClick={() => put(rules.filter((_, j) => j !== i))} aria-label={`remove rule ${i}`}><IconTrash size={14} /></ActionIcon>
                      </Group>
                    )}
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      {readOnly || !keys.length ? null : (
        <Group>
          <Button size="xs" variant="default" leftSection={<IconPlus size={14} />}
            onClick={() => put([...rules.slice(0, last), { persona: keys[0] }, ...rules.slice(last)])}>Add a rule (before the default)</Button>
        </Group>
      )}
    </Stack>
  );
}

/** Preview → dry run → draft PR. Each step needs the one before it for the same bytes. */
function FileIt({ draft, dirty, readOnly }: { draft: VoicesData; dirty: boolean; readOnly: boolean }) {
  const { runOp } = useRunner();
  const [preview, setPreview] = useState<VoicesPreview | null>(null);
  const [staged, setStaged] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const key = JSON.stringify(draft);
  useEffect(() => { setPreview(null); setStaged(null); }, [key]);

  const doPreview = async () => {
    setBusy(true);
    try {
      setPreview(await post<VoicesPreview>('/api/voices/preview', { data: draft }));
    } catch (e) {
      notifications.show({ color: 'red', title: 'Preview failed', message: (e as Error).message, autoClose: 9000 });
    } finally {
      setBusy(false);
    }
  };
  const dryRun = async () => {
    if (!preview) return;
    setBusy(true);
    try {
      const s = await post<VoicesStaged>('/api/voices/stage', { data: draft, plan_id: preview.plan_id });
      setStaged(s.plan_id);
      await runOp('voices-pr', { plan_id: s.plan_id });
    } catch (e) {
      notifications.show({ color: 'red', title: 'Not staged', message: (e as Error).message, autoClose: 9000 });
    } finally {
      setBusy(false);
    }
  };
  const ready = Boolean(preview?.ok && preview.changed);
  return (
    <Section title="Preview and file" description={<>Preview renders the edit exactly as the pull request would carry it and diffs it against <Mono>origin/main</Mono>; it writes nothing. The dry run stages those bytes outside the working tree and shows what the filer would do. Only then does <b>Open the draft PR</b> push one <Mono>chore/voices-*</Mono> branch and open one draft PR that changes <Mono>_data/voices/voices.yml</Mono> and nothing else (constitution § 11.8): it asks first, probes the token, and never merges.</>}>
      <Paper p="md">
        <Group gap="xs" wrap="wrap">
          <Button onClick={() => void doPreview()} loading={busy && !preview} disabled={readOnly}>Preview{dirty ? '' : ' (no edits yet)'}</Button>
          <Button variant="default" onClick={() => void dryRun()} disabled={readOnly || !ready || busy}>Dry run</Button>
          <Button color="red" onClick={() => void runOp('voices-pr', { plan_id: staged, apply: true })} disabled={readOnly || !ready || staged !== preview?.plan_id}>Open the draft PR</Button>
          {preview ? <Text size="xs" c="dimmed">plan <Mono>{preview.plan_id}</Mono> against {preview.base}</Text> : null}
        </Group>
        {preview && !preview.ok ? (
          <Banner tone="crit" title="tools/voices.py check refuses this edit">
            <List size="sm">{preview.errors.map((e) => <List.Item key={e}><Mono>{e}</Mono></List.Item>)}</List>
          </Banner>
        ) : null}
        {preview && preview.ok && !preview.changed ? <Banner tone="info">Nothing to file: the edit equals <Mono>voices.yml</Mono> on {preview.base}.</Banner> : null}
        {preview && preview.changes.length ? (
          <Text size="sm" mt="sm">Changes: {preview.changes.map((c) => <Badge key={c} variant="light" size="sm" mr={4} tt="none">{c}</Badge>)}</Text>
        ) : null}
        {preview?.diff ? <LogView raw={preview.diff} height={320} /> : null}
      </Paper>
    </Section>
  );
}

function Editor({ doc }: { doc: VoicesDoc }) {
  const qc = useQueryClient();
  const readOnly = !hasConsole();
  const [draft, setDraft] = useState<VoicesData | null>(() => (doc.data ? structuredClone(doc.data) : null));
  useEffect(() => setDraft(doc.data ? structuredClone(doc.data) : null), [doc.text]);
  const sites = Object.keys(draft?.sites ?? {});
  const [where, setWhere] = useState<string>(sites[0] ?? 'defaults');
  const dirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(doc.data), [draft, doc.data]);

  if (!draft) {
    return <Banner tone="crit" title={`${doc.path} could not be read`}>{doc.errors.join('; ') || 'not a mapping'}</Banner>;
  }
  const site = draft.sites[where];
  const setSite = (s: VoiceSite) => setDraft({ ...draft, sites: { ...draft.sites, [where]: s } });
  return (
    <Stack gap="md">
      <PageHeader
        title="Voices"
        badges={<>
          {doc.ok ? <Status tone="good">check passes</Status> : <Status tone="crit">{`${doc.errors.length} check error(s)`}</Status>}
          {dirty ? <Status tone="warn">edited</Status> : null}
        </>}
        description={<>The fleet voice model (<Mono>voices/v1</Mono>) that lifehacker.dev and zer0-CMS read: defaults, each site's profile, its personas and who writes what. <External href={gh.hubFile(doc.path)} size="sm">{doc.path}</External> is the only copy — this page writes it back as a draft PR, never to a database (constitution § 23 rule 7). Schema: <External href={gh.hubFile(doc.schema_path)} size="sm">{doc.schema_path}</External>.</>}
        actions={<>
          <Button size="xs" variant="default" disabled={!dirty} onClick={() => setDraft(doc.data ? structuredClone(doc.data) : null)}>Discard edits</Button>
          <Button size="xs" variant="default" onClick={() => void qc.invalidateQueries({ queryKey: ['voices'] })}>Reload the file</Button>
        </>}
      />
      {readOnly ? <LocalOnly what={<>Editing the voice model files a draft PR from the hub's checkout</>} /> : null}
      {doc.drift.differs ? (
        <Banner tone="warn" title={`The loaded file differs from ${doc.drift.ref}`}>
          <Text size="sm">{doc.drift.changes.length
            ? <>Changed here and not on main: {doc.drift.changes.map((c) => <Mono key={c}>{c} </Mono>)}. </>
            : <>The data is the same; only comments or layout differ. </>}A filed edit replaces main's file with the previewed bytes, these differences included — pull main first if they are not yours.</Text>
        </Banner>
      ) : null}
      {!doc.drift.available ? <Banner tone="info">{doc.drift.ref} could not be read here, so drift is unknown; a preview diffs against the working tree.</Banner> : null}
      {doc.errors.length ? (
        <Banner tone="crit" title={`tools/voices.py check: ${doc.errors.length} error(s) in the file as loaded`}>
          <List size="sm">{doc.errors.map((e) => <List.Item key={e}><Mono>{e}</Mono></List.Item>)}</List>
        </Banner>
      ) : null}
      <Grid gap="lg">
        <Grid.Col span={{ base: 12, md: 3 }}>
          <Paper p={6}>
            <Text size="xs" fw={700} c="dimmed" tt="uppercase" px={8} pt={6}>Layers</Text>
            <NavLink component="button" label="Defaults" description="every site, every persona" active={where === 'defaults'} onClick={() => setWhere('defaults')} />
            {sites.map((s) => (
              <NavLink key={s} component="button" label={<Mono>{s}</Mono>} description={`${Object.keys(draft.sites[s]?.personas ?? {}).length} personas · ${(draft.sites[s]?.assignment ?? []).length} rules`}
                active={where === s} onClick={() => setWhere(s)} />
            ))}
          </Paper>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 9 }}>
          {where === 'defaults' || !site ? (
            <Paper p="md">
              <Text fw={600} mb="xs">Defaults</Text>
              <ProfileForm p={draft.defaults ?? {}} enums={doc.enums} readOnly={readOnly} onChange={(next) => setDraft({ ...draft, defaults: next })} />
            </Paper>
          ) : (
            <Tabs defaultValue="personas" keepMounted={false}>
              <Tabs.List mb="md">
                <Tabs.Tab value="personas">Personas</Tabs.Tab>
                <Tabs.Tab value="profile">Site profile</Tabs.Tab>
                <Tabs.Tab value="assignment">Assignment</Tabs.Tab>
              </Tabs.List>
              <Tabs.Panel value="personas"><Personas site={site} enums={doc.enums} readOnly={readOnly} onChange={setSite} /></Tabs.Panel>
              <Tabs.Panel value="profile">
                <Paper p="md"><ProfileForm p={site.profile ?? {}} enums={doc.enums} readOnly={readOnly} onChange={(next) => setSite({ ...site, profile: next })} /></Paper>
              </Tabs.Panel>
              <Tabs.Panel value="assignment"><Rules site={site} enums={doc.enums} readOnly={readOnly} onChange={setSite} /></Tabs.Panel>
            </Tabs>
          )}
        </Grid.Col>
      </Grid>
      <FileIt draft={draft} dirty={dirty} readOnly={readOnly} />
      {!sites.length ? <Empty>No sites in the file yet.</Empty> : null}
    </Stack>
  );
}

export function Voices() {
  const q = useVoices();
  return <Load q={q} rows={8}>{(doc) => <Editor doc={doc} />}</Load>;
}
