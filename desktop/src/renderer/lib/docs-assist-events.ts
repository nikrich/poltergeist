import type { DocsAssistEvent } from '../../shared/api-types';

export interface AssistEventHandlers {
  onDelta: (text: string) => void;
  onDone: (text: string) => void;
  onError: (message: string) => void;
  /** A user-initiated stop: an error event with `interrupted` — not a failure. */
  onInterrupted: () => void;
  onTool?: (summary: string) => void;
}

/** Subscribe to one assist stream's events (docs panel and inline AI). Main
 * sends `{ key, jotId, event }`; `jotId` alone is the pre-A5 payload. */
export function subscribeAssistEvents(key: string, h: AssistEventHandlers): () => void {
  return window.gb.on('docs:event', (payload) => {
    if ((payload.key ?? payload.jotId) !== key) return;
    const event: DocsAssistEvent = payload.event;
    switch (event.type) {
      case 'delta':
        h.onDelta(event.text);
        break;
      case 'done':
        h.onDone(event.text);
        break;
      case 'error':
        if (event.interrupted) h.onInterrupted();
        else h.onError(event.message);
        break;
      case 'tool':
        h.onTool?.(event.summary);
        break;
      default:
        break;
    }
  });
}
