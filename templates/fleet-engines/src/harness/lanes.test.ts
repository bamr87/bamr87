// The fleet/v1 parser: tolerant over real manifests (gitorio's derived one, irony-works'
// hand-declared one), silent over junk, and the path → lane pin. The blueprint → lanes
// direction and its parity test stay with GitFactory's compiler.

import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { LANE_HARNESSES, laneForPath, parseFleetManifest } from './lanes.js';
import { toFleetManifestYaml } from './manifest-yaml.js';

const fx = (name: string): string => readFileSync(new URL(`./fixtures/${name}`, import.meta.url), 'utf8');

describe('parseFleetManifest over committed manifests', () => {
  it('reads gitorio’s derived manifest', () => {
    const m = parseFleetManifest(fx('gitorio.fleet.manifest.yml'));
    expect(m.spec_version).toBe('fleet/v1');
    expect(m.repo).toBe('bamr87/gitorio');
    expect(m.provenance).toBe('derived');
    expect(m.skipped).toBe(0);
    expect(m.lanes.filter((l) => l.id.startsWith('factory--')).length).toBeGreaterThanOrEqual(4);
    for (const lane of m.lanes) expect(LANE_HARNESSES).toContain(lane.harness);
  });

  it('reads irony-works’ manifest, wrapped scalars and all', () => {
    const m = parseFleetManifest(fx('irony-works.fleet.manifest.yml'));
    expect(m.spec_version).toBe('fleet/v1');
    expect(['declared', 'derived']).toContain(m.provenance);
    expect(m.summary.length).toBeGreaterThan(40);
    const germinate = m.lanes.find((l) => l.id === 'germinate');
    expect(germinate?.switch).toBe('GERMINATE_ENABLED');
    expect(germinate?.triggers.some((t) => t.kind === 'schedule')).toBe(true);
  });

  it('never throws: junk yields an empty manifest and counts what it skipped', () => {
    expect(parseFleetManifest('not: [valid').lanes).toEqual([]);
    const m = parseFleetManifest('spec_version: fleet/v1\nlanes:\n  - 42\n  - id: ok\n');
    expect(m.lanes.map((l) => l.id)).toEqual(['ok']);
    expect(m.skipped).toBe(1);
    expect(m.lanes[0].kind).toBe('other');
    expect(m.lanes[0].harness).toBe('none');
    expect(m.lanes[0].guardrails.never_merges).toBe(true);
  });

  it('pins a workflow path to its lane by implementation, else by basename', () => {
    const m = parseFleetManifest(fx('gitorio.fleet.manifest.yml'));
    const byPath = laneForPath(m, '.github/workflows/factory--docs-gardener.yml');
    expect(byPath?.id).toBe('factory--docs-gardener');
    expect(laneForPath(m, '.github/workflows/nope.yml')).toBeNull();
    expect(laneForPath(null, 'x')).toBeNull();
  });
});

describe('toFleetManifestYaml', () => {
  it('emits a document the parser reads back, with the token contract', () => {
    const m = parseFleetManifest(fx('gitorio.fleet.manifest.yml'));
    const text = toFleetManifestYaml(m.lanes, { repo: 'bamr87/gitorio', summary: 'round trip' });
    const back = parseFleetManifest(text);
    expect(back.spec_version).toBe('fleet/v1');
    expect(back.summary).toBe('round trip');
    expect(back.lanes.map((l) => l.id)).toEqual(m.lanes.map((l) => l.id));
    expect(text).toContain('tokens:');
    expect(text.startsWith('# fleet.manifest.yml')).toBe(true);
  });
});
