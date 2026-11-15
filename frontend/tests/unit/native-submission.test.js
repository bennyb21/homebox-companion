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
		generateId: () => crypto.randomUUID(),
		requestScope: () => itemsApi.scope ?? 'original',
		assertCurrentScope: (scope) => {
			if (scope !== (itemsApi.scope ?? 'original')) throw new Error('scope changed');
		},
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
test('missing upload receipt retains known item and blocks POST replay and DELETE', async () => {
	let posts = 0,
		deletes = 0,
		creates = 0;
	const { SubmissionService } = await loadSubmission({
		create: async () => {
			creates++;
			return { created: [{ id: 'created-a' }], errors: [] };
		},
		uploadAttachment: async () => {
			posts++;
			return { id: 'created-a', attachments: [] };
		},
		delete: async () => {
			deletes++;
		},
	});
	const photos = {
		...item,
		originalFile: new File(['synthetic'], 'same.jpg'),
		additionalImages: [new File(['more'], 'same.jpg')],
	};
	const service = new SubmissionService();
	await service.submitAll([photos], 'location', null);
	assert.equal(service.snapshot().itemStatuses[0], 'partial_success');
	assert.equal(service.snapshot().createdItemIds[0], 'created-a');
	assert.equal(service.snapshot().photoAttempts[0][0].state, 'unconfirmed');
	await service.retryFailed([photos], 'location', null);
	assert.equal(posts, 1);
	assert.equal(deletes, 0);
	assert.equal(creates, 1);
});

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

for (const failure of ['primary', 'additional', 'checkpoint-before', 'checkpoint-after', 'none']) {
	test(`ordered photo receipts survive ${failure} and reload without replay`, async () => {
		let calls = 0,
			service,
			durable;
		const { SubmissionService } = await loadSubmission({
			create: async () => ({ created: [{ id: 'created-a' }], errors: [] }),
			uploadAttachment: async (entity_id, file, options) => {
				assert.equal(durable.createdItemIds[0], entity_id);
				assert.equal(durable.photoAttempts[0][calls].state, 'in_flight');
				calls++;
				if ((failure === 'primary' && calls === 1) || (failure === 'additional' && calls === 2))
					throw new Error('lost');
				return {
					verified: true,
					entity_id,
					attachment_id: '22222222-2222-4222-8222-222222222222',
					attempt_id: options.attemptId,
					slot: options.slot,
					byte_length: file.size,
					sha256: 'a'.repeat(64),
					mime_type: 'image/jpeg',
					original_filename: file.name,
					title: `same__hbc_${options.attemptId}.jpg`,
				};
			},
			delete: async () => assert.fail('must not delete'),
		});
		service = new SubmissionService(async () => {
			const snapshot = service.snapshot();
			if (failure === 'checkpoint-before' && snapshot.photoAttempts[0]?.[0].state === 'in_flight')
				throw new Error('disk full');
			if (failure === 'checkpoint-after' && snapshot.photoAttempts[0]?.[0].receipt)
				throw new Error('disk full');
			durable = snapshot;
		});
		const photos = {
			...item,
			originalFile: new File(['one'], 'same.jpg'),
			additionalImages: [new File(['two'], 'same.jpg'), new File(['three'], 'third.jpg')],
		};
		await service.submitAll([photos], 'location', null);
		assert.equal(
			calls,
			failure === 'checkpoint-before'
				? 0
				: failure === 'additional'
					? 2
					: failure === 'none'
						? 3
						: 1
		);
		assert.equal(
			service.snapshot().itemStatuses[0],
			failure === 'none' ? 'success' : 'partial_success'
		);
		if (failure === 'additional')
			assert.equal(service.snapshot().photoAttempts[0][0].state, 'verified');
		const recovered = new SubmissionService();
		recovered.restore(durable);
		const previous = calls;
		await recovered.submitAll([photos], 'location', null);
		assert.equal(calls, previous);
		assert.equal(photos.additionalImages[1].name, 'third.jpg');
	});
}

test('collection change during checkpoint cannot dispatch a photo in another scope', async () => {
	const api = {
		scope: 'original',
		create: async () => ({ created: [{ id: 'created-a' }], errors: [] }),
		uploadAttachment: async () => assert.fail('wrong scope POST'),
	};
	const { SubmissionService } = await loadSubmission(api);
	const service = new SubmissionService(async () => {
		if (service.snapshot().createdItemIds[0]) api.scope = 'changed';
	});
	await service.submitAll([{ ...item, originalFile: new File(['x'], 'x.jpg') }], 'location', null);
	assert.equal(service.snapshot().itemStatuses[0], 'partial_success');
	assert.equal(service.snapshot().photoAttempts[0]?.[0]?.state, undefined);
});

test('legacy inconsistent failed row with known ID cannot recreate or lose its identity', async () => {
	let creates = 0;
	const { SubmissionService } = await loadSubmission({
		create: async () => {
			creates++;
			return { created: [], errors: ['rejected'] };
		},
	});
	const service = new SubmissionService();
	service.restore({
		itemStatuses: { 0: 'failed' },
		createdItemIds: { 0: 'known' },
		lastErrors: [],
	});
	await service.retryFailed([item], null, null);
	assert.equal(creates, 0);
	assert.equal(service.snapshot().itemStatuses[0], 'partial_success');
});
