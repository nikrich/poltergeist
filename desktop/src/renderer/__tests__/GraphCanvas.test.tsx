import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import type { NoteKind } from '../../shared/api-types';
import { DOUBLE_CLICK_MS, FIT_BOUNDS, GraphCanvas } from '../components/GraphCanvas';
import { fitCamera, nodeRadius, toScreen } from '../lib/constellation-engine';
import type { Scene, SceneNode } from '../lib/graph/layout';

const sn = (path: string, x: number, y: number, extra: Partial<SceneNode> = {}): SceneNode => ({
  path, title: path.replace('.md', ''), kind: 'note', degree: 2, ghost: false, hop: 1, x, y, r: nodeRadius(2) * 1.8, ...extra,
});
const SCENE: Scene = {
  mode: 'ego', focus: 0,
  nodes: [sn('alpha.md', 0, 0, { hop: 0, kind: 'decision' }), sn('beta.md', 200, 0), sn('later.md', -200, 0, { ghost: true })],
  edges: [{ a: 0, b: 1, weight: 0.5 }, { a: 0, b: 2, weight: 0.5 }],
};
const NONE = new Set<NoteKind>();

/** jsdom 25 has no PointerEvent; React reads clientX/pointerId off any event named pointer*. */
class TestPointerEvent extends MouseEvent {
  readonly pointerId: number;
  constructor(type: string, init: MouseEventInit & { pointerId?: number } = {}) {
    super(type, init);
    this.pointerId = init.pointerId ?? 1;
  }
}
function pointer(el: Element, type: 'pointerdown' | 'pointermove' | 'pointerup', x: number, y: number) {
  act(() => {
    el.dispatchEvent(new TestPointerEvent(type, { bubbles: true, clientX: x, clientY: y }));
  });
}
function click(el: Element, x: number, y: number) {
  pointer(el, 'pointerdown', x, y);
  pointer(el, 'pointerup', x, y);
}

let ops: string[];
/** performance.now() for the canvas: tests set it, so double-click timing never depends on the runner. */
let clock: number;
const originalGetContext = HTMLCanvasElement.prototype.getContext;

beforeEach(() => {
  ops = [];
  clock = 1000;
  vi.spyOn(performance, 'now').mockImplementation(() => clock);
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
    cb(0);
    return 1;
  });
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
    x: 0, y: 0, left: 0, top: 0, right: 800, bottom: 600, width: 800, height: 600, toJSON: () => ({}),
  } as DOMRect);
  const ctx: Record<string, unknown> = { fillStyle: '', strokeStyle: '', lineWidth: 1, font: '', textAlign: 'start', textBaseline: 'top', globalAlpha: 1 };
  for (const name of ['setTransform', 'fillRect', 'beginPath', 'moveTo', 'lineTo', 'arc', 'rect', 'fill', 'stroke', 'fillText']) {
    ctx[name] = () => ops.push(name);
  }
  HTMLCanvasElement.prototype.getContext = vi.fn(() => ctx) as unknown as typeof HTMLCanvasElement.prototype.getContext;
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  HTMLCanvasElement.prototype.getContext = originalGetContext;
});

function renderCanvas(scene: Scene = SCENE, hidden: ReadonlySet<NoteKind> = NONE) {
  const onRecenter = vi.fn();
  const onOpen = vi.fn();
  const utils = render(<GraphCanvas scene={scene} hiddenKinds={hidden} onRecenter={onRecenter} onOpen={onOpen} />);
  return { ...utils, onRecenter, onOpen, canvas: screen.getByRole('img', { name: 'link graph' }) };
}

function screenPoint(scene: Scene, i: number): [number, number] {
  const cam = fitCamera(scene.nodes, 800, 600, FIT_BOUNDS);
  return toScreen(cam, 800, 600, scene.nodes[i]!.x, scene.nodes[i]!.y);
}

describe('GraphCanvas', () => {
  it('draws the scene', () => {
    renderCanvas();
    expect(ops).toContain('arc');
    expect(ops).toContain('fillText');
  });

  it('lists nodes for keyboard and screen-reader users', () => {
    const { onRecenter, onOpen } = renderCanvas();
    fireEvent.click(screen.getByRole('button', { name: 'beta' }));
    expect(onRecenter).toHaveBeenCalledWith(SCENE.nodes[1]);
    fireEvent.click(screen.getByRole('button', { name: 'open beta' }));
    expect(onOpen).toHaveBeenCalledWith(SCENE.nodes[1]);
    expect(screen.getByRole('button', { name: 'later (not written yet)' })).toBeInTheDocument();
  });

  it('a click on a node recentres; a quick second click opens it', () => {
    const { canvas, onRecenter, onOpen } = renderCanvas();
    const [x, y] = screenPoint(SCENE, 1);
    click(canvas, x, y);
    expect(onRecenter).toHaveBeenCalledWith(SCENE.nodes[1]);
    expect(onOpen).not.toHaveBeenCalled();
    clock += DOUBLE_CLICK_MS;
    click(canvas, x, y);
    expect(onOpen).toHaveBeenCalledWith(SCENE.nodes[1]);
  });

  it('a second click after the double-click window recentres again instead of opening', () => {
    const { canvas, onRecenter, onOpen } = renderCanvas();
    const [x, y] = screenPoint(SCENE, 1);
    click(canvas, x, y);
    clock += DOUBLE_CLICK_MS + 1;
    click(canvas, x, y);
    expect(onOpen).not.toHaveBeenCalled();
    expect(onRecenter).toHaveBeenCalledTimes(2);
    expect(onRecenter).toHaveBeenLastCalledWith(SCENE.nodes[1]);
  });

  it('the second click opens the first node even after the scene changed', () => {
    const { canvas, onRecenter, onOpen, rerender } = renderCanvas();
    const [x, y] = screenPoint(SCENE, 1);
    click(canvas, x, y);
    const recentred: Scene = { ...SCENE, focus: 1, nodes: [sn('beta.md', 0, 0, { hop: 0 }), sn('gamma.md', 300, 300)], edges: [] };
    rerender(<GraphCanvas scene={recentred} hiddenKinds={NONE} onRecenter={onRecenter} onOpen={onOpen} />);
    clock += DOUBLE_CLICK_MS - 1;
    click(canvas, x, y);
    expect(onOpen).toHaveBeenCalledWith(SCENE.nodes[1]);
  });

  it('dragging pans instead of clicking, and empty space does nothing', () => {
    const { canvas, onRecenter } = renderCanvas();
    const [x, y] = screenPoint(SCENE, 1);
    pointer(canvas, 'pointerdown', x, y);
    pointer(canvas, 'pointermove', x + 40, y);
    pointer(canvas, 'pointerup', x + 40, y);
    click(canvas, 5, 5);
    expect(onRecenter).not.toHaveBeenCalled();
  });

  it('hidden kinds leave the node list, but the focus stays', () => {
    renderCanvas(SCENE, new Set<NoteKind>(['note', 'decision']));
    expect(screen.getByRole('button', { name: 'alpha' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'beta' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'later (not written yet)' })).toBeNull();
  });
});
