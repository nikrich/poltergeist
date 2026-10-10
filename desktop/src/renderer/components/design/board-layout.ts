import type { BoardItemKind, BoardModel } from '../../../shared/design-types';

export const NOTE_W = 128;
export const NOTE_H = 84;
const ACTOR_W = 84;
const ACTOR_H = 48;
const COL_GAP = 32;
const ROW_GAP = 14;
const LANE_PAD = 18;
/** Room on the left of each lane for its name. */
export const LANE_LABEL_W = 132;

export const UNASSIGNED_LANE = '__unassigned';

export interface LaidOutNote {
  id: string;
  kind: BoardItemKind;
  label: string;
  lane: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface LaidOutLane {
  id: string;
  name: string;
  y: number;
  height: number;
}

export interface LaidOutArrow {
  from: string;
  to: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface BoardLayout {
  width: number;
  height: number;
  lanes: LaidOutLane[];
  notes: LaidOutNote[];
  arrows: LaidOutArrow[];
}

function noteSize(kind: BoardItemKind): { w: number; h: number } {
  return kind === 'actor' ? { w: ACTOR_W, h: ACTOR_H } : { w: NOTE_W, h: NOTE_H };
}

/** Deterministic event-storming layout: one lane per bounded context (plus
 *  "Unassigned"), timeline columns by `order` shared across lanes, items with
 *  the same order in a lane stacked in their model order. */
export function layoutBoard(model: BoardModel): BoardLayout {
  const known = new Set(model.contexts.map((c) => c.id));
  const laneOf = (context: string | null) =>
    context !== null && known.has(context) ? context : UNASSIGNED_LANE;

  // Stable: equal orders keep their position in the model.
  const items = model.items
    .map((item, index) => ({ item, index }))
    .sort((a, b) => a.item.order - b.item.order || a.index - b.index)
    .map(({ item }) => item);

  const columns = [...new Set(items.map((i) => i.order))];
  const columnOf = new Map(columns.map((order, col) => [order, col]));

  const laneDefs = [
    ...model.contexts.map((c) => ({ id: c.id, name: c.name })),
    { id: UNASSIGNED_LANE, name: 'Unassigned' },
  ].filter((lane) => items.some((i) => laneOf(i.context) === lane.id));

  const notes: LaidOutNote[] = [];
  const lanes: LaidOutLane[] = [];
  let laneY = 0;
  for (const lane of laneDefs) {
    const stackY = new Map<number, number>(); // column → next free y offset
    let laneContent = 0;
    for (const item of items) {
      if (laneOf(item.context) !== lane.id) continue;
      const col = columnOf.get(item.order) ?? 0;
      const { w, h } = noteSize(item.kind);
      const offset = stackY.get(col) ?? 0;
      notes.push({
        id: item.id,
        kind: item.kind,
        label: item.label,
        lane: lane.id,
        x: LANE_LABEL_W + col * (NOTE_W + COL_GAP) + (NOTE_W - w) / 2,
        y: laneY + LANE_PAD + offset,
        w,
        h,
      });
      stackY.set(col, offset + h + ROW_GAP);
      laneContent = Math.max(laneContent, offset + h);
    }
    const height = laneContent + 2 * LANE_PAD;
    lanes.push({ id: lane.id, name: lane.name, y: laneY, height });
    laneY += height;
  }

  const byId = new Map(notes.map((n) => [n.id, n]));
  const arrows: LaidOutArrow[] = [];
  for (const link of model.links) {
    const a = byId.get(link.from);
    const b = byId.get(link.to);
    if (!a || !b) continue;
    arrows.push({
      from: a.id,
      to: b.id,
      x1: a.x + a.w / 2,
      y1: a.y + a.h / 2,
      x2: b.x + b.w / 2,
      y2: b.y + b.h / 2,
    });
  }

  const width =
    columns.length === 0 ? 0 : LANE_LABEL_W + columns.length * (NOTE_W + COL_GAP) - COL_GAP + LANE_PAD;
  return { width, height: laneY, lanes, notes, arrows };
}
