import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as client from '../lib/api/client';
import { ApiError } from '../lib/api/client';
import { TemplatePromptDialog, dialogFields, todayIso } from '../components/TemplatePromptDialog';
import type { TemplateSummary } from '../../shared/api-types';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return {
    ApiError: actual.ApiError,
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    del: vi.fn(),
    put: vi.fn(),
  };
});
const getMock = vi.mocked(client.get);
const postMock = vi.mocked(client.post);

function withQuery(children: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const ONE_ON_ONE: TemplateSummary = {
  id: 'one-on-one',
  path: '90-meta/templates/one-on-one.md',
  name: '1-1',
  description: '',
  prompts: [
    {
      id: 'person',
      ask: "Who's this 1-1 with?",
      type: 'person',
      optional: false,
      default: null,
      options: [],
    },
    {
      id: 'focus',
      ask: 'Anything specific to cover?',
      type: 'text',
      optional: true,
      default: null,
      options: [],
    },
  ],
  variables: ['context', 'date', 'focus', 'person'],
  valid: true,
  diagnostics: [],
};

const DECISION: TemplateSummary = {
  id: 'decision-record',
  path: '90-meta/templates/decision-record.md',
  name: 'Decision record',
  description: '',
  prompts: [
    {
      id: 'decision',
      ask: 'What did you decide?',
      type: 'text',
      optional: false,
      default: null,
      options: [],
    },
    {
      id: 'status',
      ask: 'Status',
      type: 'choice',
      optional: false,
      default: 'accepted',
      options: ['proposed', 'accepted'],
    },
    { id: 'when', ask: 'When?', type: 'date', optional: false, default: null, options: [] },
    {
      id: 'project',
      ask: 'Which project?',
      type: 'project',
      optional: true,
      default: null,
      options: [],
    },
  ],
  variables: ['context', 'decision', 'project', 'status', 'when'],
  valid: true,
  diagnostics: [],
};

beforeEach(() => {
  getMock.mockImplementation(async (path: string) => {
    if (path === '/v1/vault/contexts') return { contexts: ['work', 'personal'] };
    if (path === '/v1/projects')
      return [
        {
          id: 'work/alpha',
          context: 'work',
          slug: 'alpha',
          name: 'Alpha',
          description: '',
          archived: false,
          created_at: 0,
        },
      ];
    if (path.startsWith('/v1/vault/suggest?kind=person'))
      return {
        items: [
          {
            kind: 'person',
            label: 'Alex',
            path: '30-cross-context/people/alex.md',
            context: '',
            detail: '30-cross-context/people/alex',
            count: null,
          },
        ],
        indexing: false,
      };
    throw new Error(`unexpected GET ${path}`);
  });
});

afterEach(() => {
  getMock.mockReset();
  postMock.mockReset();
});

describe('dialogFields', () => {
  it('adds an implicit context picker only when the template uses {{context}} without a prompt', () => {
    expect(dialogFields(ONE_ON_ONE).map((f) => f.id)).toEqual(['person', 'focus', 'context']);
    expect(dialogFields({ ...ONE_ON_ONE, variables: ['person'] }).map((f) => f.id)).toEqual([
      'person',
      'focus',
    ]);
    expect(dialogFields(DECISION).map((f) => f.id)).toEqual([
      'decision',
      'status',
      'when',
      'project',
      'context',
    ]);
  });
});

describe('TemplatePromptDialog', () => {
  it('renders one field per prompt and gates submit on required answers', async () => {
    render(
      withQuery(<TemplatePromptDialog template={ONE_ON_ONE} mode="create" onClose={() => {}} />),
    );
    expect(screen.getByLabelText("Who's this 1-1 with?")).toBeInTheDocument();
    expect(screen.getByLabelText(/Anything specific to cover\? \(optional\)/)).toBeInTheDocument();
    await screen.findByRole('option', { name: 'personal' });
    expect(screen.getByLabelText('Context')).toHaveValue('work');
    expect(screen.getByRole('button', { name: 'create' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Who's this 1-1 with?"), { target: { value: 'Alex' } });
    expect(screen.getByRole('button', { name: 'create' })).toBeEnabled();
    // Let the person suggest settle so its state update lands inside the test.
    await screen.findByRole('button', { name: /^Alex/ });
  });

  it('picks a person from suggest and creates the note', async () => {
    postMock.mockResolvedValue({
      path: '20-contexts/work/one-on-ones/2026-10-09-alex-1-1.md',
      title: '2026-10-09 Alex 1-1',
      etag: 'e',
      status: 'applied',
    });
    const onCreated = vi.fn();
    const onClose = vi.fn();
    render(
      withQuery(
        <TemplatePromptDialog
          template={ONE_ON_ONE}
          mode="create"
          onClose={onClose}
          onCreated={onCreated}
        />,
      ),
    );
    await screen.findByRole('option', { name: 'personal' });
    fireEvent.change(screen.getByLabelText("Who's this 1-1 with?"), { target: { value: 'al' } });
    fireEvent.click(await screen.findByRole('button', { name: /^Alex/ }));
    expect(getMock).toHaveBeenCalledWith('/v1/vault/suggest?kind=person&q=al&limit=20');
    expect(screen.getByLabelText("Who's this 1-1 with?")).toHaveValue('Alex');
    fireEvent.click(screen.getByRole('button', { name: 'create' }));
    await waitFor(() => expect(onCreated).toHaveBeenCalled());
    expect(postMock).toHaveBeenCalledWith('/v1/templates/one-on-one/create', {
      answers: { person: '30-cross-context/people/alex.md', context: 'work' },
    });
    expect(onClose).toHaveBeenCalled();
  });

  it('submits a typed name when no suggestion is picked', async () => {
    postMock.mockResolvedValue({ path: 'x.md', title: 'x', etag: null, status: 'applied' });
    render(
      withQuery(<TemplatePromptDialog template={ONE_ON_ONE} mode="create" onClose={() => {}} />),
    );
    await screen.findByRole('option', { name: 'personal' });
    fireEvent.change(screen.getByLabelText("Who's this 1-1 with?"), { target: { value: 'Alex' } });
    fireEvent.click(screen.getByRole('button', { name: 'create' }));
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith('/v1/templates/one-on-one/create', {
        answers: { person: 'Alex', context: 'work' },
      }),
    );
  });

  it('prefills choice defaults and today for dates, and sends picked projects', async () => {
    postMock.mockResolvedValue({ path: 'x.md', title: 'x', etag: null, status: 'applied' });
    render(
      withQuery(<TemplatePromptDialog template={DECISION} mode="create" onClose={() => {}} />),
    );
    await screen.findByRole('option', { name: 'work / Alpha' });
    expect(screen.getByLabelText('Status')).toHaveValue('accepted');
    expect(screen.getByLabelText('When?')).toHaveValue(todayIso());
    fireEvent.change(screen.getByLabelText('What did you decide?'), {
      target: { value: 'Use Postgres' },
    });
    fireEvent.change(screen.getByLabelText(/Which project\?/), { target: { value: 'work/alpha' } });
    fireEvent.click(screen.getByRole('button', { name: 'create' }));
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith('/v1/templates/decision-record/create', {
        answers: {
          decision: 'Use Postgres',
          status: 'accepted',
          when: todayIso(),
          project: 'work/alpha',
          context: 'work',
        },
      }),
    );
  });

  it('shows a server error and marks the field it names', async () => {
    postMock.mockRejectedValue(
      new ApiError("person: a person's name can't contain [ ] | # or line breaks", 422),
    );
    render(
      withQuery(<TemplatePromptDialog template={ONE_ON_ONE} mode="create" onClose={() => {}} />),
    );
    await screen.findByRole('option', { name: 'personal' });
    fireEvent.change(screen.getByLabelText("Who's this 1-1 with?"), { target: { value: 'A]]' } });
    fireEvent.click(screen.getByRole('button', { name: 'create' }));
    expect(await screen.findByRole('alert')).toHaveTextContent("can't contain");
    expect(screen.getByLabelText("Who's this 1-1 with?")).toHaveAttribute('aria-invalid', 'true');
  });

  it('insert mode renders and hands back the body', async () => {
    postMock.mockResolvedValue({
      path: 'x.md',
      folder: 'f',
      filename: 'x.md',
      title: 'x',
      frontmatter: {},
      body: '# 1-1 with [[Alex]]\n',
    });
    const onInsert = vi.fn();
    render(
      withQuery(
        <TemplatePromptDialog
          template={ONE_ON_ONE}
          mode="insert"
          onClose={() => {}}
          onInsert={onInsert}
        />,
      ),
    );
    await screen.findByRole('option', { name: 'personal' });
    fireEvent.change(screen.getByLabelText("Who's this 1-1 with?"), { target: { value: 'Alex' } });
    fireEvent.click(screen.getByRole('button', { name: 'insert' }));
    await waitFor(() => expect(onInsert).toHaveBeenCalledWith('# 1-1 with [[Alex]]\n'));
    expect(postMock.mock.calls[0]![0]).toBe('/v1/templates/one-on-one/render');
  });
});

describe('todayIso', () => {
  it('formats a fixed local date as YYYY-MM-DD', () => {
    expect(todayIso(new Date(2026, 0, 5, 12, 0, 0))).toBe('2026-01-05');
    expect(todayIso(new Date(2026, 11, 31, 12, 0, 0))).toBe('2026-12-31');
  });
});

describe('TemplatePromptDialog edge cases', () => {
  it('closes on Escape without letting the key reach parent listeners', async () => {
    const onClose = vi.fn();
    const parentWindow = vi.fn();
    const parentDocument = vi.fn();
    window.addEventListener('keydown', parentWindow);
    document.addEventListener('keydown', parentDocument);
    try {
      render(
        withQuery(<TemplatePromptDialog template={ONE_ON_ONE} mode="create" onClose={onClose} />),
      );
      await screen.findByRole('option', { name: 'personal' });
      // fireEvent returns false when the handler called preventDefault.
      expect(
        fireEvent.keyDown(screen.getByLabelText("Who's this 1-1 with?"), { key: 'Escape' }),
      ).toBe(false);
      expect(onClose).toHaveBeenCalledTimes(1);
      expect(parentWindow).not.toHaveBeenCalled();
      expect(parentDocument).not.toHaveBeenCalled();
    } finally {
      window.removeEventListener('keydown', parentWindow);
      document.removeEventListener('keydown', parentDocument);
    }
  });

  it('lets non-Escape keys through to parent listeners', async () => {
    const parentWindow = vi.fn();
    window.addEventListener('keydown', parentWindow);
    try {
      render(
        withQuery(<TemplatePromptDialog template={ONE_ON_ONE} mode="create" onClose={() => {}} />),
      );
      fireEvent.keyDown(screen.getByLabelText("Who's this 1-1 with?"), { key: 'a' });
      expect(parentWindow).toHaveBeenCalled();
      // Let the contexts/projects queries settle inside the test (no late act() warnings).
      await screen.findByRole('option', { name: 'personal' });
    } finally {
      window.removeEventListener('keydown', parentWindow);
    }
  });

  it('degrades a pydantic list-detail 422 to a general error without marking a field', async () => {
    postMock.mockRejectedValue(
      new ApiError(
        '{"detail":[{"type":"missing","loc":["body","answers"],"msg":"Field required","input":null}]}',
        422,
      ),
    );
    render(
      withQuery(<TemplatePromptDialog template={ONE_ON_ONE} mode="create" onClose={() => {}} />),
    );
    await screen.findByRole('option', { name: 'personal' });
    fireEvent.change(screen.getByLabelText("Who's this 1-1 with?"), { target: { value: 'Alex' } });
    fireEvent.click(screen.getByRole('button', { name: 'create' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('could not create the note from this template');
    expect(alert).not.toHaveTextContent('detail');
    expect(screen.getByLabelText("Who's this 1-1 with?")).toHaveAttribute('aria-invalid', 'false');
  });

  it('does not mark a field for an unknown field name in the error', async () => {
    postMock.mockRejectedValue(new ApiError('nonsense: bad value', 422));
    render(
      withQuery(
        <TemplatePromptDialog
          template={ONE_ON_ONE}
          mode="insert"
          onClose={() => {}}
          onInsert={() => {}}
        />,
      ),
    );
    await screen.findByRole('option', { name: 'personal' });
    fireEvent.change(screen.getByLabelText("Who's this 1-1 with?"), { target: { value: 'Alex' } });
    fireEvent.click(screen.getByRole('button', { name: 'insert' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('nonsense: bad value');
    expect(screen.getByLabelText("Who's this 1-1 with?")).toHaveAttribute('aria-invalid', 'false');
  });
});

describe('TemplatePromptDialog person default', () => {
  it('shows a person prompt default in the input and submits it', async () => {
    postMock.mockResolvedValue({ path: 'x.md', title: 'x', etag: null, status: 'applied' });
    const withDefault: TemplateSummary = {
      ...ONE_ON_ONE,
      prompts: [{ ...ONE_ON_ONE.prompts[0]!, default: 'Alex' }, ONE_ON_ONE.prompts[1]!],
    };
    render(
      withQuery(<TemplatePromptDialog template={withDefault} mode="create" onClose={() => {}} />),
    );
    await screen.findByRole('option', { name: 'personal' });
    expect(screen.getByLabelText("Who's this 1-1 with?")).toHaveValue('Alex');
    expect(screen.getByRole('button', { name: 'create' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'create' }));
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith('/v1/templates/one-on-one/create', {
        answers: { person: 'Alex', context: 'work' },
      }),
    );
  });
});
