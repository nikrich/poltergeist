import type { ChatExportResponse } from '../../shared/api-types';
import { useChat } from '../stores/chat';
import { toast } from '../stores/toast';
import { post } from './api/client';
import { queryClient } from './api/query-client';

/** Export a conversation as a summarized jot.
 *
 * Module-level (not a component mutation) so the pending state, the success
 * toast, and the jots-cache invalidation all survive navigating away from the
 * chat screen mid-export — the sonnet summary takes ~5-15s. Pending state
 * lives in the chat store (`exporting`); the server has its own per-
 * conversation busy guard (409) as the backstop.
 */
export async function exportConversationToJot(convId: string): Promise<void> {
  const { exporting, beginExport, endExport } = useChat.getState();
  if (exporting[convId]) return;
  beginExport(convId);
  toast.info('summarizing conversation… this takes a few seconds');
  try {
    const res = await post<ChatExportResponse>(
      `/v1/chat/${encodeURIComponent(convId)}/export-jot`,
    );
    const dest =
      res.routingStatus === 'routed'
        ? [res.context, res.project].filter(Boolean).join(' / ')
        : 'inbox (needs review)';
    toast.success(`exported to jots → ${dest}`);
    void queryClient.invalidateQueries({ queryKey: ['jots'] });
  } catch (e) {
    toast.error(e instanceof Error ? e.message : 'export failed');
  } finally {
    endExport(convId);
  }
}
