import { test, expect } from './fixtures/test';
import { json } from './fixtures/api';

test('saved-item research omits attestation and shows incomplete diagnostic without automatic work', async ({
	page,
	api,
}) => {
	let queued = false;
	api.on('GET', '/api/items', () => json([{ id: 'part-1', name: 'Synthetic part' }]));
	api.on('GET', '/api/research/jobs', () =>
		json(
			queued
				? [
						{
							id: 'job-1',
							item: 'part-1',
							state: 'failed',
							result: {
								research: {
									status: 'failed',
									sources: [],
									diagnostic: {
										code: 'response_incomplete',
										stage: 'response',
										message: 'Output budget reached.',
									},
								},
								proposals: [],
							},
						},
					]
				: []
		)
	);
	api.on('POST', '/api/research/jobs', (r) => {
		expect(r.postDataJSON()).toEqual({ item_id: 'part-1', idempotency_key: expect.any(String) });
		queued = true;
		return json({ id: 'job-1' });
	});
	await page.goto('/research');
	await expect(page.getByText(/OpenAI research · API costs may apply/)).toBeVisible();
	await expect(page.getByRole('checkbox')).toHaveCount(0);
	expect(api.requests.filter((r) => r.method() === 'POST')).toHaveLength(0);
	await page.getByRole('combobox', { name: 'Saved item', exact: true }).selectOption('part-1');
	await expect(page.getByLabel('Exact part/model number')).toHaveCount(0);
	await page.getByRole('button', { name: 'Research this item', exact: true }).click();
	await expect(page.getByText(/Research incomplete/)).toBeVisible();
	await expect(page.getByText('response_incomplete', { exact: true })).not.toBeVisible();
	await page.getByText('Diagnostic details', { exact: true }).click();
	await expect(page.getByText('response_incomplete', { exact: true })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Apply selected to Homebox' })).toHaveCount(0);
	expect(api.requests.filter((r) => r.method() === 'POST')).toHaveLength(1);
});
