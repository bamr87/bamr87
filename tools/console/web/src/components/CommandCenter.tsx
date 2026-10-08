// One palette for going anywhere and running anything: ':' (keys v1) or ⌘K.
// Pages, every registry project, loops, config blocks, content sites and the
// allowlisted operations. Picking an operation that takes parameters opens its
// page with the form; one that takes none runs (through the same confirm gate).
import { useMemo } from 'react';
import { useNavigate } from 'react-router';
import { Spotlight, type SpotlightActionGroupData } from '@mantine/spotlight';
import { Badge } from '@mantine/core';
import { IconAppWindow, IconFileText, IconPlayerPlay, IconRepeat, IconSearch, IconSettings } from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import { useOps, useStateDoc } from '../api/hooks';
import type { Dict } from '../api/types';
import { useRunner } from '../jobs/JobRunner';
import { FLAT } from '../nav';
import { to } from '../lib/links';

export function CommandCenter() {
  const navigate = useNavigate();
  const state = useStateDoc();
  const ops = useOps();
  const qc = useQueryClient();
  const { runOp } = useRunner();

  const actions = useMemo<SpotlightActionGroupData[]>(() => {
    const go = (path: string) => () => navigate(path);
    const pages = FLAT.map((it) => ({
      id: `page:${it.to}`, label: it.label, description: it.hint, leftSection: <it.icon size={18} stroke={1.6} />, onClick: go(it.to),
    }));
    const projects = (state.data?.registry.projects ?? []).map((p) => ({
      id: `project:${p.name}`, label: p.name, description: [p.category, p.status].filter(Boolean).join(' · '),
      keywords: ['project', 'repo', p.category ?? ''], leftSection: <IconAppWindow size={18} stroke={1.6} />, onClick: go(to.project(p.name)),
    }));
    const loops = (state.data?.loops ?? []).map((l) => ({
      id: `loop:${l.id}`, label: l.title, description: `${l.workflow}.yml · ${l.cron_human}`, keywords: ['loop', l.workflow],
      leftSection: <IconRepeat size={18} stroke={1.6} />, onClick: go(to.loop(l.id)),
    }));
    // Content sites come from the cache when the Content page has been opened;
    // the palette never fetches the atlas just to list names.
    const content = qc.getQueryData<Dict<any>>(['content']);
    const sites = ((content?.sites ?? content?.declared ?? []) as Dict<any>[]).map((s) => {
      const name = String(s.site ?? s.name);
      return { id: `site:${name}`, label: name, description: 'content site', keywords: ['content', 'site'], leftSection: <IconFileText size={18} stroke={1.6} />, onClick: go(to.site(name)) };
    });
    const config = ['toolchain', 'schedule', 'remediation', 'issue_pipeline', 'evolution', 'harness', 'harnesses', 'rotation', 'variables'].map((k) => ({
      id: `config:${k}`, label: `${k}:`, description: 'fleet.yml block', keywords: ['config', 'fleet.yml'], leftSection: <IconSettings size={18} stroke={1.6} />, onClick: go(to.config(k)),
    }));
    const operations = (ops.data ?? []).map((o) => ({
      id: `op:${o.id}`, label: o.title, description: `${o.id} · ${o.desc}`, keywords: [o.id, o.group, 'run'],
      leftSection: <IconPlayerPlay size={18} stroke={1.6} />,
      rightSection: o.remote_write ? <Badge size="xs" color="yellow" variant="light">can write</Badge> : undefined,
      onClick: () => (o.params.length ? navigate(to.op(o.id)) : void runOp(o.id, {})),
    }));
    return [
      { group: 'Go to', actions: pages },
      { group: 'Run an operation', actions: operations },
      { group: 'Projects', actions: projects },
      { group: 'Loops', actions: loops },
      { group: 'Content sites', actions: sites },
      { group: 'Config', actions: config },
    ];
  }, [state.data, ops.data, navigate, runOp, qc]);

  return (
    <Spotlight
      actions={actions}
      nothingFound="Nothing matches"
      highlightQuery
      limit={40}
      scrollable
      maxHeight={520}
      shortcut={null}
      searchProps={{ leftSection: <IconSearch size={18} />, placeholder: 'Go to a page or project, or run an operation…' }}
    />
  );
}
