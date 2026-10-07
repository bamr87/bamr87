import { AppHeader, Chip, Button } from '@bamr87/harness-console-ui';
export const Header = () => (<AppHeader title="🛠️ Harness Console" meta={<><Chip tone="ok">● connected</Chip><span>state read 06:41 UTC</span></>} actions={<><Button>↻ Refresh</Button><Button>◐</Button></>}/>);
