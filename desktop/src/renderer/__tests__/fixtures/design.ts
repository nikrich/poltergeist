import type {
  ArtefactDetail,
  ArtefactSummary,
  BoardModel,
  CanvasSnapshot,
  DesignSessionSnapshot,
} from '../../../shared/design-types';

export function makeCanvas(over: Partial<CanvasSnapshot> = {}): CanvasSnapshot {
  return {
    state: 'off',
    rev: 0,
    running: false,
    buffered_s: 0,
    reason: null,
    last_error: null,
    revs: [],
    ...over,
  };
}

export function makeSession(
  over: Omit<Partial<DesignSessionSnapshot>, 'canvases' | 'board'> & {
    ui?: Partial<CanvasSnapshot>;
    board?: Partial<CanvasSnapshot>;
    boardModel?: BoardModel | null;
  } = {},
): DesignSessionSnapshot {
  const { ui, board, boardModel, ...rest } = over;
  return {
    id: 'sess-1',
    recording_title: 'Checkout redesign',
    context: 'work',
    project_id: null,
    pack_id: 'poltergeist-neutral',
    prototype_dir: '/vault/20-contexts/work/prototypes/2026-10-10-checkout',
    prototype_rel: '20-contexts/work/prototypes/2026-10-10-checkout',
    focus: null,
    listening: true,
    canvases: { ui: makeCanvas(ui), board: makeCanvas(board) },
    board: boardModel ?? null,
    ui_kind: 'scratch',
    codebase: null,
    install: 'idle',
    codebase_confirmed: true,
    artefact_rel: '20-contexts/work/prototypes/2026-10-10-checkout',
    ...rest,
  };
}

export const sampleBoard: BoardModel = {
  contexts: [
    { id: 'orders', name: 'Orders' },
    { id: 'billing', name: 'Billing' },
  ],
  items: [
    { id: 'place', kind: 'command', label: 'Place order', context: 'orders', order: 1 },
    { id: 'order', kind: 'aggregate', label: 'Order', context: 'orders', order: 2 },
    { id: 'placed', kind: 'event', label: 'Order placed', context: 'orders', order: 3 },
    { id: 'charge', kind: 'policy', label: 'Charge card', context: 'billing', order: 3 },
    { id: 'psp', kind: 'external', label: 'Stripe', context: null, order: 4 },
  ],
  links: [
    { from: 'place', to: 'order' },
    { from: 'order', to: 'placed' },
    { from: 'placed', to: 'charge' },
    { from: 'charge', to: 'psp' },
  ],
};

export function makeArtefact(over: Partial<ArtefactSummary> = {}): ArtefactSummary {
  return {
    id: '20-contexts/work/prototypes/2026-10-10-checkout',
    title: 'Checkout redesign',
    kind: 'prototype',
    board: false,
    date: '2026-10-10',
    context: 'work',
    project: null,
    meeting: 'Checkout sync',
    meeting_path: '20-contexts/work/calendar/transcripts/2026-10-10-checkout-sync.md',
    ui_rev: 3,
    board_rev: 0,
    codebase: null,
    ...over,
  };
}

export function makeArtefactDetail(
  over: Partial<ArtefactDetail> = {},
): ArtefactDetail {
  const summary = makeArtefact(over);
  return {
    folder: `/vault/${summary.id}`,
    revs: [
      { rev: 1, at: '2026-10-10T10:00:00Z', summary: 'first screen' },
      { rev: 2, at: '2026-10-10T10:05:00Z', summary: 'added cart' },
      { rev: 3, at: '2026-10-10T10:09:00Z', summary: 'payment step' },
    ],
    board_model: null,
    design_system: 'poltergeist-neutral',
    ...summary,
    ...over,
  };
}
