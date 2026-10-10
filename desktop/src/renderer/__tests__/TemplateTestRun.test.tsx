import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as client from '../lib/api/client';
import { TemplateTestRun } from '../components/TemplateTestRun';
import { rememberAnswers } from '../lib/templates/last-answers';
import type { TemplateDryRunResponse } from '../../shared/api-types';
import { TEMPLATE } from './helpers/template-registry';
import { stubLocalStorage } from './helpers/memory-storage';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ApiError: actual.ApiError, get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() };
});
const postMock = vi.mocked(client.post);

const PROMPTS = [
  { id: 'person', ask: 'Who?', type: 'person' as const, optional: false, default: null, options: [] },
  { id: 'focus', ask: 'Focus?', type: 'text' as const, optional: true, default: null, options: [] },
];

function ok(person: string): TemplateDryRunResponse {
  return {
    ok: true,
    prompts: PROMPTS,
    answers: { person },
    rendered: {
      path: `20-contexts/work/one-on-ones/2026-10-09-${person.toLowerCase()}-1-1.md`,
      folder: '20-contexts/work/one-on-ones',
      filename: 'x.md',
      title: `2026-10-09 ${person} 1-1`,
      frontmatter: {},
      body: `# 1-1 with [[${person}]]\n`,
      markdown: '',
    },
    wouldBeFiledAt: `20-contexts/work/one-on-ones/2026-10-09-${person.toLowerCase()}-1-1-2.md`,
    diagnostics: [],
    error: null,
  };
}

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <TemplateTestRun templateId="one-on-one" source={TEMPLATE} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  stubLocalStorage();
});
afterEach(() => {
  postMock.mockReset();
  vi.unstubAllGlobals();
});

describe('TemplateTestRun', () => {
  it('runs once on open with remembered answers and shows the filed path and rendered note', async () => {
    rememberAnswers('one-on-one', { person: 'Alex' });
    postMock.mockResolvedValue(ok('Alex'));
    mount();
    expect(await screen.findByText('20-contexts/work/one-on-ones/2026-10-09-alex-1-1-2.md')).toBeInTheDocument();
    expect(postMock).toHaveBeenCalledTimes(1);
    expect(postMock).toHaveBeenCalledWith('/v1/templates/render', {
      source: TEMPLATE,
      answers: { person: 'Alex' },
      id: 'one-on-one',
      dry_run: true,
    });
    await waitFor(() => expect(screen.getByText(/1-1 with/)).toBeInTheDocument());
    expect(screen.getByLabelText('Who?')).toHaveValue('Alex');
    expect(screen.getByLabelText('Focus?')).toHaveValue('');
  });

  it('runs again with edited answers', async () => {
    postMock.mockResolvedValueOnce(ok('Sample Person'));
    mount();
    const who = await screen.findByLabelText('Who?');
    expect(who).toHaveValue('Sample Person');
    fireEvent.change(who, { target: { value: 'Robin' } });
    postMock.mockResolvedValueOnce(ok('Robin'));
    fireEvent.click(screen.getByRole('button', { name: 'run again' }));
    await waitFor(() =>
      expect(postMock).toHaveBeenLastCalledWith('/v1/templates/render', {
        source: TEMPLATE,
        answers: { person: 'Robin' },
        id: 'one-on-one',
        dry_run: true,
      }),
    );
    expect(await screen.findByText('20-contexts/work/one-on-ones/2026-10-09-robin-1-1-2.md')).toBeInTheDocument();
  });

  it('shows a render error inline and keeps the typed answers', async () => {
    postMock.mockResolvedValueOnce({
      ok: false,
      prompts: PROMPTS,
      answers: {},
      rendered: null,
      wouldBeFiledAt: null,
      diagnostics: [],
      error: 'person: a person can not contain [ ] | #',
    });
    mount();
    expect(await screen.findByRole('alert')).toHaveTextContent('person: a person can not contain');
    expect(screen.queryByText(/would be filed at/)).not.toBeInTheDocument();
  });

  it('shows a sidecar failure', async () => {
    postMock.mockRejectedValueOnce(new Error('sidecar down'));
    mount();
    expect(await screen.findByRole('alert')).toHaveTextContent('test run failed — sidecar down');
  });
});
