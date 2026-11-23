// The radar as a map: every repo a dot, placed by how close it is to the fleet (x, the tf-idf similarity
// to its closest fleet project, 0–100) and how popular it is (y, stars on a log scale), coloured by
// category. Upper right is popular AND relevant: the first place to look. Lazy-loaded like Columns.tsx,
// so recharts stays out of the page's first script. A dot is a button: it opens the repo's drawer.
import { CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from 'recharts';
import type { StarRepo } from '../api/types';

export interface StarMapProps {
  repos: StarRepo[];
  categories: { id: string; title: string }[];
  onPick: (name: string) => void;
  height?: number;
}

// Categorical palette (Mantine's filled colours), one per category in taxonomy order.
const PALETTE = ['blue', 'grape', 'teal', 'orange', 'cyan', 'lime', 'red', 'indigo', 'yellow', 'pink', 'violet', 'gray'];
const color = (i: number) => `var(--mantine-color-${PALETTE[i % PALETTE.length]}-filled)`;

interface Point { x: number; y: number; z: number; name: string; stars: number; project: string; verdict: string }

function Tip({ active, payload }: { active?: boolean; payload?: { payload: Point }[] }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div style={{ background: 'var(--mantine-color-body)', border: '1px solid var(--mantine-color-default-border)', padding: '6px 8px', fontSize: 12 }}>
      <b>{p.name}</b>
      <div>★ {p.stars.toLocaleString()} · like {p.project || '—'} ({p.x})</div>
      {p.verdict ? <div>AI: {p.verdict}</div> : null}
    </div>
  );
}

export default function StarMap({ repos, categories, onPick, height = 420 }: StarMapProps) {
  const series = categories
    .map((c, i) => ({
      id: c.id,
      title: c.title,
      fill: color(i),
      points: repos
        // every starred repo (one like no fleet project sits at x = 0), and any other repo like a fleet project
        .filter((r) => r.category === c.id && (r.matches?.length || r.starred_at) && !r.suspect?.length)
        .map<Point>((r) => ({
          x: Math.round((r.matches?.[0]?.score ?? 0) * 100),
          y: Math.round(Math.log10(Math.max(1, r.stars)) * 100) / 100,
          z: Math.max(1, r.velocity?.d7 ?? r.velocity?.per_day ?? 1),
          name: r.name,
          stars: r.stars,
          project: r.matches?.[0]?.project ?? '',
          verdict: r.ai?.verdict ?? '',
        })),
    }))
    .filter((s) => s.points.length);
  return (
    <div role="figure" aria-label="Repos by similarity to the fleet and by stars, coloured by category">
      <ResponsiveContainer width="100%" height={height}>
        <ScatterChart margin={{ top: 8, right: 16, bottom: 28, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--mantine-color-default-border)" />
          <XAxis type="number" dataKey="x" name="similarity" domain={[0, 'dataMax']} tick={{ fontSize: 11 }}
            label={{ value: 'similarity to the closest fleet project (0–100)', position: 'insideBottom', offset: -16, fontSize: 11 }} />
          <YAxis type="number" dataKey="y" name="stars" domain={['dataMin', 'dataMax']} tick={{ fontSize: 11 }} width={48}
            tickFormatter={(v: number) => (10 ** v >= 1000 ? `${Math.round(10 ** v / 1000)}k` : String(Math.round(10 ** v)))} />
          <ZAxis type="number" dataKey="z" range={[30, 260]} />
          <Tooltip content={<Tip />} cursor={{ strokeDasharray: '3 3' }} />
          {series.map((s) => (
            <Scatter key={s.id} name={s.title} data={s.points} fill={s.fill} fillOpacity={0.75}
              onClick={(d: unknown) => {
                const name = (d as { payload?: Point; name?: string })?.payload?.name ?? (d as { name?: string })?.name;
                if (name) onPick(name);
              }} style={{ cursor: 'pointer' }} />
          ))}
        </ScatterChart>
      </ResponsiveContainer>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 12px', fontSize: 12 }}>
        {series.map((s) => (
          <span key={s.id}><span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 5, background: s.fill, marginRight: 4 }} />{s.title} ({s.points.length})</span>
        ))}
      </div>
    </div>
  );
}
