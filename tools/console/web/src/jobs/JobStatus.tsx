import { Loader } from '@mantine/core';
import { Status } from '../components/ui';

export function JobStatus({ status }: { status: string }) {
  if (status === 'succeeded') return <Status tone="good">succeeded</Status>;
  if (status === 'failed') return <Status tone="crit">failed</Status>;
  if (status === 'cancelled') return <Status tone="warn">cancelled</Status>;
  // The console restarted while this job ran; nothing finished it.
  if (status === 'interrupted') return <Status tone="warn" title="the console restarted while this job ran">interrupted</Status>;
  if (status === 'running') {
    return (
      <span className="st"><Loader size={10} />running</span>
    );
  }
  return <Status tone="info">{status}</Status>;
}
