import { useEffect, useRef, useState } from 'react';
import type { Editor } from '@tiptap/core';
import { createDocsAssistStore } from '../stores/docs-assist';
import { subscribeAssistEvents } from '../lib/docs-assist-events';
import {
  clearAiSuggestion,
  setAiSuggestionText,
  startAiSuggestion,
  type SuggestionKey,
} from '../lib/editor/ai-suggestion';
import {
  LANGUAGES,
  QUICK_ACTIONS,
  buildInlineRequest,
  cleanModelOutput,
  isLanguageName,
  joinWithSpaceFor,
  newStreamId,
  suggestionRange,
  type InlineAction,
  type InlineAssistTarget,
  type InlineContext,
} from '../lib/editor/inline-assist';
import { shortcutLabel } from '../lib/editor-shortcuts';
import { Btn } from './Btn';
import { Lucide } from './Lucide';

export interface InlineAssistPopoverProps {
  editor: Editor;
  target: InlineAssistTarget;
  /** Snapshot from when ⌘J was pressed. */
  context: InlineContext;
  /** Run this action at once (docs-panel hand-off). */
  initial?: InlineAction;
  /** Editor-focused Tab / ⌘↵ / Esc arrive here from the ai-suggestion plugin. */
  keyRef: React.MutableRefObject<((key: SuggestionKey) => boolean) | null>;
  /** Apply the ready suggestion (one transaction) and save it as the assistant's. */
  onAccept: () => void;
  onClose: () => void;
}

function anchorStyle(editor: Editor, pos: number): React.CSSProperties {
  try {
    const c = editor.view.coordsAtPos(pos);
    return { top: c.bottom + 6, left: Math.max(8, c.left) };
  } catch {
    return { top: 96, left: 96 }; // detached view (tests) or a stale position
  }
}

