let context = null;

export function activate(ctx) {
  context = ctx;
  ctx.log('familiar activated');
  ctx.ipc.handle('status', () => ({ running: false, note: 'scaffold' }));
}

export function deactivate() {
  context = null;
}
