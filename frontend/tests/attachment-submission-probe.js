// Production SubmissionService -> actual ASGI -> Homebox transport bridge.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createInterface } from 'node:readline';
import ts from 'typescript';
import { t } from './i18n.js';
const lines = createInterface({ input: process.stdin })[Symbol.asyncIterator]();
async function readMessage() {
	const line = (await lines.next()).value;
	assert.equal(typeof line, 'string');
	assert.ok(line);
	return JSON.parse(line);
}
const init = await readMessage();
let creates = 0;
let uploads = 0;
async function exchange(/** @type {unknown} */ payload) {
	console.log(JSON.stringify(payload));
	const result = await readMessage();
	if (result.status >= 400) throw new Error(JSON.stringify(result.body));
	return result.body;
}
globalThis.attachmentProbe = {
	t,
	itemsApi: {
		create: async (/** @type {unknown} */ payload) => {
			creates++;
			return exchange({ create: payload });
		},
		uploadAttachment: async (
			/** @type {string} */ entity,
			/** @type {File} */ file,
			/** @type {Record<string, unknown>} */ options
		) => {
			uploads++;
			return exchange({
				upload: {
					entity,
					filename: file.name,
					content: Buffer.from(await file.arrayBuffer()).toString('base64'),
					options,
				},
			});
		},
		delete: async () => {
			throw new Error('Forbidden DELETE');
		},
	},
	$state: (/** @type {unknown} */ v) => v,
	itemValidationError: () => null,
	normalizeAssetId: (/** @type {unknown} */ v) => v,
	hasToken: () => true,
	requestScope: () => 'synthetic',
	assertCurrentScope: () => {},
	generateId: () => crypto.randomUUID(),
	ApiError: class extends Error {},
	log: { info() {}, debug() {}, warn() {}, error() {} },
};
const source = readFileSync(
	new URL('../src/lib/workflows/submission.svelte.ts', import.meta.url),
	'utf8'
);
const compiled = ts.transpile(source.replace(/^import[\s\S]*?;\s*$/gm, ''), {
	target: ts.ScriptTarget.ES2022,
	module: ts.ModuleKind.ES2022,
});
const { SubmissionService } = await import(
	`data:text/javascript,${encodeURIComponent(`const { ${Object.keys(globalThis.attachmentProbe).join(', ')} } = globalThis.attachmentProbe;\n${compiled}`)}`
);
const bytes = Buffer.from(init.photo, 'base64');
const item = {
	name: 'Synthetic retained item',
	quantity: 1,
	entity_type_id: init.type,
	confirmed: true,
	sourceImageIndex: 0,
	notes: 'manual fields retained',
	originalFile: new File([bytes], 'same.jpg', { type: 'image/jpeg' }),
	additionalImages: [new File([bytes], 'same.jpg', { type: 'image/jpeg' })],
};
/** @type {{ photos: string[], notes: string } & Record<string, unknown> | undefined} */
let durable;
const service = new SubmissionService(async () => {
	durable = {
		...service.snapshot(),
		photos: [item.originalFile.name, ...item.additionalImages.map((file) => file.name)],
		notes: item.notes,
	};
});
await service.submitAll([item], null, null);
const snapshot = service.snapshot();
if (init.expected) assert.equal(snapshot.itemStatuses[0], init.expected);
assert.ok(snapshot.createdItemIds[0]);
assert.ok(durable);
assert.deepEqual(durable.photos, ['same.jpg', 'same.jpg']);
assert.equal(durable.notes, 'manual fields retained');
const count = uploads;
const recovered = new SubmissionService();
recovered.restore(durable);
await recovered.submitAll([item], null, null);
await service.retryFailed([item], null, null);
assert.equal(creates, 1);
assert.equal(uploads, count);
console.log(JSON.stringify({ done: { snapshot, durable, creates, uploads } }));
process.exit(0);
