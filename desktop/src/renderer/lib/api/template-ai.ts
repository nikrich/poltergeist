import { useMutation, useQueryClient } from '@tanstack/react-query';
import { post } from './client';
import type { TemplateGenerateResponse } from '../../../shared/api-types';

/** Same cap as the sidecar's MAX_DESCRIPTION_CHARS. */
export const MAX_TEMPLATE_DESCRIPTION = 2000;

/** Spec C4: draft a template with the AI. A saved draft is a pending change,
 * so the Changes queries (badge, Pending section) are refreshed. */
export function useGenerateTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (description: string) =>
      post<TemplateGenerateResponse>('/v1/templates/generate', { description }),
    onSuccess: (res) =>
      res.status === 'pending' ? qc.invalidateQueries({ queryKey: ['changes'] }) : undefined,
  });
}
