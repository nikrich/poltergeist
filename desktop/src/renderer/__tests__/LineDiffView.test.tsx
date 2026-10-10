import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { LineDiffView } from '../components/LineDiffView';

describe('LineDiffView', () => {
  it('renders the legend and prefixed added / removed / kept lines', () => {
    render(
      <LineDiffView testId="d" oldText={'keep\nold line'} newText={'keep\nnew line'} legend="- old · + new" />,
    );
    const view = screen.getByTestId('d');
    expect(view).toHaveTextContent('- old · + new');
    expect(view).toHaveTextContent('- old line');
    expect(view).toHaveTextContent('+ new line');
    expect(view).toHaveTextContent('keep');
  });
});
