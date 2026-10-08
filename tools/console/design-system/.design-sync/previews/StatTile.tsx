import { StatTile, Meter, CardGrid } from '@bamr87/harness-console-ui';
export const Basic = () => (<div style={{maxWidth:240}}><StatTile label="Spend today" value="$12.40" delta="of $25.00 daily cap"/></div>);
export const WithMeter = () => (<div style={{maxWidth:240}}><StatTile label="Actions minutes" value="1,842" delta="of 2,000 included"><Meter value={1842} max={2000}/></StatTile></div>);
