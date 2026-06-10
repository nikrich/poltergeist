import { useEffect, useRef, useState } from 'react';
import type { DocsAssistMode } from '../../shared/api-types';
import { useDocsAssist } from '../stores/docs-assist';
import type { EditorHandle } from './RichMarkdownEditor';
import { Btn } from './Btn';
import { Eyebrow } from './Eyebrow';
import { Lucide } from './Lucide';
import { MarkdownBody } from './MarkdownBody';
import { PanelError } from './PanelError';

interface Props {
  jotId: string;
  editorHandle: React.MutableRefObject<EditorHandle | null>;
}

// Quick-action mode buttons rendered at the top of the panel.
const QUICK_ACTIONS: { mode: DocsAssistMode; label: string }[] = [
  { mode: 'polish', label: 'polish' },
  { mode: 'expand', label: 'expand' },
  { mode: 'summarize', label: 'summarize' },
];

export function DocsAssistPanel({ jotId, editorHandle }: Props) {
  const phase = useDocsAssist((s) => s.phase);
  const streamed = useDocsAssist((s) => s.streamed);
  const error = useDocsAssist((s) => s.error);
  const target = useDocsAssist((s) => s.target);
  const start = useDocsAssist((s) => s.start);
  const appendDelta = useDocsAssist((s) => s.appendDelta);
  const finish = useDocsAssist((s) => s.finish);
  const fail = useDocsAssist((s) => s.fail);
  const reset = useDocsAssist((s) => s.reset);

  const [instruction, setInstruction] = useState('');
  // Last tool summary received during streaming — shown as a subtle status line.
  const [toolHint, setToolHint] = useState<string | null>(null);

  // Keep the last request parameters so the error view can offer a retry.
  const lastRequest = useRef<{
    mode: DocsAssistMode;
    instruction?: string;
    selection?: string;
    target: 'selection' | 'doc';
  } | null>(null);

  // Subscribe to docs:event — one listener for all jots, filtered to ours.
  // gb.on returns an unsubscribe function; clean it up on unmount.
  useEffect(() => {
    return window.gb.on('docs:event', ({ jotId: id, event }) => {
      if (id !== jotId) return;
      switch (event.type) {
        case 'delta':
          appendDelta(event.text);
          break;
        case 'done':
          finish(event.text);
          setToolHint(null);
          break;
        case 'error':
          fail(event.message);
          setToolHint(null);
          break;
        case 'tool':
          // Show the most recent tool summary as a subtle inline hint while streaming.
          setToolHint(event.summary);
          break;
        default:
          // session event — no UI update needed
          break;
      }
    });
  }, [jotId, appendDelta, finish, fail]);

  // When the jotId changes, reset ANY non-idle state — a surviving proposal
  // (or error) from jot A could otherwise be accepted into jot B's editor,
  // since editorHandle now points at the new jot. Only an active stream needs
  // an explicit sidecar stop.
  const prevJotIdRef = useRef(jotId);
  useEffect(() => {
    const prev = prevJotIdRef.current;
    prevJotIdRef.current = jotId;
    if (prev !== jotId && phase !== 'idle') {
      if (phase === 'streaming') void window.gb.docs.assistStop(prev);
      reset();
      setToolHint(null);
      // The retry target is gone too — a stale request must not be re-sent
      // against the new jot.
      lastRequest.current = null;
    }
  }, [jotId, phase, reset]);

  function submit(quickMode?: DocsAssistMode) {
    const sel = editorHandle.current?.getSelectionMarkdown() ?? '';
    const resolvedTarget: 'selection' | 'doc' = sel ? 'selection' : 'doc';
    const resolvedMode: DocsAssistMode = quickMode
      ? quickMode
      : instruction.trim()
        ? sel
          ? 'polish'
          : 'draft'
        : 'polish';

    const req = {
      mode: resolvedMode,
      instruction: instruction.trim() || undefined,
      selection: sel || undefined,
      target: resolvedTarget,
    };
    lastRequest.current = req;

    start({ jotId, mode: resolvedMode, target: resolvedTarget, selection: sel });

    void window.gb.docs.assist({
      jot_id: jotId,
      mode: resolvedMode,
      instruction: req.instruction,
      selection: req.selection,
    }).then((res) => {
      if (!res.ok) {
        // The sidecar rejected the request before streaming began.
        fail((res as { ok: false; error: string }).error);
      }
    });
  }

  function handleAccept() {
    editorHandle.current?.replaceWith(streamed, target);
    reset();
    setToolHint(null);
    setInstruction('');
  }

  function handleDiscard() {
    reset();
    setToolHint(null);
  }

  function handleRetry() {
    if (!lastRequest.current) return;
    const req = lastRequest.current;
    start({ jotId, mode: req.mode, target: req.target, selection: req.selection ?? '' });
    void window.gb.docs.assist({
      jot_id: jotId,
      mode: req.mode,
      instruction: req.instruction,
      selection: req.selection,
    }).then((res) => {
      if (!res.ok) {
        fail((res as { ok: false; error: string }).error);
      }
    });
  }

  const isStreaming = phase === 'streaming';
  const isProposal = phase === 'proposal';
  const isError = phase === 'error';
  const isIdle = phase === 'idle';

  return (
    <div className="flex flex-col gap-3 p-3">
      <Eyebrow>docs assist</Eyebrow>

      {/* Quick-action row — always visible so the user can start a new action
          from any non-streaming state. Disabled during streaming. */}
      <div className="flex flex-wrap gap-[6px]">
        {QUICK_ACTIONS.map(({ mode, label }) => (
          <Btn
            key={mode}
            variant="secondary"
            size="sm"
            disabled={isStreaming}
            onClick={() => submit(mode)}
          >
            {label}
          </Btn>
        ))}
      </div>

      {/* Free-form instruction + go button */}
      <div className="flex gap-2">
        <textarea
          rows={2}
          value={instruction}
          placeholder="custom instruction…"
          disabled={isStreaming}
          onChange={(e) => setInstruction(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              if (!isStreaming && instruction.trim()) submit();
            }
          }}
          className="flex-1 resize-none rounded-r6 border border-hairline-2 bg-vellum px-[10px] py-[6px] text-13 leading-[1.5] text-ink-0 placeholder:text-ink-3 focus:border-ink-3 focus:outline-none disabled:opacity-60"
        />
        <Btn
          variant="primary"
          size="sm"
          disabled={isStreaming || !instruction.trim()}
          onClick={() => submit()}
          ariaLabel="go"
        >
          go
        </Btn>
      </div>

      {/* Streaming view */}
      {isStreaming && (
        <div className="flex flex-col gap-2">
          {toolHint && (
            <div className="flex items-center gap-1 font-mono text-10 text-ink-3">
              <Lucide name="wrench" size={9} color="var(--ink-3)" />
              {toolHint}
            </div>
          )}
          <pre className="max-h-[260px] overflow-y-auto whitespace-pre-wrap rounded-r6 border border-hairline bg-vellum px-3 py-2 text-13 leading-[1.6] text-ink-0">
            {streamed || <span className="text-ink-3">generating…</span>}
          </pre>
          <Btn
            variant="danger"
            size="sm"
            icon={<Lucide name="square" size={10} />}
            onClick={() => void window.gb.docs.assistStop(jotId)}
          >
            stop
          </Btn>
        </div>
      )}

      {/* Proposal view */}
      {isProposal && (
        <div className="flex flex-col gap-2">
          <Eyebrow className="text-ink-2">proposal</Eyebrow>
          <div className="max-h-[260px] overflow-y-auto rounded-r6 border border-hairline bg-vellum px-3 py-2">
            <MarkdownBody className="text-13 leading-[1.6] text-ink-0">{streamed}</MarkdownBody>
          </div>
          <div className="flex gap-2">
            <Btn
              variant="primary"
              size="sm"
              icon={<Lucide name="check" size={12} />}
              onClick={handleAccept}
            >
              accept
            </Btn>
            <Btn variant="ghost" size="sm" onClick={handleDiscard}>
              discard
            </Btn>
          </div>
        </div>
      )}

      {/* Error view */}
      {isError && (
        <PanelError message={error ?? 'something went wrong'} onRetry={handleRetry} />
      )}

      {/* Idle hint until the first request is made in this panel. The ref read
          at render is safe: every return to idle comes with a phase re-render,
          and the jot-switch effect nulls the ref before its re-render too. */}
      {isIdle && !lastRequest.current && (
        <div className="text-12 text-ink-3">
          select text in the editor to assist a specific passage, or use the actions above to
          process the whole document.
        </div>
      )}
    </div>
  );
}
