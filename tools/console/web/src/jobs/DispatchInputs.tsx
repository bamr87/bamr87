// A workflow's own `workflow_dispatch.inputs` (read from the file by the
// workflow atlas) as form fields: a boolean is a checkbox, a choice a select,
// the rest text with the declared default as its placeholder. The dispatch
// page of a workflow and the generic operation form both use it, so neither
// keeps a list of what a workflow accepts.
import { Checkbox, Select, Stack, Text, TextInput } from '@mantine/core';
import type { WfInput } from '../api/types';

export type Fields = Record<string, string | boolean>;

/** Each input's starting value: its declared default (booleans as booleans). */
export function inputDefaults(inputs: WfInput[], preset: Fields = {}): Fields {
  const out: Fields = {};
  for (const i of inputs) {
    if (i.name in preset) out[i.name] = preset[i.name];
    else if (i.type === 'boolean') out[i.name] = i.default === true || String(i.default) === 'true';
    else out[i.name] = i.default == null ? '' : String(i.default);
  }
  return out;
}

/** The workflow's own `workflow_dispatch.inputs` as form fields. */
export function DispatchInputs({ inputs, values, onChange }: { inputs: WfInput[]; values: Fields; onChange: (v: Fields) => void }) {
  const set = (k: string, v: string | boolean) => onChange({ ...values, [k]: v });
  if (!inputs.length) return <Text size="sm" c="dimmed">This workflow declares no inputs.</Text>;
  return (
    <Stack gap="xs">
      {inputs.map((i) => {
        const label = <>{i.name} <Text span size="xs" c="dimmed">{i.type}</Text></>;
        if (i.type === 'boolean') {
          return <Checkbox key={i.name} label={<>{label} <Text span size="xs" c="dimmed">— {i.description}</Text></>} checked={Boolean(values[i.name])} onChange={(e) => set(i.name, e.currentTarget.checked)} color={/apply|force/.test(i.name) ? 'red' : undefined} />;
        }
        if (i.type === 'choice' && i.options.length) {
          return <Select key={i.name} label={label} description={i.description} data={i.options} value={String(values[i.name] ?? '')} onChange={(v) => set(i.name, v ?? '')} allowDeselect={false} />;
        }
        return <TextInput key={i.name} label={label} description={i.description} placeholder={i.default == null ? '' : String(i.default)} value={String(values[i.name] ?? '')} onChange={(e) => set(i.name, e.currentTarget.value)} />;
      })}
    </Stack>
  );
}

/** Only what differs from blank: an empty text input is left to the workflow's default. */
export function dispatchFields(values: Fields): Record<string, string | boolean> {
  return Object.fromEntries(Object.entries(values).filter(([, v]) => typeof v === 'boolean' || v.trim() !== ''));
}
