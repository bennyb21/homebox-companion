import { expect, test } from './fixtures/test';
import { json } from './fixtures/api';
import { selectLocation, analyzePhotos } from './helpers/scan';
import { readDrafts } from './helpers/recovery';
import { uploadSyntheticPhoto } from '../fullstack/synthetic-photo';

for (const bulk of [false, true]) {
	test(`focused middle-row ${bulk ? 'long-press Confirm All' : 'Confirm'} retains edits, photos and identity through reload and undo`, async ({
		page,
		api,
	}) => {
		let detections = 0;
		api.on('POST', '/api/tools/vision/detect', () => {
			detections++;
			return json({
				items: [{ name: 'Original laptop', quantity: 1, custom_fields: { Code: '0007' } }],
			});
		});
		await selectLocation(page);
		await page.getByRole('switch', { name: 'One item per photo' }).check();
		for (let i = 0; i < 3; i++) await uploadSyntheticPhoto(page);
		await analyzePhotos(page);
		for (const name of ['First laptop', 'Original laptop', 'Last laptop']) {
			await expect(page.getByLabel('Name', { exact: true })).toBeVisible();
			await page.getByLabel('Name', { exact: true }).fill(name);
			await page.getByRole('button', { name: 'Confirm', exact: true }).click();
		}
		await expect(page).toHaveURL(/\/summary$/);
		const before = (await readDrafts(page, 'deployment:user:g1'))[0].confirmedItems as Record<
			string,
			unknown
		>[];
		await page.getByRole('button', { name: 'Edit item', exact: true }).nth(1).click();
		await expect(page.getByLabel('Name', { exact: true })).toBeVisible();
		await page.getByLabel('Name', { exact: true }).fill('Manual corrected laptop');
		const fields = page.getByRole('button', { name: /Custom Fields/ });
		if ((await fields.getAttribute('aria-expanded')) !== 'true') await fields.click();
		await page.getByLabel('Code', { exact: true }).fill('0007-MANUAL');
		const button = page.getByRole('button', { name: 'Confirm', exact: true });
		if (bulk) {
			await button.focus();
			await button.hover();
			await page.mouse.down();
			try {
				await expect(page.getByRole('button', { name: 'Confirm All', exact: true })).toBeVisible();
				await page.getByRole('button', { name: 'Confirm All', exact: true }).click();
			} finally {
				await page.mouse.up();
			}
		} else await button.click();
		await expect(page).toHaveURL(/\/summary$/);
		await expect(page.locator('main h3')).toHaveText([
			'First laptop',
			'Manual corrected laptop',
			'Last laptop',
		]);
		const expected = before.map((item, index) =>
			index === 1
				? {
						...item,
						name: 'Manual corrected laptop',
						custom_fields: { Code: '0007-MANUAL' },
					}
				: item
		);
		await expect
			.poll(async () => (await readDrafts(page, 'deployment:user:g1'))[0]?.confirmedItems)
			.toEqual(expected);
		await page.reload();
		await page.getByRole('button', { name: 'Resume Session', exact: true }).click();
		await page.getByRole('button', { name: 'Remove item', exact: true }).nth(1).click();
		await page.reload();
		await page.getByRole('button', { name: 'Resume Session', exact: true }).click();
		await page.getByRole('button', { name: 'Undo removal', exact: true }).click();
		await expect
			.poll(async () => (await readDrafts(page, 'deployment:user:g1'))[0]?.confirmedItems)
			.toEqual(expected);
		expect(detections).toBe(3);
		expect(
			api.requests.filter(
				(request) =>
					request.method() === 'DELETE' ||
					(request.method() === 'POST' && !request.url().includes('/vision/detect'))
			)
		).toHaveLength(0);
	});
}
