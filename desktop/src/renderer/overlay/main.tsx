import { createRoot } from 'react-dom/client';
import '../styles.css';
import { Overlay } from './Overlay';

const root = document.getElementById('root');
if (root) createRoot(root).render(<Overlay />);
