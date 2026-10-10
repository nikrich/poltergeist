import { describe, expect, it } from 'vitest';
import { layoutEgo } from '../lib/graph/layout';
import type { OntologyGraph } from '../../shared/api-types';

describe('layoutEgo with an ontology graph', () => {
  it('lays out ontology kinds with the focus at the origin', () => {
    const graph: OntologyGraph = {
      focus: 'p1', depth: 2, truncated: false,
      nodes: [
        { path: 'p1', title: 'Orbit', context: 'Orbit', kind: 'project', degree: 2, ghost: false, hop: 0, note_path: null },
        { path: 'r1', title: 'lapse day', context: 'Orbit', kind: 'rule', degree: 2, ghost: false, hop: 1, note_path: null },
        { path: 'a1', title: 'Spec', context: 'Orbit', kind: 'artefact', degree: 1, ghost: false, hop: 2, note_path: '20-contexts/work/spec.md' },
      ],
      edges: [
        { source: 'r1', target: 'p1', weight: 1, kind: 'part_of' },
        { source: 'r1', target: 'a1', weight: 1, kind: 'evidenced_by' },
      ],
    };
    const scene = layoutEgo(graph);
    expect(scene.nodes.map((n) => n.kind)).toEqual(['project', 'rule', 'artefact']);
    expect(scene.focus).toBe(0);
    expect(scene.nodes[0]!.x).toBe(0);
    expect(scene.edges).toHaveLength(2);
  });
});
