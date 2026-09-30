// Single door to the user's configured AI provider (POST /v1/llm/run).
import { call } from '../api/backend.js';

export const BUDGETS = Object.freeze({ ask: 1, action: 1, polishPerSection: 0.5 });
export const LLM_TIMEOUT_S = 240; // the renderer's sidecar bridge gives up at 300s

export async function runLlm(plugin, { prompt, system, jsonSchema, budgetUsd, timeoutSeconds = LLM_TIMEOUT_S }) {
  if (!(typeof budgetUsd === 'number' && budgetUsd > 0)) throw new Error('runLlm: an explicit budgetUsd is required');
  const body = { prompt };
  if (system) body.system = system;
  if (jsonSchema) body.jsonSchema = jsonSchema;
  body.budgetUsd = budgetUsd;
  body.timeoutSeconds = timeoutSeconds;
  const data = await call(plugin, 'POST', '/v1/llm/run', body);
  if (data?.error) throw new Error(data.error);
  if (jsonSchema && (data?.structured === null || data?.structured === undefined)) {
    throw new Error('The AI returned no structured result');
  }
  return { text: data?.text ?? '', structured: data?.structured ?? null, costUsd: data?.costUsd ?? null };
}
