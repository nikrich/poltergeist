import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { renderMermaid, type MermaidResult } from '../../lib/editor/mermaid-render';
import { sanitizedDiagramFragment } from '../../lib/editor/svg-sanitize';
import { boardToMermaid } from './board-mermaid';
import type { BoardModel } from '../../../shared/design-types';

interface Props {
  model: BoardModel;
}

/** The board as an architecture flowchart (contexts as subgraphs). */
export function ArchitectureView({ model }: Props) {
  const source = useMemo(() => boardToMermaid(model), [model]);
  const [result, setResult] = useState<MermaidResult | null>(null);
  const svgHost = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let live = true;
    void renderMermaid(source).then((r) => {
      if (live) setResult(r);
    });
    return () => {
      live = false;
    };
  }, [source]);

  // Sanitised in an inert template before it reaches the live DOM.
  useLayoutEffect(() => {
    if (result?.ok === true) svgHost.current?.replaceChildren(sanitizedDiagramFragment(result.svg));
  }, [result]);

  if (result?.ok === false) {
    return (
      <div className="p-4 text-12 text-ink-2">
        Couldn&apos;t draw the architecture view: {result.error}
      </div>
    );
  }
  return (
    <div className="h-full min-h-[240px] overflow-auto rounded-md border border-hairline bg-paper p-4">
      {result === null && <div className="font-mono text-11 text-ink-3">Drawing…</div>}
      <div ref={svgHost} aria-label="Architecture diagram" />
    </div>
  );
}
