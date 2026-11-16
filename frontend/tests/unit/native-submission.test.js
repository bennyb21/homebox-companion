import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';
import { t } from '../i18n.js';

function deferred() {
	let resolve, reject;
	const promise = new Promise((yes, no) => {
		resolve = yes;
		reject = no;
	});
	return { promise, resolve, reject };
}

for (const settle of ['resolve', 'reject']) {
	for (const retry of [false, true]) {
		for (const boundary of ['create', 'upload', 'update', 'checkpoint']) {
			test(`reset isolates old ${boundary} ${settle} retry=${retry} and preserves newer cancellation`, async () => {
				const held = deferred(),
					reached = deferred(),
					newer = deferred(),
					newerReached = deferred();
				let calls = 0,
					checkpoints = 0;
				const api = {
					scope: 'original',
					create: async () => {
						calls++;
						if (calls === 2) {
							newerReached.resolve();
							return newer.promise;
						}
						if (boundary === 'create') {
							reached.resolve();
							return held.promise;
						}
						return { created: [{ id: 'old-id' }], errors: [] };
					},
					uploadAttachment: async () => {
						reached.resolve();
						return held.promise;
					},
					update: async () => {
						reached.resolve();
						return held.promise;
					},
				};
				const { SubmissionService } = await loadSubmission(api);
				const service = new SubmissionService(async () => {
					checkpoints++;
					if (boundary === 'checkpoint' && checkpoints === 2) {
						reached.resolve();
						await held.promise;
					}
				});
				const oldItem = {
					...item,
					name: 'Private old name',
					...(boundary === 'upload' ? { originalFile: new File(['private'], 'private.jpg') } : {}),
					...(boundary === 'update' ? { asset_id: '42' } : {}),
				};
				if (retry)
					service.restore({ itemStatuses: { 0: 'failed' }, createdItemIds: {}, lastErrors: [] });
				const old = retry
					? service.retryFailed([oldItem], null, null)
					: service.submitAll([oldItem], null, null);
				await reached.promise;
				const oldSnapshot = service.snapshot();
				service.reset();
				api.scope = 'new';
				assert.deepEqual(service.snapshot(), {
					itemStatuses: {},
					createdItemIds: {},
					lastErrors: [],
					photoAttempts: {},
				});
				const next = service.submitAll([item], null, null);
				await newerReached.promise;
				const before = service.snapshot(),
					checkpointCount = checkpoints;
				if (settle === 'reject') held.reject(new DOMException('old cancelled', 'AbortError'));
				else held.resolve({ created: [{ id: 'old-id' }], errors: [] });
				await old;
				assert.deepEqual(service.snapshot(), before);
				assert.equal(checkpoints, checkpointCount, 'obsolete checkpoint callback');
				assert.equal(service.isSubmitting, true, 'old finally cleared new controller');
				service.cancel();
				newer.reject(new DOMException('new cancelled', 'AbortError'));
				await next;
				assert.equal(service.isSubmitting, false);
				assert.equal(oldSnapshot.itemStatuses[0], 'creating');
			});
		}
	}
}

