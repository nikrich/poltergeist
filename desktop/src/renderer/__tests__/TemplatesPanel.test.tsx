import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as client from '../lib/api/client';
import { TemplatesPanel } from '../screens/templates';
import type { TemplateSummary } from '../../shared/api-types';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ApiError: actual.ApiError, get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() };
});
const editorProps = vi.fn();
const editorMounts = vi.fn();
vi.mock('../components/TemplateSourceEditor', async () => {
  const { useEffect } = await import('react');
  return {
    DISCARD_TEMPLATE_PROMPT: 'discard?',
    TemplateSourceEditor: (props: { templateId: string; onDirtyChange?: (d: boolean) => void }) => {
      editorProps(props);
      useEffect(() => {
        editorMounts(props.templateId);
      }, []); // eslint-disable-line react-hooks/exhaustive-deps
      return (
        <div>
          editing {props.templateId}
          <button type="button" onClick={() => props.onDirtyChange?.(true)}>
            make dirty
          </button>
        </div>
      );
    },
  };
});
const getMock = vi.mocked(client.get);
const postMock = vi.mocked(client.post);

function summary(id: string, name: string, valid = true): TemplateSummary {
  return {
    id,
    path: `90-meta/templates/${id}.md`,
    name,
    description: '',
    prompts: [],
    variables: [],
    valid,
    diagnostics: valid ? [] : [{ line: 3, col: 1, severity: 'error', message: 'bad', code: 'yaml' }],
  };
}

function mount(onBack = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <TemplatesPanel onBack={onBack} />
    </QueryClientProvider>,
  );
  return onBack;
}

beforeEach(() => {
  getMock.mockResolvedValue({ templates: [summary('one-on-one', '1-1'), summary('broken', 'broken', false)] });
});
afterEach(() => {
  getMock.mockReset();
  postMock.mockReset();
  editorProps.mockReset();
  editorMounts.mockReset();
  vi.restoreAllMocks();
});

describe('TemplatesPanel', () => {
  it('lists templates, broken ones too, and opens one in the editor', async () => {
    mount();
    fireEvent.click(await screen.findByRole('button', { name: 'edit template broken' }));
    expect(screen.getByText('editing broken')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'edit template broken' })).toHaveTextContent('⚠');
  });

  it('creates a blank template and opens it', async () => {
    postMock.mockResolvedValue({ id: 'weekly-review', path: 'p', etag: 'e', status: 'applied', changeId: null });
    mount();
    fireEvent.click(await screen.findByRole('button', { name: 'new template' }));
    fireEvent.change(screen.getByLabelText('template name'), { target: { value: 'Weekly review' } });
    fireEvent.click(screen.getByRole('button', { name: 'create' }));
    await waitFor(() => expect(screen.getByText('editing weekly-review')).toBeInTheDocument());
    expect(postMock).toHaveBeenCalledWith('/v1/templates', { name: 'Weekly review' });
  });

  it('remounts the editor when switching templates so text never crosses ids', async () => {
    mount();
    fireEvent.click(await screen.findByRole('button', { name: 'edit template 1-1' }));
    fireEvent.click(screen.getByRole('button', { name: 'edit template broken' }));
    expect(screen.getByText('editing broken')).toBeInTheDocument();
    expect(editorMounts.mock.calls).toEqual([['one-on-one'], ['broken']]);
  });

  it('asks before switching away from unsaved changes', async () => {
    const onBack = mount();
    fireEvent.click(await screen.findByRole('button', { name: 'edit template 1-1' }));
    fireEvent.click(screen.getByRole('button', { name: 'make dirty' }));
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    fireEvent.click(screen.getByRole('button', { name: 'edit template broken' }));
    expect(screen.getByText('editing one-on-one')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'back to jots' }));
    expect(onBack).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByRole('button', { name: 'back to jots' }));
    expect(onBack).toHaveBeenCalled();
  });
});
