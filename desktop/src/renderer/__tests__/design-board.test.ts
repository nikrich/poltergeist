import { describe, expect, it } from 'vitest';

import { layoutBoard, NOTE_H, NOTE_W } from '../components/design/board-layout';
import { boardToMermaid } from '../components/design/board-mermaid';
import { sampleBoard } from './fixtures/design';
import type { BoardModel } from '../../shared/design-types';

describe('layoutBoard', () => {
  it('puts one lane per context plus Unassigned for loose items', () => {
    const layout = layoutBoard(sampleBoard);
    expect(layout.lanes.map((l) => l.name)).toEqual(['Orders', 'Billing', 'Unassigned']);
  });

  it('omits Unassigned when every item has a known context', () => {
    const model: BoardModel = {
      ...sampleBoard,
      items: sampleBoard.items.filter((i) => i.context !== null),
    };
    expect(layoutBoard(model).lanes.map((l) => l.id)).toEqual(['orders', 'billing']);
  });

  it('treats an unknown context id as unassigned', () => {
    const model: BoardModel = {
      contexts: [],
      items: [{ id: 'a', kind: 'event', label: 'A', context: 'ghost', order: 1 }],
      links: [],
    };
    const layout = layoutBoard(model);
    expect(layout.lanes.map((l) => l.name)).toEqual(['Unassigned']);
    expect(layout.notes[0]?.lane).toBe('__unassigned');
  });

  it('places items in timeline columns shared across lanes', () => {
    const layout = layoutBoard(sampleBoard);
    const x = (id: string) => layout.notes.find((n) => n.id === id)!.x;
    expect(x('place')).toBeLessThan(x('order'));
    expect(x('order')).toBeLessThan(x('placed'));
    // Same order → same column, even across lanes.
    expect(x('placed')).toBe(x('charge'));
    const y = (id: string) => layout.notes.find((n) => n.id === id)!.y;
    expect(y('charge')).toBeGreaterThan(y('placed'));
  });

  it('stacks same-column items in a lane in their original order', () => {
    const model: BoardModel = {
      contexts: [{ id: 'c', name: 'C' }],
      items: [
        { id: 'b', kind: 'event', label: 'B', context: 'c', order: 5 },
        { id: 'a', kind: 'event', label: 'A', context: 'c', order: 5 },
      ],
      links: [],
    };
    const layout = layoutBoard(model);
    const [first, second] = layout.notes;
    expect(first?.id).toBe('b');
    expect(second?.id).toBe('a');
    expect(second!.y).toBeGreaterThan(first!.y);
    expect(first!.x).toBe(second!.x);
    expect(layout.lanes[0]!.height).toBeGreaterThanOrEqual(2 * NOTE_H);
  });

  it('is deterministic', () => {
    expect(layoutBoard(sampleBoard)).toEqual(layoutBoard(sampleBoard));
  });

  it('draws arrows between note centres and skips dangling links', () => {
    const model: BoardModel = {
      ...sampleBoard,
      links: [...sampleBoard.links, { from: 'place', to: 'missing' }],
    };
    const layout = layoutBoard(model);
    expect(layout.arrows).toHaveLength(4);
    const place = layout.notes.find((n) => n.id === 'place')!;
    const arrow = layout.arrows[0]!;
    expect(arrow.from).toBe('place');
    expect(arrow.x1).toBeCloseTo(place.x + place.w / 2);
    expect(arrow.y1).toBeCloseTo(place.y + place.h / 2);
  });

  it('makes actors smaller and fits everything in the canvas size', () => {
    const model: BoardModel = {
      contexts: [],
      items: [
        { id: 'u', kind: 'actor', label: 'Shopper', context: null, order: 1 },
        { id: 'e', kind: 'event', label: 'Thing', context: null, order: 2 },
      ],
      links: [],
    };
    const layout = layoutBoard(model);
    const actor = layout.notes.find((n) => n.id === 'u')!;
    expect(actor.w).toBeLessThan(NOTE_W);
    for (const n of layout.notes) {
      expect(n.x + n.w).toBeLessThanOrEqual(layout.width);
      expect(n.y + n.h).toBeLessThanOrEqual(layout.height);
    }
  });

  it('handles an empty board', () => {
    const layout = layoutBoard({ contexts: [], items: [], links: [] });
    expect(layout.notes).toEqual([]);
    expect(layout.lanes).toEqual([]);
  });
});

describe('boardToMermaid', () => {
  it('emits a flowchart with a subgraph per context and edges', () => {
    const text = boardToMermaid(sampleBoard);
    expect(text.startsWith('flowchart LR')).toBe(true);
    expect(text).toContain('subgraph ctx_orders["Orders"]');
    expect(text).toContain('subgraph ctx_billing["Billing"]');
    expect(text).toContain('n_place --> n_order');
    expect(text).toContain('n_charge --> n_psp');
  });

  it('uses kind-specific shapes', () => {
    const text = boardToMermaid(sampleBoard);
    expect(text).toContain('n_place["Place order"]'); // command: rectangle
    expect(text).toContain('n_order[["Order"]]'); // aggregate: subroutine
    expect(text).toContain('n_placed(["Order placed"])'); // event: stadium
    expect(text).toContain('n_charge{{"Charge card"}}'); // policy: hexagon
    expect(text).toContain('n_psp>"Stripe"]'); // external: flag
  });

  it('leaves loose items outside subgraphs', () => {
    const lines = boardToMermaid(sampleBoard).split('\n');
    const psp = lines.find((l) => l.includes('n_psp>'))!;
    expect(psp.startsWith('  n_psp')).toBe(true);
  });

  it('escapes labels', () => {
    const model: BoardModel = {
      contexts: [{ id: 'a b', name: 'Say "hi" <now>' }],
      items: [
        { id: 'x-1', kind: 'read_model', label: 'Cart "#1" <b>\nnext', context: 'a b', order: 1 },
      ],
      links: [],
    };
    const text = boardToMermaid(model);
    expect(text).toContain('subgraph ctx_a_b["Say #quot;hi#quot; #lt;now#gt;"]');
    expect(text).toContain('n_x_1[("Cart #quot;#35;1#quot; #lt;b#gt; next")]');
  });

  it('keeps sanitised ids unique', () => {
    const model: BoardModel = {
      contexts: [],
      items: [
        { id: 'a-b', kind: 'event', label: 'One', context: null, order: 1 },
        { id: 'a_b', kind: 'event', label: 'Two', context: null, order: 2 },
      ],
      links: [{ from: 'a-b', to: 'a_b' }],
    };
    const text = boardToMermaid(model);
    expect(text).toContain('n_a_b(["One"])');
    expect(text).toContain('n_a_b_2(["Two"])');
    expect(text).toContain('n_a_b --> n_a_b_2');
  });

  it('skips actors, hotspots and links that touch them', () => {
    const model: BoardModel = {
      contexts: [],
      items: [
        { id: 'u', kind: 'actor', label: 'Shopper', context: null, order: 1 },
        { id: 'h', kind: 'hotspot', label: 'Refunds?', context: null, order: 1 },
        { id: 'c', kind: 'command', label: 'Pay', context: null, order: 2 },
      ],
      links: [{ from: 'u', to: 'c' }],
    };
    const text = boardToMermaid(model);
    expect(text).not.toContain('Shopper');
    expect(text).not.toContain('Refunds');
    expect(text).not.toContain('-->');
  });
});
