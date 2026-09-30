// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { mount } from '../../renderer.jsx';

const tick = () => new Promise((r) => setTimeout(r, 20));

function fakePlugin(scripts = []) {
  const store = new Map([['scripts', scripts]]);
  return {
    pluginId: 'script-writer',
    theme: { '--paper': '#101010', '--ink-0': '#eee' },
    settings: { get: async (k) => store.get(k), set: async (k, v) => { store.set(k, v); } },
    sidecar: { request: async () => ({ ok: true, data: [] }) },
    ipc: { invoke: async () => null, on: () => () => {} },
    openExternal: () => {},
  };
}

describe('mount', () => {
  it('renders the library with registry entries and unmounts cleanly', async () => {
    const el = document.createElement('div');
    const unmount = mount(el, fakePlugin([{ path: '20-contexts/personal/projects/n/a.screenplay.md', title: 'The Long Night', context: 'personal', project: 'n', updated: '2026-09-30T10:00:00Z', pages: 97 }]));
    await tick();
    expect(el.textContent).toContain('The Long Night');
    expect(el.textContent).toContain('97 pp');
    expect(el.style.getPropertyValue('--paper')).toBe('#101010');
    unmount();
    expect(el.childNodes.length).toBe(0);
  });

  it('shows an empty state', async () => {
    const el = document.createElement('div');
    const unmount = mount(el, fakePlugin());
    await tick();
    expect(el.textContent).toContain('No scripts yet');
    unmount();
  });
});
