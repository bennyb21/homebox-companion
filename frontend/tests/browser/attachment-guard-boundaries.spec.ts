import { test, expect } from './fixtures/test';
import { json, verifiedAttachment } from './fixtures/api';
import { detectedItems, createdItem } from './fixtures/data';
import {
	selectLocation,
	uploadPhoto,
	analyzePhotos,
	confirmItems,
	submitItems,
} from './helpers/scan';
import { readDrafts, putDraft } from './helpers/recovery';
import { seedLegacySession } from './fixtures/auth';
import type { StoredSession } from '../../src/lib/services/serialize';

for (const transition of ['logout', 'reconnect-identity', 'reconnect-membership']) {
	test(`inflight ${transition} retains old recovery and keeps new capture private`, async ({
		page,
		api,
	}) => {
		if (transition === 'logout') {
			api.setAuthMode('legacy');
			await seedLegacySession(page);
		}
		let identity = 'user',
			group = 'g1';
		api.on('GET', '/api/homebox/connection', () =>
			json({
				connected: true,
				context_id: `deployment:${identity}`,
				user_id: identity,
				default_group_id: group,
			})
		);
		api.on('GET', '/api/groups', () =>
			json(
				group === 'g1'
					? [
							{ id: 'g1', name: 'Private collection' },
							{ id: 'g2', name: 'Different collection' },
						]
					: [{ id: group, name: 'Current collection' }]
			)
		);
		api.on('POST', '/api/logout', () => json({ message: 'ok' }));
		api.on('POST', '/api/tools/vision/detect', () =>
			json(detectedItems(['Private held original']))
		);
		api.on('POST', '/api/items', () =>
			json(createdItem('11111111-1111-4111-8111-111111111111', 'Private held original'))
		);
		const gate = api.gate();
		api.on('POST', /^\/api\/items\/[^/]+\/attachments$/, async (request) => {
			await gate.promise;
			return verifiedAttachment(request);
		});
		await selectLocation(page);
		await uploadPhoto(page);
		await analyzePhotos(page);
		await confirmItems(page, 1);
		const uploading = page.waitForRequest(
			(r) => r.method() === 'POST' && /\/attachments$/.test(new URL(r.url()).pathname)
		);
		await submitItems(page);
		await uploading;
		const [before] = await readDrafts(page, 'deployment:user:g1');
		expect(before.submission).toMatchObject({ photoAttempts: { 0: [{ state: 'in_flight' }] } });
		// Ordinary route changes are intentionally blocked during submission. The
		// reachable header reset is required before logout/reconnect navigation.
		await page.getByRole('link', { name: 'Settings', exact: true }).click();
		await expect(
			page.getByText('Submission is in progress. Stay here until its outcome is known.', {
				exact: true,
			})
		).toBeVisible();
		await expect(page).toHaveURL(/summary$/);
		await page.locator('#collection-selector:visible').click();
		await page.getByRole('option', { name: 'Different collection' }).click();
		group = 'g2';
		if (transition === 'logout') {
			await page.getByRole('link', { name: 'Settings', exact: true }).click();
			await page.getByRole('button', { name: 'Sign Out', exact: true }).click();
			await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
			identity = 'other';
			await page.getByLabel('Email').fill('other@example.test');
			await page.locator('#password').fill('synthetic');
			await page.getByRole('button', { name: 'Sign In', exact: true }).click();
			await expect(page).toHaveURL(/location$/);
		} else {
			api.on('GET', '/api/chat/status', () =>
				json({ detail: 'Rejected key', code: 'HOMEBOX_API_KEY_REJECTED' }, 502)
			);
			await page.locator('a[href="/chat"]').first().click();
			await expect(page.getByRole('button', { name: 'Retry', exact: true })).toBeVisible();
			if (transition === 'reconnect-identity') identity = 'other';
			else group = 'g3';
			api.on('GET', '/api/chat/status', () =>
				json({ session_id: 'new-session', message_count: 0 })
			);
			await page.getByRole('button', { name: 'Retry', exact: true }).click();
			await expect(page.getByLabel('Chat message input')).toBeVisible();
			await page.getByRole('link', { name: 'Scan', exact: true }).click();
		}
		gate.release();
		await expect(page.getByRole('button', { name: 'Resume Session' })).toHaveCount(0);
		await expect(page.getByText('Private held original', { exact: true })).toHaveCount(0);
		await page.getByRole('button', { name: /Storage/ }).click();
		await page.getByRole('button', { name: 'Select current location' }).click();
		await page.getByRole('button', { name: 'Continue to Capture' }).click();
		await expect(page).toHaveURL(/capture$/);
		api.on('POST', '/api/tools/vision/detect', () => json(detectedItems(['New private scope'])));
		await uploadPhoto(page);
		await analyzePhotos(page);
		await confirmItems(page, 1);
		const [current] = await readDrafts(page, `deployment:${identity}:${group}`);
		expect(current.submission).toEqual({
			itemStatuses: {},
			createdItemIds: {},
			lastErrors: [],
			photoAttempts: {},
		});
		expect(JSON.stringify(current)).not.toContain('Private held original');
		const [after] = await readDrafts(page, 'deployment:user:g1');
		expect(after).toEqual(before);
		expect(api.requests.filter((r) => r.method() === 'DELETE')).toHaveLength(0);
	});
}

