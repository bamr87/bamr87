// The sidebar: nine sections that fold, so the page you are on is always in
// view however long the console's list of pages grows. The section holding the
// current page opens itself; the rest stay as you left them. A number beside a
// page is live — what needs attention there — and a folded section sums its own.
import { useEffect, useId, useState } from 'react';
import { Link } from 'react-router';
import { Badge, Box, Collapse, Group, NavLink, Text, UnstyledButton, VisuallyHidden } from '@mantine/core';
import { IconChevronRight } from '@tabler/icons-react';
import { useJobs, useStateDoc } from '../api/hooks';
import { readPref, writePref } from '../lib/prefs';
import { FLAT, NAV, type NavItem, type NavSection } from '../nav';
import { to } from '../lib/links';
import { toneColor, type Tone } from '../theme';
import u from '../styles/utils.module.css';
import classes from './ShellNav.module.css';

const OPEN_KEY = 'console_nav_open';

interface Count { n: number; tone: Tone; says: string }

/** What needs attention, per page, from the documents the shell already holds. */
function useCounts(): Record<string, Count> {
  const state = useStateDoc();
  const jobs = useJobs();
  const out: Record<string, Count> = {};
  const add = (path: string, n: number, tone: Tone, says: string) => {
    if (n > 0) out[path] = { n, tone, says };
  };
  const attention = state.data?.harnesses?.totals?.attention ?? state.data?.harnesses?.attention?.length ?? 0;
  add(to.overview(), Number(attention), 'warn', 'attention items');
  add(to.inbox(), state.data?.triage?.inbox_total ?? state.data?.triage?.inbox?.length ?? 0, 'warn', 'flagged items');
  add(to.health(), (state.data?.health?.trip_wires ?? []).filter((w) => w.tripped).length, 'crit', 'trip wires tripped');
  add(to.jobs(), (jobs.data ?? []).filter((j) => j.status === 'running' || j.status === 'queued').length, 'info', 'jobs running');
  return out;
}

function CountBadge({ count }: { count: Count }) {
  return (
    <Badge size="xs" variant="light" c="var(--ink)" color={count.tone === 'info' ? 'var(--accent)' : toneColor[count.tone]}>
      {count.n}<VisuallyHidden> {count.says}</VisuallyHidden>
    </Badge>
  );
}

function Item({ item, active, count, keyHint }: { item: NavItem; active: boolean; count?: Count; keyHint?: number }) {
  const Ico = item.icon;
  return (
    <NavLink component={Link} to={item.to} label={item.label} active={active} aria-current={active ? 'page' : undefined}
      leftSection={<Ico size={17} stroke={1.6} />} title={item.hint}
      rightSection={count || keyHint ? (
        <Group gap={6} wrap="nowrap">
          {count ? <CountBadge count={count} /> : null}
          {keyHint ? <Text size="xs" c="dimmed" ff="monospace">{keyHint}</Text> : null}
        </Group>
      ) : undefined} />
  );
}

function Section({ section, index, open, onToggle, activeItem, counts }: {
  section: NavSection; index: number; open: boolean; onToggle: () => void; activeItem?: NavItem; counts: Record<string, Count>;
}) {
  const id = useId();
  const inside = section.items.map((it) => counts[it.to]).filter((c): c is Count => Boolean(c));
  const sum = inside.reduce((n, c) => n + c.n, 0);
  return (
    <Box mb={2}>
      <UnstyledButton className={classes.section} onClick={onToggle} aria-expanded={open} aria-controls={id}>
        <IconChevronRight size={13} className={classes.chevron} />
        <Text size="xs" fw={700} tt="uppercase" lts={0.6} span>{section.label}</Text>
        <Box className={u.flexFill} />
        {!open && sum ? <CountBadge count={{ n: sum, tone: inside[0].tone, says: `in ${section.label}` }} /> : null}
        <Text size="xs" ff="monospace" span>{index + 1}</Text>
      </UnstyledButton>
      <Collapse expanded={open} transitionDuration={120} id={id}>
        {section.items.map((item) => <Item key={item.to} item={item} active={item === activeItem} count={counts[item.to]} />)}
      </Collapse>
    </Box>
  );
}

export function ShellNav({ active }: { active: number }) {
  const counts = useCounts();
  const activeItem = FLAT[active];
  const home = NAV.find((s) => activeItem && s.items.includes(activeItem))?.label;
  const [open, setOpen] = useState<string[]>(() => {
    const saved = readPref<string[]>(OPEN_KEY, []);
    return home && !saved.includes(home) ? [...saved, home] : saved;
  });
  const save = (next: string[]) => {
    setOpen(next);
    writePref(OPEN_KEY, next);
  };
  // Arriving in a folded section opens it. Folding the current section by hand
  // stays folded: this runs when the section changes, not when `open` does.
  useEffect(() => {
    if (home) setOpen((now) => {
      if (now.includes(home)) return now;
      const next = [...now, home];
      writePref(OPEN_KEY, next);
      return next;
    });
  }, [home]);
  // Bring the current page into view, after its section has finished unfolding.
  useEffect(() => {
    const t = window.setTimeout(() => document.querySelector('nav a[aria-current="page"]')?.scrollIntoView({ block: 'nearest' }), 160);
    return () => window.clearTimeout(t);
  }, [active]);

  return (
    <>
      {NAV.map((section, si) => (
        // A section of one page is that page: there is nothing to fold.
        section.items.length === 1 ? (
          <Box key={section.label} mb={2}>
            <Item item={section.items[0]} active={section.items[0] === activeItem} count={counts[section.items[0].to]} keyHint={si + 1} />
          </Box>
        ) : (
          <Section key={section.label} section={section} index={si} open={open.includes(section.label)} activeItem={activeItem} counts={counts}
            onToggle={() => save(open.includes(section.label) ? open.filter((l) => l !== section.label) : [...open, section.label])} />
        )
      ))}
    </>
  );
}
