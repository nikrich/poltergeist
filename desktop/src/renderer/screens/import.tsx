import { useState } from 'react';
import { TopBar } from '../components/TopBar';
import { Btn } from '../components/Btn';
import { Lucide } from '../components/Lucide';
import { PanelEmpty } from '../components/PanelEmpty';
import { PanelError } from '../components/PanelError';
import { SkeletonRows } from '../components/SkeletonRows';
import { ApiError } from '../lib/api/client';
import {
  useConfluencePages,
  useConfluenceSearch,
  useImportItems,
  useImportSpaces,
  useJiraIssues,
} from '../lib/api/hooks';
import { useNavigation } from '../stores/navigation';
import { toast } from '../stores/toast';
import type {
  ImportItem,
  ImportItemResult,
  ImportJiraIssue,
  ImportPage,
  ImportSpace,
} from '../../shared/api-types';

type ImportTab = 'confluence' | 'jira';

export function selectionKey(item: ImportItem): string {
  return `${item.kind}:${item.site}:${item.id ?? item.key ?? ''}`;
}

function isNotConfigured(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409;
}

function errMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

// Same chip styling as the capture screen's source filter strip.
function tabClass(active: boolean): string {
  return `cursor-pointer rounded-sm border px-[10px] py-1 font-mono text-11 ${
    active
      ? 'border-neon/30 bg-neon/15 text-neon-ink'
      : 'border-hairline-2 bg-transparent text-ink-1'
  }`;
}

interface BrowseProps {
  query: string;
  selection: Map<string, ImportItem>;
  marks: Record<string, ImportItemResult>;
  onToggle: (item: ImportItem) => void;
}

export function ImportScreen() {
  const [tab, setTab] = useState<ImportTab>('confluence');
  const [confluenceQuery, setConfluenceQuery] = useState('');
  const [jiraQuery, setJiraQuery] = useState('');
  const [selection, setSelection] = useState<Map<string, ImportItem>>(new Map());
  const [progress, setProgress] = useState<string | null>(null);
  const [marks, setMarks] = useState<Record<string, ImportItemResult>>({});
  const importer = useImportItems();

  const query = tab === 'confluence' ? confluenceQuery : jiraQuery;
  const setQuery = tab === 'confluence' ? setConfluenceQuery : setJiraQuery;

  const toggle = (item: ImportItem) => {
    setSelection((prev) => {
      const next = new Map(prev);
      const key = selectionKey(item);
      if (next.has(key)) next.delete(key);
      else next.set(key, item);
      return next;
    });
  };

  const runImport = () => {
    const items = [...selection.values()];
    if (items.length === 0) return;
    setMarks({});
    importer.mutate(
      {
        items,
        onItem: (done, total, current) =>
          setProgress(`${done + 1}/${total} — importing ${current.key ?? current.id}…`),
      },
      {
        onSuccess: ({ results }) => {
          // The mutation posts items in order, one per request, so
          // results[i] belongs to items[i].
          const nextMarks: Record<string, ImportItemResult> = {};
          const keep = new Map<string, ImportItem>();
          results.forEach((result, i) => {
            const item = items[i]!;
            const key = selectionKey(item);
            nextMarks[key] = result;
            if (!result.ok) keep.set(key, item); // failed stays ticked for retry
          });
          setMarks(nextMarks);
          setSelection(keep);
          const failed = results.filter((r) => !r.ok).length;
          const okCount = results.length - failed;
          if (failed > 0) toast.error(`imported ${okCount} · ${failed} failed`);
          else toast.success(`imported ${okCount}`);
        },
        onError: (err) => toast.error(errMessage(err, 'import failed')),
        onSettled: () => setProgress(null),
      },
    );
  };

  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-paper">
      <TopBar title="import" subtitle="pull confluence pages + jira issues into the vault" />

      {/* tab strip + search */}
      <div className="flex flex-shrink-0 items-center gap-[6px] border-b border-hairline px-6 py-3">
        <button type="button" onClick={() => setTab('confluence')} className={tabClass(tab === 'confluence')}>
          confluence
        </button>
        <button type="button" onClick={() => setTab('jira')} className={tabClass(tab === 'jira')}>
          jira
        </button>
        <div className="ml-3 flex flex-1 items-center gap-2 rounded-r6 border border-hairline-2 bg-vellum px-3 py-[6px]">
          <Lucide name="search" size={13} color="var(--ink-2)" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={tab === 'confluence' ? 'search pages by title…' : 'search issues…'}
            className="flex-1 border-none bg-transparent text-13 text-ink-0 placeholder:text-ink-3 focus:outline-none"
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4">
        {tab === 'confluence' ? (
          <ConfluenceBrowse query={confluenceQuery} selection={selection} marks={marks} onToggle={toggle} />
        ) : (
          <JiraBrowse query={jiraQuery} selection={selection} marks={marks} onToggle={toggle} />
        )}
      </div>

      {(selection.size > 0 || importer.isPending) && (
        <SelectionBar
          count={selection.size}
          progress={progress}
          busy={importer.isPending}
          onImport={runImport}
          onClear={() => setSelection(new Map())}
        />
      )}
    </div>
  );
}

