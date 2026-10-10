import { Lucide } from '../Lucide';

/** Ancestors only (the page itself is the title). Plain text: a context or a
 * folder has no page to open. Chevrons, never middle dots. */
function PageBreadcrumb({ items }: { items: string[] }) {
  if (items.length === 0) return null;
  return (
    <nav aria-label="breadcrumb" className="mb-2">
      <ol className="flex flex-wrap items-center gap-x-1 gap-y-0.5 text-12 leading-5 text-ink-2">
        {items.map((it, i) => (
          <li key={`${i}:${it}`} className="flex min-w-0 items-center gap-1">
            {i > 0 && (
              <span aria-hidden className="flex flex-shrink-0 items-center text-ink-3">
                <Lucide name="chevron-right" size={12} />
              </span>
            )}
            <span className="max-w-[18rem] truncate">{it}</span>
          </li>
        ))}
      </ol>
    </nav>
  );
}

interface Props {
  breadcrumb: string[];
  title: React.ReactNode;
  byline?: React.ReactNode;
  /** A4 focus mode: the title alone. */
  focus: boolean;
}

/** Breadcrumb, the page's big title, then the byline. Only the title is loud. */
export function PageHeader({ breadcrumb, title, byline, focus }: Props) {
  return (
    <div className="gb-page-header" data-testid="page-header">
      {!focus && <PageBreadcrumb items={breadcrumb} />}
      {title}
      {!focus && byline}
    </div>
  );
}
