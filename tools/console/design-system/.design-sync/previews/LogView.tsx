import { LogView } from '@bamr87/harness-console-ui';
const t = '\x1b[1mdash audit\x1b[0m\n\x1b[32m✓\x1b[0m cv-builder-pro  tier 2 conformant\n\x1b[33m!\x1b[0m it-journey  missing .editorconfig\n\x1b[31m✖\x1b[0m law-ai  no CI workflow\n\x1b[2mdone in 4.2s\x1b[0m';
export const Colours = () => (<LogView text={t}/>);