for (const corruption of ['entity', 'duplicate-slot']) {
	test(`inconsistent ${corruption} receipt in IndexedDB stays recoverable past TTL without replay`, async ({
		page,
		api,
	}) => {
		api.on('POST', '/api/tools/vision/detect', () =>
			json(detectedItems(['Original recovery file']))
		);
		api.on('POST', '/api/items', () =>
			json(createdItem('11111111-1111-4111-8111-111111111111', 'Original recovery file'))
		);
		api.on('POST', /^\/api\/items\/[^/]+\/attachments$/, () =>
			json({ detail: 'unconfirmed' }, 409)
		);
		await selectLocation(page);
		await uploadPhoto(page);
		await analyzePhotos(page);
		await confirmItems(page, 1);
		await submitItems(page);
		await expect(page.getByRole('heading', { name: 'Items need attention' })).toBeVisible();
		const [raw] = await readDrafts(page, 'deployment:user:g1');
		const draft = raw as unknown as StoredSession;
		const attempt = draft.submission!.photoAttempts![0][0];
		attempt.state = 'verified';
		attempt.receipt = {
			verified: true,
			entity_id: '22222222-2222-4222-8222-222222222222',
			attachment_id: '33333333-3333-4333-8333-333333333333',
			attempt_id: attempt.attempt_id!,
			slot: attempt.slot,
			original_filename: attempt.original_filename,
			title: `same__hbc_${attempt.attempt_id}.jpg`,
			mime_type: 'image/jpeg',
			sha256: 'a'.repeat(64),
			byte_length: 4,
		};
		if (corruption === 'duplicate-slot')
			draft.submission!.photoAttempts![0].push(structuredClone(attempt));
		draft.submission!.itemStatuses[0] = 'success';
		draft.createdAt = Date.now() - 8 * 86400000;
		await putDraft(page, 'deployment:user:g1', draft as unknown as Record<string, unknown>);
		await page.goto('/location');
		await page.getByRole('button', { name: 'Resume Session' }).click();
		await expect(page.getByRole('button', { name: /Download original photo 1/ })).toBeVisible();
		await expect(page.getByText(/Photo\s+1: unconfirmed/)).toHaveCount(
			corruption === 'duplicate-slot' ? 2 : 1
		);
		await expect(page.getByText(/Photo\s+1: unconfirmed/).first()).toBeVisible();
		await expect(page.getByRole('button', { name: 'Submit All Items' })).toHaveCount(0);
		expect((await readDrafts(page, 'deployment:user:g1'))[0].confirmedItems).toEqual(
			raw.confirmedItems
		);
		expect(
			api.requests.filter(
				(r) => r.method() === 'POST' && new URL(r.url()).pathname === '/api/items'
			)
		).toHaveLength(1);
		expect(
			api.requests.filter(
				(r) => r.method() === 'POST' && /\/attachments$/.test(new URL(r.url()).pathname)
			)
		).toHaveLength(1);
	});
}

