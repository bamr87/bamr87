// The one way the page writes to GitHub: say what will happen, ask, POST with
// confirm=true (the server refuses a write without it), report, refresh.
import { Anchor, Stack, Text } from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { useQueryClient } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { post } from '../api/client';
import type { GhAction } from '../api/types';

export function useGhAction(nwo: string) {
  const qc = useQueryClient();
  return (action: string, params: Record<string, unknown>, what: ReactNode, opts: { danger?: boolean; skipConfirm?: boolean } = {}) =>
    new Promise<GhAction | null>((resolve) => {
      const run = async () => {
        try {
          const r = await post<GhAction>(`/api/github/repos/${nwo}/actions`, { action, params, confirm: true });
          notifications.show({
            color: 'teal', title: `${r.label} — done`,
            message: r.url ? <Anchor href={r.url} target="_blank" rel="noopener" size="sm">{nwo} {r.target}</Anchor> : `${nwo} ${r.target}`,
          });
          await Promise.all([
            qc.invalidateQueries({ queryKey: ['github', 'repo', nwo] }),
            qc.invalidateQueries({ queryKey: ['github', 'issue', nwo] }),
            qc.invalidateQueries({ queryKey: ['github', 'log'] }),
          ]);
          resolve(r);
        } catch (e) {
          notifications.show({ color: 'red', title: 'GitHub refused', message: (e as Error).message, autoClose: 10000 });
          resolve(null);
        }
      };
      if (opts.skipConfirm) {
        void run();
        return;
      }
      modals.openConfirmModal({
        title: 'This writes to GitHub',
        children: (
          <Stack gap="xs">
            <Text size="sm">{what}</Text>
            <Text size="xs" c="dimmed">On {nwo}, as the account the console is connected as. It is recorded in the action log on the GitHub page.</Text>
          </Stack>
        ),
        labels: { confirm: 'Do it', cancel: 'Cancel' },
        confirmProps: { color: opts.danger ? 'red' : undefined },
        onConfirm: () => void run(),
        onCancel: () => resolve(null),
      });
    });
}
