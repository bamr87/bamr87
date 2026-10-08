// keys v1 in the page — the table the terminal dash binds (/api/keys ←
// tools/fleetcore/keys.py). Typing in a field, or any key with ctrl/⌘/alt
// held, is left to the browser; the one exception is ⌘K / ctrl+K, the
// browser-native way to open the same palette ':' opens.
import { useEffect } from 'react';
import { useNavigate } from 'react-router';
import { Group, SimpleGrid, Text } from '@mantine/core';
import { modals } from '@mantine/modals';
import { spotlight } from '@mantine/spotlight';
import { useQueryClient } from '@tanstack/react-query';
import { useKeys } from '../api/hooks';
import { useRunner } from '../jobs/JobRunner';
import { FLAT, NAV, activeIndex } from '../nav';
import { handlerFor } from './keyscope';

function showKeys(keys: { dom: string; label: string; action: string; group: string }[]) {
  const label = (dom: string) => (dom === 'Escape' ? 'esc' : dom);
  modals.open({
    title: 'Keys — the same in the terminal dash',
    size: 'lg',
    children: (
      <SimpleGrid cols={{ base: 1, sm: 2 }} spacing={6} verticalSpacing={6}>
        {keys.filter((k) => !k.action.startsWith('tab:')).map((k) => (
          <Group key={k.action} gap={8} wrap="nowrap">
            <kbd className="k">{label(k.dom)}</kbd>
            <Text size="sm">{k.label}{k.group === 'dash' ? <Text span c="dimmed" size="xs"> (lists)</Text> : null}</Text>
          </Group>
        ))}
        <Group gap={8} wrap="nowrap"><kbd className="k">1</kbd><Text size="sm">… <kbd className="k">{NAV.length}</kbd> go to a section</Text></Group>
        <Group gap={8} wrap="nowrap"><kbd className="k">enter</kbd><Text size="sm">Open the selected row</Text></Group>
        <Group gap={8} wrap="nowrap"><kbd className="k">⌘K</kbd><Text size="sm">Search and commands</Text></Group>
      </SimpleGrid>
    ),
  });
}

export function GlobalKeys() {
  const keys = useKeys();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { runOp } = useRunner();

  useEffect(() => {
    const table = keys.data ?? [];
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        spotlight.toggle();
        return;
      }
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      const typing = Boolean(t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)));
      // A dialog, drawer or the palette owns the keyboard while it is open.
      if (document.querySelector('[role="dialog"]')) return;
      // The terminal page hands every key to the TUI.
      if (t?.closest('.xterm')) return;
      if (typing) {
        if (e.key === 'Escape') t?.blur();
        return;
      }
      if (e.key === 'Enter') {
        const act = handlerFor('activate');
        if (act) {
          act();
          e.preventDefault();
        }
        return;
      }
      const k = table.find((x) => x.dom === e.key);
      if (!k) return;
      const nav = (i: number) => navigate(FLAT[(i + FLAT.length) % FLAT.length].to);
      const scroll = (y: number) => window.scrollBy({ top: y, behavior: 'smooth' });
      const map: Record<string, () => void> = {
        help: () => showKeys(table),
        palette: () => spotlight.open(),
        search: () => {
          const f = document.querySelector<HTMLInputElement>('[data-page-search]');
          if (f) f.focus();
          else spotlight.open();
        },
        back: () => {
          if (handlerFor('back')?.()) return;
          if (window.history.length > 1) navigate(-1);
        },
        down: () => (handlerFor('move') ?? (() => scroll(120)))(1),
        up: () => (handlerFor('move') ?? (() => scroll(-120)))(-1),
        top: () => (handlerFor('edge') ?? (() => window.scrollTo({ top: 0 })))(0),
        bottom: () => (handlerFor('edge') ?? (() => window.scrollTo({ top: document.body.scrollHeight })))(1),
        next_tab: () => nav(activeIndex(window.location.pathname) + 1),
        prev_tab: () => nav(activeIndex(window.location.pathname) - 1),
        refresh: () => void qc.invalidateQueries(),
        refresh_full: () => void runOp('health', {}),
        open: () => handlerFor('open')?.(),
        open_live: () => handlerFor('openLive')?.(),
        copy: () => handlerFor('copy')?.(),
        sort: () => handlerFor('sort')?.(),
      };
      if (k.action.startsWith('tab:')) {
        const section = NAV[Number(k.action.slice(4)) - 1];
        if (section) {
          navigate(section.items[0].to);
          e.preventDefault();
        }
        return;
      }
      const fn = map[k.action];
      if (fn) {
        fn();
        e.preventDefault();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [keys.data, navigate, qc, runOp]);

  return null;
}