for (const width of [390, 1280]) {
	test(`partial success reload exposes recovery without a success claim at ${width}`, async ({
		page,
		api,
	}) => {
		await page.setViewportSize({ width, height: 844 });
		api.on('POST', '/api/tools/vision/detect', () =>
			json(detectedItems(['Retained private original']))
		);
		api.on('POST', '/api/items', () =>
			json(createdItem('11111111-1111-4111-8111-111111111111', 'Retained private original'))
		);
		api.on('POST', /^\/api\/items\/[^/]+\/attachments$/, () =>
			json({ detail: 'unconfirmed' }, 409)
		);
		await selectLocation(page);
		await uploadPhoto(page);
		await analyzePhotos(page);
		await confirmItems(page, 1);
		await submitItems(page);
		await expect(page.getByRole('heading', { name: 'Items need attention' })).toBeVisible();
		const [before] = await readDrafts(page, 'deployment:user:g1');
		expect(before.submission).toMatchObject({ itemStatuses: { 0: 'partial_success' } });
		const authGate = api.gate();
		api.on('GET', '/api/homebox/connection', async () => {
			await authGate.promise;
			return json({
				connected: true,
				context_id: 'deployment:user',
				user_id: 'user-1',
				default_group_id: 'g1',
			});
		});
		const connecting = page.waitForRequest('**/api/homebox/connection');
		await page.reload();
		await connecting;
		await expect(page.getByRole('button', { name: 'Resume Session' })).toHaveCount(0);
		await expect(page.getByText('Retained private original', { exact: true })).toHaveCount(0);
		authGate.release();
		await expect(page.locator('main h2')).toBeVisible();
		await expect(page.getByRole('heading', { name: 'Success!', exact: true })).toHaveCount(0);
		await expect(page.getByText('Items have been added to your inventory')).toHaveCount(0);
		const resume = page.getByRole('button', { name: 'Resume Session', exact: true });
		await expect(resume).toBeInViewport();
		await page.screenshot({ path: test.info().outputPath(`reload-${width}.png`) });
		await resume.click();
		await expect(page.getByRole('button', { name: /Download original photo 1/ })).toBeVisible();
		const link = page.getByRole('link', { name: 'Review existing item in Homebox' });
		await expect(link).toHaveAttribute('href', /11111111-1111-4111-8111-111111111111$/);
		await expect(page).toHaveURL(/summary$/);
		await expect(page.getByRole('button', { name: /Submit All Items/ })).toHaveCount(0);
		await page.evaluate(async () => {
			await document.fonts.ready;
			await Promise.all(
				document
					.getAnimations()
					.filter((a) => Number.isFinite(Number(a.effect?.getComputedTiming().endTime)))
					.map((a) => a.finished.catch(() => {}))
			);
		});
		await link.scrollIntoViewIfNeeded();
		await page.screenshot({ path: test.info().outputPath(`resumed-${width}.png`) });
		const [after] = await readDrafts(page, 'deployment:user:g1');
		expect(after.confirmedItems).toEqual(before.confirmedItems);
		expect(
			api.requests.filter(
				(r) => r.method() === 'POST' && /\/attachments$/.test(new URL(r.url()).pathname)
			)
		).toHaveLength(1);
		expect(
			api.requests.filter(
				(r) => r.method() === 'POST' && new URL(r.url()).pathname === '/api/items'
			)
		).toHaveLength(1);
		expect(api.requests.filter((r) => r.method() === 'DELETE')).toHaveLength(0);
	});
}

test('independent inflight collection switch must not adopt old item IDs into new collection', async ({
	page,
	api,
}) => {
	api.on('GET', '/api/groups', () =>
		json([
			{ id: 'g1', name: 'Private collection' },
			{ id: 'g2', name: 'Different collection' },
		])
	);
	let name = 'Private account A item';
	api.on('POST', '/api/tools/vision/detect', () => json(detectedItems([name])));
	api.on('POST', '/api/items', () =>
		json(createdItem('11111111-1111-4111-8111-111111111111', name))
	);
	const gate = api.gate();
	api.on('POST', /^\/api\/items\/[^/]+\/attachments$/, async (request) => {
		await gate.promise;
		return verifiedAttachment(request);
	});
	await selectLocation(page);
	await uploadPhoto(page);
	await analyzePhotos(page);
	await confirmItems(page, 1);
	const uploading = page.waitForRequest(
		(r) => r.method() === 'POST' && /\/attachments$/.test(new URL(r.url()).pathname)
	);
	await submitItems(page);
	await uploading;
	await page.locator('#collection-selector:visible').click();
	await page.getByRole('option', { name: 'Different collection' }).click();
	gate.release();
	await page.getByRole('link', { name: 'Scan', exact: true }).click();
	name = 'New collection camera';
	await page.getByRole('button', { name: /Storage/ }).click();
	await page.getByRole('button', { name: 'Select current location' }).click();
	await page.getByRole('button', { name: 'Continue to Capture' }).click();
	await test.info().attach('scope-switch-state', {
		body: JSON.stringify({
			url: page.url(),
			oldDraft: await readDrafts(page, 'deployment:user:g1'),
			newDraft: await readDrafts(page, 'deployment:user:g2'),
		}),
		contentType: 'application/json',
	});
	await expect(page).toHaveURL(/capture$/);
	await uploadPhoto(page);
	await analyzePhotos(page);
	await confirmItems(page, 1);
	await expect.poll(async () => (await readDrafts(page, 'deployment:user:g2')).length).toBe(1);
	const [draft] = await readDrafts(page, 'deployment:user:g2');
	await test
		.info()
		.attach('new-scope-draft', { body: JSON.stringify(draft), contentType: 'application/json' });
	expect(
		(draft.submission as { createdItemIds: Record<string, string>; lastErrors: string[] })
			.createdItemIds
	).toEqual({});
	expect(
		(
			draft.submission as { createdItemIds: Record<string, string>; lastErrors: string[] }
		).lastErrors.join(' ')
	).not.toContain('Private account A item');
});
