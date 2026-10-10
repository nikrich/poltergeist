import type { GraphKind, NoteKind, OntologyKind } from '../../../shared/api-types';

export const NOTE_KINDS: readonly NoteKind[] = [
  'person', 'meeting', 'decision', 'action', 'ticket', 'doc', 'jot', 'note',
];

export const ONTOLOGY_KINDS: readonly OntologyKind[] = [
  'self', 'context', 'project', 'artefact', 'concept', 'rule',
  'decision', 'requirement', 'system', 'role', 'question', 'topic',
];

/** Mirrors the --kind-* tokens in colors_and_type.css (graph-kinds.test keeps
 * them equal). Canvas needs literal colours, so they are duplicated here. */
export const KIND_COLORS: Record<GraphKind, string> = {
  person: '#7FB3D5',
  meeting: '#A78BFA',
  decision: '#C5FF3D',
  action: '#FF6B5A',
  ticket: '#F5B94A',
  doc: '#5EC8B8',
  jot: '#E58FD0',
  note: '#B7BAC2',
  self: '#F2F3F5',
  context: '#8C93A8',
  project: '#4FD1FF',
  artefact: '#6E7381',
  concept: '#9AD1FF',
  rule: '#FFB86B',
  requirement: '#F5E663',
  system: '#62D69B',
  role: '#D9A6FF',
  question: '#FF8FA3',
  topic: '#F28C38',
};

export const KIND_LABELS: Record<GraphKind, string> = {
  person: 'people',
  meeting: 'meetings',
  decision: 'decisions',
  action: 'actions',
  ticket: 'tickets',
  doc: 'docs',
  jot: 'jots',
  note: 'notes',
  self: 'me',
  context: 'contexts',
  project: 'projects',
  artefact: 'sources',
  concept: 'concepts',
  rule: 'rules',
  requirement: 'requirements',
  system: 'systems',
  role: 'roles',
  question: 'open questions',
  topic: 'topics',
};

export const GHOST_COLOR = '#7A7E88'; // --ink-2
export const FOCUS_COLOR = '#C5FF3D'; // --neon
export const LABEL_COLOR = '#B7BAC2'; // --ink-1
export const GROUND_COLOR = '#090B14'; // the constellation's dark ground
export const EDGE_COLOR = 'rgba(183, 186, 194, 0.16)';
export const EDGE_HI_COLOR = 'rgba(197, 255, 61, 0.55)';
export const LABEL_FONT = '11px "JetBrains Mono", ui-monospace, monospace';
