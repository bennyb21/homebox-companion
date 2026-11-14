import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

let sequence = 0;
async function loadSubmission(itemsApi) {
	const source = await readFile(
		new URL('../../src/lib/workflows/submission.svelte.ts', import.meta.url),
		'utf8'
	);
	const id = `nativeSubmission${sequence++}`;
	globalThis[id] = {
		itemsApi,
		$state: (value) => value,
		itemValidationError: () => null,
		normalizeAssetId: (value) => value,
		hasToken: () => true,
		withRetry: (fn) => fn(),
		ApiError: class extends Error {},
		log: { info() {}, debug() {}, warn() {}, error() {} },
	};
	const compiled = ts.transpile(source.replace(/^import[\s\S]*?;\s*$/gm, ''), {
		target: ts.ScriptTarget.ES2022,
		module: ts.ModuleKind.ES2022,
	});
	return import(
		`data:text/javascript,${encodeURIComponent(`const { ${Object.keys(globalThis[id]).join(', ')} } = globalThis.${id};\n${compiled}`)}`
	);
}
const item = {
	name: 'Native',
	quantity: 1,
	confirmed: true,
	sourceImageIndex: 0,
	entity_type_id: 'type-a',
	template_id: 'template-a',
	custom_fields: { Code: '0007' },
};

for (const name of ['NetworkError', 'AbortError']) {
	test(`uncertain POST ${name} cannot be retried as another create`, async () => {
		let calls = 0;
		const { SubmissionService } = await loadSubmission({
			create: async () => {
				calls++;
				throw Object.assign(new Error('response lost'), { name });
			},
		});
		const service = new SubmissionService();
		await service.submitAll([item], 'location', null);
		assert.equal(service.snapshot().itemStatuses[0], 'partial_success');
		await service.submitAll([item], 'location', null);
		assert.equal(calls, 1);
	});
}

test('submission checkpoints unknown in-flight creation before writes and recovers without retrying it', async () => {
	let checkpoints = [];
	let service;
	const { SubmissionService } = await loadSubmission({
		create: async () => {
			assert.equal(checkpoints.at(-1).itemStatuses[0], 'creating');
			return { created: [{ id: 'created-a' }], errors: [] };
		},
	});
	service = new SubmissionService(async () => {
		checkpoints.push(service.snapshot());
	});
	await service.submitAll([item], 'location', null);
	assert.ok(checkpoints.length >= 2);
	const recovered = new SubmissionService();
	recovered.restore({
		itemStatuses: { 0: 'creating', 1: 'pending' },
		createdItemIds: {},
		lastErrors: [],
	});
	assert.equal(recovered.snapshot().itemStatuses[0], 'partial_success');
	assert.equal(recovered.snapshot().itemStatuses[1], 'failed');
	assert.match(recovered.snapshot().lastErrors.join(' '), /unconfirmed/i);
});

test('aborted attachment upload retains created identity across recovery and resubmission', async () => {
	let calls = 0;
	const { SubmissionService } = await loadSubmission({
		create: async () => {
			calls++;
			return { created: [{ id: 'created-a' }], errors: [] };
		},
		uploadAttachment: async () => {
			throw new DOMException('cancelled', 'AbortError');
		},
	});
	const service = new SubmissionService();
	await service.submitAll([{ ...item, originalFile: new File(['x'], 'x.jpg') }], 'location', null);
	assert.equal(service.snapshot().createdItemIds[0], 'created-a');
	assert.equal(service.snapshot().itemStatuses[0], 'partial_success');
	const recovered = new SubmissionService();
	recovered.restore(service.snapshot());
	await recovered.submitAll([item], 'location', null);
	assert.equal(calls, 1);
});

test('repeated submit after partial detail update never recreates a known native item', async () => {
	let calls = 0;
	const { SubmissionService } = await loadSubmission({
		create: async (payload) => {
			calls++;
			assert.equal(payload.items[0].entity_type_id, item.entity_type_id);
			assert.deepEqual(payload.items[0].custom_fields, item.custom_fields);
			return { created: [{ id: 'created-a' }], errors: ['Update failed; cleanup unconfirmed'] };
		},
	});
	const service = new SubmissionService();
	await service.submitAll([item], 'location', null);
	const recovered = new SubmissionService();
	recovered.restore(service.snapshot());
	await recovered.submitAll([item], 'location', null);
	assert.equal(calls, 1);
	assert.equal(recovered.snapshot().createdItemIds[0], 'created-a');
});

test('concurrent retries cannot create the same failed row twice', async () => {
	let calls = 0;
	let finish;
	const { SubmissionService } = await loadSubmission({
		create: async () => {
			calls++;
			if (calls === 1)
				return new Promise((done) => {
					finish = done;
				});
			return { created: [{ id: 'created-b' }], errors: [] };
		},
	});
	const service = new SubmissionService();
	service.restore({
		itemStatuses: { 0: 'failed', 1: 'failed' },
		createdItemIds: {},
		lastErrors: [],
	});
	const first = service.retryFailed([item, item], 'location', null);
	const second = service.retryFailed([item, item], 'location', null);
	await new Promise((resolve) => setImmediate(resolve));
	finish({ created: [{ id: 'created-a' }], errors: [] });
	await Promise.all([first, second]);
	assert.equal(calls, 2);
});
