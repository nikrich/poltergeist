import Table from '@tiptap/extension-table';
import TableCell from '@tiptap/extension-table-cell';
import TableHeader from '@tiptap/extension-table-header';
import { isInTable, selectedRect } from '@tiptap/pm/tables';
import type { MarkdownSerializerState } from 'prosemirror-markdown';
import type { Node as PMNode } from 'prosemirror-model';
import { codeSpan } from './status';

export type CellAlign = 'left' | 'center' | 'right';

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    gbTable: { setColumnAlign: (align: CellAlign | null) => ReturnType };
  }
}

/** tiptap-markdown's state adds `inTable`; `out` is internal in prosemirror-markdown's types. */
type TableState = MarkdownSerializerState & { out: string; inTable: boolean };

export function normalizeAlign(v: string | null | undefined): CellAlign | null {
  const s = (v ?? '').trim().toLowerCase();
  return s === 'left' || s === 'center' || s === 'right' ? s : null;
}

export function delimiterFor(align: CellAlign | null): string {
  if (align === 'left') return ':---';
  if (align === 'center') return ':---:';
  if (align === 'right') return '---:';
  return '---';
}

/** GFM splits cells on unescaped pipes — escape every bare `|` in a cell. */
export function escapeTablePipes(s: string): string {
  return s.replace(/(?<!\\)\|/g, '\\|');
}

const alignAttribute = {
  align: {
    default: null,
    parseHTML: (el: HTMLElement) => normalizeAlign(el.style.textAlign || el.getAttribute('align')),
    renderHTML: (a: { align?: CellAlign | null }) => (a.align ? { style: `text-align: ${a.align}` } : {}),
  },
};

export const GbTableCell = TableCell.extend({
  addAttributes() {
    return { ...this.parent?.(), ...alignAttribute };
  },
});

export const GbTableHeader = TableHeader.extend({
  addAttributes() {
    return { ...this.parent?.(), ...alignAttribute };
  },
});

function cells(row: PMNode): PMNode[] {
  const out: PMNode[] = [];
  row.forEach((c) => out.push(c));
  return out;
}

function span(cell: PMNode): number {
  return Math.max(1, (cell.attrs.colspan as number | undefined) ?? 1);
}

function rowWidth(row: PMNode): number {
  return cells(row).reduce((n, c) => n + span(c), 0);
}

/** Same shape as JotImage's serializer, written inline (no closeBlock) so it stays in the cell. */
function imageMarkdown(node: PMNode): string {
  const alt = ((node.attrs.alt as string | null) ?? '').replace(/([[\]])/g, '\\$1');
  const width = node.attrs.width ? `|${node.attrs.width as number}` : '';
  return `![${alt}${width}](${(node.attrs.src as string | null) ?? ''})`;
}

/**
 * A textblock split at its hard breaks. tiptap-markdown's hardBreak serializer
 * writes the `[hardBreak]` HTML fallback while `state.inTable` is set, so line
 * breaks never reach it: each segment is rendered on its own and joined with a space.
 */
function inlineSegments(block: PMNode): PMNode[] {
  const out: PMNode[] = [];
  let from = 0;
  const push = (to: number): void => {
    if (to > from) out.push(block.copy(block.content.cut(from, to)));
  };
  block.forEach((child, offset) => {
    if (child.type.name !== 'hardBreak') return;
    push(offset);
    from = offset + child.nodeSize;
  });
  push(block.content.size);
  return out;
}

function renderCell(state: TableState, cell: PMNode): void {
  const start = state.out.length;
  let written = 0;
  cell.forEach((child) => {
    if (child.type.spec.code) {
      // Code block: its raw newlines would end the table row — one inline code span instead.
      const text = child.textContent.replace(/\s+/g, ' ').trim();
      if (!text) return;
      if (written) state.write(' ');
      state.write(codeSpan(text));
      written++;
    } else if (child.isTextblock) {
      for (const segment of inlineSegments(child)) {
        if (written) state.write(' ');
        state.renderInline(segment);
        written++;
      }
    } else if (child.type.name === 'image') {
      // Block image (JotImage is inline: false) — textContent would drop it.
      if (!child.attrs.src) return;
      if (written) state.write(' ');
      state.write(imageMarkdown(child));
      written++;
    } else {
      const text = child.textContent.replace(/\s+/g, ' ').trim();
      if (!text) return;
      if (written) state.write(' ');
      state.text(text);
      written++;
    }
  });
  // Backstop: a newline anywhere in the cell would split the row.
  state.out = state.out.slice(0, start) + escapeTablePipes(state.out.slice(start).replace(/\n/g, ' '));
}

