import type { Node as PMNode } from '@tiptap/pm/model';

/** One sentence to speak. `from`/`to` are the doc range (for the highlight);
 * `text` is what the voice says, with markdown-only noise removed. */
export interface SpeechSegment {
  from: number;
  to: number;
  text: string;
}

const SENTENCES = new Intl.Segmenter(undefined, { granularity: 'sentence' });
const WIKILINK = /\[\[([^\][|]+?)(?:\|([^\]]+))?\]\]/g;
const URL_RE = /\bhttps?:\/\/\S+/gi;
const TAG = /(^|\s)#([\p{L}\p{N}_][\p{L}\p{N}_/-]*)/gu;
const HAS_WORD = /[\p{L}\p{N}]/u;

/** Spoken form of a sentence: wikilinks → alias (or note name), tags → words,
 * bare URLs → "link", whitespace collapsed. */
export function speakable(raw: string): string {
  return raw
    .replace(WIKILINK, (_m: string, target: string, alias?: string) => {
      const label = alias ?? (target.split('/').pop() ?? target).replace(/\.md$/, '');
      return label.replace(/^@/, '');
    })
    .replace(URL_RE, 'link')
    .replace(TAG, (_m: string, pre: string, tag: string) => `${pre}${tag.replace(/[/_-]+/g, ' ')}`)
    .replace(/\s+/g, ' ')
    .trim();
}

/** Sentences of every textblock in document order. Code blocks (any node
 * whose spec says `code: true`, which includes mermaid fences) are skipped.
 * Inline non-text nodes (hard break, status lozenge) count as spaces of their
 * node size, so char index i ↔ doc position contentStart + i holds exactly.
 * With `range`, only the part inside it is returned (partial sentences
 * clipped). */
export function collectSegments(
  doc: PMNode,
  range?: { from: number; to: number },
): SpeechSegment[] {
  const out: SpeechSegment[] = [];
  doc.descendants((node, pos) => {
    if (node.type.spec.code) return false;
    if (!node.isTextblock) return true;
    const contentStart = pos + 1;
    let text = '';
    node.forEach((child) => {
      text += child.isText ? (child.text ?? '') : ' '.repeat(child.nodeSize);
    });
    const lo = range ? Math.max(0, range.from - contentStart) : 0;
    const hi = range ? Math.min(text.length, range.to - contentStart) : text.length;
    if (hi <= lo) return false;
    for (const s of SENTENCES.segment(text)) {
      let a = Math.max(s.index, lo);
      let b = Math.min(s.index + s.segment.length, hi);
      while (a < b && /\s/.test(text[a]!)) a++;
      while (b > a && /\s/.test(text[b - 1]!)) b--;
      if (b <= a) continue;
      const spoken = speakable(text.slice(a, b));
      if (!HAS_WORD.test(spoken)) continue;
      out.push({ from: contentStart + a, to: contentStart + b, text: spoken });
    }
    return false;
  });
  return out;
}

/** Index of the sentence containing `pos` (or the next one after it); 0 when
 * the cursor is past the last sentence, so "read" starts from the top. */
export function startIndexFor(segments: SpeechSegment[], pos: number): number {
  const i = segments.findIndex((s) => s.to > pos);
  return i === -1 ? 0 : i;
}
