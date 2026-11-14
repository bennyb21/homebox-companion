import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

let moduleId = 0;
async function loadEditor(bindings = {}) {
	const source = await readFile(
		new URL('../../src/lib/services/reviewEditor.svelte.ts', import.meta.url),
		'utf8'
	);
	const id = `nativeReview${moduleId++}`;
	globalThis[id] = {
		$state: (value) => value,
		authStore: { connection: 'synthetic', verifiedScope: { contextId: 'c', groupId: 'g' } },
		showToast() {},
		log: { error() {} },
		...bindings,
	};
	const compiled = ts.transpile(source.replace(/^import[\s\S]*?;\s*$/gm, ''), {
		target: ts.ScriptTarget.ES2022,
		module: ts.ModuleKind.ES2022,
	});
	return import(
		`data:text/javascript,${encodeURIComponent(`const { ${Object.keys(globalThis[id]).join(', ')} } = globalThis.${id};\n${compiled}`)}`
	);
}

test('type changes load native defaults and preserve all current manual values', async () => {
	const notices = [];
	const { ReviewEditor } = await loadEditor({
		apiRequest: async (url) => {
			assert.equal(url, '/capture-profiles/b');
			return {
				entity_type: { id: 'b' },
				template: {
					id: 'tb',
					fields: [
						{ name: 'Shared', type: 'text', textValue: 'default' },
						{ name: 'New', type: 'text', textValue: 'new default' },
					],
				},
			};
		},
		showToast: (message) => notices.push(message),
	});
	let updates;
	const changed = await new ReviewEditor().changeProfile(
		'b',
		() => true,
		() => ({ Shared: '', Old: '0007' }),
		(value) => {
			updates = value;
		}
	);
	assert.equal(changed, true);
	assert.deepEqual(updates, {
		entity_type_id: 'b',
		template_id: 'tb',
		custom_fields: { Shared: '', New: 'new default', Old: '0007' },
	});
	assert.ok(notices.some((message) => /preserved/i.test(message)));
});

test('review correction refuses native fields before constructing a lossy payload', async () => {
	let calls = 0;
	let notice;
	const { ReviewEditor } = await loadEditor({
		vision: {
			correct: async () => {
				calls++;
				return { items: [] };
			},
		},
		showToast: (message) => {
			notice = message;
		},
	});
	const item = {
		name: 'Native',
		quantity: 1,
		entity_type_id: 'a',
		custom_fields: { Code: '0007' },
	};
	const changed = await new ReviewEditor().correct(
		item,
		new File(['x'], 'x.png'),
		'fix',
		() => true,
		() => assert.fail('must not apply')
	);
	assert.equal(changed, false);
	assert.equal(calls, 0);
	assert.match(notice, /native.*manual/i);
});

for (const type of ['number', 'boolean', 'time']) {
	test(`unsupported ${type} review profile leaves all draft values untouched`, async () => {
		let notice;
		const { ReviewEditor } = await loadEditor({
			apiRequest: async () => ({
				entity_type: { id: 'b' },
				template: { id: 'tb', fields: [{ name: 'Typed', type }] },
			}),
			showToast: (message) => {
				notice = message;
			},
		});
		const result = await new ReviewEditor().changeProfile(
			'b',
			() => true,
			() => ({ Code: '0007' }),
			() => assert.fail('no mutation')
		);
		assert.equal(result, false);
		assert.match(notice, /text.*unchanged/i);
	});
}

test('profile fetch uses latest manual fields and ignores invalidated responses', async () => {
	let resolve;
	const { ReviewEditor } = await loadEditor({
		apiRequest: () =>
			new Promise((done) => {
				resolve = done;
			}),
	});
	const editor = new ReviewEditor();
	let fields = { Code: 'before' };
	let updates;
	const pending = editor.changeProfile(
		'b',
		() => true,
		() => fields,
		(value) => {
			updates = value;
		}
	);
	fields = { Code: 'after' };
	resolve({ entity_type: { id: 'b' }, template: null });
	assert.equal(await pending, true);
	assert.equal(updates.custom_fields.Code, 'after');
	const stale = editor.changeProfile(
		'b',
		() => true,
		() => fields,
		() => assert.fail('stale response')
	);
	editor.invalidate();
	resolve({ entity_type: { id: 'b' }, template: null });
	assert.equal(await stale, false);
});
