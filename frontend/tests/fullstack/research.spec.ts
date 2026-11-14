import { test, expect } from '@playwright/test';

test('synthetic research adoption reaches isolated Homebox', async ({ page }) => {
	test.skip(process.env.HBC_RESEARCH_SMOKE !== '1', 'Separate research acceptance harness');
	await page.goto('/research');
	await page
		.getByRole('combobox', { name: 'Saved item', exact: true })
		.selectOption(process.env.HBC_RESEARCH_ITEM!);
	await page.getByLabel('Exact part/model number').fill('AB-123-x');
	await page
		.getByLabel(
			'I confirm this public part/model number (not serial) and authorize one paid research attempt'
		)
		.check();
	await page.getByRole('button', { name: 'Queue research', exact: true }).click();
	await expect(async () => {
		await page.getByRole('button', { name: 'Refresh jobs' }).click();
		await expect(page.getByText('matched', { exact: true })).toBeVisible();
	}).toPass();
	await expect(page.getByRole('link', { name: 'Synthetic source', exact: true })).toBeVisible();
	await page.getByLabel('Adopt Specifications').check();
	await page.getByRole('button', { name: 'Apply selected to Homebox' }).click();
	await expect(page.getByText('applied', { exact: true })).toBeVisible();
});
