import { ColumnChart } from '@bamr87/harness-console-ui';
const labels=Array.from({length:30},(_, i)=>'Sep '+(i+1));
const human=labels.map((_, i)=>4+((i*7)%9));
const bot=labels.map((_, i)=>2+((i*5)%6));
export const Single = () => (<ColumnChart labels={labels} series={[{label:'commits',values:human}]}/>);
export const Stacked = () => (<ColumnChart labels={labels} series={[{label:'human',values:human},{label:'bot',values:bot}]}/>);
