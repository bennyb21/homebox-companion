// Each create crosses real ASGI and MockTransport via the pytest stdin bridge.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createInterface } from 'node:readline';
import ts from 'typescript';
const lines = createInterface({ input: process.stdin })[Symbol.asyncIterator]();
const retryable = process.argv[2] === 'rejected';
let calls = 0;
globalThis.p14dispatch = {
	itemsApi: {
		create: async () => {
			calls++;
			console.log(JSON.stringify({ create: true }));
			const line = (await lines.next()).value;
			assert.equal(typeof line, 'string');
			assert.ok(line);
			return JSON.parse(line);
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
	`data:text/javascript,${encodeURIComponent(`const { ${Object.keys(globalThis.p14dispatch).join(', ')} } = globalThis.p14dispatch;\n${compiled}`)}`
);
let checkpoint;
const service = new SubmissionService(async () => {
	checkpoint = service.snapshot();
});
const item = { name: 'Native', quantity: 1, confirmed: true, sourceImageIndex: 0 };
await service.submitAll([item], null, null);
assert.equal(service.snapshot().itemStatuses[0], retryable ? 'failed' : 'partial_success');
await service.submitAll([item], null, null);
assert.equal(calls, retryable ? 2 : 1);
// ScanWorkflow persists the settled snapshot after submitAll returns, in
// addition to SubmissionService's mandatory pre-dispatch checkpoint.
checkpoint = service.snapshot();
const recovered = new SubmissionService();
recovered.restore(JSON.parse(JSON.stringify(checkpoint)));
await recovered.submitAll([item], null, null);
assert.equal(calls, retryable ? 3 : 1);
if (retryable) assert.equal(recovered.snapshot().createdItemIds[0], 'synthetic-created');
process.exit(0);
