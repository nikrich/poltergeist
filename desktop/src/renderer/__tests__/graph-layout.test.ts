import { describe, expect, it } from 'vitest';
import type { EgoGraph, EgoGraphNode, VaultGraph } from '../../shared/api-types';
import { nodeRadius } from '../lib/constellation-engine';
import { EGO_RADIUS_SCALE, layoutEgo, sceneFromVaultGraph } from '../lib/graph/layout';

const n = (path: string, hop: number, extra: Partial<EgoGraphNode> = {}): EgoGraphNode => ({
  path, title: path.replace('.md', ''), context: 'work', kind: 'note', degree: 1, ghost: false, hop, ...extra,
});
const e = (source: string, target: string) => ({ source, target, weight: 0.5, kind: 'wikilink' as const });

const SMALL: EgoGraph = {
  focus: 'a.md', depth: 2, truncated: false, indexing: false,
  nodes: [n('a.md', 0, { degree: 4 }), n('b.md', 1), n('c.md', 1), n('d.md', 1), n('later.md', 1, { ghost: true }), n('e.md', 2)],
  edges: [e('a.md', 'b.md'), e('a.md', 'c.md'), e('a.md', 'd.md'), e('a.md', 'later.md'), e('b.md', 'e.md'), e('a.md', 'gone.md')],
};

function mean(xs: number[]): number {
  return xs.reduce((s, x) => s + x, 0) / xs.length;
}

describe('layoutEgo', () => {
  it('pins the focus at the origin and keeps hop rings in order', () => {
    const s = layoutEgo(SMALL);
    expect(s.mode).toBe('ego');
    expect(s.focus).toBe(0);
    expect(s.nodes[0]).toMatchObject({ path: 'a.md', x: 0, y: 0 });
    const dist = (hop: number) => mean(s.nodes.filter((x) => x.hop === hop).map((x) => Math.hypot(x.x, x.y)));
    expect(dist(1)).toBeLessThan(dist(2));
  });

  it('is deterministic', () => {
    expect(layoutEgo(SMALL).nodes).toEqual(layoutEgo(SMALL).nodes);
  });

  it('maps edges to node indices and drops edges to unknown nodes', () => {
    const s = layoutEgo(SMALL);
    expect(s.edges).toHaveLength(5);
    expect(s.edges[0]).toEqual({ a: 0, b: 1, weight: 0.5 });
  });

  it('sizes nodes by link count and keeps ghosts', () => {
    const s = layoutEgo(SMALL);
    expect(s.nodes[0]!.r).toBeCloseTo(nodeRadius(4) * EGO_RADIUS_SCALE);
    expect(s.nodes[0]!.r).toBeGreaterThan(s.nodes[1]!.r);
    expect(s.nodes.find((x) => x.path === 'later.md')!.ghost).toBe(true);
  });

  it('lays out a full 300-node neighbourhood with finite positions', () => {
    const nodes = [n('f.md', 0, { degree: 60 })];
    const edges = [];
    for (let i = 0; i < 60; i++) {
      nodes.push(n(`h1-${i}.md`, 1, { degree: 5 }));
      edges.push(e('f.md', `h1-${i}.md`));
    }
    for (let i = 0; i < 239; i++) {
      nodes.push(n(`h2-${i}.md`, 2));
      edges.push(e(`h1-${i % 60}.md`, `h2-${i}.md`));
    }
    const s = layoutEgo({ focus: 'f.md', depth: 2, truncated: true, indexing: false, nodes, edges });
    expect(s.nodes).toHaveLength(300);
    expect(s.nodes.every((x) => Number.isFinite(x.x) && Number.isFinite(x.y))).toBe(true);
  });
});

describe('sceneFromVaultGraph', () => {
  const VAULT: VaultGraph = {
    nodes: [
      { path: 'a.md', title: 'A', context: 'work', tags: [], x: 10, y: -20, degree: 3, updated: null, kind: 'decision' },
      { path: 'b.md', title: 'B', context: 'work', tags: [], x: -5, y: 7, degree: 0, updated: null },
    ],
    edges: [{ source: 'a.md', target: 'b.md', weight: 0.5, kind: 'wikilink' }, { source: 'a.md', target: 'x.md', weight: 1, kind: 'wikilink' }],
    regions: [],
  };

  it('uses the server positions and defaults a missing kind to note', () => {
    const s = sceneFromVaultGraph(VAULT);
    expect(s.mode).toBe('vault');
    expect(s.nodes.map((x) => [x.path, x.x, x.y, x.kind])).toEqual([['a.md', 10, -20, 'decision'], ['b.md', -5, 7, 'note']]);
    expect(s.edges).toEqual([{ a: 0, b: 1, weight: 0.5 }]);
    expect(s.focus).toBe(-1);
    expect(sceneFromVaultGraph(VAULT, 'b.md').focus).toBe(1);
  });
});
