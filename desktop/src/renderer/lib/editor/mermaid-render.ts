export type MermaidResult = { ok: true; svg: string } | { ok: false; error: string };

type MermaidApi = {
  initialize(config: Record<string, unknown>): void;
  render(id: string, text: string): Promise<{ svg: string }>;
};

let loader: Promise<MermaidApi> | null = null;
let counter = 0;

/** Lazy: the mermaid chunk only loads when a diagram is actually on screen. */
function loadMermaid(): Promise<MermaidApi> {
  loader ??= import('mermaid')
    .then((m) => m.default as unknown as MermaidApi)
    .catch((err: unknown) => {
      loader = null; // allow a retry after a failed chunk load
      throw err;
    });
  return loader;
}

export function resetMermaidForTests(): void {
  loader = null;
  counter = 0;
}

export async function renderMermaid(source: string): Promise<MermaidResult> {
  if (source.trim() === '') return { ok: false, error: 'empty diagram' };
  const id = `gb-mermaid-${++counter}`;
  try {
    const mermaid = await loadMermaid();
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      theme: document.body.dataset.theme === 'light' ? 'default' : 'dark',
      fontFamily: 'inherit',
    });
    const { svg } = await mermaid.render(id, source);
    return { ok: true, svg };
  } catch (err) {
    // mermaid leaves a temporary container behind on parse errors.
    document.getElementById(id)?.remove();
    document.getElementById(`d${id}`)?.remove();
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }
}
