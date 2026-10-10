import { useMemo } from 'react';
import { lineDiff } from '../lib/line-diff';

const lineClass = {
  same: 'text-ink-2',
  del: 'bg-oxblood/10 text-oxblood',
  add: 'bg-neon/10 text-ink-0',
} as const;
const prefix = { same: '  ', del: '- ', add: '+ ' } as const;

interface Props {
  oldText: string;
  newText: string;
  /** One-line key, e.g. "- theirs · + yours". */
  legend: string;
  testId?: string;
  className?: string;
}

/** Line diff of oldText → newText (conflict banner, page history, B2's Changes screen). */
export function LineDiffView({ oldText, newText, legend, testId, className = '' }: Props) {
  const lines = useMemo(() => lineDiff(oldText, newText), [oldText, newText]);
  return (
    <pre
      data-testid={testId}
      className={`overflow-auto rounded-sm border border-hairline bg-paper p-2 font-mono text-11 ${className}`}
    >
      <div className="mb-1 text-ink-3">{legend}</div>
      {lines.map((line, i) => (
        <div key={i} className={lineClass[line.kind]}>
          {prefix[line.kind]}
          {line.text}
        </div>
      ))}
    </pre>
  );
}
