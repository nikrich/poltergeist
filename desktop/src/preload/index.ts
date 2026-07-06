import { contextBridge, ipcRenderer } from 'electron';
import type { GbBridge } from '../shared/types';

const bridge: GbBridge = {
  settings: {
    getAll: () => ipcRenderer.invoke('gb:settings:getAll'),
    set: (key, value) => ipcRenderer.invoke('gb:settings:set', key, value),
  },
  dialogs: {
    pickVaultFolder: () => ipcRenderer.invoke('gb:dialogs:pickVaultFolder'),
  },
  shell: {
    openPath: (path: string) => ipcRenderer.invoke('gb:shell:openPath', path),
    openExternal: (url: string) => ipcRenderer.invoke('gb:shell:openExternal', url),
  },
  platform: process.platform,
  api: {
    request: (method, path, body) =>
      ipcRenderer.invoke('gb:api:request', method, path, body),
  },
  sidecar: {
    retry: () => ipcRenderer.invoke('gb:sidecar:retry'),
  },
  chat: {
    send: (convId, text, attachmentPaths) =>
      ipcRenderer.invoke('gb:chat:send', convId, text, attachmentPaths),
    stop: (convId) => ipcRenderer.invoke('gb:chat:stop', convId),
  },
  docs: {
    assist: (req) => ipcRenderer.invoke('gb:docs:assist', req),
    assistStop: (jotId) => ipcRenderer.invoke('gb:docs:assist-stop', jotId),
    exportPdf: (payload) => ipcRenderer.invoke('gb:docs:export-pdf', payload),
    openGenerated: (path: string) => ipcRenderer.invoke('gb:docs:open-generated', path),
  },
  tray: {
    setFailing: (names: string[]) => ipcRenderer.invoke('gb:tray:setFailing', names),
  },
  clipboard: {
    writeRich: (payload: { html: string; text: string }) =>
      ipcRenderer.invoke('gb:clipboard:write-rich', payload),
  },
  assets: {
    write: (payload) => ipcRenderer.invoke('gb:assets:write', payload),
    toUrl: (vaultRelPath: string) =>
      'gbasset://asset/' +
      vaultRelPath
        .split('/')
        .map((seg) => encodeURIComponent(seg))
        .join('/'),
  },
  jot: {
    save: (body: string) => ipcRenderer.invoke('gb:jot:save', body),
    cancel: () => ipcRenderer.invoke('gb:jot:cancel'),
    onFocus: (cb: () => void) => {
      const handler = () => cb();
      ipcRenderer.on('gb:jot:focus', handler);
      return () => ipcRenderer.removeListener('gb:jot:focus', handler);
    },
    onSaveFailed: (cb: (payload: { body: string; error: string }) => void) => {
      const handler = (_: unknown, payload: { body: string; error: string }) => cb(payload);
      ipcRenderer.on('gb:jot:save-failed', handler as Parameters<typeof ipcRenderer.on>[1]);
      return () => ipcRenderer.removeListener('gb:jot:save-failed', handler as Parameters<typeof ipcRenderer.on>[1]);
    },
  },
  plugins: {
    list: () => ipcRenderer.invoke('gb:plugins:list'),
    active: () => ipcRenderer.invoke('gb:plugins:active'),
    setEnabled: (id, on) => ipcRenderer.invoke('gb:plugins:setEnabled', id, on),
    reload: () => ipcRenderer.invoke('gb:plugins:reload'),
    installFromFolder: () => ipcRenderer.invoke('gb:plugins:installFromFolder'),
    installFromGit: (url, subdir) => ipcRenderer.invoke('gb:plugins:installFromGit', url, subdir),
    uninstall: (id) => ipcRenderer.invoke('gb:plugins:uninstall', id),
    onChanged: (cb) => {
      const handler = (_e: Electron.IpcRendererEvent, active: unknown) =>
        cb(active as Parameters<typeof cb>[0]);
      ipcRenderer.on('gb:plugins:changed', handler);
      return () => ipcRenderer.removeListener('gb:plugins:changed', handler);
    },
  },
  plugin: (id: string) => ({
    invoke: (channel: string, ...args: unknown[]) =>
      ipcRenderer.invoke(`gb:plugin:${id}:${channel}`, ...args),
    on: (channel: string, cb: (payload: unknown) => void) => {
      const full = `gb:plugin:${id}:${channel}`;
      const handler = (_e: Electron.IpcRendererEvent, payload: unknown) => cb(payload);
      ipcRenderer.on(full, handler);
      return () => ipcRenderer.removeListener(full, handler);
    },
    settings: {
      get: (key: string) => ipcRenderer.invoke('gb:plugins:data:get', id, key),
      set: (key: string, v: unknown) => ipcRenderer.invoke('gb:plugins:data:set', id, key, v),
    },
  }),
  on: ((channel: string, listener: (...args: unknown[]) => void) => {
    const wrapped = (_e: Electron.IpcRendererEvent, ...args: unknown[]) =>
      listener(...args);
    const ipcChannel = `gb:${channel}`;
    ipcRenderer.on(ipcChannel, wrapped);
    return () => {
      ipcRenderer.off(ipcChannel, wrapped);
    };
  }) as GbBridge['on'],
};

contextBridge.exposeInMainWorld('gb', bridge);
