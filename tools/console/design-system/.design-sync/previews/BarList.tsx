import { BarList } from '@bamr87/harness-console-ui';
export const Topics = () => (<BarList rows={[{label:'bash',value:42},{label:'jekyll',value:31},{label:'docker',value:18},{label:'github-actions',value:9}]}/>);
export const Empty = () => (<BarList rows={[]}/>);
