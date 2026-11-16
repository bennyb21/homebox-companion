import { createHash, randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { test, expect } from './fixtures/test';
import { json, verifiedAttachment } from './fixtures/api';
import { createdItem, detectedItems } from './fixtures/data';
import {
	selectLocation,
	uploadPhoto,
	analyzePhotos,
	confirmItems,
	submitItems,
} from './helpers/scan';

const sha256 = (bytes: Uint8Array) => createHash('sha256').update(bytes).digest('hex');
async function describeBody(body: Buffer, contentType: string) {
	const form = await new Response(new Uint8Array(body), {
		headers: { 'content-type': contentType },
	}).formData();
	const file = form.get('file') as File;
	return {
		body_length: body.length,
		body_sha256: sha256(body),
		file_length: file.size,
		file_sha256: sha256(new Uint8Array(await file.arrayBuffer())),
		filename: file.name,
		attempt_id: form.get('attempt_id'),
		slot: form.get('slot'),
		original_filename: form.get('original_filename'),
	};
}

for (const label of ['desktop', 'phone @mobile']) {
	test(`production uploads verify actual HTTP bytes rather than inspector bodies ${label}`, async ({
		page,
		api,
		browser,
	}, testInfo) => {
		const expected = await readFile(
			new URL('../../../tests/assets/multi_item_single_image.jpg', import.meta.url)
		);
		const receipts: Array<Record<string, unknown>> = [];
		api.on('POST', '/api/tools/vision/detect', () =>
			json(detectedItems(['Desk tools', 'Storage box']))
		);
		let created = 0;
		api.on('POST', '/api/items', () => json(createdItem(`item-${++created}`)));
		api.on('POST', /^\/api\/items\/[^/]+\/attachments$/, async (request) => {
			const reply = await verifiedAttachment(request);
			receipts.push(JSON.parse(reply.body));
			return reply;
		});
		await selectLocation(page);
		await uploadPhoto(page);
		await analyzePhotos(page);
		await confirmItems(page, 2);
		await submitItems(page);
		await expect(page.getByRole('heading', { name: 'Success!' })).toBeVisible();
		expect(api.multipart.received).toHaveLength(2);
		const evidence = [];
		for (const [index, upload] of api.multipart.received.entries()) {
			const wire = await describeBody(upload.body, upload.contentType);
			const inspector = await describeBody(upload.inspectorBody!, upload.contentType);
			expect(wire.file_length).toBe(expected.length);
			expect(wire.file_sha256).toBe(sha256(expected));
			expect(wire.attempt_id).toMatch(
				/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/
			);
			expect(wire.slot).toBe('0');
			expect(wire.original_filename).toBe('multi_item_single_image.jpg');
			expect(inspector.attempt_id).toBe(wire.attempt_id);
			expect(inspector.slot).toBe(wire.slot);
			expect(inspector.original_filename).toBe(wire.original_filename);
			expect(receipts[index]).toMatchObject({
				verified: true,
				entity_id: `item-${index + 1}`,
				attempt_id: wire.attempt_id,
				slot: wire.slot,
				original_filename: wire.original_filename,
				byte_length: wire.file_length,
				sha256: wire.file_sha256,
			});
			evidence.push({
				wire,
				inspector,
				receipt: receipts[index],
				content_type: upload.contentType,
				wire_body_base64: upload.body.toString('base64'),
			});
		}
		expect(new Set(evidence.map((entry) => entry.wire.attempt_id)).size).toBe(2);
		await testInfo.attach('actual-inspector-vs-wire', {
			body: JSON.stringify({ browser: browser.version(), evidence }, null, 2),
			contentType: 'application/json',
		});
	});

	test(`multipart receipts bind different native bytes and fields ${label}`, async ({
		page,
		api,
	}) => {
		api.on('POST', /^\/api\/items\/[^/]+\/attachments$/, verifiedAttachment);
		await page.goto('/location');
		for (const [index, bytes] of [
			[0, 255, 128, 1],
			[17, 0, 44, 255, 31],
		].entries()) {
			const attempt = randomUUID();
			const slot = String(index);
			const filename = `synthetic-${index}.jpg`;
			const result = await page.evaluate(
				async ({ bytes, attempt, slot, filename, index }) => {
					const form = new FormData();
					form.append('file', new File([new Uint8Array(bytes)], filename, { type: 'image/jpeg' }));
					form.append('attempt_id', attempt);
					form.append('slot', slot);
					form.append('original_filename', filename);
					const response = await fetch(`/api/items/item-${index + 1}/attachments`, {
						method: 'POST',
						body: form,
					});
					return { status: response.status, receipt: await response.json() };
				},
				{ bytes, attempt, slot, filename, index }
			);
			expect(result.status).toBe(200);
			expect(result.receipt).toMatchObject({
				verified: true,
				attempt_id: attempt,
				slot,
				original_filename: filename,
				entity_id: `item-${index + 1}`,
				byte_length: bytes.length,
				sha256: sha256(new Uint8Array(bytes)),
			});
			const upload = api.multipart.received[index];
			expect(await describeBody(upload.body, upload.contentType)).toMatchObject({
				file_length: bytes.length,
				file_sha256: result.receipt.sha256,
				attempt_id: attempt,
				slot,
				original_filename: filename,
			});
		}
		expect(api.multipart.received).toHaveLength(2);
	});

	test(`real zero-byte file cannot produce a verified receipt ${label}`, async ({
		page,
		api,
	}, testInfo) => {
		let rejected = false;
		api.on('POST', '/api/items/empty/attachments', async (request) => {
			try {
				return await verifiedAttachment(request);
			} catch (error) {
				expect(String(error)).toContain('Missing durable photo attempt');
				rejected = true;
				return json({ verified: false }, 422);
			}
		});
		await page.goto('/location');
		const attempt = randomUUID();
		const result = await page.evaluate(async (attempt) => {
			const form = new FormData();
			form.append('file', new File([], 'empty.jpg', { type: 'image/jpeg' }));
			form.append('attempt_id', attempt);
			form.append('slot', '0');
			form.append('original_filename', 'empty.jpg');
			const response = await fetch('/api/items/empty/attachments', { method: 'POST', body: form });
			return { status: response.status, body: await response.json() };
		}, attempt);
		expect(result).toEqual({ status: 422, body: { verified: false } });
		expect(rejected).toBe(true);
		expect(api.multipart.received).toHaveLength(1);
		const upload = api.multipart.received[0];
		const wire = await describeBody(upload.body, upload.contentType);
		expect(wire).toMatchObject({
			file_length: 0,
			attempt_id: attempt,
			slot: '0',
			original_filename: 'empty.jpg',
		});
		await testInfo.attach('actual-empty-wire-rejected', {
			body: JSON.stringify({
				wire,
				result,
				content_type: upload.contentType,
				wire_body_base64: upload.body.toString('base64'),
			}),
			contentType: 'application/json',
		});
	});
}
