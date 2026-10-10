import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { KIND_COLORS, KIND_LABELS, NOTE_KINDS, ONTOLOGY_KINDS } from '../lib/graph/kinds';

describe('graph kinds', () => {
  it('lists the sidecar kinds in spec order', () => {
    expect(NOTE_KINDS).toEqual(['person', 'meeting', 'decision', 'action', 'ticket', 'doc', 'jot', 'note']);
    expect(Object.keys(KIND_LABELS).sort()).toEqual([...new Set([...NOTE_KINDS, ...ONTOLOGY_KINDS])].sort());
  });

  it('mirrors the --kind-* design tokens', () => {
    // Vitest runs with cwd = desktop/.
    const css = readFileSync('colors_and_type.css', 'utf8');
    for (const kind of NOTE_KINDS) {
      const m = css.match(new RegExp(`--kind-${kind}:\\s*(#[0-9A-Fa-f]{6})`));
      expect(m?.[1]?.toUpperCase(), kind).toBe(KIND_COLORS[kind].toUpperCase());
    }
  });

  it('mirrors the ontology --kind-* tokens and labels every kind', () => {
    const css = readFileSync('colors_and_type.css', 'utf8');
    for (const kind of ONTOLOGY_KINDS) {
      const m = css.match(new RegExp(`--kind-${kind}:\\s*(#[0-9A-Fa-f]{6})`));
      expect(m?.[1]?.toUpperCase(), kind).toBe(KIND_COLORS[kind].toUpperCase());
      expect(KIND_LABELS[kind]).toBeTruthy();
    }
  });
});
