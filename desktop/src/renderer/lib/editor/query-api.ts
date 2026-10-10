import type { NoteStatusResponse, NoteStatusValue, VaultQueryResponse } from '../../../shared/api-types';
import { patch, post } from '../api/client';

/** Sidecar calls for the ```query``` NodeView. Plain functions (no React):
 * the node view is vanilla ProseMirror. */
export function runVaultQuery(source: string): Promise<VaultQueryResponse> {
  return post<VaultQueryResponse>('/v1/vault/query', { query: source });
}

export function setNoteStatus(
  path: string,
  status: NoteStatusValue,
  etag: string | null,
): Promise<NoteStatusResponse> {
  return patch<NoteStatusResponse>('/v1/vault/status', { path, status }, { ifMatch: etag });
}
