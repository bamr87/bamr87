import { Banner } from '@bamr87/harness-console-ui';
export const Info = () => (<Banner>Console is bound to 127.0.0.1:4001 — GitHub-writing operations ask for confirmation.</Banner>);
export const Warn = () => (<Banner tone="warn">No DASH_CONSOLE_TOKEN set — anything that can reach this port can run operations.</Banner>);
export const Crit = () => (<Banner tone="crit">FLEET_TOKEN lacks secrets:write — token-rotation cannot propagate.</Banner>);