/**
 * Always emits a GFM table (never tiptap-markdown's `[table]` HTML fallback):
 *  - alignment from the first row's cells → delimiter row;
 *  - no header row → an empty header row (`|  |  |`), stripped again on parse;
 *  - multi-paragraph / block cells → joined with a single space;
 *  - code blocks → one inline code span (whitespace collapsed);
 *  - colspans → padded with empty cells.
 */
export function serializeTable(rawState: MarkdownSerializerState, node: PMNode): void {
  const state = rawState as TableState;
  const rows = cells(node);
  const first = rows[0];
  if (!first) {
    state.closeBlock(node);
    return;
  }
  const width = Math.max(...rows.map(rowWidth));
  const hasHeader = cells(first).every((c) => c.type.name === 'tableHeader');
  state.inTable = true;

  const writeRow = (row: PMNode | null): void => {
    state.write('| ');
    let col = 0;
    for (const cell of row ? cells(row) : []) {
      if (col) state.write(' | ');
      renderCell(state, cell);
      col++;
      for (let s = 1; s < span(cell); s++) {
        state.write(' | ');
        col++;
      }
    }
    for (; col < width; col++) state.write(col ? ' | ' : '');
    state.write(' |');
    state.ensureNewLine();
  };

  const aligns: Array<CellAlign | null> = [];
  for (const cell of cells(first)) {
    for (let s = 0; s < span(cell); s++) aligns.push((cell.attrs.align as CellAlign | null) ?? null);
  }
  while (aligns.length < width) aligns.push(null);

  writeRow(hasHeader ? first : null);
  state.write(`| ${aligns.map(delimiterFor).join(' | ')} |`);
  state.ensureNewLine();
  for (const row of hasHeader ? rows.slice(1) : rows) writeRow(row);

  state.closeBlock(node);
  state.inTable = false;
}

/** parse.updateDOM: an all-empty header row above ≥1 body row means "headerless". */
export function stripEmptyHeaderRows(root: HTMLElement): void {
  root.querySelectorAll('table').forEach((table) => {
    const thead = table.tHead;
    const body = table.tBodies[0];
    if (!thead || !body || body.rows.length === 0) return;
    const ths = Array.from(thead.querySelectorAll('th'));
    if (ths.length === 0) return;
    if (ths.some((th) => (th.textContent ?? '').trim() !== '' || th.children.length > 0)) return;
    thead.remove();
  });
}

export const GbTable = Table.extend({
  addCommands() {
    return {
      ...this.parent?.(),
      setColumnAlign:
        (align) =>
        ({ state, tr, dispatch }) => {
          if (!isInTable(state)) return false;
          if (dispatch) {
            const rect = selectedRect(state);
            const seen = new Set<number>();
            for (let row = 0; row < rect.map.height; row++) {
              for (let col = rect.left; col < rect.right; col++) {
                const cellPos = rect.map.map[row * rect.map.width + col]!;
                if (seen.has(cellPos)) continue;
                seen.add(cellPos);
                const cell = rect.table.nodeAt(cellPos);
                if (!cell) continue;
                tr.setNodeMarkup(rect.tableStart + cellPos, undefined, { ...cell.attrs, align });
              }
            }
          }
          return true;
        },
    };
  },

  addStorage() {
    return {
      markdown: {
        serialize: serializeTable,
        parse: {
          updateDOM(element: HTMLElement) {
            stripEmptyHeaderRows(element);
          },
        },
      },
    };
  },
});
