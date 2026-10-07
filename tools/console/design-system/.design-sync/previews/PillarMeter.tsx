import { PillarMeter } from '@bamr87/harness-console-ui';
export const Coverage = () => (<div style={{display:'grid',gap:14,maxWidth:300}}><PillarMeter share={0.22} target={0.4}/><PillarMeter share={0.55} target={0.5}/><PillarMeter share={0.8}/></div>);
