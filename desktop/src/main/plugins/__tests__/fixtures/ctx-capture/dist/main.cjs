module.exports = {
  activate(ctx) {
    globalThis.__lastCtx = ctx;
  },
  deactivate() {
    globalThis.__lastCtx = undefined;
  },
};
