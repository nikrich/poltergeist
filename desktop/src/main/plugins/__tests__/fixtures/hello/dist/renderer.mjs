export function mount(el) {
  el.textContent = 'hello';
  return () => {};
}
