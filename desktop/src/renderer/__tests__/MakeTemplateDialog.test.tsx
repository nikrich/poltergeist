import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as client from '../lib/api/client';
import { MakeTemplateDialog } from '../components/MakeTemplateDialog';
import { registerNavigationGuard, useNavigation } from '../stores/navigation';
import type { TemplateGenerateResponse } from '../../shared/api-types';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ApiError: actual.ApiError, get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() };
});
const postMock = vi.mocked(client.post);

function mount(onClose = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MakeTemplateDialog onClose={onClose} />
    </QueryClientProvider>,
  );
  return onClose;
}

function describeAndGenerate(text: string) {
  fireEvent.change(screen.getByLabelText('describe the template'), { target: { value: text } });
  fireEvent.click(screen.getByRole('button', { name: 'generate' }));
}

const PENDING: TemplateGenerateResponse = {
  status: 'pending',
  id: 'weekly-review',
  path: '90-meta/templates/weekly-review.md',
  name: 'Weekly review',
  changeId: '7',
};

beforeEach(() => useNavigation.setState({ active: 'jots' }));
afterEach(() => {
  postMock.mockReset();
  vi.unstubAllGlobals();
});

describe('MakeTemplateDialog', () => {
  it('needs a description before generating', () => {
    mount();
    expect(screen.getByRole('button', { name: 'generate' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('describe the template'), { target: { value: '   ' } });
    expect(screen.getByRole('button', { name: 'generate' })).toBeDisabled();
  });

  it('says the template waits for approval and opens the changes screen', async () => {
    postMock.mockResolvedValue(PENDING);
    const onClose = mount();
    describeAndGenerate('  a weekly review  ');
    expect(await screen.findByText(/pending your approval on the changes screen/)).toHaveTextContent('Weekly review');
    expect(postMock).toHaveBeenCalledWith('/v1/templates/generate', { description: 'a weekly review' });
    fireEvent.click(screen.getByRole('button', { name: 'open changes' }));
    expect(onClose).toHaveBeenCalled();
    expect(useNavigation.getState().active).toBe('changes');
  });

  it('stays open when a navigation guard cancels open changes', async () => {
    postMock.mockResolvedValue(PENDING);
    const unregister = registerNavigationGuard('screen', () => false);
    try {
      const onClose = mount();
      describeAndGenerate('a weekly review');
      fireEvent.click(await screen.findByRole('button', { name: 'open changes' }));
      expect(useNavigation.getState().active).toBe('jots');
      expect(onClose).not.toHaveBeenCalled();
      expect(screen.getByRole('dialog', { name: 'make a template with ai' })).toBeInTheDocument();
    } finally {
      unregister();
    }
  });

  it('shows the problems and the raw draft when validation failed twice', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', { clipboard: { writeText } });
    postMock.mockResolvedValue({
      status: 'invalid',
      message: 'the draft is not a valid template (line 9: `{{teem}}` is not a known placeholder)',
      draft: '---\ntemplate:\n  name: Standup\n---\n# {{teem}}\n',
      diagnostics: [{ line: 5, col: 3, severity: 'error', message: '`{{teem}}` is not a known placeholder', code: 'unknown-placeholder' }],
    });
    mount();
    describeAndGenerate('standup');
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('nothing was saved');
    expect(screen.getByRole('list', { name: 'problems' })).toHaveTextContent('line 5: `{{teem}}` is not a known placeholder');
    expect(screen.getByLabelText('ai draft')).toHaveTextContent('name: Standup');
    fireEvent.click(screen.getByRole('button', { name: 'copy draft' }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('---\ntemplate:\n  name: Standup\n---\n# {{teem}}\n'));
  });

  it('shows a provider or sidecar error', async () => {
    postMock.mockRejectedValue(new client.ApiError('no AI provider is set up', 412));
    mount();
    describeAndGenerate('standup');
    expect(await screen.findByRole('alert')).toHaveTextContent('could not make a template — no AI provider is set up');
  });
});
