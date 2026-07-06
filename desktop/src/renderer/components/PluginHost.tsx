import { useEffect, useRef, useState } from 'react';
import { PanelError } from './PanelError';
import type { ActivePluginInfo } from '../../shared/plugin-types';

// Mounts a plugin's renderer bundle. The contract is framework-free:
// `mount(el, api)` returns an unmount function; the plugin owns the DOM under
// el and bundles any framework it wants. Failures render inside the host —
// they never break the app shell.

interface PluginModule {
  mount?: (el: HTMLElement, api: PluginApi) => () => void;
}

export interface PluginApi {
  pluginId: string;
  ipc: {
    invoke(channel: string, ...args: unknown[]): Promise<unknown>;
    on(channel: string, cb: (payload: unknown) => void): () => void;
  };
  settings: {
    get(key: string): Promise<unknown>;
    set(key: string, v: unknown): Promise<void>;
  };
  sidecar: {
    request(
      method: string,
      path: string,
      body?: unknown,
    ): Promise<{ ok: true; data: unknown } | { ok: false; error: string; status?: number }>;
  };
  openExternal(url: string): void;
  theme: Record<string, string>;
}

function themeVars(): Record<string, string> {
  const style = getComputedStyle(document.documentElement);
  const vars: Record<string, string> = {};
  for (const name of ['--paper', '--vellum', '--fog', '--hairline', '--hairline-2', '--ink-0', '--ink-1', '--ink-2', '--neon', '--moss', '--oxblood']) {
    vars[name] = style.getPropertyValue(name).trim();
  }
  return vars;
}

export function PluginHost({ plugin }: { plugin: ActivePluginInfo }) {
  const elRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const el = elRef.current;
    if (!el || !plugin.rendererEntry) return;
    let unmount: (() => void) | null = null;
    let cancelled = false;
    setError(null);

    const bridge = window.gb.plugin(plugin.id);
    const api: PluginApi = {
      pluginId: plugin.id,
      ipc: { invoke: bridge.invoke, on: bridge.on },
      settings: bridge.settings,
      sidecar: bridge.sidecar,
      openExternal: (url) => void window.gb.shell.openExternal(url),
      theme: themeVars(),
    };

    import(/* @vite-ignore */ `plugin://${plugin.id}/${plugin.rendererEntry}`)
      .then((mod: PluginModule) => {
        if (cancelled) return;
        if (typeof mod.mount !== 'function') {
          throw new Error('plugin renderer has no mount() export');
        }
        unmount = mod.mount(el, api);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });

    return () => {
      cancelled = true;
      try {
        unmount?.();
      } catch {
        // a plugin that throws on unmount doesn't get to break navigation
      }
      el.replaceChildren();
    };
  }, [plugin.id, plugin.rendererEntry, attempt]);

  if (!plugin.rendererEntry) {
    return <PanelError message={`${plugin.name} has no UI (main-process only plugin).`} />;
  }
  if (error) {
    return (
      <PanelError
        message={`${plugin.name} failed to load: ${error}`}
        onRetry={() => setAttempt((a) => a + 1)}
      />
    );
  }
  return <div ref={elRef} className="flex-1 overflow-y-auto" />;
}
