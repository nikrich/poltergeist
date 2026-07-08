export function mount(el, api) {
  el.textContent = `Familiar scaffold (plugin ${api.pluginId})`;
  return () => {};
}
