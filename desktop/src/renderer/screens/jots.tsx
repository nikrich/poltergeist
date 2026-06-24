import { useEffect, useMemo, useRef, useState } from 'react';
import { TopBar } from '../components/TopBar';
import { Btn } from '../components/Btn';
import { ConfluenceExportDialog } from '../components/ConfluenceExportDialog';
import { Lucide } from '../components/Lucide';
import { Pill } from '../components/Pill';
import { JotTree } from '../components/JotTree';
import { RichMarkdownEditor } from '../components/RichMarkdownEditor';
import type { EditorHandle } from '../components/RichMarkdownEditor';
import { DocsAssistPanel } from '../components/DocsAssistPanel';
import {
  useAutoRouteJot,
  useConnectors,
  useCreateJot,
  useDeleteJot,
  useExtractPhoto,
  useJot,
  useJots,
  useProjects,
  useRouteJot,
  useUpdateJot,
} from '../lib/api/hooks';
import { toast } from '../stores/toast';
import { useNoteView } from '../stores/note-view';
import { useDocsAssist } from '../stores/docs-assist';

const KNOWN_CONTEXTS = ['sanlam', 'codeship', 'reducedrecipes', 'personal'];

export function JotsScreen() {
  const [q, setQ] = useState('');
  const openNote = useNoteView((s) => s.open);
  const list = useJots({ q: q || undefined });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showConfluenceDialog, setShowConfluenceDialog] = useState(false);
  const [cameraSignal, setCameraSignal] = useState(0);

  const assistOpen = useDocsAssist((s) => s.open);
  const toggleAssist = useDocsAssist((s) => s.toggleOpen);

  const selectedItem = useMemo(
    () => list.data?.items.find((i) => i.id === selectedId) ?? null,
    [list.data, selectedId],
  );

  const detail = useJot(selectedItem?.path ?? null);

  // Autosave-race mitigation:
  // useJots polls every 5s and useJot invalidates after autosave. Without a
  // guard, every React Query refetch would update `detail.data.body` and the
  // body prop passed to JotEditor would change — resetting the editor
  // mid-typing (the useEffect([body]) in JotEditor clears its internal state).
  //
  // Fix: capture the FIRST successful body for each selectedId in a ref. The
  // JotEditor is rendered with `key={selectedId}` so it remounts when the user
  // switches jots (wiping old debounce timers cleanly), but it does NOT remount
  // on background refetches. The frozen `initialBody` from the ref is passed as
  // the `body` prop; subsequent RQ refetches change `detail.data.body` but do
  // NOT change `initialBody`, so the editor never sees a mid-session prop flip.
  // On jot switch the ref is cleared and repopulated when the new detail lands.
  const initialBodyRef = useRef<{ id: string; body: string } | null>(null);
  if (
    detail.data &&
    selectedId &&
    (initialBodyRef.current === null || initialBodyRef.current.id !== selectedId)
  ) {
    initialBodyRef.current = { id: selectedId, body: detail.data.body };
  }
  if (selectedId === null) {
    initialBodyRef.current = null;
  }
  const editorBody =
    initialBodyRef.current?.id === selectedId ? initialBodyRef.current.body : undefined;

  // Imperative handle wired to the editor for docs-assist and PDF export.
  const editorHandle = useRef<EditorHandle | null>(null);

  const connectors = useConnectors();
  const confluenceConnector = connectors.data?.find((c) => c.id === 'confluence');
  const confluenceEnabled = confluenceConnector?.state === 'on';

  const projects = useProjects();
  const createJot = useCreateJot();
  const updateJot = useUpdateJot();
  const routeJot = useRouteJot();
  const autoRoute = useAutoRouteJot();
  const extractPhoto = useExtractPhoto();
  const deleteJot = useDeleteJot();

  // Auto-select the newest jot when the list first loads.
  useEffect(() => {
    if (selectedId === null && list.data?.items.length) {
      setSelectedId(list.data.items[0]!.id);
    }
  }, [list.data, selectedId]);

  // Auto-route on leave: when the user moves away from an unrouted jot, fire
  // route-auto in the background.
  //
  // currentSelectionRef always holds the latest {id, status} so the unmount
  // cleanup and the selectedId-change effect can both read it without stale
  // closures. It is updated on every render (not just inside an effect) so it
  // always reflects the current list state.
  const currentSelectionRef = useRef<{ id: string; status: string; excerpt: string } | null>(
    null,
  );
  currentSelectionRef.current =
    selectedId && selectedItem
      ? {
          id: selectedId,
          status: selectedItem.routingStatus,
          excerpt: selectedItem.excerpt,
        }
      : null;

  // Placeholder/empty jots would just round-trip to manual_review — skip the
  // LLM call entirely until there's real content.
  const isRoutableContent = (excerpt: string) => {
    const t = excerpt.trim();
    return t !== '' && t !== 'new jot';
  };

  const fireAutoRoute = (id: string) => {
    autoRoute.mutate(id, {
      onSuccess: (res) => {
        if (res.routingStatus === 'routed' && res.context) {
          toast.info(`filed to ${res.context}`);
        }
        // No toast when it stays manual_review — ambiguous content, silent is fine
      },
      // No error toast — fire-and-forget, don't alarm the user
    });
  };

  // prevIdRef tracks the id that was selected *before* the latest selectedId change.
  const prevIdRef = useRef<string | null>(null);

  // Leave-by-switch lives in the effect BODY. Deliberately no cleanup here:
  // an effect cleanup also runs on every selectedId change, at which point the
  // ref already points at the NEWLY selected jot — routing it on arrival was a
  // double-fire bug. Unmount is handled by the mount-once effect below.
  useEffect(() => {
    const prevId = prevIdRef.current;
    prevIdRef.current = selectedId;

    if (prevId && prevId !== selectedId) {
      const prevItem = list.data?.items.find((i) => i.id === prevId);
      if (
        prevItem &&
        prevItem.routingStatus !== 'routed' &&
        isRoutableContent(prevItem.excerpt)
      ) {
        fireAutoRoute(prevId);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  // Unmount-only: route the jot the user was holding when they left the screen.
  useEffect(() => {
    return () => {
      const current = currentSelectionRef.current;
      if (current && current.status !== 'routed' && isRoutableContent(current.excerpt)) {
        autoRoute.mutate(current.id);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleNew() {
    createJot.mutate(
      { body: 'new jot\n\n', route: false },
      {
        onSuccess: (res) => {
          setSelectedId(res.id);
          toast.info('jot created');
        },
        onError: (err) => toast.error(`could not create jot: ${err.message}`),
      },
    );
  }

  function handleSaveBody(next: string) {
    if (!selectedId) return;
    updateJot.mutate({ id: selectedId, body: next });
  }

  function handleReroute(value: string) {
    if (!selectedId) return;
    // After re-routing, the file path changes. The list refetches via
    // useRouteJot's onSuccess invalidation, and selectedItem is resolved from
    // the refreshed list by id — so the editor path updates automatically via
    // useJot(selectedItem?.path). The initialBodyRef is keyed by selectedId
    // (not path), so it does not go stale on path change. No special handling
    // needed; the editor continues showing the correct content.
    const [context, project] = value.includes('/') ? value.split('/', 2) : [value, undefined];
    const dest = project ? `${context} / ${project}` : context;
    routeJot.mutate(
      { id: selectedId, context: context!, project },
      {
        onSuccess: () => toast.info(`re-routed to ${dest}`),
        onError: (err) => toast.error(`re-route failed: ${err.message}`),
      },
    );
  }

  function handleDelete() {
    if (!selectedId) return;
    deleteJot.mutate(selectedId, {
      onSuccess: () => {
        setSelectedId(null);
        toast.info('jot deleted');
      },
      onError: (err) => toast.error(`delete failed: ${err.message}`),
    });
  }

  function handleExportSelect(value: string) {
    if (!value) return;
    if (value === 'confluence') {
      setShowConfluenceDialog(true);
    } else if (value === 'pdf') {
      const html = editorHandle.current?.getHTML() ?? '';
      if (!html) {
        toast.info('switch to rich mode to export pdf');
        return;
      }
      void window.gb.docs
        .exportPdf({ title: selectedItem?.title ?? 'document', html })
        .then((res) => {
          if ('cancelled' in res) {
            // user dismissed the save dialog — silent
          } else if (res.ok) {
            toast.success(`pdf saved — ${res.path}`);
          } else {
            toast.error(`pdf export failed: ${res.error}`);
          }
        });
    }
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-paper">
      <TopBar
        title="jots"
        subtitle={list.data ? `${list.data.total} total` : '…'}
        right={
          <div className="flex gap-2">
            <Btn
              variant="ghost"
              size="sm"
              icon={<Lucide name="sparkles" size={13} />}
              onClick={toggleAssist}
            >
              assist
            </Btn>
            <Btn
              icon={<Lucide name="camera" size={13} />}
              variant="ghost"
              size="sm"
              onClick={() => {
                if (selectedId) {
                  setCameraSignal((n) => n + 1);
                } else {
                  handleNew();
                  toast.info('jot created — tap capture to add a photo');
                }
              }}
            />
            <Btn
              variant="primary"
              size="sm"
              icon={<Lucide name="plus" size={13} />}
              onClick={handleNew}
              disabled={createJot.isPending}
            >
              new
            </Btn>
          </div>
        }
      />
      <div className="flex flex-shrink-0 border-b border-hairline px-4 py-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="search jots…"
          className="w-full bg-transparent text-12 text-ink-0 outline-none"
        />
      </div>
      <div className="flex flex-1 overflow-hidden">
        <aside className="w-[260px] flex-shrink-0 overflow-y-auto border-r border-hairline">
          {list.data?.items.length === 0 && !list.isLoading && (
            <div className="flex flex-1 items-center justify-center px-4 py-8 text-center text-12 text-ink-3">
              no jots yet — press ⌥-J to create one
            </div>
          )}
          <JotTree
            items={list.data?.items ?? []}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
        </aside>
        <main className="flex flex-1 flex-col">
          {editorBody !== undefined ? (
            <>
              <div className="flex-1 overflow-auto">
                {/* key={selectedId} remounts the editor on jot switch, wiping
                    internal debounce timers. The markdown prop is frozen to
                    the initial fetch so mid-session RQ refetches never reset
                    the editor's internal value. */}
                <RichMarkdownEditor
                  key={selectedId!}
                  markdown={editorBody}
                  onSave={handleSaveBody}
                  onWikilinkClick={openNote}
                  handleRef={editorHandle}
                  jotId={selectedId!}
                  openCameraSignal={cameraSignal}
                  onPhotoInserted={(jotId, assetPath) => {
                    toast.info('reading photo…');
                    extractPhoto.mutate({ jotId, assetPath }, {
                      onSuccess: (res) => {
                        if (res.extracted) {
                          editorHandle.current?.replaceWith(res.body, 'doc');
                          toast.success('photo text extracted');
                        } else {
                          toast.info(`couldn't read photo: ${res.reason ?? ''}`);
                        }
                      },
                      onError: (err) => toast.error(`extract failed: ${err.message}`),
                    });
                  }}
                />
              </div>
              <footer className="flex items-center gap-2 border-t border-hairline px-4 py-2 text-11 text-ink-2">
                {selectedItem?.context && (
                  <Pill>
                    {selectedItem.context}
                    {selectedItem.project ? ` / ${selectedItem.project}` : ''}
                  </Pill>
                )}
                {selectedItem?.routingStatus && <Pill>{selectedItem.routingStatus}</Pill>}
                <div className="ml-auto flex items-center gap-2">
                  {selectedItem?.routingStatus !== 'routed' && (
                    <Btn
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        if (!selectedId) return;
                        autoRoute.mutate(selectedId, {
                          onSuccess: (res) => {
                            if (res.routingStatus === 'routed' && res.context) {
                              toast.info(`filed to ${res.context}`);
                            } else {
                              toast.info('kept for manual review — content too ambiguous');
                            }
                          },
                          onError: (err) => toast.error(`auto-route failed: ${err.message}`),
                        });
                      }}
                      disabled={autoRoute.isPending}
                    >
                      route now
                    </Btn>
                  )}
                  <select
                    onChange={(e) => {
                      if (e.target.value) {
                        handleReroute(e.target.value);
                        // Reset so the placeholder shows again after selection
                        e.target.value = '';
                      }
                    }}
                    defaultValue=""
                    className="bg-transparent text-11 text-ink-1"
                  >
                    <option value="" disabled>
                      re-route…
                    </option>
                    {KNOWN_CONTEXTS.map((c) => (
                      <optgroup key={c} label={c}>
                        <option value={c}>{c}</option>
                        {(Array.isArray(projects.data) ? projects.data : [])
                          .filter((p) => p.context === c)
                          .map((p) => (
                            <option key={p.id} value={p.id}>
                              {c} / {p.name}
                            </option>
                          ))}
                      </optgroup>
                    ))}
                  </select>
                  <select
                    onChange={(e) => {
                      const v = e.target.value;
                      e.target.value = '';
                      handleExportSelect(v);
                    }}
                    defaultValue=""
                    className="bg-transparent text-11 text-ink-1"
                    aria-label="export…"
                  >
                    <option value="" disabled>
                      export…
                    </option>
                    <option value="confluence" disabled={!confluenceEnabled}>
                      confluence{!confluenceEnabled ? ' (not connected)' : ''}
                    </option>
                    <option value="pdf">pdf</option>
                  </select>
                  <Btn variant="ghost" size="sm" onClick={handleDelete}>
                    delete
                  </Btn>
                </div>
              </footer>
            </>
          ) : (
            <div className="flex flex-1 items-center justify-center text-13 text-ink-3">
              {list.data?.items.length === 0
                ? 'no jots yet — press ⌥-J to create one'
                : 'select a jot'}
            </div>
          )}
        </main>
        {/* Docs assist panel — right aside, only when open and a jot is selected */}
        {assistOpen && selectedId && (
          <aside className="w-[320px] flex-shrink-0 overflow-y-auto border-l border-hairline">
            <DocsAssistPanel jotId={selectedId} editorHandle={editorHandle} />
          </aside>
        )}
      </div>
      {/* Confluence export dialog */}
      {showConfluenceDialog && selectedId && (
        <ConfluenceExportDialog
          jotId={selectedId}
          defaultTitle={selectedItem?.title ?? 'document'}
          onClose={() => setShowConfluenceDialog(false)}
        />
      )}
    </div>
  );
}