export function InlineAssistPopover({
  editor,
  target,
  context,
  initial,
  keyRef,
  onAccept,
  onClose,
}: InlineAssistPopoverProps) {
  const [store] = useState(createDocsAssistStore);
  const phase = store((s) => s.phase);
  const error = store((s) => s.error);
  const [instruction, setInstruction] = useState('');
  const [translateOpen, setTranslateOpen] = useState(false);
  const [otherOpen, setOtherOpen] = useState(false);
  const [otherLanguage, setOtherLanguage] = useState('');
  const [toolHint, setToolHint] = useState<string | null>(null);
  const [hint, setHint] = useState<string | null>(null);
  const [style] = useState(() => anchorStyle(editor, context.to));
  const streamRef = useRef<string | null>(null);
  const unsubRef = useRef<(() => void) | null>(null);
  const lastAction = useRef<InlineAction | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  /** Stop listening, stop a running turn, remove the diff. */
  const teardown = () => {
    unsubRef.current?.();
    unsubRef.current = null;
    const id = streamRef.current;
    if (id && store.getState().phase === 'streaming') void window.gb.docs.assistStop(id);
    streamRef.current = null;
    if (!editor.isDestroyed) clearAiSuggestion(editor);
  };

  const run = (action: InlineAction) => {
    teardown();
    lastAction.current = action;
    setHint(null);
    setToolHint(null);
    const streamId = newStreamId();
    streamRef.current = streamId;
    startAiSuggestion(editor, suggestionRange(action, context), {
      joinWithSpace: joinWithSpaceFor(action, context),
    });
    store.getState().start({
      jotId: streamId,
      mode: action.mode,
      target: context.empty ? 'doc' : 'selection',
      selection: context.selection,
    });
    // Events of an older (stopped, retried) stream must never reach this one.
    const live = () => streamRef.current === streamId && !editor.isDestroyed;
    unsubRef.current = subscribeAssistEvents(streamId, {
      onDelta: (text) => {
        if (!live()) return;
        store.getState().appendDelta(text);
        setAiSuggestionText(editor, cleanModelOutput(store.getState().streamed), 'streaming');
      },
      onDone: (text) => {
        if (!live()) return;
        store.getState().finish(text);
        setToolHint(null);
        const out = cleanModelOutput(store.getState().streamed);
        if (!out) {
          clearAiSuggestion(editor);
          store.getState().fail('the assistant returned nothing');
          return;
        }
        setAiSuggestionText(editor, out, 'ready');
      },
      onError: (message) => {
        if (!live()) return;
        clearAiSuggestion(editor);
        store.getState().fail(message);
        setToolHint(null);
      },
      onInterrupted: () => {
        if (!live()) return;
        clearAiSuggestion(editor);
        store.getState().reset();
        setToolHint(null);
      },
      onTool: (summary) => {
        if (live()) setToolHint(summary);
      },
    });
    const refuse = (message: string) => {
      if (!live()) return;
      clearAiSuggestion(editor);
      store.getState().fail(message);
    };
    window.gb.docs.assist(buildInlineRequest(target, action, context, streamId)).then(
      (res) => {
        if (!res.ok) refuse((res as { ok: false; error: string }).error);
      },
      (err: unknown) => refuse(err instanceof Error ? err.message : String(err)),
    );
  };

  const accept = () => {
    if (store.getState().phase !== 'proposal') return;
    unsubRef.current?.();
    unsubRef.current = null;
    streamRef.current = null;
    onAccept(); // the suggestion is still on the doc: the parent applies + saves it
  };

  /** Stop while streaming discards; the popover stays for another try. */
  const stop = () => {
    teardown();
    store.getState().reset();
    setToolHint(null);
  };

  const reject = () => {
    teardown();
    store.getState().reset();
    onClose();
  };

  // Latest closures for the editor-focused keys (the plugin calls keyRef).
  useEffect(() => {
    keyRef.current = (key) => {
      if (key === 'accept') accept();
      else reject();
      return true;
    };
    return () => {
      keyRef.current = null;
    };
  });

  useEffect(() => {
    if (initial) run(initial);
    else inputRef.current?.focus();
    // Unmount (accept, close, note switch): never leave a turn or a diff behind.
    return () => teardown();
    // mount-only by design: context/initial are a snapshot of this open
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submitInstruction = () => {
    const text = instruction.trim();
    if (!text) return;
    run({ mode: context.empty ? 'draft' : 'polish', instruction: text });
  };

  const draftFromVault = () => {
    const text = instruction.trim();
    if (!text) {
      setHint('say what to draft first');
      inputRef.current?.focus();
      return;
    }
    run({ mode: 'draft', instruction: text });
  };

  const translate = (language: string) => {
    const name = language.trim();
    if (!name) return;
    setTranslateOpen(false);
    setOtherOpen(false);
    run({ mode: 'translate', targetLanguage: name, instruction: instruction.trim() || undefined });
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      reject();
      return;
    }
    const acceptKey =
      (e.key === 'Tab' && !e.shiftKey && !e.metaKey && !e.ctrlKey) ||
      (e.key === 'Enter' && (e.metaKey || e.ctrlKey));
    if (acceptKey && store.getState().phase === 'proposal') {
      e.preventDefault();
      accept();
    }
  };

  const busy = phase === 'streaming';
  const otherValid = isLanguageName(otherLanguage);

  return (
    <div
      role="dialog"
      aria-label="inline ai"
      onKeyDown={onKeyDown}
      style={{ position: 'fixed', zIndex: 60, width: 380, ...style }}
      className="flex flex-col gap-2 rounded border border-hairline bg-vellum p-2 shadow-md"
    >
      <div className="flex flex-wrap gap-[6px]">
        {QUICK_ACTIONS.map(({ mode, label, needsSelection }) => (
          <Btn
            key={mode}
            variant="secondary"
            size="sm"
            disabled={busy || (needsSelection && context.empty)}
            onClick={() => run({ mode, instruction: instruction.trim() || undefined })}
          >
            {label}
          </Btn>
        ))}
        <Btn
          variant="secondary"
          size="sm"
          disabled={busy || context.empty}
          onClick={() => setTranslateOpen((o) => !o)}
        >
          translate
        </Btn>
        <Btn variant="secondary" size="sm" disabled={busy} onClick={draftFromVault}>
          draft from vault
        </Btn>
      </div>

      {translateOpen && (
        <div className="flex flex-wrap items-center gap-[6px]">
          {LANGUAGES.map(({ name, label }) => (
            <Btn key={name} variant="ghost" size="sm" onClick={() => translate(name)}>
              {label}
            </Btn>
          ))}
          <Btn variant="ghost" size="sm" onClick={() => setOtherOpen((o) => !o)}>
            other…
          </Btn>
          {otherOpen && (
            <>
              <input
                aria-label="language"
                value={otherLanguage}
                maxLength={40}
                onChange={(e) => setOtherLanguage(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    if (otherValid) translate(otherLanguage);
                  }
                }}
                className="w-[120px] rounded-r6 border border-hairline bg-paper px-2 py-[2px] text-12 text-ink-0"
              />
              <Btn variant="primary" size="sm" disabled={!otherValid} onClick={() => translate(otherLanguage)}>
                go
              </Btn>
            </>
          )}
        </div>
      )}

      <textarea
        ref={inputRef}
        aria-label="instruction"
        rows={2}
        value={instruction}
        placeholder="ask the assistant…"
        disabled={busy}
        onChange={(e) => setInstruction(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey && !e.metaKey && !e.ctrlKey) {
            e.preventDefault();
            if (!busy) submitInstruction();
          }
        }}
        className="resize-none rounded-r6 border border-hairline bg-paper px-[10px] py-[6px] text-13 leading-[1.5] text-ink-0 placeholder:text-ink-3 focus:border-ink-3 focus:outline-none disabled:opacity-60"
      />
      {hint && <div className="text-11 text-ink-3">{hint}</div>}

      {busy && (
        <div className="flex items-center gap-2">
          {toolHint && (
            <span className="flex items-center gap-1 font-mono text-10 text-ink-3">
              <Lucide name="wrench" size={9} color="var(--ink-3)" />
              {toolHint}
            </span>
          )}
          <span className="text-11 text-ink-3">writing…</span>
          <Btn
            variant="danger"
            size="sm"
            icon={<Lucide name="square" size={10} />}
            onClick={stop}
          >
            stop
          </Btn>
        </div>
      )}

      {phase === 'proposal' && (
        <div className="flex items-center gap-2">
          <Btn variant="primary" size="sm" icon={<Lucide name="check" size={12} />} onClick={accept}>
            accept ⇥
          </Btn>
          <Btn variant="ghost" size="sm" onClick={reject}>
            discard esc
          </Btn>
        </div>
      )}

      {phase === 'error' && (
        <div
          role="alert"
          className="flex items-center gap-2 rounded-r6 bg-oxblood-mist px-2 py-1 text-12 text-ink-0"
        >
          <span className="flex-1">{error ?? 'something went wrong'}</span>
          <Btn
            variant="ghost"
            size="sm"
            onClick={() => {
              if (lastAction.current) run(lastAction.current);
            }}
          >
            retry
          </Btn>
        </div>
      )}

      <div className="font-mono text-10 text-ink-3">{shortcutLabel('inlineAi')} · esc closes</div>
    </div>
  );
}
