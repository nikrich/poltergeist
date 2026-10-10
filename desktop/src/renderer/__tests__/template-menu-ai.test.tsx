import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as client from '../lib/api/client';
import { TemplateMenu } from '../components/TemplatePicker';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ApiError: actual.ApiError, get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() };
});
const getMock = vi.mocked(client.get);

afterEach(() => getMock.mockReset());

describe('TemplateMenu: make one with ai', () => {
  it('opens the AI dialog from the template menu', async () => {
    getMock.mockResolvedValue({ templates: [] });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <TemplateMenu onCreated={() => {}} />
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'template' }));
    fireEvent.click(await screen.findByRole('button', { name: 'make one with ai…' }));
    expect(screen.getByRole('dialog', { name: 'make a template with ai' })).toBeInTheDocument();
    expect(screen.queryByRole('menu', { name: 'templates' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'close' }));
    expect(screen.queryByRole('dialog', { name: 'make a template with ai' })).not.toBeInTheDocument();
  });
});
