// The small pieces every page is built from. Status is always icon + label
// (never colour alone); every repo name, operation and source links somewhere.
import type { ReactNode } from 'react';
import { Link } from 'react-router';
import {
  Alert, Anchor, Box, Breadcrumbs, Group, Loader, Paper, Skeleton, Stack, Text, Title, Tooltip,
} from '@mantine/core';
import { IconAlertTriangle, IconExternalLink, IconInfoCircle } from '@tabler/icons-react';
import type { UseQueryResult } from '@tanstack/react-query';
import type { Level } from '../api/types';
import { to } from '../lib/links';
import { repoName } from '../lib/format';

export type Tone = 'good' | 'warn' | 'crit' | 'info';
const GLYPH: Record<Tone, string> = { good: '✓', warn: '⚠', crit: '✖', info: '●' };

export function Status({ tone, children, title }: { tone: Tone; children: ReactNode; title?: string }) {
  const pill = (
    <span className={`st ${tone === 'info' ? '' : tone}`}>
      <span aria-hidden>{GLYPH[tone]}</span>
      {children}
    </span>
  );
  return title ? <Tooltip label={title}>{pill}</Tooltip> : pill;
}

/** A run/workflow conclusion as a status pill. */
export function Conclusion({ value }: { value?: string | null }) {
  if (value === 'success') return <Status tone="good">success</Status>;
  if (value === 'failure' || value === 'timed_out' || value === 'startup_failure') return <Status tone="crit">{value}</Status>;
  if (value === 'cancelled') return <Status tone="warn">cancelled</Status>;
  return <Text span c="dimmed" size="sm">{value || '—'}</Text>;
}

export function LevelDot({ level, label }: { level?: Level | null; label?: ReactNode }) {
  if (!level) return <Text span c="dimmed">·</Text>;
  return (
    <span className={`lvl-${level}`} title={level}>
      ● {label !== undefined ? <Text span size="sm" c="var(--ink)">{label}</Text> : null}
      <span style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)' }}>{level}</span>
    </span>
  );
}

export const severityTone = (ratio: number): Tone => (ratio >= 1 ? 'crit' : ratio >= 0.7 ? 'warn' : 'info');

export function Meter({ value, cap, tone }: { value: number; cap: number; tone?: Tone }) {
  const ratio = cap ? value / cap : 0;
  const t = tone ?? severityTone(ratio);
  return (
    <div className={`meter ${t === 'info' ? '' : t}`} role="meter" aria-valuenow={value} aria-valuemax={cap}>
      <i style={{ width: `${Math.min(100, Math.max(0, 100 * ratio))}%` }} />
    </div>
  );
}

export function StatTile({
  label, value, sub, meter, href, tone,
}: { label: ReactNode; value: ReactNode; sub?: ReactNode; meter?: ReactNode; href?: string; tone?: Tone }) {
  const body = (
    <Stack gap={4}>
      <Text size="sm" c="dimmed">{label}</Text>
      <Group gap={8} align="baseline">
        <Text fz={26} fw={600} lh={1.1} c={tone === 'crit' ? 'var(--critical)' : undefined}>{value}</Text>
      </Group>
      {meter}
      {sub ? <Text size="xs" c="dimmed">{sub}</Text> : null}
    </Stack>
  );
  return href ? (
    <Paper p="md" component={Link} to={href} style={{ textDecoration: 'none', color: 'inherit' }} className="tile-link">
      {body}
    </Paper>
  ) : (
    <Paper p="md">{body}</Paper>
  );
}

export interface Crumb {
  label: ReactNode;
  to?: string;
}

