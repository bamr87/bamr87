import { Tabs } from '@bamr87/harness-console-ui';
const items=['Overview','Harnesses','Schedules','Costs','Observe','Config','Auth','Jobs'].map(l=>({id:l.toLowerCase(),label:l}));
export const Nav = () => (<Tabs items={items} value="costs"/>);
export const Panes = () => (<Tabs variant="panes" items={[{id:'lake',label:'Lake'},{id:'kibana',label:'Kibana'},{id:'grafana',label:'Grafana'}]} value="kibana"/>);
