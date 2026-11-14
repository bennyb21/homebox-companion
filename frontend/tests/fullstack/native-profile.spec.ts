import { test, expect } from '@playwright/test';
import { analyzePhotos, confirmItems, selectLocation, submitItems } from '../browser/helpers/scan';
import { uploadSyntheticPhoto } from './synthetic-photo';

test('stores a manually chosen native text profile', async ({ page }) => {
	test.skip(process.env.HBC_NATIVE_SMOKE !== '1', 'Native profile scenario only');
	await selectLocation(page, 'Smoke storage');
	await uploadSyntheticPhoto(page);
	await page.getByRole('button', { name: 'Expand options', exact: true }).click();
	if (process.env.HBC_AUTO_SMOKE === '1') {
		await expect(page.getByRole('combobox', { name: 'Item type', exact: true })).toHaveValue(
			'__auto__'
		);
	} else
		await page
			.getByRole('combobox', { name: 'Item type', exact: true })
			.selectOption({ label: 'Synthetic spare part' });
	await analyzePhotos(page);
	await expect(page.getByRole('combobox', { name: 'Item type', exact: true })).toBeEnabled();
	const customFields = page.getByRole('button', { name: /Custom Fields/ });
	if ((await customFields.getAttribute('aria-expanded')) !== 'true') await customFields.click();
	await expect(page.getByLabel('Part number', { exact: true })).toHaveValue('0007-SYN-A');
	await expect(page.getByLabel('Condition', { exact: true })).toHaveValue('unknown');
	await expect(page.getByLabel('Operator note', { exact: true })).toHaveValue('Keep this');
	await page.getByLabel('Condition', { exact: true }).fill('manual condition');
	await page
		.getByRole('combobox', { name: 'Item type', exact: true })
		.selectOption({ label: 'Synthetic alternate' });
	await expect(page.getByLabel('New field', { exact: true })).toHaveValue('new value');
	await expect(page.getByLabel('Condition', { exact: true })).toHaveValue('manual condition');
	await expect(page.getByLabel('Part number', { exact: true })).toHaveValue('0007-SYN-A');
	await page.getByLabel('Name', { exact: true }).fill('Synthetic spare part reviewed');
	await expect(page.getByRole('status').filter({ hasText: /^Saved$/ })).toBeVisible();
	await page.reload();
	await page.getByRole('button', { name: 'Resume Session', exact: true }).click();
	await expect(page.getByLabel('Part number', { exact: true })).toHaveValue('0007-SYN-A');
	await page.screenshot({ path: 'test-results/native-profile-review.png', fullPage: true });
	await confirmItems(page, 1);
	await submitItems(page);
	await expect(page).toHaveURL(/\/success$/);
	await page.screenshot({ path: 'test-results/native-profile-success.png', fullPage: true });
});