export function PageHeader({
  title, description, crumbs, actions, badges,
}: { title: ReactNode; description?: ReactNode; crumbs?: Crumb[]; actions?: ReactNode; badges?: ReactNode }) {
  return (
    <Stack gap={6} mb="lg">
      {crumbs?.length ? (
        <Breadcrumbs separatorMargin={6} fz="sm">
          {crumbs.map((c, i) =>
            c.to ? <Anchor key={i} component={Link} to={c.to} size="sm">{c.label}</Anchor> : <Text key={i} size="sm" c="dimmed">{c.label}</Text>,
          )}
        </Breadcrumbs>
      ) : null}
      <Group justify="space-between" align="flex-start" wrap="wrap" gap="sm">
        <Group gap="sm" align="center" wrap="wrap">
          <Title order={2} fz={22}>{title}</Title>
          {badges}
        </Group>
        {actions ? <Group gap="xs" wrap="wrap">{actions}</Group> : null}
      </Group>
      {description ? <Text size="sm" c="dimmed" maw={900}>{description}</Text> : null}
    </Stack>
  );
}

export function Section({
  title, description, actions, children, mt = 'xl',
}: { title: ReactNode; description?: ReactNode; actions?: ReactNode; children: ReactNode; mt?: string | number }) {
  return (
    <Box mt={mt}>
      <Group justify="space-between" align="flex-end" mb={description ? 4 : 8} wrap="wrap" gap="xs">
        <Title order={3} fz={15}>{title}</Title>
        {actions ? <Group gap="xs" wrap="wrap">{actions}</Group> : null}
      </Group>
      {description ? <Text size="sm" c="dimmed" mb="sm" maw={900}>{description}</Text> : null}
      {children}
    </Box>
  );
}

export function Banner({ tone, children, title }: { tone: Tone; children: ReactNode; title?: ReactNode }) {
  const color = tone === 'crit' ? 'red' : tone === 'warn' ? 'yellow' : tone === 'good' ? 'teal' : 'gray';
  const icon = tone === 'info' || tone === 'good' ? <IconInfoCircle size={18} /> : <IconAlertTriangle size={18} />;
  return (
    <Alert color={color} variant="light" icon={icon} title={title} my="sm" styles={{ message: { color: 'var(--ink)' } }}>
      {children}
    </Alert>
  );
}

export function External({ href, children, size }: { href?: string | null; children: ReactNode; size?: string }) {
  if (!href) return <>{children}</>;
  return (
    <Anchor href={href} target="_blank" rel="noopener noreferrer" size={size} inline>
      {children}
      <IconExternalLink size={12} style={{ marginLeft: 3, verticalAlign: -1 }} />
    </Anchor>
  );
}

/** A registry project name (or an owner/name) → its drill-down page. */
export function RepoLink({ name, nwo }: { name?: string | null; nwo?: string | null }) {
  const n = name || repoName(nwo);
  if (!n) return <Text span c="dimmed">fleet</Text>;
  return (
    <Anchor component={Link} to={to.project(n)} ff="monospace" fz="sm">
      {nwo && nwo !== n ? nwo : n}
    </Anchor>
  );
}

export function Mono({ children, dim }: { children: ReactNode; dim?: boolean }) {
  return <Text span ff="monospace" fz={12.5} c={dim ? 'dimmed' : undefined} style={{ overflowWrap: 'anywhere' }}>{children}</Text>;
}

/** Loading / error states for one query; renders children only with data. */
export function Load<T>({ q, children, rows = 4 }: { q: UseQueryResult<T>; children: (data: T) => ReactNode; rows?: number }) {
  if (q.isError) return <Banner tone="crit" title="Could not load">{(q.error as Error).message}</Banner>;
  if (q.data === undefined) {
    return (
      <Stack gap="xs">
        {Array.from({ length: rows }, (_, i) => <Skeleton key={i} h={28} />)}
      </Stack>
    );
  }
  return <>{children(q.data)}</>;
}

export function Spinner({ label }: { label?: string }) {
  return (
    <Group gap="xs"><Loader size="xs" /><Text size="sm" c="dimmed">{label ?? 'loading…'}</Text></Group>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <Text size="sm" c="dimmed" py="sm">{children}</Text>;
}
