// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it, vi } from 'vitest';
import { AiPanel, renderAnswer } from '../AiPanel.jsx';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const SCRIPT = '20-contexts/personal/projects/night/draft.screenplay.md';
const flush = () => act(() => new Promise((r) => setTimeout(r, 0)));

function fakePlugin({ llm }) {
  const calls = [];
  const threads = {};
  return {
    calls,
    threads,
    openExternal: vi.fn(),
    ipc: {
      invoke: async (ch, arg) => {
        if (ch === 'thread-read') return threads[arg] ?? [];
        if (ch === 'thread-write') { threads[arg.key] = arg.messages; return true; }
        return null;
      },
    },
    sidecar: {
      request: async (method, path, body) => {
        calls.push({ method, path, body });
        if (path === '/v1/search') {
          return { ok: true, data: { items: [
            { path: '20-contexts/personal/projects/night/mara.md', title: 'Mara bio', snippet: 'Mara is 40', score: 0.9 },
            { path: '20-contexts/personal/projects/night/town.md', title: 'Town', snippet: 'Foggy', score: 0.8 },
            { path: '20-contexts/personal/projects/night/joe.md', title: 'Joe', snippet: 'Joe lies', score: 0.7 },
          ] } };
        }
        if (path.startsWith('/v1/notes')) return { ok: true, data: { body: 'Mara is 40 and hates boats.' } };
        if (path === '/v1/llm/run') return { ok: true, data: llm(body) };
        return { ok: false, error: 'no route', status: 500 };
      },
    },
  };
}

const ctx = { text: 'INT. A - DAY\n\nMara waits.', elements: [], cursorLine: 2, scene: { from: 0, to: 25, text: 'INT. A - DAY\n\nMara waits.' }, selection: { from: 14, to: 14, text: '' } };

async function mount(plugin, props = {}) {
  const el = document.createElement('div');
  document.body.appendChild(el);
  const root = createRoot(el);
  await act(async () => { root.render(<AiPanel plugin={plugin} scriptPath={SCRIPT} getContext={() => props.ctx ?? ctx} onPropose={props.onPropose ?? (() => {})} notify={props.notify ?? (() => {})} focusToken={0} />); });
  await flush();
  return { el, root };
}

describe('renderAnswer', () => {
  it('renders markdown, drops raw html, and turns [n] into citation buttons', () => {
    const html = renderAnswer('**Mara** is 40 [1].<script>x</script>');
    expect(html).toContain('<strong>Mara</strong>');
    expect(html).toContain('<button type="button" class="sw-cite" data-n="1">[1]</button>');
    expect(html).not.toContain('<script>');
  });
  it('neutralises links, images and raw html, and only exposes http(s) links as buttons', () => {
    const html = renderAnswer('[x](https://a.b) <img src=x onerror=1> [y](javascript:alert(1)) ![p](http://i)');
    expect(html).not.toContain('<a ');
    expect(html).not.toContain('<img');
    expect(html).not.toContain('onerror');
    expect(html).not.toContain('javascript:');
    expect(html).toContain('class="sw-link" data-href="https://a.b"');
    expect(html).toContain('y');
    expect(html).toContain('p');
  });

  it('only turns [n] in prose text into citations, not code or attributes', () => {
    const html = renderAnswer('`code [1]` and [1]');
    expect(html.match(/class="sw-cite"/g)).toHaveLength(1);
    expect(html).toContain('<code>code [1]</code>');
    const d = document.createElement('div');
    d.innerHTML = renderAnswer('[a](https://x "t[1]")');
    expect(d.querySelectorAll('.sw-link').length).toBeLessThanOrEqual(1);
    expect(d.querySelectorAll('.sw-cite')).toHaveLength(0);
    expect(d.innerHTML).not.toContain('data-n');
  });
});

