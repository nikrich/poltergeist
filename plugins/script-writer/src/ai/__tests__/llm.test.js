import { describe, expect, it } from 'vitest';
import { BUDGETS, runLlm } from '../llm.js';

function fake(reply) {
  const calls = [];
  return {
    calls,
    sidecar: { request: async (method, path, body) => { calls.push({ method, path, body }); return reply(body); } },
  };
}

describe('runLlm', () => {
  it('posts prompt, system, schema, explicit budget and timeout (no model)', async () => {
    const p = fake(() => ({ ok: true, data: { text: 'hi', structured: { fountain: 'X' }, error: null, costUsd: 0.01 } }));
    const out = await runLlm(p, { prompt: 'P', system: 'S', jsonSchema: { type: 'object' }, budgetUsd: BUDGETS.ask });
    expect(p.calls[0]).toEqual({ method: 'POST', path: '/v1/llm/run', body: { prompt: 'P', system: 'S', jsonSchema: { type: 'object' }, budgetUsd: 1, timeoutSeconds: 240 } });
    expect(out).toEqual({ text: 'hi', structured: { fountain: 'X' }, costUsd: 0.01 });
  });
  it('refuses to run without an explicit budget', async () => {
    await expect(runLlm(fake(() => ({ ok: true, data: {} })), { prompt: 'P' })).rejects.toThrow(/budgetUsd/);
  });
  it('throws the provider error and HTTP errors', async () => {
    await expect(runLlm(fake(() => ({ ok: true, data: { text: '', error: 'RateLimit: slow down' } })), { prompt: 'P', budgetUsd: 1 }))
      .rejects.toThrow('RateLimit: slow down');
    await expect(runLlm(fake(() => ({ ok: false, error: 'sidecar down', status: 502 })), { prompt: 'P', budgetUsd: 1 }))
      .rejects.toThrow('sidecar down');
  });
  it('requires a structured result when a schema was requested', async () => {
    await expect(runLlm(fake(() => ({ ok: true, data: { text: 'prose', structured: null, error: null } })), { prompt: 'P', jsonSchema: {}, budgetUsd: 1 }))
      .rejects.toThrow(/structured/);
  });
});
