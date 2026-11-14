// Real ASGI response supplied on stdin by pytest; production workflow, no network.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
const response = JSON.parse(readFileSync(0, 'utf8'));
let calls = 0;
globalThis.p14 = {
	itemsApi: {
		create: async () => {
			calls++;
			return response;
		},
	},
	$state: (/** @type {unknown} */ v) => v,
	itemValidationError: () => null,
	normalizeAssetId: (/** @type {unknown} */ v) => v,
	hasToken: () => true,
	withRetry: (/** @type {() => Promise<unknown>} */ fn) => fn(),
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
	`data:text/javascript,${encodeURIComponent(`const { ${Object.keys(globalThis.p14).join(', ')} } = globalThis.p14;\n${compiled}`)}`
);
let checkpoint;
const service = new SubmissionService(async () => {
	checkpoint = service.snapshot();
});
const item = {
	name: 'Native',
	quantity: 1,
	confirmed: true,
	sourceImageIndex: 0,
	entity_type_id: '00000000-0000-4000-8000-000000000010',
};
await service.submitAll([item], null, null);
assert.equal(service.snapshot().itemStatuses[0], 'partial_success');
await service.submitAll([item], null, null);
const recovered = new SubmissionService();
recovered.restore(checkpoint);
await recovered.submitAll([item], null, null);
assert.equal(calls, 1);
console.log('actual ASGI outcome: same-session and persisted recovery recreation blocked');
