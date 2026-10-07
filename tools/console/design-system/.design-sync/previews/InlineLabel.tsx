import { InlineLabel, TextInput } from '@bamr87/harness-console-ui';
export const Controls = () => (<div style={{display:'flex',gap:16,flexWrap:'wrap'}}><InlineLabel label="dry run"><input type="checkbox" defaultChecked/></InlineLabel><InlineLabel label="limit"><TextInput type="number" defaultValue={5} style={{width:70}}/></InlineLabel></div>);
