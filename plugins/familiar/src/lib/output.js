export const SWEEP_JSON_SCHEMA = {
  type: 'object',
  required: ['briefingMarkdown', 'memoryMarkdown', 'openLoops', 'decisions'],
  properties: {
    briefingMarkdown: { type: 'string' },
    memoryMarkdown: { type: 'string' },
    openLoops: {
      type: 'array',
      items: {
        type: 'object',
        required: ['id', 'text', 'sourcePath', 'firstSeen', 'status'],
        properties: {
          id: { type: 'string', pattern: '^loop-[a-z0-9-]+$' },
          text: { type: 'string' },
          owedTo: { type: ['string', 'null'] },
          sourcePath: { type: 'string' },
          firstSeen: { type: 'string', pattern: '^\\d{4}-\\d{2}-\\d{2}$' },
          status: { type: 'string', enum: ['open', 'done', 'stale'] },
        },
      },
    },
    decisions: {
      type: 'array',
      items: {
        type: 'object',
        required: ['date', 'text', 'sourcePath'],
        properties: {
          date: { type: 'string', pattern: '^\\d{4}-\\d{2}-\\d{2}$' },
          text: { type: 'string' },
          sourcePath: { type: 'string' },
        },
      },
    },
  },
};

const LOOP_ID_RE = /^loop-[a-z0-9-]+$/;
const STATUSES = new Set(['open', 'done', 'stale']);

function extractJson(text) {
  const fenced = /```(?:json)?\s*\n([\s\S]*?)\n?```/.exec(text);
  const raw = fenced ? fenced[1] : text;
  try {
    return JSON.parse(raw);
  } catch (e) {
    throw new Error(`output is not valid JSON: ${e.message}`);
  }
}

export function parseSweepOutput(res) {
  const data = res.structured ?? extractJson(res.text ?? '');
  for (const k of ['briefingMarkdown', 'memoryMarkdown', 'openLoops', 'decisions']) {
    if (!(k in (data ?? {}))) throw new Error(`output missing key: ${k}`);
  }
  if (typeof data.briefingMarkdown !== 'string' || typeof data.memoryMarkdown !== 'string') {
    throw new Error('briefingMarkdown/memoryMarkdown must be strings');
  }
  if (!Array.isArray(data.openLoops)) {
    throw new Error('openLoops must be an array');
  }
  if (!Array.isArray(data.decisions)) {
    throw new Error('decisions must be an array');
  }
  for (const l of data.openLoops) {
    if (!LOOP_ID_RE.test(l.id ?? '')) throw new Error(`bad loop id: ${JSON.stringify(l.id)}`);
    if (!STATUSES.has(l.status)) throw new Error(`bad loop status: ${JSON.stringify(l.status)}`);
    if (typeof l.text !== 'string' || typeof l.sourcePath !== 'string') {
      throw new Error(`loop ${l.id}: text/sourcePath must be strings`);
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(l.firstSeen ?? '')) {
      throw new Error(`loop ${l.id}: firstSeen must match YYYY-MM-DD format`);
    }
    if (typeof l.owedTo !== 'string' && l.owedTo !== null && l.owedTo !== undefined) {
      throw new Error(`loop ${l.id}: owedTo must be a string or null`);
    }
    l.owedTo ??= null;
  }
  for (const d of data.decisions) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(d.date ?? '')) throw new Error(`bad decision date: ${JSON.stringify(d.date)}`);
    if (typeof d.text !== 'string') {
      throw new Error('decision text must be a string');
    }
    if (typeof d.sourcePath !== 'string') {
      throw new Error('decision sourcePath must be a string');
    }
  }
  return data;
}
