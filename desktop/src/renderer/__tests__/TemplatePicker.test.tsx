import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as client from '../lib/api/client';
import { TemplateInsertDialog, TemplateMenu } from '../components/TemplatePicker';
import type { TemplateSummary } from '../../shared/api-types';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ApiError: actual.ApiError, get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() };
});
const getMock = vi.mocked(client.get);
const postMock = vi.mocked(client.post);

function withQuery(children: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const MEETING: TemplateSummary = {
  id: 'meeting-notes',
  path: '90-meta/templates/meeting-notes.md',
  name: 'Meeting notes',
  description: 'Agenda, notes, decisions',
  prompts: [{ id: 'topic', ask: 'Topic', type: 'text', optional: false, default: null, options: [] }],
  variables: ['context', 'date', 'topic'],
  valid: true,
  diagnostics: [],
};
const BROKEN: TemplateSummary = {
  id: 'broken',
  path: '90-meta/templates/broken.md',
  name: 'broken',
  description: '',
  prompts: [],
  variables: [],
  valid: false,
  diagnostics: [{ line: 3, col: 1, severity: 'error', message: 'template.name: Field required', code: 'schema' }],
};

beforeEach(() => {
  getMock.mockImplementation(async (path: string) => {
    if (path === '/v1/templates') return { templates: [MEETING, BROKEN] };
    if (path === '/v1/vault/contexts') return { contexts: ['work'] };
    if (path === '/v1/projects') return [];
    throw new Error(`unexpected GET ${path}`);
  });
});

afterEach(() => {
  getMock.mockReset();
  postMock.mockReset();
});

async function fillTopicAndSubmit(label: 'create' | 'insert') {
  fireEvent.change(await screen.findByLabelText('Topic'), { target: { value: 'Planning' } });
  await waitFor(() => expect(screen.getByRole('button', { name: label })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: label }));
}

describe('TemplateMenu', () => {
  it('fetches templates only once the menu opens', async () => {
    render(withQuery(<TemplateMenu onCreated={() => {}} />));
    expect(getMock).not.toHaveBeenCalledWith('/v1/templates');
    fireEvent.click(screen.getByRole('button', { name: 'template' }));
    expect(await screen.findByRole('menuitem', { name: /Meeting notes/ })).toBeEnabled();
  });

  it('shows a broken template disabled with its first error', async () => {
    render(withQuery(<TemplateMenu onCreated={() => {}} />));
    fireEvent.click(screen.getByRole('button', { name: 'template' }));
    const item = await screen.findByRole('menuitem', { name: /broken/ });
    expect(item).toBeDisabled();
    expect(item).toHaveAttribute('title', 'line 3: template.name: Field required');
  });

  it('picking a template opens its prompts and reports the created note', async () => {
    const res = { path: '20-contexts/work/meetings/2026-10-09-planning.md', title: '2026-10-09 Planning', etag: 'e', status: 'applied' as const };
    postMock.mockResolvedValue(res);
    const onCreated = vi.fn();
    render(withQuery(<TemplateMenu onCreated={onCreated} />));
    fireEvent.click(screen.getByRole('button', { name: 'template' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: /Meeting notes/ }));
    expect(screen.queryByRole('menu')).toBeNull();
    await fillTopicAndSubmit('create');
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(res));
  });

  it('shows an error when templates cannot load', async () => {
    getMock.mockRejectedValue(new Error('sidecar down'));
    render(withQuery(<TemplateMenu onCreated={() => {}} />));
    fireEvent.click(screen.getByRole('button', { name: 'template' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('templates unavailable — sidecar down');
  });
});

describe('TemplateInsertDialog', () => {
  it('lists templates, prompts, and inserts the rendered body', async () => {
    postMock.mockResolvedValue({ path: 'x.md', folder: 'f', filename: 'x.md', title: 'x', frontmatter: {}, body: '# Planning\n' });
    const onInsert = vi.fn();
    render(withQuery(<TemplateInsertDialog onClose={() => {}} onInsert={onInsert} />));
    expect(screen.getByRole('dialog', { name: 'insert template' })).toBeInTheDocument();
    fireEvent.click(await screen.findByRole('menuitem', { name: /Meeting notes/ }));
    await fillTopicAndSubmit('insert');
    await waitFor(() => expect(onInsert).toHaveBeenCalledWith('# Planning\n'));
    expect(postMock).toHaveBeenCalledWith('/v1/templates/meeting-notes/render', {
      answers: { topic: 'Planning', context: 'work' },
    });
  });
});