// ── Confluence tab ──────────────────────────────────────────────────────

function ConfluenceBrowse({ query, selection, marks, onToggle }: BrowseProps) {
  const spaces = useImportSpaces();
  const searching = query.trim().length >= 2;
  const search = useConfluenceSearch(query);

  if (searching) {
    if (search.isLoading) return <SkeletonRows count={4} />;
    if (search.isError) {
      if (isNotConfigured(search.error)) return <NotConfigured connector="confluence" />;
      return (
        <PanelError
          message={errMessage(search.error, 'search failed')}
          onRetry={() => search.refetch()}
        />
      );
    }
    const hits = search.data ?? [];
    if (hits.length === 0) {
      return <PanelEmpty icon="search" message="no pages match in the monitored spaces" />;
    }
    return (
      <div className="flex flex-col gap-[2px]">
        {hits.map((page) => (
          <PageRow
            key={`${page.site}:${page.id}`}
            page={page}
            depth={0}
            expandable={false}
            selection={selection}
            marks={marks}
            onToggle={onToggle}
          />
        ))}
      </div>
    );
  }

  if (spaces.isLoading) return <SkeletonRows count={4} />;
  if (spaces.isError) {
    if (isNotConfigured(spaces.error)) return <NotConfigured connector="confluence" />;
    return (
      <PanelError
        message={errMessage(spaces.error, 'failed to load spaces')}
        onRetry={() => spaces.refetch()}
      />
    );
  }
  const rows = spaces.data ?? [];
  if (rows.length === 0) {
    return <PanelEmpty icon="inbox" message="no monitored spaces — add confluence.spaces to routing.yaml" />;
  }
  return (
    <div className="flex flex-col gap-2">
      {rows.map((space) => (
        <SpaceSection
          key={`${space.site}:${space.key}`}
          space={space}
          selection={selection}
          marks={marks}
          onToggle={onToggle}
        />
      ))}
    </div>
  );
}

function SpaceSection({
  space,
  selection,
  marks,
  onToggle,
}: {
  space: ImportSpace;
  selection: Map<string, ImportItem>;
  marks: Record<string, ImportItemResult>;
  onToggle: (item: ImportItem) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="rounded-r6 border border-hairline bg-vellum">
      <button
        type="button"
        aria-label={`toggle space ${space.key}`}
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full cursor-pointer items-center gap-2 border-0 bg-transparent px-3 py-[10px] text-left"
      >
        <Lucide name={expanded ? 'chevron-down' : 'chevron-right'} size={13} color="var(--ink-2)" />
        <span className="font-mono text-11 text-ink-2">{space.key}</span>
        <span className="flex-1 text-13 font-medium text-ink-0">{space.name}</span>
        <span className="font-mono text-9 text-ink-3">→ {space.context}</span>
      </button>
      {expanded && (
        <div className="border-t border-hairline px-2 py-2">
          <PageList
            site={space.site}
            space={space.key}
            depth={0}
            selection={selection}
            marks={marks}
            onToggle={onToggle}
          />
        </div>
      )}
    </div>
  );
}

function PageList({
  site,
  space,
  parent,
  depth,
  selection,
  marks,
  onToggle,
}: {
  site: string;
  space: string;
  parent?: string;
  depth: number;
  selection: Map<string, ImportItem>;
  marks: Record<string, ImportItemResult>;
  onToggle: (item: ImportItem) => void;
}) {
  const pages = useConfluencePages(site, space, parent);
  if (pages.isLoading) return <SkeletonRows count={2} height={24} />;
  if (pages.isError) {
    return (
      <PanelError
        message={errMessage(pages.error, 'failed to load pages')}
        onRetry={() => pages.refetch()}
      />
    );
  }
  const items = pages.data?.items ?? [];
  if (items.length === 0) {
    return <p className="m-0 px-2 py-1 text-11 text-ink-3">no pages</p>;
  }
  return (
    <div className="flex flex-col gap-[2px]">
      {items.map((page) => (
        <PageRow
          key={page.id}
          page={page}
          depth={depth}
          expandable
          selection={selection}
          marks={marks}
          onToggle={onToggle}
        />
      ))}
    </div>
  );
}

