import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles.css';

// The host page links design-pack/tokens.css and owns scroll/route keeping
// across bundle swaps; only the prototype's layout styles are imported here.

const root = document.getElementById('root');
if (root) {
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}
