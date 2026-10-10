import { useEffect, useRef, useState } from 'react';
import type { Editor } from '@tiptap/core';
import type { Transaction } from '@tiptap/pm/state';
import { useSettings } from '../stores/settings';
import { toast } from '../stores/toast';
import { isMac } from '../lib/platform';
import { matchesShortcut, shortcutLabel } from '../lib/editor-shortcuts';
import { collectSegments, startIndexFor, type SpeechSegment } from '../lib/read-aloud/segments';
import { detectLanguage } from '../lib/read-aloud/language';
import { attachReadAloudHighlight, setReadAloudHighlight } from '../lib/read-aloud/highlight';
import { ReadAloudController, type ReadAloudStatus } from '../lib/read-aloud/controller';
import {
  isSpeechSupported,
  makeUtterance,
  pickVoice,
  useSpeechVoices,
} from '../lib/read-aloud/voices';
import { Btn } from './Btn';
import { Lucide } from './Lucide';

/** Scroll the spoken sentence into view; best effort (jsdom has no
 * scrollIntoView, and the view can be detached during unmount). */
function reveal(editor: Editor, seg: SpeechSegment): void {
  try {
    const { node } = editor.view.domAtPos(seg.from);
    const el = node.nodeType === 1 ? (node as Element) : node.parentElement;
    el?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' });
  } catch {
    // view not attached — nothing to scroll
  }
}

/** ▶ read / pause / resume / stop for one editor instance (A4). Reads the
 * selection, or from the cursor to the end; ⌘⇧L / Ctrl+Shift+L toggles while
 * the editor has focus. Unmount (note switch, source mode) stops speech. */
export function ReadAloudControls({ editor }: { editor: Editor }) {
  const supported = isSpeechSupported();
  const voices = useSpeechVoices();
  const voiceUri = useSettings((s) => s.readAloudVoice);
  const rate = useSettings((s) => s.readAloudRate);
  const [status, setStatus] = useState<ReadAloudStatus>('idle');
  const ctrlRef = useRef<ReadAloudController | null>(null);
  const optsRef = useRef({ voices, voiceUri, rate });
  optsRef.current = { voices, voiceUri, rate };

  useEffect(() => {
    if (!supported) return;
    const detach = attachReadAloudHighlight(editor);
    const ctrl = new ReadAloudController(window.speechSynthesis, makeUtterance, {
      onHighlight: (seg) => {
        setReadAloudHighlight(editor, seg ? { from: seg.from, to: seg.to } : null);
        if (seg) reveal(editor, seg);
      },
      onStatus: setStatus,
      onError: (msg) => toast.error(`read-aloud stopped: ${msg}`),
    });
    ctrlRef.current = ctrl;
    const onTransaction = ({ transaction }: { transaction: Transaction }) => {
      if (transaction.docChanged) {
        ctrl.mapPositions((pos, assoc) => transaction.mapping.map(pos, assoc));
      }
    };
    editor.on('transaction', onTransaction);
    return () => {
      editor.off('transaction', onTransaction);
      ctrl.stop();
      ctrlRef.current = null;
      detach();
    };
  }, [editor, supported]);

  const toggle = () => {
    const ctrl = ctrlRef.current;
    if (!ctrl) return;
    if (ctrl.status === 'playing') return ctrl.pause();
    if (ctrl.status === 'paused') return ctrl.resume();
    const { from, to, empty } = editor.state.selection;
    const doc = editor.state.doc;
    const segments = empty ? collectSegments(doc) : collectSegments(doc, { from, to });
    if (segments.length === 0) {
      toast.info('nothing to read here');
      return;
    }
    const o = optsRef.current;
    ctrl.start(segments, empty ? startIndexFor(segments, from) : 0, {
      voice: pickVoice(o.voices, o.voiceUri, detectLanguage(doc.textContent)),
      rate: o.rate,
    });
  };
  const toggleRef = useRef(toggle);
  toggleRef.current = toggle;

  useEffect(() => {
    if (!supported) return;
    const dom = editor.view.dom;
    const onKey = (e: KeyboardEvent) => {
      if (!matchesShortcut(e, 'readAloud', isMac)) return;
      e.preventDefault();
      toggleRef.current();
    };
    dom.addEventListener('keydown', onKey);
    return () => dom.removeEventListener('keydown', onKey);
  }, [editor, supported]);

  if (!supported) return null;

  return (
    <div role="group" aria-label="read aloud controls" className="flex items-center gap-1">
      {status === 'idle' && (
        <Btn
          variant="ghost"
          size="sm"
          icon={<Lucide name="play" size={12} />}
          onClick={toggle}
          ariaLabel={`read aloud (${shortcutLabel('readAloud')})`}
        >
          read
        </Btn>
      )}
      {status === 'playing' && (
        <Btn
          variant="ghost"
          size="sm"
          icon={<Lucide name="pause" size={12} />}
          onClick={toggle}
          ariaLabel="pause reading"
        >
          pause
        </Btn>
      )}
      {status === 'paused' && (
        <Btn
          variant="ghost"
          size="sm"
          icon={<Lucide name="play" size={12} />}
          onClick={toggle}
          ariaLabel="resume reading"
        >
          resume
        </Btn>
      )}
      {status !== 'idle' && (
        <Btn
          variant="ghost"
          size="sm"
          icon={<Lucide name="square" size={12} />}
          onClick={() => ctrlRef.current?.stop()}
          ariaLabel="stop reading"
        >
          stop
        </Btn>
      )}
    </div>
  );
}
