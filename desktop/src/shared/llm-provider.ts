import type { LlmProvider } from './types';
import type { SidecarProviderId } from './api-types';

/** Desktop-facing provider id -> sidecar's `/v1/settings/llm` provider id.
 * Every id is identical except `local`, which the sidecar exposes as its
 * generic OpenAI-compatible HTTP driver (`openai_http`) since that one
 * driver can point at Ollama, LM Studio, or any other local server. */
export function toSidecarProvider(provider: LlmProvider): SidecarProviderId {
  return provider === 'local' ? 'openai_http' : provider;
}

/** Sidecar provider id -> desktop-facing provider id. Inverse of {@link toSidecarProvider}. */
export function fromSidecarProvider(id: SidecarProviderId): LlmProvider {
  return id === 'openai_http' ? 'local' : id;
}
