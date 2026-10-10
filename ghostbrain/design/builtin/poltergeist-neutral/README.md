# Poltergeist Neutral

A calm, product-neutral design system for quick prototypes: warm-grey
neutrals, one confident blue primary, a teal accent, generous whitespace.
Use it when the project has no brand of its own.

All tokens live in `tokens.css` as CSS custom properties. It also styles
bare elements (`body`, headings, `a`, `button`, `input`, `select`,
`textarea`, `table`), so plain semantic HTML already looks right.

## Rules

- Style **only** with `var(--ds-…)` tokens. Never hard-code hex colours,
  pixel font sizes or ad-hoc shadows.
- Spacing follows a 4px grid: `--ds-space-1` (4px) … `--ds-space-16` (64px).
  Prefer `--ds-space-4` inside components and `--ds-space-6`/`--ds-space-8`
  between sections.
- One primary action per screen (`button.primary`). Everything else is a
  default or ghost button.
- Text colour hierarchy: `--ds-color-text` for content,
  `--ds-color-text-muted` for labels and secondary text,
  `--ds-color-text-subtle` for hints and placeholders.
- Surfaces: page `--ds-color-bg`, cards `--ds-color-surface`, wells and
  table headers `--ds-color-surface-muted`.
- Status colours are for status only (badges, alerts, validation), never for
  decoration. Pair each with its `-soft` background.
- Radius: `--ds-radius-md` for controls, `--ds-radius-lg` for cards,
  `--ds-radius-full` for pills and avatars.
- Keep content width under `--ds-layout-max-width`; sidebars use
  `--ds-layout-sidebar`.

## Tokens

| Group | Tokens |
|---|---|
| Neutrals | `--ds-color-bg`, `-surface`, `-surface-muted`, `-surface-sunken`, `-border`, `-border-strong`, `-text`, `-text-muted`, `-text-subtle`, `-text-inverse` |
| Brand | `--ds-color-primary`, `-primary-hover`, `-primary-soft`, `-primary-text`, `-accent`, `-accent-soft` |
| Status | `--ds-color-success`, `-warning`, `-danger`, `-info` (each with `-soft`) |
| Type | `--ds-font-sans`, `--ds-font-mono`, `--ds-font-size-xs … 3xl`, `--ds-font-weight-regular/medium/semibold/bold`, `--ds-font-line-tight/normal` |
| Space | `--ds-space-0 … 16` |
| Radius | `--ds-radius-sm/md/lg/xl/full` |
| Shadow | `--ds-shadow-sm/md/lg` |
| Motion | `--ds-motion-fast/normal`, `--ds-motion-ease` |

## Components

Buttons — default, primary, ghost, danger:

```html
<button>Cancel</button>
<button class="primary">Save changes</button>
<button class="ghost">More</button>
<button class="danger">Delete</button>
```

Card:

```html
<section class="ds-card">
  <h3>Monthly summary</h3>
  <p>Twelve new claims, three awaiting review.</p>
</section>
```

Form field:

```html
<div>
  <label for="email">Email</label>
  <input id="email" type="email" placeholder="you@example.com" />
</div>
```

Badges and alerts:

```html
<span class="ds-badge ds-badge-success">Paid</span>
<span class="ds-badge ds-badge-warning">Pending</span>
<div class="ds-alert">Your changes are saved automatically.</div>
```

Table: plain `<table>` with `<thead>`/`<tbody>`; numbers right-aligned with
`style="text-align: right"`.

App shell: a top bar (`--ds-color-surface`, bottom border
`--ds-color-border`, height ~56px) or a left sidebar of width
`--ds-layout-sidebar`, content on `--ds-color-bg` with `--ds-space-8` padding.

## Do / don't

- Do use real-looking content (names, amounts, dates) — never lorem ipsum.
- Do show empty, loading and error states where the conversation implies them.
- Don't introduce new colours, fonts or icon libraries.
- Don't nest cards inside cards; use spacing and dividers instead.
- Don't use more than three type sizes on one screen.
