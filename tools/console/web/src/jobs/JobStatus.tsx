import { Loader } from '@mantine/core';
import { Status } from '../components/ui';

export function JobStatus({ status }: { status: string }) {
  if (status === 'succeeded') return <Status tone="good">succeeded</Status>;
  if (status === 'failed') return <Status tone="crit">failed</Status>;
  if (status === 'cancelled') return <Status tone="warn">cancelled</Status>;
  if (status === 'running') {
    return (
      <span className="st"><Loader size={10} />running</span>
    );
  }
  return <Status tone="info">{status}</Status>;
}
