import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as client from '../lib/api/client';
import { PendingChanges } from '../components/PendingChanges';
import { PENDING_CHANGES_PATH } from '../lib/api/hooks';
import type { ChangeDetailResponse, ChangeSummary } from '../../shared/api-types';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ApiError: actual.ApiError, get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() };
});
const getMock = vi.mocked(client.get);

afterEach(() => getMock.mockReset());

const AI_TEMPLATE: ChangeSummary = {
  id: 9, ts: '2026-10-10T09:00:00+00:00', actor: 'assistant',
  path: '90-meta/templates/x.md', destPath: null, op: 'create', reason: 'ai-drafted template',
  status: 'pending', riskReasons: ['edits a template'], resolvedTs: null,
};

describe('PendingChanges: an ai-drafted template', () => {
  it('shows every line of the proposed template, not a truncated preview', async () => {
    const lines = ['---', 'template:', '  name: Long one', '---', ...Array.from({ length: 45 }, (_, i) => `line number ${i + 1} of the body`)];
    const detail: ChangeDetailResponse = {
      ...AI_TEMPLATE, before: null, after: lines.join('\n'), current: null, changedSince: false, diff: '',
    };
    getMock.mockImplementation(async (path: string) => {
      if (path === PENDING_CHANGES_PATH) return { items: [AI_TEMPLATE], pendingCount: 1, degraded: false };
      if (path === '/v1/changes/9') return detail;
      throw new Error(`unexpected GET ${path}`);
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <PendingChanges />
      </QueryClientProvider>,
    );
    const diff = await screen.findByTestId('pending-diff-9');
    expect(lines.length).toBeGreaterThanOrEqual(40);
    for (const line of lines) expect(diff.textContent).toContain(`+ ${line}`);
  });
});