function verifiedSnapshot() {
	const entity = '11111111-1111-4111-8111-111111111111';
	return {
		itemStatuses: { 0: 'success' },
		createdItemIds: { 0: entity },
		lastErrors: [],
		photoAttempts: {
			0: [0, 1].map((i) => {
				const attempt = crypto.randomUUID();
				return {
					state: 'verified',
					slot: String(i),
					attempt_id: attempt,
					original_filename: 'same.jpg',
					receipt: {
						verified: true,
						entity_id: entity,
						attachment_id: crypto.randomUUID(),
						attempt_id: attempt,
						slot: String(i),
						original_filename: 'same.jpg',
						title: `same__hbc_${attempt}.jpg`,
						mime_type: 'image/jpeg',
						byte_length: 4,
						sha256: 'a'.repeat(64),
					},
				};
			}),
		},
	};
}
const corruptions = {
	entity: (s) => {
		s.photoAttempts[0][0].receipt.entity_id = crypto.randomUUID();
	},
	attempt: (s) => {
		s.photoAttempts[0][0].receipt.attempt_id = crypto.randomUUID();
	},
	slot: (s) => {
		s.photoAttempts[0][0].receipt.slot = '99';
	},
	filename: (s) => {
		s.photoAttempts[0][0].receipt.original_filename = 'other.jpg';
	},
	mime: (s) => {
		s.photoAttempts[0][0].receipt.mime_type = 'application/pdf';
	},
	hash: (s) => {
		s.photoAttempts[0][0].receipt.sha256 = 'not-a-hash';
	},
	length: (s) => {
		s.photoAttempts[0][0].receipt.byte_length = 0;
	},
	fraction: (s) => {
		s.photoAttempts[0][0].receipt.byte_length = 1.5;
	},
	title: (s) => {
		s.photoAttempts[0][0].receipt.title = 'same__hbc_other.jpg';
	},
	shape: (s) => {
		s.photoAttempts[0][0].receipt = {};
	},
	nullReceipt: (s) => {
		s.photoAttempts[0][0].receipt = null;
	},
	numberTitle: (s) => {
		s.photoAttempts[0][0].receipt.title = 42;
	},
	missing: (s) => {
		delete s.photoAttempts[0][0].receipt;
	},
	duplicateAttachment: (s) => {
		s.photoAttempts[0][1].receipt.attachment_id = s.photoAttempts[0][0].receipt.attachment_id;
	},
	duplicateAttempt: (s) => {
		s.photoAttempts[0][1].attempt_id = s.photoAttempts[0][0].attempt_id;
		s.photoAttempts[0][1].receipt.attempt_id = s.photoAttempts[0][0].attempt_id;
	},
	duplicateSlot: (s) => {
		s.photoAttempts[0][1].slot = '0';
		s.photoAttempts[0][1].receipt.slot = '0';
	},
	invalidAttempt: (s) => {
		s.photoAttempts[0][0].attempt_id = 'bad';
		s.photoAttempts[0][0].receipt.attempt_id = 'bad';
	},
	missingKnownId: (s) => {
		delete s.createdItemIds[0];
	},
};
corruptions.combined = (s) => {
	corruptions.entity(s);
	corruptions.attempt(s);
	corruptions.slot(s);
	corruptions.filename(s);
};
for (const [name, corrupt] of Object.entries(corruptions)) {
	test(`restore rejects ${name} receipt without replay or successful clearing`, async () => {
		const { SubmissionService } = await loadSubmission({
			create: async () => assert.fail('recreate'),
			uploadAttachment: async () => assert.fail('reupload'),
		});
		const snapshot = verifiedSnapshot();
		corrupt(snapshot);
		const service = new SubmissionService();
		service.restore(snapshot);
		assert.equal(service.allItemsSuccessful(), false);
		assert.equal(service.snapshot().itemStatuses[0], 'partial_success');
		assert.ok(service.snapshot().photoAttempts[0].some((a) => a.state === 'unconfirmed'));
		assert.deepEqual(service.snapshot().createdItemIds, snapshot.createdItemIds);
		assert.equal((await service.submitAll([item], null, null)).success, false);
	});
}
test('valid identical-name and identical-hash distinct attempts roundtrip unchanged', async () => {
	const { SubmissionService } = await loadSubmission({});
	const s = new SubmissionService();
	const snapshot = verifiedSnapshot();
	s.restore(snapshot);
	assert.deepEqual(s.snapshot(), snapshot);
	assert.equal(s.allItemsSuccessful(), true);
});
test('legacy absent attempts retains known ID conservatively without recreation', async () => {
	const { SubmissionService } = await loadSubmission({
		create: async () => assert.fail('recreate'),
	});
	const s = new SubmissionService();
	const snapshot = verifiedSnapshot();
	delete snapshot.photoAttempts;
	s.restore(snapshot);
	assert.equal(s.allItemsSuccessful(), false);
	assert.equal((await s.submitAll([item], null, null)).success, false);
	assert.deepEqual(s.snapshot().createdItemIds, snapshot.createdItemIds);
});

for (const change of ['name', 'count']) {
	test(`restore checks ${change} against retained original photos`, async () => {
		const { SubmissionService } = await loadSubmission({});
		const s = new SubmissionService();
		const snapshot = verifiedSnapshot();
		const photos = {
			...item,
			originalFile: new File(['x'], 'same.jpg'),
			additionalImages: [new File(['y'], 'same.jpg')],
		};
		if (change === 'name') photos.additionalImages = [new File(['y'], 'different.jpg')];
		else photos.additionalImages.push(new File(['z'], 'third.jpg'));
		s.restore(snapshot, [photos]);
		assert.equal(s.allItemsSuccessful(), false);
		assert.equal(s.snapshot().itemStatuses[0], 'partial_success');
	});
}

test('restore retains an orphaned known ID even when status metadata is missing', async () => {
	const { SubmissionService } = await loadSubmission({
		create: async () => assert.fail('recreate'),
	});
	const s = new SubmissionService();
	s.restore({ itemStatuses: {}, createdItemIds: { 0: 'known' }, lastErrors: [] });
	assert.equal(s.snapshot().itemStatuses[0], 'partial_success');
	await s.submitAll([item], null, null);
	assert.equal(s.snapshot().createdItemIds[0], 'known');
});

let sequence = 0;
async function loadSubmission(itemsApi) {
	const source = await readFile(
		new URL('../../src/lib/workflows/submission.svelte.ts', import.meta.url),
		'utf8'
	);
	const id = `nativeSubmission${sequence++}`;
	globalThis[id] = {
		t,
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
