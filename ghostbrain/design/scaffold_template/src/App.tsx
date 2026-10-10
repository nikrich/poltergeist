import { Link, useRoute } from './router';

const TITLE = "__PROTOTYPE_TITLE__";

/** Screens shown in the nav. Add one entry per screen. */
export const screens: { path: string; label: string }[] = [{ path: '/', label: 'Start' }];

function Waiting() {
  return (
    <section className="placeholder">
      <div className="placeholder-dot" aria-hidden="true" />
      <h1>{TITLE}</h1>
      <p>Waiting for the conversation…</p>
    </section>
  );
}

function NotFound({ route }: { route: string }) {
  return (
    <section className="placeholder">
      <h2>No screen at {route}</h2>
      <Link to="/">Back to start</Link>
    </section>
  );
}

export default function App() {
  const route = useRoute();
  return (
    <div className="app">
      <header className="app-header">
        <span className="app-title">{TITLE}</span>
        <nav className="app-nav">
          {screens.map((s) => (
            <Link key={s.path} to={s.path}>
              {s.label}
            </Link>
          ))}
        </nav>
      </header>
      <main className="app-main">{route === '/' ? <Waiting /> : <NotFound route={route} />}</main>
    </div>
  );
}
