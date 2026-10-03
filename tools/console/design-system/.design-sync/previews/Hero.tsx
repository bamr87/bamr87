import { Hero, Status } from '@bamr87/harness-console-ui';
export const Score = () => (<Hero value="87" label="Harness health (6 layers)"><div style={{display:'flex',gap:8,flexWrap:'wrap'}}><Status tone="good">context</Status><Status tone="good">tools</Status><Status tone="warn">memory</Status><Status tone="crit">budget trip wire</Status></div></Hero>);
