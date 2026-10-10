import { useEffect, useState } from 'react';
import { Lucide } from '../Lucide';
import type { ArtefactDetail } from '../../../shared/design-types';

type Load = { status: 'loading' } | { status: 'ready'; url: string } | { status: 'error'; message: string };

function Frame({ title, url, sandbox }: { title: string; url: string; sandbox: string }) {
  return (
    <iframe
      title={`${title} preview`}
      src={url}
      sandbox={sandbox}
      className="h-full min-h-[min(560px,62vh)] w-full rounded-md border border-hairline bg-white"
    />
  );
}

function Message({ icon, children, tone = 'muted' }: { icon: string; children: React.ReactNode; tone?: 'muted' | 'error' }) {
  return (
    <div className="flex h-full min-h-[240px] flex-col items-center justify-center gap-2 text-center">
      <Lucide
        name={icon}
        size={18}
        className={tone === 'error' ? 'text-oxblood' : 'text-ink-3'}
        style={icon === 'loader' ? { animation: 'gb-spin 0.9s linear infinite' } : undefined}
      />
      <p className={`m-0 max-w-[460px] text-13 leading-[1.5] ${tone === 'error' ? 'text-oxblood' : 'text-ink-1'}`}>
        {children}
      </p>
    </div>
  );
}

const errMsg = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** A scratch prototype, bundled by main at its latest revision. */
export function ArtefactPrototype({ detail }: { detail: ArtefactDetail }) {
  const [load, setLoad] = useState<Load>({ status: 'loading' });
  const { folder, ui_rev: rev } = detail;

  useEffect(() => {
    if (rev <= 0) return;
    let live = true;
    window.gb.design
      .build(folder, rev)
      .then((res) => {
        if (!live) return;
        setLoad(res.ok ? { status: 'ready', url: res.url } : { status: 'error', message: res.error });
      })
      .catch((e: unknown) => {
        if (live) setLoad({ status: 'error', message: errMsg(e) });
      });
    return () => {
      live = false;
    };
  }, [folder, rev]);

  if (rev <= 0) return <Message icon="app-window">No prototype revisions yet.</Message>;
  if (load.status === 'loading') return <Message icon="loader">Bundling rev {rev}…</Message>;
  if (load.status === 'error') return <Message icon="alert-triangle" tone="error">Build failed: {load.message}</Message>;
  return <Frame title={detail.title} url={load.url} sandbox="allow-scripts allow-same-origin allow-forms" />;
}

/** A worktree artefact, served by its own dev server while shown. */
export function ArtefactWorktree({ detail }: { detail: ArtefactDetail }) {
  const [load, setLoad] = useState<Load>({ status: 'loading' });
  const codebase = detail.codebase;
  const worktree = codebase && !codebase.missing ? codebase.worktree : null;
  const appDir = codebase?.app_dir ?? null;

  useEffect(() => {
    if (!worktree || !appDir) return;
    let live = true;
    window.gb.design.devserver
      .ensure(worktree, appDir)
      .then((res) => {
        if (!live) return;
        setLoad(res.ok ? { status: 'ready', url: res.url } : { status: 'error', message: res.error });
      })
      .catch((e: unknown) => {
        if (live) setLoad({ status: 'error', message: errMsg(e) });
      });
    return () => {
      live = false;
      void window.gb.design.devserver.release(worktree);
    };
  }, [worktree, appDir]);

  if (!worktree) {
    return (
      <Message icon="git-branch">
        The worktree was removed — nothing to preview.
        {codebase && (
          <span className="mt-1 block font-mono text-11 text-ink-3">branch {codebase.branch}</span>
        )}
      </Message>
    );
  }
  if (load.status === 'loading') return <Message icon="loader">Starting dev server…</Message>;
  if (load.status === 'error') return <Message icon="alert-triangle" tone="error">{load.message}</Message>;
  return (
    <Frame
      title={detail.title}
      url={load.url}
      sandbox="allow-scripts allow-same-origin allow-forms"
    />
  );
}
