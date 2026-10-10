import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { EditorView } from '@codemirror/view';
import * as client from '../lib/api/client';
import { TemplateSourceEditor } from '../components/TemplateSourceEditor';
import { navigationAllowed } from '../stores/navigation';
import { REGISTRY, TEMPLATE } from './helpers/template-registry';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ApiError: actual.ApiError, get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() };
});
vi.mock('../components/TemplateTestRun', () => ({
  TemplateTestRun: ({ source }: { source: string }) => <div data-testid="test-run">{source.length}</div>,
}));
const getMock = vi.mocked(client.get);
const postMock = vi.mocked(client.post);
const patchMock = vi.mocked(client.patch);

const SOURCE = { id: 'one-on-one', path: '90-meta/templates/one-on-one.md', source: TEMPLATE, etag: 'e1' };

function setup(onDirtyChange?: (d: boolean) => void) {
  let view: EditorView | undefined;
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <TemplateSourceEditor
        templateId="one-on-one"
        onDirtyChange={onDirtyChange}
        onCreateEditor={(v) => {
          view = v;
        }}
      />
    </QueryClientProvider>,
  );
  return {
    edit(text: string) {
      act(() => {
        if (!view) throw new Error('no editor');
        view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: text } });
      });
    },
  };
}

beforeEach(() => {
  getMock.mockImplementation(async (path: string) => {
    if (path === '/v1/templates/one-on-one/source') return SOURCE;
    if (path === '/v1/templates/functions') return REGISTRY;
    if (path === '/v1/templates/query-values') return { types: [], statuses: [], indexing: false };
    if (path === '/v1/vault/contexts') return { contexts: ['work'] };
    throw new Error(`unexpected GET ${path}`);
  });
  postMock.mockResolvedValue({ diagnostics: [] });
});
afterEach(() => {
  getMock.mockReset();
  postMock.mockReset();
  patchMock.mockReset();
  vi.restoreAllMocks();
});

describe('TemplateSourceEditor', () => {
  it('loads the template source and its path', async () => {
    setup();
    expect(await screen.findByText('90-meta/templates/one-on-one.md')).toBeInTheDocument();
    expect(screen.getByText(/1-1 with/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'save' })).toBeDisabled();
  });

  it('saves the edited text with the etag it loaded', async () => {
    const dirty = vi.fn();
    const ed = setup(dirty);
    await screen.findByText('90-meta/templates/one-on-one.md');
    ed.edit(TEMPLATE + '\nmore\n');
    expect(dirty).toHaveBeenLastCalledWith(true);
    expect(screen.getByText('unsaved')).toBeInTheDocument();
    patchMock.mockResolvedValue({ id: 'one-on-one', path: SOURCE.path, etag: 'e2', status: 'applied', changeId: null });
    fireEvent.click(screen.getByRole('button', { name: 'save' }));
    await waitFor(() => expect(dirty).toHaveBeenLastCalledWith(false));
    expect(patchMock).toHaveBeenCalledWith(
      '/v1/templates/one-on-one/source',
      { source: TEMPLATE + '\nmore\n' },
      { ifMatch: 'e1' },
    );
  });

  it('on 409 shows the conflict banner; keep mine overwrites without an etag', async () => {
    const ed = setup();
    await screen.findByText('90-meta/templates/one-on-one.md');
    ed.edit('changed\n');
    patchMock.mockRejectedValueOnce(new client.ApiError('changed', 409));
    fireEvent.click(screen.getByRole('button', { name: 'save' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('changed outside the editor');
    patchMock.mockResolvedValueOnce({ id: 'one-on-one', path: SOURCE.path, etag: 'e3', status: 'applied', changeId: null });
    fireEvent.click(screen.getByRole('button', { name: 'keep mine' }));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    expect(patchMock).toHaveBeenLastCalledWith('/v1/templates/one-on-one/source', { source: 'changed\n' }, { ifMatch: null });
  });

  it('reload theirs replaces the text with the file on disk', async () => {
    const ed = setup();
    await screen.findByText('90-meta/templates/one-on-one.md');
    ed.edit('mine\n');
    patchMock.mockRejectedValueOnce(new client.ApiError('changed', 409));
    fireEvent.click(screen.getByRole('button', { name: 'save' }));
    await screen.findByRole('alert');
    fireEvent.click(screen.getByRole('button', { name: 'reload theirs' }));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    expect(screen.queryByText('unsaved')).not.toBeInTheDocument();
  });

  it('asks before leaving the screen with unsaved changes', async () => {
    const ed = setup();
    await screen.findByText('90-meta/templates/one-on-one.md');
    expect(navigationAllowed('screen')).toBe(true);
    ed.edit('mine\n');
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    expect(navigationAllowed('screen')).toBe(false);
    expect(confirm).toHaveBeenCalled();
  });

  it('toggles the test run pane with the current text', async () => {
    setup();
    await screen.findByText('90-meta/templates/one-on-one.md');
    fireEvent.click(screen.getByRole('button', { name: 'test run' }));
    expect(screen.getByTestId('test-run')).toHaveTextContent(String(TEMPLATE.length));
  });
});
