import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useToasts } from '../stores/toast';

import * as client from '../lib/api/client';
import { ProjectsSettings } from '../screens/settings';
import type { Project } from '../../shared/api-types';

const projects: Project[] = [
  {
    id: 'consulting/poltergeist',
    context: 'consulting',
    slug: 'poltergeist',
    name: 'Poltergeist',
    description: 'second brain',
    archived: false,
    created_at: 1,
  },
  {
    id: 'work/paymnets',
    context: 'work',
    slug: 'paymnets',
    name: 'Paymnets',
    description: 'card rails',
    archived: false,
    created_at: 2,
  },
  {
    id: 'work/old-thing',
    context: 'work',
    slug: 'old-thing',
    name: 'Old Thing',
    description: '',
    archived: true,
    created_at: 3,
  },
];

vi.mock('../lib/api/client', () => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
}));

function renderSection() {
  vi.mocked(client.get).mockImplementation(((path: string) =>
    path === '/v1/vault/contexts'
      ? Promise.resolve({ contexts: ['work', 'consulting', 'side-project', 'personal'] })
      : Promise.resolve(projects)) as never);
  vi.mocked(client.post).mockResolvedValue(projects[0] as never);
  vi.mocked(client.patch).mockResolvedValue(projects[0] as never);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ProjectsSettings />
    </QueryClientProvider>,
  );
}

