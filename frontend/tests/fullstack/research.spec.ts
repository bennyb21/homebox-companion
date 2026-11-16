import { test, expect } from '@playwright/test';

test('synthetic research adoption reaches isolated Homebox', async ({ page }) => {
	test.skip(process.env.HBC_RESEARCH_SMOKE !== '1', 'Separate research acceptance harness');
	await page.goto('/research');
	await page
		.getByRole('combobox', { name: 'Saved item', exact: true })
		.selectOption(process.env.HBC_RESEARCH_ITEM!);
	await expect(page.getByLabel('Exact part/model number')).toHaveCount(0);
	await expect(
		page.getByText('OpenAI research · API costs may apply', { exact: true })
	).toBeVisible();
	await page.getByText('OpenAI research · API costs may apply', { exact: true }).click();
	await expect(
		page.getByText(/Product information and associated photos are sent to OpenAI/)
	).toBeVisible();
	await page.getByRole('button', { name: 'Research this item', exact: true }).click();
	await expect(async () => {
		await page.getByRole('button', { name: 'Refresh jobs' }).click();
		await expect(
			page.getByText('Research ready. Compare sources and choose which fields to adopt.', {
				exact: true,
			})
		).toBeVisible();
	}).toPass();
	await expect(page.getByRole('link', { name: 'Synthetic source', exact: true })).toBeVisible();
	await page.getByLabel('Adopt Specifications').check();
	await page.getByRole('button', { name: 'Apply selected to Homebox' }).click();
	await expect(page.getByText('Applied', { exact: true })).toBeVisible();
});
