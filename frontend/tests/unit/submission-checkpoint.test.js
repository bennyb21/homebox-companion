import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import { t } from '../i18n.js';

const log = { error() {}, info() {}, debug() {}, warn() {} };
function load(path, imports = {}) {
	const exports = {};
	const code = ts.transpileModule(
		readFileSync(new URL(`../../src/lib/${path}`, import.meta.url), 'utf8'),
		{
			compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
		}
	).outputText;
	runInNewContext(code, {
		exports,
		require: (n) => (n === '$lib/i18n/index.svelte' ? { t } : imports[n]),
		$state: (v) => v,
		crypto,
		structuredClone,
		File,
		Map,
		AbortController,
		DOMException,
		fetch,
		URL,
		setTimeout,
		clearTimeout,
		console,
	});
	return exports;
}
const turn = () => new Promise((resolve) => setImmediate(resolve));
for (const boundary of ['attempt', 'receipt']) {
	for (const failure of ['superseded', 'storage']) {
		test(`explicit ${boundary} checkpoint ${failure} cannot authorize the next POST`, async () => {
			const pending = [],
				durable = [];
			let writes = 0,
				posts = 0;
			const scope = () => ({ contextId: 'A', groupId: 'g1' });
			const { ScanPersistence } = load('services/scanPersistence.ts', {
				'$lib/utils/uuid': { createUuidV4: () => crypto.randomUUID() },
				'./serialize': {
					serializeImage: () =>
						new Promise((resolve) =>
							pending.push(() =>
								resolve({ id: 'image', dataUrl: 'data:image/jpeg;base64,ZGF0YQ==' })
							)
						),
					serializeReviewItem: (i) => i,
					serializeConfirmedItem: (i) => i,
					serializeReviewPhotos: async () => [],
				},
				'./sessionPersistence': {
					captureSessionScope: scope,
					clear: async () => {},
					save: async (s) => {
						writes++;
						if (failure === 'storage' && writes === (boundary === 'attempt' ? 3 : 4)) return false;
						durable.push(structuredClone(s));
						return true;
					},
				},
				'$lib/utils/logger': { workflowLogger: log },
			});
			const { SubmissionService } = load('workflows/submission.svelte.ts', {
				'$lib/utils/itemValidation': { itemValidationError: () => null },
				'$lib/utils/assetId': { normalizeAssetId: (v) => v },
				'$lib/api/index': {
					items: {
						create: async () => ({
							created: [{ id: '11111111-1111-4111-8111-111111111111' }],
							errors: [],
						}),
						uploadAttachment: async (entity, file, o) => {
							posts++;
							return {
								verified: true,
								entity_id: entity,
								attachment_id: crypto.randomUUID(),
								attempt_id: o.attemptId,
								slot: o.slot,
								original_filename: o.originalFilename,
								title: `same__hbc_${o.attemptId}.jpg`,
								mime_type: 'image/jpeg',
								byte_length: 4,
								sha256: 'a'.repeat(64),
							};
						},
					},
				},
				'$lib/api/client': {
					requestScope: () => 'A',
					assertCurrentScope: () => {},
					ApiError: class extends Error {},
				},
				'$lib/utils/uuid': { createUuidV4: () => crypto.randomUUID() },
				'$lib/utils/logger': { workflowLogger: log },
				'$lib/utils/token': { hasToken: () => true },
			});
			const Empty = class {
				images = [];
				detectedItems = [];
				confirmedItems = [];
				removedItems = [];
				currentReviewIndex = 0;
				imageStatuses = {};
			};
			const { scanWorkflow: w } = load('workflows/scan.svelte.ts', {
				'$lib/services/serialize': {},
				'$lib/utils/itemValidation': { itemValidationError: () => null },
				'$lib/utils/logger': { workflowLogger: log },
				'./capture.svelte': { CaptureService: Empty },
				'./analysis.svelte': { AnalysisService: Empty },
				'./review.svelte': { ReviewService: Empty },
				'./submission.svelte': { SubmissionService },
				'$lib/services/scanPersistence': { ScanPersistence, captureSessionScope: scope },
			});
			const file = new File(['data'], 'same.jpg', { type: 'image/jpeg' });
			w._status = 'confirming';
			w.captureService.images = [{ file }];
			w.reviewService.confirmedItems = [
				{
					name: 'Synthetic',
					quantity: 1,
					confirmed: true,
					sourceImageIndex: 0,
					originalFile: file,
					additionalImages: [file],
				},
			];
			let finished = false;
			const run = w.submitAll().then(() => {
				finished = true;
			});
			const prior = boundary === 'attempt' ? 2 : 3;
			for (let i = 0; i < prior; i++) {
				await turn();
				assert.equal(pending.length, 1);
				pending.shift()();
			}
			await turn();
			assert.equal(pending.length, 1);
			const required = pending.shift();
			const newer = failure === 'superseded' ? w.persistAsync() : Promise.resolve();
			required();
			await turn();
			assert.equal(
				posts,
				boundary === 'attempt' ? 0 : 1,
				'unacknowledged checkpoint must stop dispatch'
			);
			if (failure === 'superseded') {
				assert.equal(durable.length, prior);
				assert.equal(w.saveState, 'saving');
			}
			// Release only test-owned barriers; no timers, polling, or automatic upload retry.
			for (let i = 0; i < 12 && !finished; i++) {
				pending.splice(0).forEach((resolve) => resolve());
				await turn();
			}
			assert.equal(finished, true);
			await run;
			await newer;
			assert.equal(posts, boundary === 'attempt' ? 0 : 1);
			assert.equal(w.submissionCheckpoint.itemStatuses[0], 'partial_success');
			assert.equal(
				w.submissionCheckpoint.createdItemIds[0],
				'11111111-1111-4111-8111-111111111111'
			);
		});
	}
}
