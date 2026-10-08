// The parameter form for one allowlisted operation. The server validates every
// value again (regex / range → argv elements, never a shell string); this form
// only makes the valid shapes easy to enter.
import { useEffect, useState } from 'react';
import { Button, Checkbox, Group, NumberInput, Select, Stack, Text, TextInput } from '@mantine/core';
import { IconPlayerPlay } from '@tabler/icons-react';
import type { Op } from '../api/types';
import { remoteWrite, useRunner } from './JobRunner';

type Params = Record<string, unknown>;

const WORKFLOWS = ['harness-fanout', 'fleet-pulse', 'issue-pipeline', 'token-rotation', 'repo-evolution', 'standardize-fanout',
  'schema-fanout', 'build-dash', 'reconcile-registry', 'refresh-dash', 'update-submodules'];

const BOOL: Record<string, string> = {
  upgrade: 'Upgrade machine seeds',
  apply: 'Apply — write to GitHub (otherwise a dry run)',
  local: "Include this machine's Claude Code sessions",
  dry_run: 'Dry run (preview only)',
  force: 'Force (resend what was already exported / shipped)',
  no_fetch: 'Local checkouts only (no clone / fetch)',
  hub_only: 'Hub only (the weekly rotation fans out)',
  allow_long_lived: 'Allow keys that outlive the lifetime policy',
};

const DEFAULTS: Params = { days: 14, artifacts: 'claude', dry_run: true, jobs: 'ai', logs: 'ai', workflow: 'harness-fanout' };

export function initialParams(op: Op, preset: Params = {}): Params {
  const out: Params = {};
  for (const k of op.params) {
    if (k in preset) out[k] = preset[k];
    else if (k in DEFAULTS) out[k] = DEFAULTS[k];
    else if (k in BOOL) out[k] = false;
    else out[k] = '';
  }
  return out;
}

function clean(op: Op, values: Params): Params {
  const out: Params = {};
  for (const k of op.params) {
    const v = values[k];
    if (k === 'fields') {
      if (typeof v === 'string' && v.trim()) {
        const f: Record<string, string> = {};
        v.split(',').forEach((kv) => {
          const [key, ...rest] = kv.split('=');
          if (key.trim()) f[key.trim()] = rest.join('=').trim();
        });
        out.fields = f;
      } else if (v && typeof v === 'object') out.fields = v;
      continue;
    }
    if (typeof v === 'boolean') out[k] = v;
    else if (v !== '' && v !== null && v !== undefined) out[k] = typeof v === 'number' ? String(v) : v;
  }
  return out;
}

export function OpForm({ op, preset, onStarted }: { op: Op; preset?: Params; onStarted?: (id: string) => void }) {
  const { runOp } = useRunner();
  const [values, setValues] = useState<Params>(() => initialParams(op, preset));
  const presetKey = JSON.stringify(preset ?? {});
  // Reset when the operation or the preset's CONTENT changes (not its identity).
  useEffect(() => setValues(initialParams(op, preset)), [op.id, presetKey]);
  const set = (k: string, v: unknown) => setValues((s) => ({ ...s, [k]: v }));
  const params = clean(op, values);
  const writes = remoteWrite(op, params);

  const field = (k: string) => {
    if (k in BOOL) {
      return <Checkbox key={k} label={BOOL[k]} checked={Boolean(values[k])} onChange={(e) => set(k, e.currentTarget.checked)} color={k === 'apply' ? 'red' : undefined} />;
    }
    switch (k) {
      case 'days':
        return <NumberInput key={k} label="Days" min={1} max={90} w={140} value={Number(values[k]) || 14} onChange={(v) => set(k, v)} />;
      case 'target':
        return <TextInput key={k} label="Target" description="A submodule / repo / site name — blank for all" value={String(values[k] ?? '')} onChange={(e) => set(k, e.currentTarget.value)} />;
      case 'artifacts':
        return <TextInput key={k} label="Artifacts" description="Kit artifacts, comma-separated" value={String(values[k] ?? '')} onChange={(e) => set(k, e.currentTarget.value)} />;
      case 'key':
        return <TextInput key={k} label="Key" placeholder="harnesses.budget" value={String(values[k] ?? '')} onChange={(e) => set(k, e.currentTarget.value)} />;
      case 'secret':
        return <TextInput key={k} label="Secret name" description="Blank: every contract secret in .env" value={String(values[k] ?? '')} onChange={(e) => set(k, e.currentTarget.value)} />;
      case 'workflow':
        return <Select key={k} label="Workflow" data={WORKFLOWS} value={String(values[k] ?? '')} onChange={(v) => set(k, v ?? '')} allowDeselect={false} />;
      case 'fields':
        return (
          <TextInput key={k} label="Inputs" placeholder="key=value,key=value" description="workflow_dispatch inputs (only the ones that workflow declares are accepted)"
            value={typeof values[k] === 'string' ? (values[k] as string) : Object.entries((values[k] as Record<string, unknown>) ?? {}).map(([a, b]) => `${a}=${String(b)}`).join(',')}
            onChange={(e) => set(k, e.currentTarget.value)} />
        );
      case 'jobs':
      case 'logs':
        return <Select key={k} label={k === 'jobs' ? 'Jobs + steps for' : 'Logs for'} w={200} data={['ai', 'all', 'none']} value={String(values[k] ?? 'ai')} onChange={(v) => set(k, v ?? 'ai')} allowDeselect={false} />;
      default:
        return <TextInput key={k} label={k} value={String(values[k] ?? '')} onChange={(e) => set(k, e.currentTarget.value)} />;
    }
  };

  return (
    <Stack gap="sm">
      {op.params.length ? op.params.map(field) : <Text size="sm" c="dimmed">This operation takes no parameters.</Text>}
      <Group gap="sm" mt="xs">
        <Button leftSection={<IconPlayerPlay size={16} />} color={writes ? 'red' : undefined}
          onClick={async () => { const job = await runOp(op.id, params); if (job) onStarted?.(job.id); }}>
          {writes ? 'Run — writes to GitHub' : 'Run'}
        </Button>
        {op.remote_write && !writes ? <Text size="xs" c="dimmed">Dry run: nothing reaches GitHub.</Text> : null}
      </Group>
    </Stack>
  );
}
