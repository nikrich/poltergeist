import { autocompletion } from '@codemirror/autocomplete';
import { analysisField } from './analysis.js';
import { typeAt } from './commands.js';
import { completionsFor } from './completions.js';

export function scriptCompletions() {
  return autocompletion({
    icons: false,
    activateOnTyping: true,
    override: [(ctx) => {
      const line = ctx.state.doc.lineAt(ctx.pos);
      const text = line.text.slice(0, ctx.pos - line.from);
      const type = typeAt(ctx.state, line.number);
      if (!text.trim() && !ctx.explicit && type !== 'character') return null;
      const prevBlank = line.number === 1 || ctx.state.doc.line(line.number - 1).text.trim() === '';
      const r = completionsFor({ text, type, prevBlank, elements: ctx.state.field(analysisField).elements });
      if (!r) return null;
      return { from: line.from + r.from, options: r.options.map((label) => ({ label, type: 'text' })) };
    }],
  });
}
