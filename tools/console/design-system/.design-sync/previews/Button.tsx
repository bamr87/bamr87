import { Button, Toolbar } from '@bamr87/harness-console-ui';
export const Variants = () => (<Toolbar><Button>↻ Refresh</Button><Button variant="primary">Run daily pulse</Button><Button variant="danger">Rotate from .env</Button></Toolbar>);
export const Disabled = () => (<Toolbar><Button disabled>Dispatch workflow</Button><Button variant="primary" disabled>Apply</Button></Toolbar>);
