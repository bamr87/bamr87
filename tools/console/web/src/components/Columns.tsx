// The Recharts-backed column chart, loaded lazily by Charts.tsx: Recharts is
// the page's largest dependency after xterm.js and only three pages draw one.
import { BarChart } from '@mantine/charts';
import { Rectangle, type BarProps } from 'recharts';

type Row = Record<string, unknown>;

const SERIES_COLOR = ['var(--series-1)', 'var(--series-2)'];

// Recharts renders each bar through `shape`, handing it the row (`payload`)
// — the one place a per-ROW colour can be decided. A row the caller marked
// critical draws in the critical role; every other bar keeps its series colour.
type BarShape = NonNullable<BarProps['shape']>;
const critShape: BarShape = (props) => {
  const { payload, fill, ...rest } = props as typeof props & { payload?: { __crit?: boolean }; fill?: string };
  return <Rectangle {...rest} fill={payload?.__crit ? 'var(--critical)' : fill} />;
};

export interface ColumnsProps {
  data: Row[];
  dataKey: string;
  series: { name: string; s2?: boolean }[];
  height: number;
  every: number;
  critical: boolean;
  valueFormatter: (v: number) => string;
}

export default function Columns({ data, dataKey, series, height, every, critical, valueFormatter }: ColumnsProps) {
  return (
    <BarChart
      h={height}
      data={data}
      dataKey={dataKey}
      type={series.length > 1 ? 'stacked' : 'default'}
      series={series.map((s, i) => ({ name: s.name, color: SERIES_COLOR[s.s2 ? 1 : Math.min(i, 1)] }))}
      withLegend={series.length > 1}
      legendProps={{ verticalAlign: 'top', height: 24 }}
      valueFormatter={valueFormatter}
      tickLine="none"
      gridAxis="y"
      strokeDasharray="2 4"
      maxBarWidth={28}
      barProps={critical ? { radius: [4, 4, 0, 0], isAnimationActive: false, shape: critShape } : { radius: [4, 4, 0, 0], isAnimationActive: false }}
      xAxisProps={{ interval: every - 1, tickMargin: 6 }}
      // Wide enough for a formatted tick such as "1,400" or "$1.20"; 40 clipped the leading digit.
      yAxisProps={{ width: 56, tickFormatter: (v: number) => valueFormatter(v) }}
      barChartProps={{ margin: { left: 0, right: 8, top: 4, bottom: 0 } }}
    />
  );
}
