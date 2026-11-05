// The parameter form for one allowlisted operation. The server validates every
// value again (regex / range → argv elements, never a shell string); this form
// only makes the valid shapes easy to enter.
import { useEffect, useState } from 'react';
import { Button, Checkbox, Group, NumberInput, Select, Stack, Text, TextInput, Textarea } from '@mantine/core';
import { IconPlayerPlay } from '@tabler/icons-react';
import { useWorkflows } from '../api/hooks';
import type { Op } from '../api/types';
import { DispatchInputs, dispatchFields, inputDefaults } from './DispatchInputs';
import { remoteWrite, useRunner } from './JobRunner';

type Params = Record<string, unknown>;

const BOOL: Record<string, string> = {
  upgrade: 'Upgrade machine seeds',
  apply: 'Apply — write to GitHub (otherwise a dry run)',
  local: "Include this machine's Claude Code sessions",
  dry_run: 'Dry run (preview only)',
  force: 'Force (resend what was already exported / shipped)',
  no_fetch: 'Local checkouts only (no clone / fetch)',
  hub_only: 'Hub only (the weekly rotation fans out)',
  allow_long_lived: 'Allow keys that outlive the lifetime policy',
  rehearse: 'Rehearse — everything up to the model call, $0 (no attempt, no preview)',
};

const DEFAULTS: Params = { days: 14, artifacts: 'claude', dry_run: true, jobs: 'ai', logs: 'ai', workflow: 'fanout', kind: 'loop' };

export function initialParams(op: Op, preset: Params = {}): Params {
  const out: Params = {};
  const steps = op.agent_steps ?? [];
  for (const k of op.params) {
    if (k in preset) out[k] = preset[k];
    else if (k === 'loop' && steps.length) out[k] = steps[0].loop;
    else if (k in DEFAULTS) out[k] = DEFAULTS[k];
    else if (k in BOOL) out[k] = false;
    else out[k] = '';
  }
  // the loop's one local step needs no choosing
  if (op.params.includes('step') && !out.step) {
    const mine = steps.filter((s) => s.loop === out.loop);
    if (mine.length === 1) out.step = mine[0].step;
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
      } else if (v && typeof v === 'object') out.fields = dispatchFields(v as Record<string, string | boolean>);
      continue;
    }
    if (typeof v === 'boolean') out[k] = v;
    else if (v !== '' && v !== null && v !== undefined) out[k] = typeof v === 'number' ? String(v) : v;
  }
  return out;
}

