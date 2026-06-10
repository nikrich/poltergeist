import type { HeatmapDay } from '../../shared/api-types';

export interface ActivityHeatmapProps {
  /** Heatmap payload indexed by ISO date — build with indexHeatmapDays(). */
  days: Record<string, HeatmapDay>;
  /** Number of week-columns; the last column contains endDate. */
  weeks: number;
  /** Server-side max daily count — drives the intensity buckets. */
  maxCount: number;
  selectedDate?: string | null;
  onSelectDay?: (date: string) => void;
  /** Compact tile mode: smaller cells, no weekday gutter. */
  compact?: boolean;
  /** Last day of the grid (ISO date). Defaults to today; injectable for tests. */
  endDate?: string;
}

export function indexHeatmapDays(days: HeatmapDay[]): Record<string, HeatmapDay> {
  const index: Record<string, HeatmapDay> = {};
  for (const d of days) index[d.date] = d;
  return index;
}

/** Bucket a daily count into 0–4: zero, then quartiles of maxCount. */
export function levelFor(count: number, maxCount: number): 0 | 1 | 2 | 3 | 4 {
  if (count <= 0 || maxCount <= 0) return 0;
  const level = Math.ceil((Math.min(count, maxCount) / maxCount) * 4);
  return Math.max(1, Math.min(4, level)) as 1 | 2 | 3 | 4;
}

// Level 0 uses the hairline tone; 1–3 are neon at 25/50/75% alpha; 4 is full
// neon — consistent with the design tokens in styles.css / colors_and_type.css.
const LEVEL_BG = [
  'var(--hairline)',
  'color-mix(in srgb, var(--neon) 25%, transparent)',
  'color-mix(in srgb, var(--neon) 50%, transparent)',
  'color-mix(in srgb, var(--neon) 75%, transparent)',
  'var(--neon)',
] as const;

const MONTHS = [
  'jan', 'feb', 'mar', 'apr', 'may', 'jun',
  'jul', 'aug', 'sep', 'oct', 'nov', 'dec',
] as const;

// [row, label] — rows are Monday-first (0=mon … 6=sun).
const WEEKDAY_HINTS: Array<[number, string]> = [
  [0, 'mon'],
  [2, 'wed'],
  [4, 'fri'],
];

function isoDate(d: Date): string {
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${m}-${day}`;
}

function parseIso(iso: string): Date {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y!, m! - 1, d!);
}

function addDays(d: Date, n: number): Date {
  const c = new Date(d);
  c.setDate(c.getDate() + n);
  return c;
}

function mondayOf(d: Date): Date {
  const dow = (d.getDay() + 6) % 7; // 0=mon … 6=sun
  return addDays(d, -dow);
}

export function ActivityHeatmap({
  days,
  weeks,
  maxCount,
  selectedDate,
  onSelectDay,
  compact = false,
  endDate,
}: ActivityHeatmapProps) {
  // Fluid grid: columns stretch to the container width; cells stay square
  // via aspect-ratio. Only the gap and the weekday gutter are fixed.
  const gap = compact ? 2 : 3;
  const gutter = compact ? 0 : 26;
  const end = endDate ? parseIso(endDate) : new Date();
  const firstMonday = addDays(mondayOf(end), -7 * (weeks - 1));

  const columns: Date[] = [];
  for (let w = 0; w < weeks; w += 1) columns.push(addDays(firstMonday, w * 7));

  const monthLabels = columns.map((monday, i) => {
    const month = monday.getMonth();
    if (i === 0 || month !== columns[i - 1]!.getMonth()) return MONTHS[month]!;
    return '';
  });

  return (
    <div className="flex flex-col gap-1" data-testid="activity-heatmap">
      {/* month labels */}
      <div
        className="grid font-mono text-9 text-ink-3"
        style={{
          gridTemplateColumns: `repeat(${weeks}, minmax(0, 1fr))`,
          gap: `${gap}px`,
          marginLeft: gutter,
        }}
      >
        {monthLabels.map((label, i) => (
          <span key={i} className="overflow-visible whitespace-nowrap">
            {label}
          </span>
        ))}
      </div>
      <div className="flex" style={{ gap: `${gap}px` }}>
        {/* weekday gutter (non-compact only) — a 7-row grid that stretches to
            the same height as the cell grid, so hints track fluid cell sizes */}
        {!compact && (
          <div
            className="grid flex-shrink-0 font-mono text-9 text-ink-3"
            style={{
              width: gutter - gap,
              gridTemplateRows: 'repeat(7, 1fr)',
              rowGap: gap,
            }}
          >
            {Array.from({ length: 7 }, (_, row) => (
              <span key={row} className="flex items-center">
                {WEEKDAY_HINTS.find(([r]) => r === row)?.[1] ?? ''}
              </span>
            ))}
          </div>
        )}
        {/* cells — column flow so each week-column reads top (mon) to bottom (sun) */}
        <div
          className="grid min-w-0 flex-1"
          style={{
            gridTemplateColumns: `repeat(${weeks}, minmax(0, 1fr))`,
            gridTemplateRows: 'repeat(7, auto)',
            gridAutoFlow: 'column',
            gap: `${gap}px`,
          }}
        >
          {columns.flatMap((monday) =>
            Array.from({ length: 7 }, (_, row) => {
              const d = addDays(monday, row);
              const iso = isoDate(d);
              if (d > end) {
                // Future days keep the grid shape but are not interactive.
                return (
                  <span
                    key={`pad-${iso}`}
                    aria-hidden
                    style={{ width: '100%', aspectRatio: '1 / 1' }}
                  />
                );
              }
              const count = days[iso]?.count ?? 0;
              const level = levelFor(count, maxCount);
              const selected = selectedDate === iso;
              return (
                <button
                  key={iso}
                  type="button"
                  data-level={level}
                  data-date={iso}
                  aria-label={`${iso} — ${count} ${count === 1 ? 'event' : 'events'}`}
                  onClick={onSelectDay ? () => onSelectDay(iso) : undefined}
                  className={`border-0 p-0 ${onSelectDay ? 'cursor-pointer' : 'cursor-default'}`}
                  style={{
                    width: '100%',
                    aspectRatio: '1 / 1',
                    borderRadius: 2,
                    background: LEVEL_BG[level],
                    outline: selected ? '1px solid var(--neon)' : 'none',
                    outlineOffset: 1,
                  }}
                />
              );
            }),
          )}
        </div>
      </div>
    </div>
  );
}
