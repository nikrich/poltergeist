module.exports = {
  activate(ctx) {
    ctx.ipc.handle('ping', () => 'pong-' + ctx.pluginId);
  },
  deactivate() {},
};
