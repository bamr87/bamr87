// Every GitHub write the page makes goes through here: say what it will do,
// ask, POST it with confirm=true, then refresh the repo and the action log.
// The server refuses a write without confirm, outside the fleet, or when
// DASH_CONSOLE_GITHUB_WRITES is off — the page asking first is courtesy, the
// server refusing is the guarantee.
import { Text } from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { useQueryClient } from '@tanstack/react-query';
import { post } from '../api/client';
import type { GhAction } from '../api/types';

export type GhActionName =
  | 'issue.create' | 'issue.comment' | 'issue.close' | 'issue.reopen' | 'issue.labels'
  | 'run.rerun_failed' | 'run.cancel' | 'workflow.enable' | 'workflow.disable';

const confirmed = (title: string, what: string, label: string, danger: boolean) =>
  new Promise<boolean>((resolve) =>
    modals.openConfirmModal({
      title,
      children: <Text size="sm">{what}</Text>,
      labels: { confirm: label, cancel: 'Cancel' },
      confirmProps: { color: danger ? 'red' : undefined },
      onConfirm: () => resolve(true),
      onCancel: () => resolve(false),
      onClose: () => resolve(false),
    }));

export interface GhActionAsk {
  title: string;
  /** Plain words: what GitHub will do. */
  what: string;
  label?: string;
  danger?: boolean;
}

/** Returns `act(action, params, ask)` → the logged entry, or null when declined or refused. */
export function useGhAction(nwo: string) {
  const qc = useQueryClient();
  return async (action: GhActionName, params: Record<string, unknown>, ask: GhActionAsk): Promise<GhAction | null> => {
    if (!(await confirmed(ask.title, `${ask.what} (${nwo})`, ask.label ?? 'Do it', ask.danger ?? false))) return null;
    try {
      const entry = await post<GhAction>(`/api/github/repos/${nwo}/actions`, { action, params, confirm: true });
      notifications.show({ color: 'teal', title: entry.label, message: `${nwo} ${entry.target}`.trim() });
      return entry;
    } catch (e) {
      notifications.show({ color: 'red', title: 'GitHub refused', message: (e as Error).message, autoClose: 9000 });
      return null;
    } finally {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['github', 'repo', nwo] }),
        qc.invalidateQueries({ queryKey: ['github', 'issue', nwo] }),
        qc.invalidateQueries({ queryKey: ['github', 'log'] }),
      ]);
    }
  };
}
