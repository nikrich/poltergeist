// Live design session — wire contract between the sidecar (/v1/design/*),
// Electron main (bundler, gbproto://) and the renderer. Python mirrors these
// shapes in ghostbrain/api/models/design.py; keep both in step.

export type DesignCanvas = 'ui' | 'board';

/** scratch: standalone prototype in the vault, bundled by main.
 *  worktree: a git worktree of an existing frontend, run by its own dev server. */
export type UiKind = 'scratch' | 'worktree';

export interface CodebaseInfo {
  /** Main checkout of the repo. */
  repo: string;
  name: string;
  /** The app folder inside the worktree (== worktree unless nested). */
  app_dir: string;
  worktree: string;
  branch: string;
  base: string;
}

export type InstallState = 'idle' | 'running' | 'failed' | 'done';

/** off: never started · active: listening + updating · paused: kept, no
 *  updates · ended: recording over · unavailable: cannot run (reason set). */
export type CanvasState = 'off' | 'active' | 'paused' | 'ended' | 'unavailable';

export interface RevInfo {
  rev: number;
  at: string; // ISO timestamp
  summary: string;
}

export interface CanvasSnapshot {
  state: CanvasState;
  /** Latest successful revision (0 = nothing generated yet). */
  rev: number;
  /** An agent run is in flight. */
  running: boolean;
  /** Seconds of relevant speech waiting for the next run. */
  buffered_s: number;
  reason: string | null;
  last_error: string | null;
  revs: RevInfo[];
}

export type BoardItemKind =
  | 'event'
  | 'command'
  | 'aggregate'
  | 'policy'
  | 'read_model'
  | 'external'
  | 'actor'
  | 'hotspot';

export interface BoardItem {
  id: string;
  kind: BoardItemKind;
  label: string;
  /** BoardContext.id, or null when not yet placed in a bounded context. */
  context: string | null;
  /** Timeline position (ascending, left → right). */
  order: number;
}

export interface BoardModel {
  contexts: { id: string; name: string }[];
  items: BoardItem[];
  links: { from: string; to: string }[];
}

export interface DesignSessionSnapshot {
  id: string;
  recording_title: string | null;
  context: string;
  project_id: string | null; // "<context>/<slug>"
  pack_id: string;
  /** Absolute path of the prototype folder (main bundles from here). */
  prototype_dir: string;
  /** Vault-relative path of the same folder. */
  prototype_rel: string;
  focus: DesignCanvas | null;
  /** Spoken-command listener is running for this recording. */
  listening: boolean;
  canvases: Record<DesignCanvas, CanvasSnapshot>;
  board: BoardModel | null;
  ui_kind: UiKind;
  codebase: CodebaseInfo | null;
  /** Dependency install of the worktree (idle for scratch). */
  install: InstallState;
  /** A repo picked by voice installs/runs nothing until the user confirms
   *  it (POST /session/codebase with its path). True for scratch and for
   *  repos picked in the panel. */
  codebase_confirmed: boolean;
  /** Vault-relative artefact folder (same as prototype_rel). */
  artefact_rel: string;
}

export type DesignCommandKind =
  | 'start_ui'
  | 'start_board'
  | 'focus_ui'
  | 'focus_board'
  | 'pause'
  | 'resume'
  | 'nudge'
  | 'codebase';

/** Events on GET /v1/design/live (forwarded to `design:live:event`). */
export type DesignLiveEvent =
  | { type: 'snapshot'; session: DesignSessionSnapshot }
  | {
      type: 'command';
      command: DesignCommandKind;
      canvas: DesignCanvas | 'both' | null;
      /** Toast copy, e.g. "Started frontend prototype". */
      label: string;
      /** Pass to POST /v1/design/session/undo; null when not undoable. */
      undo_token: string | null;
      /** True when spoken (from the transcript), false when from a button. */
      spoken: boolean;
    }
  | { type: 'revision'; canvas: DesignCanvas; rev: number; summary: string }
  | { type: 'error'; canvas: DesignCanvas | null; message: string }
  | { type: 'idle' } // no recording in progress
  | { type: 'end' };

export interface DesignPack {
  id: string;
  name: string;
  source: string;
  imported_at: string | null;
  builtin: boolean;
}

export interface DesignPackImportJob {
  id: string;
  source: string;
  status: 'running' | 'done' | 'error';
  message: string | null;
  pack_id: string | null;
}

export interface DesignSettings {
  /** Listen for spoken design commands during recordings. */
  listen: boolean;
  /** Max spend per UI/board agent run. */
  budget_usd: number;
  /** Pack used when the project has none. */
  default_pack: string;
  /** Folders searched for existing codebases ("~" allowed). */
  code_roots: string[];
}

/** Result of bundling a prototype in Electron main. */
export type DesignBuildResult =
  | { ok: true; rev: number; url: string }
  | { ok: false; rev: number; error: string };

/** A git repo found under the code roots (codebase picker). */
export interface CodebaseCandidate {
  path: string;
  rel: string;
  name: string;
  frontend: boolean;
}

export type ArtefactKind = 'prototype' | 'worktree' | 'board';

export interface ArtefactSummary {
  /** Vault-relative artefact folder. */
  id: string;
  title: string;
  kind: ArtefactKind;
  /** Has an event-storming board too. */
  board: boolean;
  date: string; // YYYY-MM-DD
  context: string;
  project: string | null;
  meeting: string | null;
  /** Vault-relative meeting note. */
  meeting_path: string | null;
  ui_rev: number;
  board_rev: number;
  codebase: (CodebaseInfo & { missing: boolean }) | null;
}

export interface ArtefactDetail extends ArtefactSummary {
  /** Absolute artefact folder. */
  folder: string;
  revs: RevInfo[];
  board_model: BoardModel | null;
  design_system: string | null;
}

export type DevServerResult =
  | { ok: true; url: string; errors: string[] }
  | { ok: false; error: string };
