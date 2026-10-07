import { Status } from '@bamr87/harness-console-ui';
export const Tones = () => (<div style={{display:'flex',gap:8,flexWrap:'wrap'}}><Status tone="good">in the environment</Status><Status tone="warn">absent</Status><Status tone="crit">P1</Status><Status tone="info">in .env</Status></div>);
