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
		expect(r.postDataJSON().identity).toEqual({
			identifier_exact: 'AB-123',
			identifier_kind: 'part_number',
		});
		queued = true;
		return json({ id: 'job-1' });
	});
	await page.goto('/research');
	await expect(page.getByText(/inputs are sent to OpenAI/)).toBeVisible();
	await expect(page.getByRole('checkbox')).toHaveCount(0);
	expect(api.requests.filter((r) => r.method() === 'POST')).toHaveLength(0);
	await page.getByRole('combobox', { name: 'Saved item', exact: true }).selectOption('part-1');
	await page.getByLabel('Exact part/model number').fill('AB-123');
	await page.getByRole('button', { name: 'Queue research', exact: true }).click();
	await expect(page.getByText(/Research incomplete/)).toBeVisible();
	await expect(page.getByText('response_incomplete', { exact: true })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Apply selected to Homebox' })).toHaveCount(0);
	expect(api.requests.filter((r) => r.method() === 'POST')).toHaveLength(1);
});
