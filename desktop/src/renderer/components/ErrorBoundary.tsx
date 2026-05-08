import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    if (import.meta.env.DEV) {
      console.error('Renderer error:', error, info.componentStack);
    }
  }

  reload = () => {
    window.location.reload();
  };

  render() {
    if (this.state.error) {
      return (
        <div className="flex h-full items-center justify-center bg-paper p-8">
          <div className="max-w-[480px] rounded-lg border border-oxblood/30 bg-oxblood/10 p-6">
            <h2 className="m-0 font-display text-22 font-semibold tracking-tight-x text-ink-0">
              ghostbrain hit a snag.
            </h2>
            <p className="mt-3 text-13 text-ink-1">
              the renderer process threw an error and stopped drawing. you can reload to recover —
              your settings and vault are unaffected.
            </p>
            <pre className="mt-4 overflow-auto rounded-sm bg-paper p-3 font-mono text-11 text-ink-2">
              {this.state.error.message}
            </pre>
            <button
              type="button"
              onClick={this.reload}
              className="mt-4 cursor-pointer rounded-r6 border border-transparent bg-neon px-[18px] py-[11px] font-body text-14 font-medium text-[#0E0F12] transition-all duration-[120ms] hover:bg-neon-dark"
            >
              reload
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
