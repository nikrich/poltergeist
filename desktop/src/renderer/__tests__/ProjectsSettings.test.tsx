import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import * as client from '../lib/api/client';
import { ProjectsSettings } from '../screens/settings';
import type { Project } from '../../shared/api-types';

const projects: Project[] = [
  {
    id: 'codeship/poltergeist',
    context: 'codeship',
    slug: 'poltergeist',
    name: 'Poltergeist',
    description: 'second brain',
    archived: false,
    created_at: 1,
  },
];

vi.mock('../lib/api/client', () => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
}));

function renderSection() {
  vi.mocked(client.get).mockResolvedValue(projects as never);
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
  it('lists projects grouped under their context', async () => {
    renderSection();
    expect(await screen.findByText('Poltergeist')).toBeTruthy();
    // Eyebrow context heading exists (may also appear in select options — use getAllByText)
    expect(screen.getAllByText('codeship').length).toBeGreaterThanOrEqual(1);
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
});
