// Renderer entry. Task 11 replaces this stub with the React app.
export function mount(el) {
  el.textContent = 'Script Writer';
  return () => { el.textContent = ''; };
}
