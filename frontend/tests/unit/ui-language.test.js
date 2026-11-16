import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import test from 'node:test';
import { parse } from 'svelte/compiler';
import { compileModule } from 'svelte/compiler';
import ts from 'typescript';
import { de, detectLocale, translate, messagesModuleUrl, i18nModuleUrl } from '../i18n.js';

for (const [languages, stored, expected] of [
	[['de-DE'], null, 'de'],
	[['de-CH', 'en-US'], null, 'de'],
	[['en-GB', 'de'], null, 'en'],
	[['fr-FR'], null, 'en'],
	[['fr', 'de-AT'], null, 'de'],
	[[], null, 'en'],
	[['de-DE'], 'en', 'en'],
	[['en'], 'de', 'de'],
	[['de'], 'bad-value', 'de'],
])
	test(`detect ${languages} with override ${stored}`, () =>
		assert.equal(detectLocale(languages, stored), expected));

test('catalog is complete and interpolation never rewrites inserted content', () => {
	for (const [key, value] of Object.entries(de)) {
		assert.ok(value.trim(), key);
		assert.deepEqual(
			[...key.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort(),
			[...value.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort(),
			key
		);
		assert.equal(translate('en', key), key);
	}
	assert.equal(
		translate('de', 'Adopt {p0}', { p0: 'Manufacturer {p1} AB-123' }),
		'Manufacturer {p1} AB-123 übernehmen'
	);
});

test('language module imports safely on the server without window, storage or navigator', async () => {
	const source = readFileSync(
		new URL('../../src/lib/i18n/index.svelte.ts', import.meta.url),
		'utf8'
	);
	const js = ts.transpile(source, { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 });
	const compiled = compileModule(js, { filename: 'i18n.svelte.js', generate: 'server' })
		.js.code.replaceAll("'./messages'", JSON.stringify(messagesModuleUrl))
		.replaceAll(
			"'svelte/internal/server'",
			JSON.stringify(import.meta.resolve('svelte/internal/server'))
		);
	const module = await import(`data:text/javascript,${encodeURIComponent(compiled)}`);
	assert.equal(module.uiLanguage.current, 'en');
	assert.doesNotThrow(() => module.initializeUiLanguage());
	assert.equal(module.t('Settings'), 'Settings');
});

test('proposal classification is initial, index preserving, and does not normalize identifiers', async () => {
	const source = readFileSync(
		new URL('../../src/lib/api/research.ts', import.meta.url),
		'utf8'
	).replace("'$lib/i18n/index.svelte'", JSON.stringify(i18nModuleUrl));
	const { prepareProposals, researchSources } = await import(
		`data:text/javascript,${encodeURIComponent(ts.transpile(source, { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 }))}`
	);
	const original = [
		{ name: 'part', current: 'AB-123', value: 'AB-123', source_urls: [] },
		{ name: 'model', current: 'AB', value: 'AB ', source_urls: ['https://example.com'] },
		{
			name: 'Description',
			current: '',
			value: 'Two lines\nwith identifiers AB-123',
			source_urls: [],
		},
	];
	const prepared = prepareProposals(original);
	assert.deepEqual(
		prepared.map((p) => p.unchanged),
		[true, false, false]
	);
	assert.deepEqual(
		prepared.map((p) => p.name),
		original.map((p) => p.name)
	);
	prepared[1].value = 'AB';
	prepared[0].value = 'edited';
	assert.equal(prepared[1].unchanged, false);
	assert.equal(prepared[0].unchanged, true);
	assert.equal(original[1].value, 'AB ');
	assert.equal(prepared[2].multiline, true);
	assert.deepEqual(researchSources({ sources: [] }, prepared), [
		{ title: 'https://example.com', url: 'https://example.com' },
	]);
});

// Literal UI inventory: inventory values, API identifiers and technical payloads are expressions,
// not candidates for automatic translation. This only audits app-owned markup/attributes.
test('normal Svelte markup and accessible attributes use explicit catalog calls', () => {
	const root = new URL('../../src/', import.meta.url);
	const allowedText = new Set([
		'Homebox Companion',
		'v',
		's',
		'Chat | Homebox Companion',
		'HBC_CHAT_ENABLED=true',
		'Deutsch',
		'English',
	]);
	const allowedAttributes = new Set(['you@example.com']);
	const attrs = new Set([
		'placeholder',
		'title',
		'aria-label',
		'alt',
		'label',
		'confirmLabel',
		'cancelLabel',
		'message',
		'loadingText',
		'subtitle',
		'text',
	]);
	const missed = [];
	function walk(node, parent, file) {
		if (!node || typeof node !== 'object') return;
		if (Array.isArray(node)) {
			for (const child of node) walk(child, parent, file);
			return;
		}
		if (node.type === 'Text' && parent?.type !== 'Attribute') {
			const text = node.data.trim();
			if (/[A-Za-z]/.test(text) && !allowedText.has(text)) missed.push(`${file}: ${text}`);
		}
		if (node.type === 'Attribute' && attrs.has(node.name)) {
			for (const value of node.value || []) {
				if (value.type !== 'Text') continue;
				const text = value.data;
				if (/[A-Za-z]/.test(text) && !allowedAttributes.has(text))
					missed.push(`${file} ${node.name}: ${text}`);
			}
		}

		for (const [key, value] of Object.entries(node))
			if (!['loc', 'comments'].includes(key) && value && typeof value === 'object')
				walk(value, node, file);
	}
	for (const file of readdirSync(root, { recursive: true }).filter((f) => f.endsWith('.svelte')))
		walk(parse(readFileSync(new URL(file, root), 'utf8')).html, null, file);
	assert.deepEqual(missed, []);
});
