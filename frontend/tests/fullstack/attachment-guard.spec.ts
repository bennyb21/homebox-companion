import { test, expect } from '@playwright/test';
import { writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { selectLocation, analyzePhotos, confirmItems, submitItems } from '../browser/helpers/scan';
import { readDrafts } from '../browser/helpers/recovery';
import type { StoredSession } from '../../src/lib/services/serialize';
import type { AttachmentReceipt } from '../../src/lib/api/items';

test('native attachment receipts and retained uncertainty cross the served application', async ({
	page,
}) => {
	test.skip(!process.env.HBC_ATTACHMENT_CASE, 'Attachment boundary acceptance only');
	const mode = process.env.HBC_ATTACHMENT_CASE!;
	const artifacts = process.env.HBC_SMOKE_ARTIFACT_DIR!;
	const responses: Array<{ status: number; body: AttachmentReceipt; lost: boolean }> = [];
	let creates = 0;
	let deletes = 0;
	page.on('request', (request) => {
		if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/items') creates++;
		if (request.method() === 'DELETE') deletes++;
	});
	// Do not fabricate Companion responses: observe the actual HTTP reply. The
	// lost-receipt case drops that real verified reply only after the native write.
	await page.route('**/api/items/*/attachments', async (route) => {
		const response = await route.fetch({ maxRetries: 0 });
		const lost = mode === 'lost-primary';
		responses.push({ status: response.status(), body: await response.json(), lost });
		if (lost) await route.abort('failed');
		else await route.fulfill({ response });
	});
	await selectLocation(page, 'Attachment guard storage');
	const encoded = await page.evaluate(() => {
		const canvas = document.createElement('canvas');
		canvas.width = 320;
		canvas.height = 240;
		const ctx = canvas.getContext('2d')!;
		ctx.fillStyle = '#7d193c';
		ctx.fillRect(0, 0, 320, 240);
		return canvas.toDataURL('image/png').split(',')[1];
	});
	const buffer = Buffer.from(encoded, 'base64');
	await writeFile(join(artifacts, 'source.png'), buffer);
	await page
		.locator('input[type="file"]')
		.first()
		.setInputFiles([
			{ name: 'same.png', mimeType: 'image/png', buffer },
			{ name: 'same.png', mimeType: 'image/png', buffer },
		]);
	await page.getByRole('button', { name: 'Expand options', exact: true }).click();
	await page
		.getByRole('combobox', { name: 'Item type', exact: true })
		.selectOption(process.env.HBC_ATTACHMENT_TYPE!);
	await page.getByRole('button', { name: 'Collapse options', exact: true }).click();
	await analyzePhotos(page);
	await page.getByLabel('Name', { exact: true }).fill('Attachment reviewed');
	await confirmItems(page, 1);
	await submitItems(page);
	await expect(page).toHaveURL(/\/success$/);
	if (mode === 'normal') {
		await expect(page.getByRole('heading', { name: 'Success!', exact: true })).toBeVisible();
		expect(responses).toHaveLength(2);
		for (const { status, body } of responses) {
			expect(status).toBe(200);
			expect(body.verified).toBe(true);
			expect(body.attachment_id).not.toBe(body.entity_id);
			expect(body.sha256).toMatch(/^[a-f0-9]{64}$/);
			expect(body.title).toContain(`__hbc_${body.attempt_id}.`);
			expect(body.original_filename).toBe('same.png');
		}
	} else {
		expect(responses).toHaveLength(mode === 'false-additional' ? 2 : 1);
		if (mode === 'lost-primary') {
			expect(responses[0]).toMatchObject({ status: 200, lost: true, body: { verified: true } });
		} else {
			expect(responses.at(-1)).toMatchObject({
				status: 409,
				body: { detail: { code: 'ATTACHMENT_PERSISTENCE_UNCONFIRMED' } },
			});
		}
		const recovery = page.getByRole('region', { name: 'Retained photos' });
		await expect(recovery).toBeVisible();
		await expect(recovery.getByRole('button', { name: /Download original photo/ })).toHaveCount(2);
		await expect
			.poll(async () => {
				const draft = (await readDrafts(page))[0] as unknown as StoredSession;
				return draft?.submission?.itemStatuses[0];
			})
			.toBe('partial_success');
		const draft = (await readDrafts(page))[0] as unknown as StoredSession;
		expect(draft.submission?.createdItemIds[0]).toBeTruthy();
		expect(draft.confirmedItems[0].name).toBe('Attachment reviewed');
		expect(draft.confirmedItems[0].photos).toHaveLength(2);
		for (const photo of draft.confirmedItems[0].photos!) {
			expect(photo.filename).toBe('same.png');
			expect(photo.dataUrl.split(',')[1]).toBe(encoded);
		}
		const states = draft.submission?.photoAttempts?.[0].map((attempt) => attempt.state);
		expect(states).toEqual(
			mode === 'false-additional' ? ['verified', 'unconfirmed'] : ['unconfirmed', 'not_sent']
		);
		await writeFile(join(artifacts, 'draft.json'), JSON.stringify(draft, null, 2));
		const sent = responses.length;
		await page.reload();
		// Recovery is offered at Location, not by the display-only success route.
		await page.goto('/location');
		await page.getByRole('button', { name: 'Resume Session' }).click();
		await expect(page.getByRole('region', { name: 'Retained photos' })).toBeVisible();
		await expect(page.getByRole('button', { name: /Retry Failed/ })).toHaveCount(0);
		expect(responses).toHaveLength(sent);
		for (const width of [390, 1280]) {
			await page.setViewportSize({ width, height: 844 });
			await page.evaluate(async () => {
				await document.fonts.ready;
				await Promise.allSettled(
					document
						.getAnimations()
						.filter((animation) => animation.effect?.getTiming().iterations !== Infinity)
						.map((animation) => animation.finished)
				);
			});
			await page.getByRole('region', { name: 'Retained photos' }).scrollIntoViewIfNeeded();
			await page.screenshot({ path: join(artifacts, `recovery-${width}.png`) });
		}
	}
	expect(creates).toBe(1);
	expect(deletes).toBe(0);
	await writeFile(
		join(artifacts, 'browser.json'),
		JSON.stringify({ mode, creates, deletes, responses }, null, 2)
	);
});
