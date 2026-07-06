import { describe, it, expect } from 'vitest';
import { toScreen, toWorld, fitCamera, hitTest, buildAdjacency } from '../lib/constellation-engine';
import type { VaultGraph } from '../../shared/api-types';

const node = (path: string, x: number, y: number) =>
  ({ path, title: path, context: 'a', tags: [], x, y, degree: 0, updated: null });

describe('constellation-engine', () => {
  it('toScreen and toWorld are inverses', () => {
    const cam = { x: 10, y: -5, scale: 0.8 };
    const [sx, sy] = toScreen(cam, 800, 600, 42, 17);
    const [wx, wy] = toWorld(cam, 800, 600, sx, sy);
    expect(wx).toBeCloseTo(42);
    expect(wy).toBeCloseTo(17);
  });

  it('fitCamera centres on the node cloud', () => {
    const cam = fitCamera([node('a', -100, -100), node('b', 100, 100)], 800, 600);
    expect(cam.x).toBeCloseTo(0);
    expect(cam.y).toBeCloseTo(0);
    expect(cam.scale).toBeGreaterThanOrEqual(0.7);
    expect(cam.scale).toBeLessThanOrEqual(1.5);
  });

  it('hitTest finds the node under the cursor', () => {
    const cam = { x: 0, y: 0, scale: 1 };
    const nodes = [node('a', 0, 0), node('b', 500, 0)];
    const [sx, sy] = toScreen(cam, 800, 600, 0, 0);
    expect(hitTest(cam, 800, 600, nodes, sx, sy)).toBe(0);
    expect(hitTest(cam, 800, 600, nodes, 5, 5)).toBe(-1); // empty gap → miss
  });

  it('buildAdjacency maps neighbours both ways', () => {
    const graph: VaultGraph = {
      nodes: [node('a', 0, 0), node('b', 1, 1)],
      edges: [{ source: 'a', target: 'b', weight: 0.7, kind: 'related' }],
      regions: [],
    };
    const adj = buildAdjacency(graph);
    expect(adj.get('a')).toEqual(['b']);
    expect(adj.get('b')).toEqual(['a']);
  });
});
