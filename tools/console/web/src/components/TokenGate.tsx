// The console-token prompt. Mounted once; the API client calls it (once,
// however many requests got a 401) through registerTokenAsker.
import { useEffect, useRef, useState } from 'react';
import { Button, Code, Group, Modal, PasswordInput, Stack, Text } from '@mantine/core';
import { registerTokenAsker } from '../api/client';
import { Status } from './ui';

export function TokenGate() {
  const [open, setOpen] = useState(false);
  const [rejected, setRejected] = useState(false);
  const [value, setValue] = useState('');
  const resolver = useRef<((v: string | null) => void) | null>(null);

  useEffect(() => {
    registerTokenAsker((wasRejected) => new Promise((resolve) => {
      resolver.current = resolve;
      setRejected(wasRejected);
      setValue('');
      setOpen(true);
    }));
    return () => registerTokenAsker(null);
  }, []);

  const done = (v: string | null) => {
    setOpen(false);
    resolver.current?.(v);
    resolver.current = null;
  };

  return (
    <Modal opened={open} onClose={() => done(null)} title="Console token" centered closeOnClickOutside={false}>
      <form onSubmit={(e) => { e.preventDefault(); done(value); }}>
        <Stack gap="sm">
          <Text size="sm">This console requires its bearer token: the <Code>DASH_CONSOLE_TOKEN</Code> it was started with (the hub's <Code>.env</Code>, or the shell that ran <Code>docker compose</Code>).</Text>
          {rejected ? <Status tone="crit">That token was rejected — it does not match the one this console runs with.</Status> : null}
          <PasswordInput data-autofocus value={value} onChange={(e) => setValue(e.currentTarget.value)} aria-label="console token" autoComplete="off" spellCheck={false} />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => done(null)}>Cancel</Button>
            <Button type="submit">Unlock</Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
