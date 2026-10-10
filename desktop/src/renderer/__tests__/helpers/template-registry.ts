import type { TemplateFunctionSpec, TemplateRegistry } from '../../../shared/api-types';

function spec(
  name: string,
  kind: TemplateFunctionSpec['kind'],
  type: string,
  doc: string,
  example: string,
  extra: Partial<TemplateFunctionSpec> = {},
): TemplateFunctionSpec {
  return { name, kind, type, doc, example, owner: null, accepts: [], arg: null, argRequired: false, ...extra };
}

/** A trimmed copy of GET /v1/templates/functions (C1 + C2's queryKeys). */
export const REGISTRY: TemplateRegistry = {
  variables: [
    spec('date', 'variable', 'date', 'Today, or the date prompt.', '{{date | format: D MMM YYYY}}'),
    spec('now', 'variable', 'datetime', 'The current date and time.', '{{now.iso}}'),
    spec('context', 'variable', 'text', 'The context.', '20-contexts/{{context}}/notes'),
    spec('title', 'variable', 'text', 'The note title.', '# {{title}}'),
  ],
  fields: [
    spec('name', 'field', 'text', 'The person name.', '{{person.name}}', { owner: 'person' }),
    spec('link', 'field', 'text', 'A wikilink to the person.', '{{person.link}}', { owner: 'person' }),
    spec('iso', 'field', 'text', 'The date as YYYY-MM-DD.', '{{date.iso}}', { owner: 'date' }),
    spec('date', 'field', 'date', 'Just the date part.', '{{now.date}}', { owner: 'datetime' }),
  ],
  filters: [
    spec('format', 'filter', 'text', 'Formats a date.', '{{date | format: D MMM}}', {
      arg: '<pattern>',
      argRequired: true,
    }),
    spec('upper', 'filter', 'text', 'UPPER CASE.', '{{context | upper}}'),
  ],
  promptTypes: [
    spec('text', 'prompt_type', 'text', 'Free text.', 'type: text'),
    spec('person', 'prompt_type', 'person', 'A person.', 'type: person'),
    spec('date', 'prompt_type', 'date', 'A date.', 'type: date'),
  ],
  queryKeys: [
    spec('type', 'variable', 'text', 'Notes of this type.', 'type: action_item'),
    spec('status', 'variable', 'text', 'open = not done.', 'status: open'),
    spec('sort', 'variable', 'text', 'created or updated.', 'sort: created desc'),
    spec('context', 'variable', 'text', 'Notes in this context.', 'context: work'),
  ],
};

export const TEMPLATE = `---
template:
  name: 1-1
  prompts:
    - id: person
      ask: "Who?"
      type: person
    - ask: "Focus?"
      type: text
      id: focus
  file:
    name: "{{date | format: YYYY-MM-DD}} {{person.name}}"
  frontmatter:
    id: not-a-prompt
    type: meeting
---
# 1-1 with {{person.link}}

\`\`\`query
type: action_item
status: open
\`\`\`
`;
