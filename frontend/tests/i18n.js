// Use the real English catalog/interpolation in source-level workflow probes.
import { readFileSync } from 'node:fs';
import ts from 'typescript';
const source = readFileSync(new URL('../src/lib/i18n/messages.ts', import.meta.url), 'utf8');
export const messagesModuleUrl = `data:text/javascript,${encodeURIComponent(ts.transpile(source, { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 }))}`;
export const { translate, detectLocale, de } = await import(messagesModuleUrl);
export const t = (
	/** @type {string} */ key,
	/** @type {Record<string, string | number>} */ params = {}
) => translate('en', key, params);
export const i18nModuleUrl = `data:text/javascript,${encodeURIComponent(`import { translate } from ${JSON.stringify(messagesModuleUrl)}; export const t = (key, params) => translate('en', key, params);`)}`;