function PageRow({
  page,
  depth,
  expandable,
  selection,
  marks,
  onToggle,
}: {
  page: ImportPage;
  depth: number;
  expandable: boolean;
  selection: Map<string, ImportItem>;
  marks: Record<string, ImportItemResult>;
  onToggle: (item: ImportItem) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const item: ImportItem = { kind: 'confluence_page', site: page.site, id: page.id };
  const key = selectionKey(item);
  const isFolder = page.type === 'folder';
  const canExpand = expandable && page.hasChildren;
  return (
    <div>
      <div
        className="flex items-center gap-2 rounded-sm px-[6px] py-[5px] hover:bg-vellum"
        style={{ paddingLeft: 6 + depth * 18 }}
      >
        {canExpand ? (
          <button
            type="button"
            aria-label={`${expanded ? 'collapse' : 'expand'} ${page.title}`}
            onClick={() => setExpanded((v) => !v)}
            className="cursor-pointer border-0 bg-transparent p-0"
          >
            <Lucide name={expanded ? 'chevron-down' : 'chevron-right'} size={12} color="var(--ink-2)" />
          </button>
        ) : (
          <span className="inline-block w-3 flex-shrink-0" />
        )}
        {isFolder ? (
          // Folders aren't importable as pages — navigation only.
          <Lucide name="folder" size={13} color="var(--ink-2)" />
        ) : (
          <input
            type="checkbox"
            aria-label={`select ${page.title}`}
            checked={selection.has(key)}
            onChange={() => onToggle(item)}
            className="h-[13px] w-[13px] cursor-pointer accent-[var(--neon)]"
          />
        )}
        <span className="flex-1 overflow-hidden text-ellipsis whitespace-nowrap text-12 text-ink-0">
          {page.title}
        </span>
        {page.space && <span className="font-mono text-9 text-ink-3">{page.space}</span>}
        <ResultMark mark={marks[key]} />
        <span className="font-mono text-9 text-ink-3">{page.updatedAt?.slice(0, 10) ?? ''}</span>
      </div>
      {expanded && page.space && (
        <PageList
          site={page.site}
          space={page.space}
          parent={page.id}
          depth={depth + 1}
          selection={selection}
          marks={marks}
          onToggle={onToggle}
        />
      )}
    </div>
  );
}

// ── Jira tab ────────────────────────────────────────────────────────────

function JiraBrowse({ query, selection, marks, onToggle }: BrowseProps) {
  const issues = useJiraIssues(query);
  if (issues.isLoading) return <SkeletonRows count={4} />;
  if (issues.isError) {
    if (isNotConfigured(issues.error)) return <NotConfigured connector="jira" />;
    return (
      <PanelError
        message={errMessage(issues.error, 'failed to load issues')}
        onRetry={() => issues.refetch()}
      />
    );
  }
  const rows = issues.data ?? [];
  if (rows.length === 0) {
    return <PanelEmpty icon="search" message="no issues found" />;
  }
  return (
    <div className="flex flex-col gap-[2px]">
      {rows.map((issue) => (
        <IssueRow
          key={`${issue.site}:${issue.key}`}
          issue={issue}
          selection={selection}
          marks={marks}
          onToggle={onToggle}
        />
      ))}
    </div>
  );
}

function IssueRow({
  issue,
  selection,
  marks,
  onToggle,
}: {
  issue: ImportJiraIssue;
  selection: Map<string, ImportItem>;
  marks: Record<string, ImportItemResult>;
  onToggle: (item: ImportItem) => void;
}) {
  const item: ImportItem = { kind: 'jira_issue', site: issue.site, key: issue.key };
  const key = selectionKey(item);
  return (
    <div className="flex items-center gap-2 rounded-sm px-[6px] py-[5px] hover:bg-vellum">
      <input
        type="checkbox"
        aria-label={`select ${issue.key}`}
        checked={selection.has(key)}
        onChange={() => onToggle(item)}
        className="h-[13px] w-[13px] cursor-pointer accent-[var(--neon)]"
      />
      <span className="font-mono text-11 text-neon-ink">{issue.key}</span>
      <span className="flex-1 overflow-hidden text-ellipsis whitespace-nowrap text-12 text-ink-0">
        {issue.summary}
      </span>
      <ResultMark mark={marks[key]} />
      {issue.status && <span className="font-mono text-9 text-ink-3">{issue.status}</span>}
    </div>
  );
}

// ── Shared bits ─────────────────────────────────────────────────────────

function ResultMark({ mark }: { mark?: ImportItemResult }) {
  if (!mark) return null;
  if (mark.ok) {
    return (
      <span className="font-mono text-9 text-neon-ink" title={mark.path ?? undefined}>
        {mark.updated ? 'updated' : 'imported'}
      </span>
    );
  }
  return (
    <span className="font-mono text-9 text-oxblood" title={mark.error ?? undefined}>
      failed
    </span>
  );
}

function NotConfigured({ connector }: { connector: string }) {
  const setActive = useNavigation((s) => s.setActive);
  return (
    <PanelEmpty
      icon="plug"
      message={`${connector} is not connected yet — set it up to browse and import`}
      cta={{ label: 'open connectors', onClick: () => setActive('connectors') }}
    />
  );
}

function SelectionBar({
  count,
  progress,
  busy,
  onImport,
  onClear,
}: {
  count: number;
  progress: string | null;
  busy: boolean;
  onImport: () => void;
  onClear: () => void;
}) {
  return (
    <div className="flex flex-shrink-0 items-center gap-3 border-t border-hairline bg-vellum px-6 py-3">
      <span className="font-mono text-11 text-ink-1">
        {progress ?? `${count} selected`}
      </span>
      <div className="flex-1" />
      <Btn variant="ghost" size="sm" onClick={onClear} disabled={busy}>
        clear
      </Btn>
      <Btn
        variant="primary"
        size="sm"
        icon={<Lucide name="download" size={13} />}
        onClick={onImport}
        disabled={busy || count === 0}
        ariaLabel={`import ${count} selected`}
      >
        import {count} selected
      </Btn>
    </div>
  );
}
