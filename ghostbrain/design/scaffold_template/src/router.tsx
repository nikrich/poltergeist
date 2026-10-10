import { useEffect, useState, type ReactNode } from 'react';

// Tiny hash router. The route lives in location.hash so a reload (or a bundle
// swap in the host) lands on the same screen.

function currentPath(): string {
  const raw = window.location.hash.replace(/^#/, '');
  return raw.startsWith('/') ? raw : `/${raw}`;
}

export function navigate(path: string): void {
  const next = path.startsWith('/') ? path : `/${path}`;
  if (currentPath() !== next) window.location.hash = next;
}

export function useRoute(): string {
  const [route, setRoute] = useState(currentPath);
  useEffect(() => {
    const onChange = () => setRoute(currentPath());
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);
  return route;
}

/** Match "/orders/:id" against a path; returns the params or null. */
export function matchRoute(pattern: string, path: string): Record<string, string> | null {
  const want = pattern.split('/').filter(Boolean);
  const got = path.split('?')[0].split('/').filter(Boolean);
  if (want.length !== got.length) return null;
  const params: Record<string, string> = {};
  for (let i = 0; i < want.length; i++) {
    if (want[i].startsWith(':')) params[want[i].slice(1)] = decodeURIComponent(got[i]);
    else if (want[i] !== got[i]) return null;
  }
  return params;
}

export function Link({
  to,
  children,
  className,
}: {
  to: string;
  children: ReactNode;
  className?: string;
}) {
  const active = useRoute() === to;
  return (
    <a
      href={`#${to}`}
      className={[className, active ? 'active' : ''].filter(Boolean).join(' ') || undefined}
      aria-current={active ? 'page' : undefined}
    >
      {children}
    </a>
  );
}
