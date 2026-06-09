import { useEffect, useMemo, useRef, useState } from 'react';
import { TopBar } from '../components/TopBar';
import { Btn } from '../components/Btn';
import { Lucide } from '../components/Lucide';
import { Pill } from '../components/Pill';
import { JotTree } from '../components/JotTree';
import { JotEditor } from '../components/JotEditor';
import {
  useCreateJot,
  useDeleteJot,
  useJot,
  useJots,
  useRouteJot,
  useUpdateJot,
} from '../lib/api/hooks';
import { toast } from '../stores/toast';

const KNOWN_CONTEXTS = ['sanlam', 'codeship', 'reducedrecipes', 'personal'];

export function JotsScreen() {
  const [q, setQ] = useState('');
  const list = useJots({ q: q || undefined });
  const [selectedId, setSelectedId] = useState<string | null>(null);

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

  const createJot = useCreateJot();
  const updateJot = useUpdateJot();
  const routeJot = useRouteJot();
  const deleteJot = useDeleteJot();

  // Auto-select the newest jot when the list first loads.
  useEffect(() => {
    if (selectedId === null && list.data?.items.length) {
      setSelectedId(list.data.items[0]!.id);
    }
  }, [list.data, selectedId]);

  function handleNew() {
    createJot.mutate(
      { body: 'new jot\n\n' },
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

  function handleReroute(ctx: string) {
    if (!selectedId) return;
    // After re-routing, the file path changes. The list refetches via
    // useRouteJot's onSuccess invalidation, and selectedItem is resolved from
    // the refreshed list by id — so the editor path updates automatically via
    // useJot(selectedItem?.path). The initialBodyRef is keyed by selectedId
    // (not path), so it does not go stale on path change. No special handling
    // needed; the editor continues showing the correct content.
    routeJot.mutate(
      { id: selectedId, context: ctx },
      {
        onSuccess: () => toast.info(`re-routed to ${ctx}`),
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

  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-paper">
      <TopBar
        title="jots"
        subtitle={list.data ? `${list.data.total} total` : '…'}
        right={
          <div className="flex gap-2">
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
                {/* key={selectedId} remounts JotEditor on jot switch, wiping
                    internal debounce timers. The body prop is frozen to the
                    initial fetch so mid-session RQ refetches never reset the
                    editor's internal value. */}
                <JotEditor
                  key={selectedId!}
                  body={editorBody}
                  onSave={handleSaveBody}
                />
              </div>
              <footer className="flex items-center gap-2 border-t border-hairline px-4 py-2 text-11 text-ink-2">
                {selectedItem?.context && <Pill>{selectedItem.context}</Pill>}
                {selectedItem?.routingStatus && <Pill>{selectedItem.routingStatus}</Pill>}
                <div className="ml-auto flex items-center gap-2">
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
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
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
      </div>
    </div>
  );
}
