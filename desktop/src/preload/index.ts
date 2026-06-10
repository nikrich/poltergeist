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
    send: (convId, text) => ipcRenderer.invoke('gb:chat:send', convId, text),
    stop: (convId) => ipcRenderer.invoke('gb:chat:stop', convId),
  },
  tray: {
    setFailing: (names: string[]) => ipcRenderer.invoke('gb:tray:setFailing', names),
  },
  clipboard: {
    writeRich: (payload: { html: string; text: string }) =>
      ipcRenderer.invoke('gb:clipboard:write-rich', payload),
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
