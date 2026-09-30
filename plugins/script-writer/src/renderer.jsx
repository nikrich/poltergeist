import { createRoot } from 'react-dom/client';
import { App } from './ui/App.jsx';
import { appCss } from './ui/styles.js';

export function mount(el, plugin) {
  for (const [k, v] of Object.entries(plugin.theme ?? {})) if (v) el.style.setProperty(k, v);
  const style = document.createElement('style');
  style.textContent = appCss();
  const host = document.createElement('div');
  host.style.height = '100%';
  el.append(style, host);
  const root = createRoot(host);
  root.render(<App plugin={plugin} />);
  return () => {
    root.unmount();
    el.replaceChildren();
  };
}
