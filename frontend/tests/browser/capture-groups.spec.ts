import { expect, test } from './fixtures/test';
import { json } from './fixtures/api';
import { selectLocation, analyzePhotos } from './helpers/scan';
import { uploadSyntheticPhoto } from '../fullstack/synthetic-photo';
import { readDrafts, putDraft } from './helpers/recovery';

test('skipping the last unconfirmed result leaves an explicit empty summary, not a review loop', async ({
	page,
	api,
}) => {
	api.on('POST', '/api/tools/vision/detect', () =>
		json({ items: [{ name: 'Part', quantity: 1 }] })
	);
	await selectLocation(page);
	await uploadSyntheticPhoto(page);
	await page.getByRole('button', { name: /Analyze with AI/ }).click();
	await page.waitForURL('**/review');
	await page.getByRole('button', { name: 'Skip', exact: true }).click();
	await page.waitForURL('**/summary');
	await expect(page.getByText('No draft items remain.', { exact: true })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Add photos', exact: true })).toBeVisible();
});

test('legacy capture checkpoints preserve original groups until explicit regrouping', async ({
	page,
}) => {
	await selectLocation(page);
	await page.getByRole('switch', { name: 'One item per photo' }).check();
	await uploadSyntheticPhoto(page);
	await uploadSyntheticPhoto(page);
	await expect
		.poll(
			async () => ((await readDrafts(page, 'deployment:user:g1'))[0]?.images as unknown[])?.length
		)
		.toBe(2);
	const legacy = (await readDrafts(page, 'deployment:user:g1'))[0];
	delete legacy.oneItemPerPhoto;
	delete legacy.analysisStale;
	delete legacy.legacyGrouping;
	await putDraft(page, 'deployment:user:g1', legacy);
	await page.reload();
	await page.getByRole('button', { name: 'Resume Session', exact: true }).click();
	await expect(page.getByText(/Legacy draft: existing photo groups/)).toBeVisible();
	await expect(page.getByText('2 items · 2 photos', { exact: true })).toBeVisible();
	const photos = (value: unknown) =>
		(value as Record<string, unknown>[]).map((image) => ({ ...image, id: undefined }));
	await expect
		.poll(async () => photos((await readDrafts(page, 'deployment:user:g1'))[0]?.images))
		.toEqual(photos(legacy.images));
	await page.getByRole('switch', { name: 'One item per photo' }).uncheck();
	await expect(page.getByText('1 item · 2 photos', { exact: true })).toBeVisible();
});

test('explicit reanalysis keeps review-added photos without merging manual fields', async ({
	page,
	api,
}) => {
	let calls = 0;
	api.on('POST', '/api/tools/vision/detect', () => {
		calls++;
		return json({ items: [{ name: 'Part', quantity: 1 }] });
	});
	await selectLocation(page);
	await uploadSyntheticPhoto(page);
	await analyzePhotos(page);
	await page.getByLabel('Name', { exact: true }).fill('Manual field');
	const data = await page.evaluate(() => {
		const c = document.createElement('canvas');
		c.width = 30;
		c.height = 30;
		c.getContext('2d')!.fillRect(0, 0, 30, 30);
		return c.toDataURL().split(',')[1];
	});
	await page
		.locator('input[type="file"]')
		.first()
		.setInputFiles({
			name: 'new-label.png',
			mimeType: 'image/png',
			buffer: Buffer.from(data, 'base64'),
		});
	await page.getByRole('link', { name: 'Back to Capture', exact: true }).click();
	await page
		.getByRole('button', { name: 'Change photos or analysis options', exact: true })
		.click();
	await page.getByRole('button', { name: 'Discard results and edit inputs', exact: true }).click();
	await expect(page.getByText('1 item · 2 photos', { exact: true })).toBeVisible();
	expect(calls).toBe(1);
	await page.getByRole('button', { name: 'Reanalyze with AI', exact: true }).click();
	await expect(page.getByLabel('Name', { exact: true })).toHaveValue('Part');
	expect(calls).toBe(2);
});

test('capture explains stored-photo quality separately from AI close-up input', async ({
	page,
}) => {
	await selectLocation(page);
	await page.getByText('Saved photo quality — not AI input', { exact: true }).click();
	await expect(page.getByText(/HBC_IMAGE_QUALITY changes stored Homebox photos/)).toBeVisible();
	await expect(page.getByText(/2048.*85/)).toBeVisible();
	await expect(page.getByText(/engraved numbers/)).toBeVisible();
});

test('grouping defaults off, regroups photos, resumes mode, and starts fresh off', async ({
	page,
}) => {
	await selectLocation(page);
	const mode = page.getByRole('switch', { name: 'One item per photo' });
	await expect(mode).not.toBeChecked();
	await uploadSyntheticPhoto(page);
	await uploadSyntheticPhoto(page);
	await uploadSyntheticPhoto(page);
	await expect(page.getByText('1 item · 3 photos', { exact: true })).toBeVisible();
	await mode.check();
	await expect(page.getByText('3 items · 3 photos', { exact: true })).toBeVisible();
	await expect
		.poll(async () => (await readDrafts(page, 'deployment:user:g1'))[0]?.oneItemPerPhoto)
		.toBe(true);
	await page.reload();
	await page.getByRole('button', { name: 'Resume Session', exact: true }).click();
	await expect(mode).toBeChecked();
	await mode.uncheck();
	await expect(page.getByText('1 item · 3 photos', { exact: true })).toBeVisible();
	await mode.check();
	await page.getByRole('button', { name: 'Discard entire draft', exact: true }).click();
	await page.getByRole('button', { name: 'Cancel', exact: true }).click();
	await expect(mode).toBeChecked();
	await page.getByRole('button', { name: 'Discard entire draft', exact: true }).click();
	await page.getByRole('button', { name: 'Discard draft', exact: true }).click();
	await selectLocation(page);
	await expect(mode).not.toBeChecked();
});

test('reached steps preserve drafts and summary edits retain their original row order', async ({
	page,
	api,
}) => {
	let calls = 0;
	api.on('POST', '/api/tools/vision/detect', () => {
		calls++;
		return json({ items: [{ name: 'Part', quantity: 1 }] });
	});
	await selectLocation(page);
	await page.getByRole('switch', { name: 'One item per photo' }).check();
	await uploadSyntheticPhoto(page);
	await uploadSyntheticPhoto(page);
	await analyzePhotos(page);
	await page.getByLabel('Name', { exact: true }).fill('First');
	await page.getByRole('button', { name: 'Confirm', exact: true }).click();
	await page.getByLabel('Name', { exact: true }).fill('Second');
	await page.getByRole('button', { name: 'Confirm', exact: true }).click();
	await page.getByRole('button', { name: 'Edit item', exact: true }).first().click();
	await page.getByLabel('Name', { exact: true }).fill('First edited');
	await page.getByRole('button', { name: 'Step 2: Capture', exact: true }).click();
	await page.getByRole('button', { name: 'Return to Review', exact: true }).click();
	await expect(page.getByLabel('Name', { exact: true })).toHaveValue('First edited');
	await page.getByRole('button', { name: 'Step 4: Summary', exact: true }).click();
	await page.getByRole('button', { name: 'Step 3: Review', exact: true }).click();
	await expect(page.getByLabel('Name', { exact: true })).toHaveValue('First edited');
	await page.getByRole('button', { name: 'Confirm', exact: true }).click();
	await expect(page.locator('main h3')).toHaveText(['First edited', 'Second']);
	await page.getByRole('button', { name: 'Back to Capture', exact: true }).click();
	await page.getByRole('button', { name: 'Return to Summary', exact: true }).click();
	await page.getByRole('button', { name: 'Step 1: Location', exact: true }).click();
	await expect(page).toHaveURL(/\/location$/);
	await page.getByRole('button', { name: 'Step 2: Capture', exact: true }).click();
	await page.getByRole('button', { name: 'Return to Summary', exact: true }).click();
	await expect(page.locator('main h3')).toHaveText(['First edited', 'Second']);
	expect(calls).toBe(2);
	expect(
		api.requests.filter(
			(request) =>
				request.method() === 'DELETE' ||
				(request.method() === 'POST' && new URL(request.url()).pathname === '/api/items')
		)
	).toHaveLength(0);
});

test('in-flight and uncertain writes cannot navigate backwards to re-create items', async ({
	page,
	api,
}) => {
	let posts = 0;
	const gate = api.gate();
	api.on('POST', '/api/tools/vision/detect', () =>
		json({ items: [{ name: 'Part', quantity: 1 }] })
	);
	api.on('POST', '/api/items', async () => {
		posts++;
		await gate.promise;
		return json(
			{
				created: [],
				errors: ['Write uncertain; reconcile in Homebox'],
				outcomes: [{ index: 0, status: 'unknown_write' }],
			},
			207
		);
	});
	await selectLocation(page);
	await uploadSyntheticPhoto(page);
	await analyzePhotos(page);
	await page.getByRole('button', { name: 'Confirm', exact: true }).click();
	await page.getByRole('button', { name: /Submit All Items/ }).click();
	await expect.poll(() => posts).toBe(1);
	await page.evaluate(() => history.back());
	await expect(page).toHaveURL(/\/summary$/);
	await expect(page.getByRole('button', { name: 'Step 2: Capture', exact: true })).toBeDisabled();
	gate.release();
	await expect(page.getByText(/Creation is unconfirmed/)).toBeVisible();
	await page.evaluate(() => history.back());
	await expect(page).toHaveURL(/\/success$/);
	await page.goto('/capture');
	await page.getByRole('button', { name: 'Resume Session', exact: true }).click();
	await expect(page.getByRole('button', { name: /Submit All Items/ })).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Undo removal', exact: true })).toHaveCount(0);
	expect(posts).toBe(1);
});

test('removing even the last draft stays in summary; undo restores exact fields, photos and order after reload', async ({
	page,
	api,
}) => {
	api.on('POST', '/api/tools/vision/detect', () =>
		json({ items: [{ name: 'Synthetic part', quantity: 1, custom_fields: { Code: '0007' } }] })
	);
	await selectLocation(page);
	await page.getByRole('switch', { name: 'One item per photo' }).check();
	await uploadSyntheticPhoto(page);
	await uploadSyntheticPhoto(page);
	await analyzePhotos(page);
	await page.getByLabel('Name', { exact: true }).fill('First manual');
	await page.getByRole('button', { name: 'Confirm', exact: true }).click();
	await page.getByLabel('Name', { exact: true }).fill('Second manual');
	await page.getByRole('button', { name: 'Confirm', exact: true }).click();
	await expect(page).toHaveURL(/\/summary$/);
	const before = (await readDrafts(page, 'deployment:user:g1'))[0];
	await page.getByRole('button', { name: 'Remove item', exact: true }).first().click();
	await page.getByRole('button', { name: 'Remove item', exact: true }).click();
	await expect(page).toHaveURL(/\/summary$/);
	await expect(page.getByText('No draft items remain.', { exact: true })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Add photos', exact: true })).toBeVisible();
	await expect
		.poll(
			async () =>
				((await readDrafts(page, 'deployment:user:g1'))[0]?.removedItems as unknown[])?.length
		)
		.toBe(2);
	await page.reload();
	await page.getByRole('button', { name: 'Resume Session', exact: true }).click();
	await page.getByRole('button', { name: 'Undo removal', exact: true }).click();
	await page.getByRole('button', { name: 'Undo removal', exact: true }).click();
	await expect
		.poll(async () => (await readDrafts(page, 'deployment:user:g1'))[0]?.confirmedItems)
		.toEqual(before.confirmedItems);
	await expect(
		page.getByRole('button', { name: 'Research product data', exact: true })
	).toHaveCount(2);
	api.on('GET', '/api/research/capabilities', () => json({ enabled: false }));
	for (const [index, name] of ['First manual', 'Second manual'].entries()) {
		await page
			.getByRole('button', { name: 'Research product data', exact: true })
			.nth(index)
			.click();
		await expect(page).toHaveURL(/\/review#product-research$/);
		await expect(page.getByLabel('Name', { exact: true })).toHaveValue(name);
		await expect(
			page.getByRole('button', { name: 'Research this item', exact: true })
		).toBeVisible();
		await expect(page.getByLabel('Exact part/model number')).toHaveCount(0);
		await page.getByRole('button', { name: 'Confirm', exact: true }).click();
	}
	expect(
		api.requests.filter(
			(request) => request.method() === 'POST' && request.url().includes('/research/')
		)
	).toHaveLength(0);
});

test('visible Back retains manual review; confirmed input invalidation needs explicit reanalysis', async ({
	page,
	api,
}) => {
	let requests = 0;
	api.on('POST', '/api/tools/vision/detect', () => {
		requests++;
		return json({
			items: [{ name: 'Synthetic part', quantity: 1, custom_fields: { Code: '0007' } }],
		});
	});
	await selectLocation(page);
	await uploadSyntheticPhoto(page);
	await uploadSyntheticPhoto(page);
	await analyzePhotos(page);
	await page.getByLabel('Name', { exact: true }).fill('Manual retained');
	await page.getByRole('link', { name: 'Back to Capture', exact: true }).click();
	await page.getByRole('button', { name: 'Return to Review', exact: true }).click();
	await expect(page.getByLabel('Name', { exact: true })).toHaveValue('Manual retained');
	expect(requests).toBe(1);
	await page.getByRole('link', { name: 'Back to Capture', exact: true }).click();
	await page
		.getByRole('button', { name: 'Change photos or analysis options', exact: true })
		.click();
	await page.getByRole('button', { name: 'Cancel', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Return to Review', exact: true })).toBeVisible();
	await page
		.getByRole('button', { name: 'Change photos or analysis options', exact: true })
		.click();
	await page.getByRole('button', { name: 'Discard results and edit inputs', exact: true }).click();
	await expect(page.getByText(/Analysis is stale/)).toBeVisible();
	await page.getByRole('switch', { name: 'One item per photo' }).check();
	expect(requests).toBe(1);
	await page.getByRole('button', { name: 'Reanalyze with AI', exact: true }).click();
	await expect(page).toHaveURL(/\/review$/);
	expect(requests).toBe(3);
});
