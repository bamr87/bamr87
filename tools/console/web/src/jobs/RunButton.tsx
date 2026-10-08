// A button that runs one allowlisted operation, labelled with what it does.
import type { ReactNode } from 'react';
import { Button, Tooltip, type ButtonProps } from '@mantine/core';
import { IconCloudUpload, IconPlayerPlay } from '@tabler/icons-react';
import { useOps } from '../api/hooks';
import { remoteWrite, useRunner } from './JobRunner';

export function RunButton({
  op, params, children, variant = 'default', ...rest
}: { op: string; params?: Record<string, unknown>; children: ReactNode } & Omit<ButtonProps, 'children'>) {
  const { runOp } = useRunner();
  const ops = useOps();
  const meta = ops.data?.find((o) => o.id === op);
  const writes = remoteWrite(meta, params);
  const icon = writes || op === 'dispatch' ? <IconCloudUpload size={15} /> : <IconPlayerPlay size={14} />;
  const button = (
    <Button size="xs" variant={variant} color={writes ? 'red' : undefined} leftSection={icon} onClick={() => void runOp(op, params ?? {})} {...rest}>
      {children}
    </Button>
  );
  return meta?.desc ? <Tooltip label={meta.desc}>{button}</Tooltip> : button;
}
