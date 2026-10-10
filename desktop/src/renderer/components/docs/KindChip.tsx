// desktop/src/renderer/components/docs/KindChip.tsx
import type { DocSummary } from '../../../shared/api-types';
import { KIND_META, kindLabel } from './kinds';

export function KindChip({ doc }: { doc: Pick<DocSummary, 'kind' | 'original'> }) {
  const meta = KIND_META[doc.kind] ?? KIND_META.opaque;
  return (
    <span
      className="shrink-0 rounded-[4px] px-[5px] py-[2px] font-mono text-9 font-semibold tracking-[0.06em]"
      style={{ color: meta.fg, background: meta.bg }}
    >
      {kindLabel(doc)}
    </span>
  );
}
