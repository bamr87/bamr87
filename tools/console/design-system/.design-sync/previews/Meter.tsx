import { Meter } from '@bamr87/harness-console-ui';
export const Levels = () => (<div style={{display:'grid',gap:14,maxWidth:360}}><div>Under budget — 35%<Meter value={35} max={100}/></div><div>Approaching cap — 78%<Meter value={78} max={100}/></div><div>At cap — 100%<Meter value={100} max={100}/></div></div>);
