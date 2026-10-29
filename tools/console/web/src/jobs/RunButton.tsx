// A button that runs one allowlisted operation, labelled with what it does.
import type { ReactNode } from 'react';
import { Button, Tooltip, type ButtonProps } from '@mantine/core';
import { IconCloudUpload, IconPlayerPlay } from '@tabler/icons-react';
import { useOps } from '../api/hooks';
import { remoteWrite, useRunner } from './JobRunner';
import u from '../styles/utils.module.css';

export function RunButton({
  op, params, children, variant = 'default', ...rest
}: { op: string; params?: Record<string, unknown>; children: ReactNode } & Omit<ButtonProps, 'children'>) {
  const { runOp } = useRunner();
  const ops = useOps();
  const meta = ops.data?.find((o) => o.id === op);
  const writes = remoteWrite(meta, params);
  const icon = writes || op === 'dispatch' ? <IconCloudUpload size={15} /> : <IconPlayerPlay size={14} />;
  // An op this console cannot run at all (no Docker in its container) is shown
  // disabled with the reason — it used to start, and fail, every time.
  const blocked = meta?.unavailable ?? null;
  const button = (
    <Button size="xs" variant={variant} color={writes ? 'red' : undefined} leftSection={icon} disabled={Boolean(blocked)}
      onClick={() => void runOp(op, params ?? {})} {...rest}>
      {children}
    </Button>
  );
  const label = blocked ?? meta?.desc;
  // A disabled button fires no pointer events, so the tooltip wraps a span.
  return label ? <Tooltip label={label} multiline maw={360}><span className={u.inlineBlock}>{button}</span></Tooltip> : button;
}
