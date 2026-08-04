import { app, BrowserWindow, screen } from 'electron';
import { existsSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { join, dirname } from 'node:path';

interface WindowState {
  x?: number;
  y?: number;
  width: number;
  height: number;
  maximized: boolean;
}

const DEFAULTS: WindowState = { width: 1280, height: 800, maximized: false };

function statePath(): string {
  return join(app.getPath('userData'), 'window-state.json');
}

function read(): WindowState {
  const path = statePath();
  if (!existsSync(path)) return { ...DEFAULTS };
  try {
    const raw = readFileSync(path, 'utf-8');
    const parsed = JSON.parse(raw) as Partial<WindowState>;
    return { ...DEFAULTS, ...parsed };
  } catch {
    return { ...DEFAULTS };
  }
}

function inBounds(state: WindowState): boolean {
  if (state.x === undefined || state.y === undefined) return true;
  const displays = screen.getAllDisplays();
  return displays.some(
    (d) =>
      state.x! >= d.bounds.x &&
      state.y! >= d.bounds.y &&
      state.x! + state.width <= d.bounds.x + d.bounds.width &&
      state.y! + state.height <= d.bounds.y + d.bounds.height,
  );
}

export function loadInitialState(): WindowState {
  const state = read();
  if (!inBounds(state)) {
    return { ...DEFAULTS, maximized: state.maximized };
  }
  return state;
}

export function attachStatePersistence(win: BrowserWindow): void {
  const persist = () => {
    if (win.isDestroyed()) return;
    const isMaximized = win.isMaximized();
    const bounds = isMaximized ? win.getNormalBounds() : win.getBounds();
    const state: WindowState = {
      x: bounds.x,
      y: bounds.y,
      width: bounds.width,
      height: bounds.height,
      maximized: isMaximized,
    };
    const path = statePath();
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, JSON.stringify(state, null, 2), 'utf-8');
  };
  win.on('resize', persist);
  win.on('move', persist);
  win.on('close', persist);
}
