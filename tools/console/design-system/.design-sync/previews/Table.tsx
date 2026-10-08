import { Table } from '@bamr87/harness-console-ui';
export const Workflows = () => (<Table><thead><tr><th>Workflow</th><th>Repo</th><th className="hc-num">Runs</th><th className="hc-num">Minutes</th></tr></thead><tbody>
<tr><td>fleet-pulse.yml</td><td>bamr87/bamr87</td><td className="hc-num">30</td><td className="hc-num">212</td></tr>
<tr className="hc-flag"><td>issue-pipeline.yml</td><td>bamr87/bamr87</td><td className="hc-num">118</td><td className="hc-num">904</td></tr>
<tr className="hc-bad"><td>deploy.yml</td><td>bamr87/it-journey</td><td className="hc-num">12</td><td className="hc-num">57</td></tr>
<tr className="hc-sel"><td>standard-ci.yml</td><td>bamr87/zer0-mistakes</td><td className="hc-num">64</td><td className="hc-num">310</td></tr></tbody></Table>);
export const Reference = () => (<Table reference><thead><tr><th>Key</th><th>Value</th></tr></thead><tbody><tr><td>schedule.fleet_pulse</td><td>37 6 * * * (daily agent chain, never on the hour)</td></tr><tr><td>budget.local_usd</td><td>{'{"max": 5, "per_call_site": {"doctor": 3, "intake": 1}}'}</td></tr></tbody></Table>);
