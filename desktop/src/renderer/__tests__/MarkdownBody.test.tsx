import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { MarkdownBody } from '../components/MarkdownBody';
import { useNoteView } from '../stores/note-view';

describe('MarkdownBody wikilinks', () => {
  beforeEach(() => {
    useNoteView.setState({ path: null });
  });

  it('renders a wikilink as a gb-note anchor (sanitizer must not strip it)', () => {
    render(<MarkdownBody>{'See [[20-contexts/foo/bar|the note]].'}</MarkdownBody>);
    const link = screen.getByRole('link', { name: 'the note' });
    // react-markdown's default urlTransform rewrites unknown schemes to "" —
    // this locks in our gb-note passthrough.
    expect(link.getAttribute('href')).toBe(
      `gb-note:${encodeURIComponent('20-contexts/foo/bar')}`,
    );
  });

  it('clicking a wikilink opens the note in NoteView', () => {
    render(<MarkdownBody>{'See [[10-daily/2026-06-09]].'}</MarkdownBody>);
    fireEvent.click(screen.getByRole('link', { name: '10-daily/2026-06-09' }));
    expect(useNoteView.getState().path).toBe('10-daily/2026-06-09');
  });
});
