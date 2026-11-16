# UI language

- `messages.ts`: explicit English source keys and German messages; typed parameters.
- `index.svelte.ts`: Svelte 5 reactive browser preference (`hbc.ui-language`), language detection, `t`, and document language. No backend setting or workflow dependencies.
- Settings exposes **Deutsch / English**. A valid stored choice wins; otherwise the first supported browser language is used, falling back to English. Blocked storage still permits a session-only choice.

Add app-owned copy to `messages.ts` and call `t(key, params)` at render/use time. Do not translate once into a module-level constant: it would keep the initial language after a switch. Use full messages for plurals or mixed attributes, including placeholders, accessible names, tooltips and dialogs.

Do **not** send inventory content through the catalog: Homebox type/custom-field names, product values, model/profile IDs, prompts, source titles, AI output, provider diagnostics and logs stay original. UI language does not change AI `output_language`.

Event-generated error/toast strings and restored historical messages retain the language in which they were created. New events use the selected language; raw backend/provider errors are not machine-translated.

## Focused checks

- `npm run verify`: type checks, lint/design tokens, format and unit tests. The locale unit test also inventories literal Svelte UI text and accessible attributes.
- `tests/browser/ui-language.spec.ts`: browser defaults/override, unsaved settings and drafts, no requests caused by switching, DE/EN capture-to-save, native names/values, stable selective research adoption and error visibility.
- Existing Playwright tests explicitly default to English. `@mobile` cases use the existing WebKit-mobile project; desktop cases also exercise narrow viewports.

Research grouping is captured when results arrive. Original proposal indices are never reordered. Editing a proposal back to its current value may remove redundant previous-value text, but must not remove or move the editable row.