describe('ProjectsSettings', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useToasts.setState({ toasts: [] });
  });

  it('lists projects grouped under their context', async () => {
    renderSection();
    expect(await screen.findByText('Poltergeist')).toBeTruthy();
    // Eyebrow context heading exists (may also appear in select options — use getAllByText)
    expect(screen.getAllByText('consulting').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('second brain')).toBeTruthy();
  });

  it('creates a project from the form', async () => {
    renderSection();
    await screen.findByText('Poltergeist');
    fireEvent.change(screen.getByPlaceholderText(/project name/i), {
      target: { value: 'Hive IDE' },
    });
    fireEvent.click(screen.getByRole('button', { name: /add project/i }));
    await waitFor(() =>
      expect(vi.mocked(client.post)).toHaveBeenCalledWith('/v1/projects', {
        context: expect.any(String),
        name: 'Hive IDE',
        description: '',
      }),
    );
  });

  it('offers the vault-configured contexts, not a hardcoded list', async () => {
    vi.mocked(client.get).mockImplementation(((path: string) =>
      path === '/v1/vault/contexts'
        ? Promise.resolve({ contexts: ['work', 'home'] })
        : Promise.resolve([])) as never);
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <ProjectsSettings />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getByRole('option', { name: 'work' })).toBeTruthy());
    expect(screen.getByRole('option', { name: 'home' })).toBeTruthy();
    // Only the endpoint-served list renders — no baked-in defaults sneak in.
    expect(screen.getAllByRole('option')).toHaveLength(2);
    expect(screen.queryByRole('option', { name: 'personal' })).toBeNull();
  });

  it('edits a project name and saves with the PATCH body', async () => {
    renderSection();
    await screen.findByText('Paymnets');
    fireEvent.click(screen.getByRole('button', { name: 'edit work/paymnets' }));
    const nameInput = screen.getByLabelText('project name work/paymnets');
    fireEvent.change(nameInput, { target: { value: 'Payments' } });
    expect(screen.getByText('renames the folder too')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'save' }));
    await waitFor(() =>
      expect(vi.mocked(client.patch)).toHaveBeenCalledWith('/v1/projects/work/paymnets', {
        name: 'Payments',
        description: 'card rails',
        archived: undefined,
      }),
    );
  });

  it('shows no folder hint when the slug is unchanged', async () => {
    renderSection();
    await screen.findByText('Paymnets');
    fireEvent.click(screen.getByRole('button', { name: 'edit work/paymnets' }));
    fireEvent.change(screen.getByLabelText('project name work/paymnets'), {
      target: { value: 'PAYMNETS!' },
    });
    expect(screen.queryByText('renames the folder too')).toBeNull();
  });

  it('Enter saves and Escape cancels', async () => {
    renderSection();
    await screen.findByText('Paymnets');
    fireEvent.click(screen.getByRole('button', { name: 'edit work/paymnets' }));
    const input = screen.getByLabelText('project name work/paymnets');
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(screen.queryByLabelText('project name work/paymnets')).toBeNull();
    expect(vi.mocked(client.patch)).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'edit work/paymnets' }));
    fireEvent.change(screen.getByLabelText('project name work/paymnets'), {
      target: { value: 'Payments' },
    });
    fireEvent.keyDown(screen.getByLabelText('project name work/paymnets'), { key: 'Enter' });
    await waitFor(() => expect(vi.mocked(client.patch)).toHaveBeenCalledTimes(1));
  });

  it('unarchives an archived row', async () => {
    renderSection();
    await screen.findByText('Old Thing');
    fireEvent.click(screen.getByRole('button', { name: 'unarchive' }));
    await waitFor(() =>
      expect(vi.mocked(client.patch)).toHaveBeenCalledWith('/v1/projects/work/old-thing', {
        name: undefined,
        description: undefined,
        archived: false,
      }),
    );
  });

  it('toasts the server detail when a rename fails', async () => {
    renderSection();
    vi.mocked(client.patch).mockRejectedValue(new Error('project name already taken'));
    await screen.findByText('Paymnets');
    fireEvent.click(screen.getByRole('button', { name: 'edit work/paymnets' }));
    fireEvent.change(screen.getByLabelText('project name work/paymnets'), {
      target: { value: 'Poltergeist' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'save' }));
    await waitFor(() =>
      expect(
        useToasts.getState().toasts.some((t) => t.message === 'project name already taken'),
      ).toBe(true),
    );
  });
  it('keeps the editor open with the draft when the PATCH is rejected', async () => {
    renderSection();
    vi.mocked(client.patch).mockRejectedValue(
      new Error('project busy: a doc is still being indexed or summarised'),
    );
    await screen.findByText('Paymnets');
    fireEvent.click(screen.getByRole('button', { name: 'edit work/paymnets' }));
    fireEvent.change(screen.getByLabelText('project name work/paymnets'), {
      target: { value: 'Payments' },
    });
    fireEvent.change(screen.getByLabelText('project description work/paymnets'), {
      target: { value: 'card + EFT rails' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'save' }));
    await waitFor(() =>
      expect(
        useToasts.getState().toasts.some((t) => t.message.startsWith('project busy')),
      ).toBe(true),
    );
    await waitFor(() => expect(screen.getByRole('button', { name: 'save' })).toBeTruthy());
    expect(
      (screen.getByLabelText('project name work/paymnets') as HTMLInputElement).value,
    ).toBe('Payments');
    expect(
      (screen.getByLabelText('project description work/paymnets') as HTMLInputElement).value,
    ).toBe('card + EFT rails');
  });

  it('disables save while the PATCH is pending and closes on success', async () => {
    renderSection();
    let resolve!: (p: Project) => void;
    vi.mocked(client.patch).mockReturnValue(
      new Promise<Project>((r) => {
        resolve = r;
      }) as never,
    );
    await screen.findByText('Paymnets');
    fireEvent.click(screen.getByRole('button', { name: 'edit work/paymnets' }));
    fireEvent.change(screen.getByLabelText('project name work/paymnets'), {
      target: { value: 'Payments' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'save' }));
    const pending = await screen.findByRole('button', { name: 'saving…' });
    expect((pending as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByLabelText('project name work/paymnets')).toBeTruthy();
    fireEvent.keyDown(screen.getByLabelText('project name work/paymnets'), { key: 'Enter' });
    expect(vi.mocked(client.patch)).toHaveBeenCalledTimes(1);
    resolve({ ...projects[1], slug: 'payments', id: 'work/payments', name: 'Payments' });
    await waitFor(() => expect(screen.queryByLabelText('project name work/paymnets')).toBeNull());
  });
});
