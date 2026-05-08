import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import App from '../App';

describe('App', () => {
  it('renders the brand without throwing', async () => {
    render(<App />);
    expect(await screen.findByText('ghostbrain')).toBeInTheDocument();
  });
});
