import { describe, expect, it, vi } from 'vitest';
vi.mock('electron', () => ({ app: { getPath: () => '/tmp/ghostbrain-desktop-test' } }));
import { DEFAULT_SETTINGS, migrateLlmProvider } from '../settings';

describe('llm provider setting', () => {
  it('defaults to claude', () => {
    expect(DEFAULT_SETTINGS.llmProvider).toBe('claude');
  });
  it('migrates legacy values', () => {
    expect(migrateLlmProvider('anthropic')).toBe('claude');
    expect(migrateLlmProvider('openai')).toBe('codex');
    expect(migrateLlmProvider('local')).toBe('local');
    expect(migrateLlmProvider('gemini')).toBe('gemini');
    expect(migrateLlmProvider('garbage')).toBe('claude');
  });
});
