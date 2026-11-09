# UI redesign plan — "Translator Workbench"

Date: 2026-11-10 · Scope: `static/` (+ 3 small read-only API additions). No build step,
no framework: vanilla ES modules served by FastAPI, works offline.

## Why
The current UI is a wide 7-column table where the source, MTL and translation compete
for space, every action is an emoji button, and confirmations use `alert/confirm/prompt`.
Long sessions (thousands of lines) need: less chrome, one clear focus, keyboard flow,
and an editor that shows *why* a line is flagged.

## Research takeaways (sources in the PR/chat)
- Overview + detail beats sentence-by-sentence grids for comprehension/accuracy (arXiv 2011.05978).
- Lighter interface, QA on confirm, on-demand detail (LILT editor redesign).
- Keyboard: arrows move between rows, Enter edits, Ctrl+Enter saves/confirms (WAI-ARIA grid, Weblate).
- Dark theme: dark grey (not black) surfaces, off-white text, desaturated accents, WCAG ≥ 4.5:1.

## Layout
```
┌ Topbar: logo · project switcher · overall progress (segmented) · AI model · Translate ▾ · Patch · Tools ▾ · ⚙ ┐
├ Sidebar (files) ─┬ Segment list ───────────────────────┬ Inspector (selected row) ─────────┤
│ search files     │ filter chips w/ counts · type · 🔍   │ meta: #id · type · file · path    │
│ ▸ Maps   (bar)   │ ▌#123 Message  source │ translation  │ Source (codes as chips, copy)      │
│ ▸ Common (bar)   │ ▌...                                 │ Translation editor (auto-grow)     │
│ ▸ DB     (bar)   │                                      │ live QA chips · AI suggestion      │
│                  │ pagination                            │ Context (±2 lines, same file)      │
│                  │                                       │ Glossary hits · actions            │
└ Statusbar: counts · shortcuts hint · background job progress ──────────────────────────────┘
```
- Row = left status stripe (empty / machine / QA / reviewed / locked) + source + translation preview.
- Control codes (`\c[2]`, `\s[7]`, `\E`, `<C>`, `@1`) rendered as small mono chips in source/preview.
- Locked rows: muted, inspector shows *why* it is locked instead of an editor.
- Batch translation: setup in a dialog, then runs in a docked, minimisable job panel
  (non-blocking) with live feed; list refreshes as batches land.

## Interaction
| Key | Action |
|---|---|
| ↑ ↓ / J K | previous / next row |
| Enter | focus translation editor |
| Esc | leave editor (back to list) |
| Ctrl+Enter | save + mark reviewed + next row |
| Ctrl+S | save without confirming |
| Alt+↓ / Alt+↑ | next / previous unreviewed row (0, 1, 3) |
| Ctrl+Shift+A | AI-translate current row |
| Ctrl+Shift+U | use AI suggestion as translation |
| Ctrl+F | focus search · `?` shortcut sheet |

- Saves only when text changed; unsaved indicator in the inspector.
- Live client-side QA (same rules as `qa.py`) while typing.
- All `alert/confirm/prompt` replaced by promise-based dialogs; toast stack with types.

## Visual system
- Tokens on `:root` for dark (default) and light; font stack Segoe UI Variable / system,
  JP fallback Yu Gothic UI / Meiryo, mono Cascadia Mono / Consolas.
- Dark: bg `#15171b`, surface `#1b1e23`, raised `#22262c`, text `#dfe3ea`, muted `#8d95a3`,
  accent `#7aa2f7`; status: empty grey, machine amber `#d9b061`, QA rose `#e08585`,
  reviewed green `#7cc79a`, locked slate.
- Light: bg `#f5f4f1`, surface `#fff`, text `#1f2328`.
- Density setting (comfortable / compact) and text size in Settings → Giao diện.
- Inline SVG icons (stroke style) for chrome; no emoji in buttons.

## Settings
Modal with left nav: AI (provider tabs: Gemini keys + 5 priority models / Kaggle / OpenRouter,
test connection, per-key test), Dịch & QA (batch size, system prompt w/ reset, QA line length),
Giao diện (theme, density, font size — stored in localStorage).

## API additions (read-only)
- `GET /api/rows/{id}/context?n=2` — neighbouring rows in the same file.
- `GET /api/stats?file=` — counts scoped to a file (for filter chips).
- `POST /api/rows` accepts `row_type`.

## Feature parity checklist
Projects (switch / create / import .nel / export .nel), file list, search, status & type
filters, pagination, edit/save, confirm, single AI translate, page translate, batch
(file / all, types, auto-fill, overwrite, live feed, stop), clear (row / file / range /
type / all, mtl / trans / both), patch (blocked errors → force), tools (glossary, unify,
QA recheck, validate, game path, re-sync, re-extract, restore), settings (all fields,
key list add/test/use/move/delete, test connection), theme.

## Milestones (one commit each)
1. API additions + tests.
2. Design tokens, shell layout, base components (buttons, inputs, dialogs, toasts, menus, icons).
3. Sidebar + segment list + filters + keyboard navigation.
4. Inspector editor (codes, live QA, context, glossary, actions, shortcuts).
5. Batch job panel + translate menu.
6. Settings, projects, clear tools, patch, tools menu, glossary dialog.
7. Remove old `app.js`, README screenshots/shortcut docs.
