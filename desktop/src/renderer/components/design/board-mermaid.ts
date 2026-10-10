import type { BoardItemKind, BoardModel } from '../../../shared/design-types';

/** Mermaid node shape per kind; actors and hotspots stay on the sticky board. */
const SHAPES: Partial<Record<BoardItemKind, [string, string]>> = {
  command: ['[', ']'],
  aggregate: ['[[', ']]'],
  event: ['([', '])'],
  policy: ['{{', '}}'],
  read_model: ['[(', ')]'],
  external: ['>', ']'],
};

const CLASS_DEFS: Partial<Record<BoardItemKind, string>> = {
  command: 'fill:#60a5fa,stroke:#2563eb,color:#0E0F12',
  aggregate: 'fill:#fde047,stroke:#ca8a04,color:#0E0F12',
  event: 'fill:#f59e0b,stroke:#b45309,color:#0E0F12',
  policy: 'fill:#c4b5fd,stroke:#7c3aed,color:#0E0F12',
  read_model: 'fill:#86efac,stroke:#16a34a,color:#0E0F12',
  external: 'fill:#f9a8d4,stroke:#db2777,color:#0E0F12',
};

/** Quoted mermaid label: entity codes for the characters that would end
 *  the string or be read as markup. */
export function escapeMermaidLabel(text: string): string {
  return text
    .replace(/#/g, '#35;')
    .replace(/"/g, '#quot;')
    .replace(/</g, '#lt;')
    .replace(/>/g, '#gt;')
    .replace(/\s*\n\s*/g, ' ')
    .trim();
}

function makeIdFactory(prefix: string): (raw: string) => string {
  const assigned = new Map<string, string>();
  const used = new Set<string>();
  return (raw) => {
    const existing = assigned.get(raw);
    if (existing) return existing;
    const base = `${prefix}${raw.replace(/[^A-Za-z0-9]/g, '_')}`;
    let id = base;
    for (let n = 2; used.has(id); n++) id = `${base}_${n}`;
    used.add(id);
    assigned.set(raw, id);
    return id;
  };
}

/** The architecture view of an event-storming board as a mermaid flowchart:
 *  a subgraph per bounded context, kind-shaped nodes, edges from links. */
export function boardToMermaid(model: BoardModel): string {
  const nodeId = makeIdFactory('n_');
  const ctxId = makeIdFactory('ctx_');
  const items = model.items
    .map((item, index) => ({ item, index }))
    .sort((a, b) => a.item.order - b.item.order || a.index - b.index)
    .map(({ item }) => item)
    .filter((i) => SHAPES[i.kind]);
  // Assign ids in model order so they don't depend on which nodes render.
  for (const item of items) nodeId(item.id);

  const node = (item: (typeof items)[number], indent: string) => {
    const [open, close] = SHAPES[item.kind]!;
    return `${indent}${nodeId(item.id)}${open}"${escapeMermaidLabel(item.label)}"${close}`;
  };

  const lines = ['flowchart LR'];
  const known = new Set(model.contexts.map((c) => c.id));
  for (const ctx of model.contexts) {
    const members = items.filter((i) => i.context === ctx.id);
    if (members.length === 0) continue;
    lines.push(`  subgraph ${ctxId(ctx.id)}["${escapeMermaidLabel(ctx.name)}"]`);
    for (const item of members) lines.push(node(item, '    '));
    lines.push('  end');
  }
  for (const item of items) {
    if (item.context === null || !known.has(item.context)) lines.push(node(item, '  '));
  }

  const shown = new Set(items.map((i) => i.id));
  for (const link of model.links) {
    if (shown.has(link.from) && shown.has(link.to)) {
      lines.push(`  ${nodeId(link.from)} --> ${nodeId(link.to)}`);
    }
  }

  for (const [kind, style] of Object.entries(CLASS_DEFS)) {
    const members = items.filter((i) => i.kind === kind).map((i) => nodeId(i.id));
    if (members.length === 0) continue;
    lines.push(`  classDef ${kind} ${style}`);
    lines.push(`  class ${members.join(',')} ${kind}`);
  }
  return lines.join('\n');
}