describe('AiPanel', () => {
  it('asks: searches the project, answers with a clickable citation, persists the thread', async () => {
    const plugin = fakePlugin({ llm: () => ({ text: 'Mara is 40 [1].', structured: null, error: null }) });
    const { el, root } = await mount(plugin);
    const ta = el.querySelector('textarea');
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
      setter.call(ta, 'How old is Mara?');
      ta.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => { el.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); });
    await flush();
    const llmCall = plugin.calls.find((c) => c.path === '/v1/llm/run');
    expect(llmCall.body.budgetUsd).toBe(1);
    expect(llmCall.body.prompt).toContain('[1] Mara bio');
    expect(el.textContent).toContain('Mara is 40');
    await act(async () => { el.querySelector('.sw-cite').dispatchEvent(new MouseEvent('click', { bubbles: true })); });
    expect(el.querySelector('.sw-source').textContent).toContain('Mara bio');
    expect(plugin.threads['20-contexts-personal-projects-night-draft-screenplay-md']).toHaveLength(2);
    act(() => root.unmount());
  });

  it('runs an action on the scene and proposes a replace edit', async () => {
    const onPropose = vi.fn();
    const plugin = fakePlugin({ llm: () => ({ text: '', structured: { fountain: 'INT. A - DAY\n\nMara paces.' }, error: null }) });
    const { el, root } = await mount(plugin, { onPropose });
    const select = el.querySelector('.sw-ai-actions select');
    await act(async () => { select.value = 'punchup'; select.dispatchEvent(new Event('change', { bubbles: true })); });
    await act(async () => { el.querySelector('.sw-ai-actions .sw-primary').dispatchEvent(new MouseEvent('click', { bubbles: true })); });
    await flush();
    expect(onPropose).toHaveBeenCalledWith({ from: 0, to: 25, text: 'INT. A - DAY\n\nMara paces.', mode: 'replace', label: 'Punch up dialogue', original: 'INT. A - DAY\n\nMara waits.', anchorFrom: 0 });
    act(() => root.unmount());
  });

  it('rejects prose with no screenplay structure for a replace action', async () => {
    const onPropose = vi.fn();
    const plugin = fakePlugin({ llm: () => ({ text: '', structured: { fountain: 'she paces around the room nervously and then leaves' }, error: null }) });
    const { el, root } = await mount(plugin, { onPropose });
    const select = el.querySelector('.sw-ai-actions select');
    await act(async () => { select.value = 'punchup'; select.dispatchEvent(new Event('change', { bubbles: true })); });
    await act(async () => { el.querySelector('.sw-ai-actions .sw-primary').dispatchEvent(new MouseEvent('click', { bubbles: true })); });
    await flush();
    expect(onPropose).not.toHaveBeenCalled();
    expect(el.textContent).toContain("wasn't usable screenplay text");
    act(() => root.unmount());
  });

  it('shows invalid AI output as a message instead of an edit', async () => {
    const onPropose = vi.fn();
    const plugin = fakePlugin({ llm: () => ({ text: '', structured: { fountain: '' }, error: null }) });
    const { el, root } = await mount(plugin, { onPropose });
    await act(async () => { el.querySelector('.sw-ai-actions .sw-primary').dispatchEvent(new MouseEvent('click', { bubbles: true })); });
    await flush();
    expect(onPropose).not.toHaveBeenCalled();
    expect(el.textContent).toContain("wasn't usable screenplay text");
    act(() => root.unmount());
  });

  it('surfaces provider errors inline', async () => {
    const plugin = fakePlugin({ llm: () => ({ text: '', structured: null, error: 'Budget exceeded' }) });
    const { el, root } = await mount(plugin);
    await act(async () => { el.querySelector('.sw-ai-actions .sw-primary').dispatchEvent(new MouseEvent('click', { bubbles: true })); });
    await flush();
    expect(el.querySelector('.sw-err').textContent).toContain('Budget exceeded');
    act(() => root.unmount());
  });
  it('opens external links through the host', async () => {
    const plugin = fakePlugin({ llm: () => ({ text: 'See [docs](https://a.b/x).', structured: null, error: null }) });
    plugin.threads['20-contexts-personal-projects-night-draft-screenplay-md'] = [{ role: 'user', text: 'q' }, { role: 'assistant', text: 'See [docs](https://a.b/x).' }];
    const { el, root } = await mount(plugin);
    await act(async () => { el.querySelector('.sw-link').dispatchEvent(new MouseEvent('click', { bubbles: true })); });
    expect(plugin.openExternal).toHaveBeenCalledWith('https://a.b/x');
    act(() => root.unmount());
  });

  it('disables input, Run and Clear until the thread has loaded', async () => {
    let release;
    const plugin = fakePlugin({ llm: () => ({ text: '', structured: null, error: null }) });
    plugin.ipc.invoke = (ch) => (ch === 'thread-read' ? new Promise((r) => { release = r; }) : Promise.resolve(true));
    const { el, root } = await mount(plugin);
    expect(el.querySelector('textarea').disabled).toBe(true);
    expect(el.querySelector('.sw-ai-actions .sw-primary').disabled).toBe(true);
    expect(el.querySelector('button[title="Clear conversation"]').disabled).toBe(true);
    await act(async () => { release([]); });
    await flush();
    expect(el.querySelector('textarea').disabled).toBe(false);
    expect(el.querySelector('.sw-ai-actions .sw-primary').disabled).toBe(false);
    act(() => root.unmount());
  });

  it('keeps the trailing newline of a whole-line selection in a replace proposal', async () => {
    const onPropose = vi.fn();
    const plugin = fakePlugin({ llm: () => ({ text: '', structured: { fountain: 'INT. A - DAY\n\nMara paces.' }, error: null }) });
    const sel = { from: 14, to: 26, text: 'Mara waits.\n' };
    const { el, root } = await mount(plugin, { onPropose, ctx: { ...ctx, selection: sel } });
    const select = el.querySelector('.sw-ai-actions select');
    await act(async () => { select.value = 'punchup'; select.dispatchEvent(new Event('change', { bubbles: true })); });
    await act(async () => { el.querySelector('.sw-ai-actions .sw-primary').dispatchEvent(new MouseEvent('click', { bubbles: true })); });
    await flush();
    expect(onPropose).toHaveBeenCalledTimes(1);
    expect(onPropose.mock.calls[0][0].text.endsWith('\n')).toBe(true);
    act(() => root.unmount());
  });

  it('focuses the textarea once the thread has loaded', async () => {
    const plugin = fakePlugin({ llm: () => ({ text: '', structured: null, error: null }) });
    let release;
    plugin.ipc.invoke = (ch) => (ch === 'thread-read' ? new Promise((r) => { release = r; }) : Promise.resolve(true));
    const { el, root } = await mount(plugin);
    expect(document.activeElement).not.toBe(el.querySelector('textarea'));
    await act(async () => { release([]); });
    await flush();
    expect(document.activeElement).toBe(el.querySelector('textarea'));
    act(() => root.unmount());
  });
});
