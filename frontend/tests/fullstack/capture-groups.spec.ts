import { test, expect } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { selectLocation, analyzePhotos, confirmItems, submitItems } from '../browser/helpers/scan';

test('native grouped capture persists every synthetic view exactly once', async ({ page }) => {
	test.skip(process.env.HBC_GROUP_SMOKE !== '1', 'Grouped native acceptance only');
	const perPhoto = process.env.HBC_PER_PHOTO === '1';
	const count = perPhoto ? 2 : 3;
	const artifacts = process.env.HBC_SMOKE_ARTIFACT_DIR!;
	await mkdir(artifacts, { recursive: true });
	await selectLocation(page, 'Group smoke storage');
	await expect(page.getByRole('switch', { name: 'One item per photo' })).not.toBeChecked();
	if (perPhoto) await page.getByRole('switch', { name: 'One item per photo' }).check();
	const files = [];
	for (let i = 0; i < count; i++) {
		const data = await page.evaluate((index) => {
			const canvas = document.createElement('canvas');
			canvas.width = 3072;
			canvas.height = 1536;
			const ctx = canvas.getContext('2d')!;
			ctx.fillStyle = ['#ddddee', '#eedddd', '#ddeedd'][index];
			ctx.fillRect(0, 0, 3072, 1536);
			ctx.fillStyle = '#000000';
			ctx.font = '100px sans-serif';
			ctx.fillText(`SYNTHETIC VIEW ${index} — 0007`, 100, 500);
			return canvas.toDataURL('image/png').split(',')[1];
		}, i);
		const buffer = Buffer.from(data, 'base64');
		await writeFile(join(artifacts, `source-${i}.png`), buffer);
		files.push({ name: `view-${i}.png`, mimeType: 'image/png', buffer });
	}
	await page.locator('input[type="file"]').first().setInputFiles(files.slice(0, 2));
	await expect(
		page.getByText(`${perPhoto ? 2 : 1} ${perPhoto ? 'items' : 'item'} · 2 photos`, { exact: true })
	).toBeVisible();
	for (let i = 0; i < (perPhoto ? 2 : 1); i++) {
		await page.getByRole('button', { name: 'Expand options', exact: true }).nth(i).click();
		await page
			.getByRole('combobox', { name: 'Item type', exact: true })
			.selectOption({ label: 'Group native part' });
		if (!perPhoto) {
			// A later additional photo must join both the provider request and saved attachments.
			await page.locator('input[type="file"]').first().setInputFiles(files[2]);
		}
		await page.getByRole('button', { name: 'Collapse options', exact: true }).click();
	}
	await analyzePhotos(page);
	await page.getByLabel('Name', { exact: true }).fill('Group reviewed 0');
	await page.getByRole('link', { name: 'Back to Capture', exact: true }).click();
	await page.getByRole('button', { name: 'Return to Review', exact: true }).click();
	await expect(page.getByLabel('Name', { exact: true })).toHaveValue('Group reviewed 0');
	if (perPhoto) {
		await page.getByRole('button', { name: 'Confirm', exact: true }).click();
		await page.getByLabel('Name', { exact: true }).fill('Group reviewed 1');
	}
	await confirmItems(page, 1);
	await page.getByRole('button', { name: 'Remove item', exact: true }).first().click();
	await page.getByRole('button', { name: 'Undo removal', exact: true }).click();
	await page.getByRole('button', { name: 'Back to Capture', exact: true }).click();
	await page.getByRole('button', { name: 'Return to Summary', exact: true }).click();
	await page.screenshot({ path: join(artifacts, 'summary.png'), fullPage: true });
	await submitItems(page);
	await expect(page).toHaveURL(/\/success$/);
	await page.screenshot({ path: join(artifacts, 'success.png'), fullPage: true });
});
