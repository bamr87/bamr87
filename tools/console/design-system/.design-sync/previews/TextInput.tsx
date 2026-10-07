import { TextInput } from '@bamr87/harness-console-ui';
export const States = () => (<div style={{display:'grid',gap:8,maxWidth:300}}><TextInput placeholder="owner/repo"/><TextInput defaultValue="bamr87/cv-builder-pro"/><TextInput type="password" defaultValue="secretvalue" aria-label="token"/></div>);
