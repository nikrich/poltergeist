import { describe, it, expect, vi, beforeEach } from 'vitest';

const { initialize, renderFn } = vi.hoisted(() => ({ initialize: vi.fn(), renderFn: vi.fn() }));
vi.mock('mermaid', () => ({ default: { initialize, render: renderFn } }));

import { renderMermaid, resetMermaidForTests } from '../lib/editor/mermaid-render';

describe('renderMermaid', () => {
  beforeEach(() => {
    resetMermaidForTests();
    initialize.mockReset();
    renderFn.mockReset();
  });

  it('returns svg on success with strict security and the app theme', async () => {
    renderFn.mockResolvedValue({ svg: '<svg id="x"></svg>' });
    document.body.dataset.theme = 'light';
    const r = await renderMermaid('flowchart TD\n A-->B');
    expect(r).toEqual({ ok: true, svg: '<svg id="x"></svg>' });
    expect(initialize).toHaveBeenCalledWith(
      expect.objectContaining({ startOnLoad: false, securityLevel: 'strict', theme: 'default' }),
    );
  });

  it('returns the error message instead of throwing, and removes mermaid leftovers', async () => {
    renderFn.mockImplementation(async (id: string) => {
      const stray = document.createElement('div');
      stray.id = `d${id}`;
      document.body.appendChild(stray);
      throw new Error('Parse error on line 1');
    });
    const r = await renderMermaid('nonsense');
    expect(r).toEqual({ ok: false, error: 'Parse error on line 1' });
    expect(document.querySelector('[id^="dgb-mermaid-"]')).toBeNull();
  });

  it('short-circuits an empty diagram without loading mermaid', async () => {
    const r = await renderMermaid('   ');
    expect(r).toEqual({ ok: false, error: 'empty diagram' });
    expect(renderFn).not.toHaveBeenCalled();
  });
});