export function OpForm({ op, preset, onStarted }: { op: Op; preset?: Params; onStarted?: (id: string) => void }) {
  const { runOp } = useRunner();
  // The dispatchable workflows and their inputs come from the workflow files
  // (the atlas), never from a list kept here: that list had drifted.
  const atlas = useWorkflows();
  const dispatchable = (atlas.data?.workflows ?? []).filter((w) => w.dispatchable);
  const [values, setValues] = useState<Params>(() => initialParams(op, preset));
  const presetKey = JSON.stringify(preset ?? {});
  // Reset when the operation or the preset's CONTENT changes (not its identity).
  useEffect(() => setValues(initialParams(op, preset)), [op.id, presetKey]);
  const set = (k: string, v: unknown) => setValues((s) => ({ ...s, [k]: v }));
  const params = clean(op, values);
  const writes = remoteWrite(op, params);

  const field = (k: string) => {
    if (k === 'apply' && op.id === 'loop-run') {
      const mine = (op.agent_steps ?? []).filter((s) => s.loop === values.loop);
      const chosen = mine.find((x) => x.step === values.step) ?? (mine.length === 1 ? mine[0] : undefined);
      if (chosen && chosen.can_apply === false) {
        // refused server-side too: this step's filer cannot file yet (bamr87/bamr87#488's publish step)
        return <Checkbox key={k} label={BOOL.apply} checked={false} disabled
          description={`Refused for ${chosen.loop}/${chosen.step}: its filer cannot file yet (#488's publish step). Run the dry run and review .fleet/runs/<run_id>/.`} />;
      }
      return <Checkbox key={k} label={BOOL.apply} checked={Boolean(values[k])} onChange={(e) => set(k, e.currentTarget.checked)} color="red"
        description="Files the reviewed preview through the engine's publish gate — the OPS remote-write path (constitution § 11.8): a GitHub write at tier high behind this console's confirm, the token probed first, never scheduled." />;
    }
    if (k in BOOL) {
      return <Checkbox key={k} label={BOOL[k]} checked={Boolean(values[k])} onChange={(e) => set(k, e.currentTarget.checked)} color={k === 'apply' ? 'red' : undefined} />;
    }
    switch (k) {
      case 'days':
        return <NumberInput key={k} label="Days" min={1} max={90} w={140} value={Number(values[k]) || 14} onChange={(v) => set(k, v)} />;
      case 'run_id':
        return <TextInput key={k} label="Run id" description="An earlier run to publish (tools/dash loop publish): its reviewed preview, read-only without Apply" value={String(values[k] ?? '')} onChange={(e) => set(k, e.currentTarget.value)} />;
      case 'item':
        return <TextInput key={k} label="Item" description="With a run id: the preview's key — owner/repo, or owner/repo:path for the doctor — when the run has several" value={String(values[k] ?? '')} onChange={(e) => set(k, e.currentTarget.value)} />;
      case 'target':
        return <TextInput key={k} label="Target" description={op.id === 'loop-run' ? "One registry name — blank for today's sample (one capped attempt per repo in it); not used with a run id" : 'A submodule / repo / site name — blank for all'} value={String(values[k] ?? '')} onChange={(e) => set(k, e.currentTarget.value)} />;
      case 'loop': {
        const loops = [...new Set((op.agent_steps ?? []).map((s) => s.loop))];
        return <Select key={k} label="Loop" description="A loop whose agent step has a local spec (tools/jev/steps/)" data={loops} value={String(values[k] ?? '')}
          onChange={(v) => { set(k, v ?? ''); const mine = (op.agent_steps ?? []).filter((s) => s.loop === v); set('step', mine.length === 1 ? mine[0].step : ''); }} allowDeselect={false} />;
      }
      case 'step': {
        const mine = (op.agent_steps ?? []).filter((s) => s.loop === values.loop);
        const s = mine.find((x) => x.step === values.step) ?? mine[0];
        return <Select key={k} label="Step" data={mine.map((x) => x.step)} value={String(values[k] ?? '')} onChange={(v) => set(k, v ?? '')} allowDeselect={false}
          description={s ? `${s.model} · ${s.max_turns} turns · $${s.cap_usd} cap per attempt (${s.cost_label})` : 'which agent step'} />;
      }
      case 'artifacts':
        return <TextInput key={k} label="Artifacts" description="Kit artifacts, comma-separated" value={String(values[k] ?? '')} onChange={(e) => set(k, e.currentTarget.value)} />;
      case 'key':
        return <TextInput key={k} label="Key" placeholder="harnesses.budget" value={String(values[k] ?? '')} onChange={(e) => set(k, e.currentTarget.value)} />;
      case 'secret':
        return <TextInput key={k} label="Secret name" description="Blank: every contract secret in .env" value={String(values[k] ?? '')} onChange={(e) => set(k, e.currentTarget.value)} />;
      case 'workflow':
        return <Select key={k} label="Workflow" data={dispatchable.map((w) => ({ value: w.id, label: w.name.toLowerCase() === w.id ? w.id : `${w.id} — ${w.name}` }))} value={String(values[k] ?? '')}
          onChange={(v) => { set(k, v ?? ''); set('fields', {}); }} allowDeselect={false} />;
      case 'kind':
        return <Select key={k} label="Kind" data={Object.entries(atlas.data?.kinds ?? {}).map(([value, d]) => ({ value, label: `${value} — ${d}` }))} value={String(values[k] ?? '')} onChange={(v) => set(k, v ?? '')} allowDeselect={false} />;
      case 'purpose':
        return <Textarea key={k} label="Purpose" description="The header comment: what it is for" autosize minRows={2} value={String(values[k] ?? '')} onChange={(e) => set(k, e.currentTarget.value)} />;
      case 'fields': {
        const wf = dispatchable.find((w) => w.id === values.workflow);
        if (wf) {
          const current = (values[k] && typeof values[k] === 'object' ? values[k] : {}) as Record<string, string | boolean>;
          const shown = inputDefaults(wf.dispatch_inputs, current);
          return (
            <Stack key={k} gap={4}>
              <Text size="sm" fw={500}>Inputs <Text span size="xs" c="dimmed">— declared by {wf.id}.yml</Text></Text>
              <DispatchInputs inputs={wf.dispatch_inputs} values={shown} onChange={(v) => set(k, v)} />
            </Stack>
          );
        }
        return (
          <TextInput key={k} label="Inputs" placeholder="key=value,key=value" description="workflow_dispatch inputs (only the ones that workflow declares are accepted)"
            value={typeof values[k] === 'string' ? (values[k] as string) : Object.entries((values[k] as Record<string, unknown>) ?? {}).map(([a, b]) => `${a}=${String(b)}`).join(',')}
            onChange={(e) => set(k, e.currentTarget.value)} />
        );
      }
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
        <Button leftSection={<IconPlayerPlay size={16} />} color={writes ? 'red' : undefined} disabled={Boolean(op.unavailable)}
          onClick={async () => { const job = await runOp(op.id, params); if (job) onStarted?.(job.id); }}>
          {writes ? (op.confirm === 'spend' ? 'Run — spends Claude budget' : 'Run — writes to GitHub') : 'Run'}
        </Button>
        {op.unavailable ? <Text size="xs" c="dimmed">Not available in this console: {op.unavailable}</Text> : null}
        {op.remote_write && !writes ? <Text size="xs" c="dimmed">Dry run: nothing reaches GitHub.</Text> : null}
      </Group>
    </Stack>
  );
}
