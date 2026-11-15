import { createServer } from 'node:http';
import { createHash, randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import type { Request } from '@playwright/test';
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
	test(`multipart inspector matches real production upload wire ${label}`, async ({
		page,
		context,
		api,
		browser,
	}, testInfo) => {
		const pending = new Map<string, { request: Request; originalUrl: string }>();
		const evidence: unknown[] = [];
		const failures: string[] = [];
		const expected = await readFile(
			new URL('../../../tests/assets/multi_item_single_image.jpg', import.meta.url)
		);
		const server = createServer(async (incoming, outgoing) => {
			try {
				const entry = pending.get(incoming.url!);
				if (!entry || incoming.method !== 'POST') throw new Error('Unknown receiver request');
				const { request, originalUrl } = entry;
				pending.delete(incoming.url!);
				const chunks: Buffer[] = [];
				let length = 0;
				for await (const chunk of incoming) {
					length += chunk.length;
					if (length > 8 * 1024 * 1024) throw new Error('Receiver body limit');
					chunks.push(chunk);
				}
				const body = Buffer.concat(chunks);
				const type = incoming.headers['content-type']!;
				const wire = await describeBody(body, type);
				const inspector = await describeBody(
					request.postDataBuffer()!,
					request.headers()['content-type']
				);
				evidence.push({ wire, inspector });
				expect(wire.file_length).toBe(expected.length);
				expect(wire.file_sha256).toBe(sha256(expected));
				// Only bytes received by this HTTP server can authorize the synthetic receipt.
				const received = new Proxy(request, {
					get(target, key) {
						if (key === 'url') return () => originalUrl;
						if (key === 'postDataBuffer') return () => body;
						if (key === 'headers') return () => ({ ...request.headers(), 'content-type': type });
						const value = Reflect.get(target, key);
						return typeof value === 'function' ? value.bind(target) : value;
					},
				});
				const reply = await verifiedAttachment(received);
				outgoing.writeHead(reply.status, { 'content-type': reply.contentType });
				outgoing.end(reply.body);
			} catch (error) {
				failures.push(String(error));
				outgoing.writeHead(422, { 'content-type': 'application/json' });
				outgoing.end(JSON.stringify({ detail: String(error) }));
			}
		});
		await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
		const address = server.address();
		if (!address || typeof address === 'string') throw new Error('No receiver port');
		const origin = new URL(testInfo.project.use.baseURL! as string).origin;
		await context.route(`${origin}/api/items/*/attachments`, async (route) => {
			const token = `/${randomUUID()}`;
			pending.set(token, { request: route.request(), originalUrl: route.request().url() });
			// Preserve browser-native body: never replay inspector postData or override headers.
			await route.continue({ url: `http://127.0.0.1:${address.port}${token}` });
		});
		api.on('POST', '/api/tools/vision/detect', () =>
			json(detectedItems(['Desk tools', 'Storage box']))
		);
		let created = 0;
		api.on('POST', '/api/items', () => json(createdItem(`item-${++created}`)));
		try {
			await selectLocation(page);
			await uploadPhoto(page);
			await analyzePhotos(page);
			await confirmItems(page, 2);
			await submitItems(page);
			await expect(page.getByRole('heading', { name: 'Success!' })).toBeVisible();
			expect(failures).toEqual([]);
			expect(evidence).toHaveLength(2);
			// RED diagnostic: tests the old fixture assumption, not application behavior.
			for (const entry of evidence as Array<{ wire: unknown; inspector: unknown }>) {
				expect(entry.inspector).toEqual(entry.wire);
			}
		} finally {
			await testInfo.attach('actual-inspector-vs-wire', {
				body: JSON.stringify({ browser: browser.version(), evidence, failures }, null, 2),
				contentType: 'application/json',
			});
			server.closeAllConnections();
			await new Promise<void>((resolve, reject) =>
				server.close((error) => (error ? reject(error) : resolve()))
			);
		}
	});
}
