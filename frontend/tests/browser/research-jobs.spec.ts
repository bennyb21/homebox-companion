import { test, expect } from './fixtures/test';
import { json } from './fixtures/api';

test('saved-item research jobs show durable status and require selected adoption', async ({
	page,
	api,
}) => {
	await page.addInitScript(() => Object.defineProperty(crypto, 'randomUUID', { value: undefined }));
	let state = 'matched';
	const job = () => ({
		id: 'job1',
		item: 'item1',
		state,
		result: {
			research: {
				status: 'matched',
				sources: [{ url: 'https://example.com/spec', title: 'Synthetic source' }],
			},
			proposals: [
				{
					name: 'Specifications',
					current: '',
					value: 'Steel',
					evidence: 'Cited synthesis',
					source_urls: ['https://example.com/spec'],
				},
			],
		},
	});
	api.on('GET', '/api/items', () => json([{ id: 'item1', name: 'Synthetic part', quantity: 1 }]));
	api.on('GET', '/api/research/jobs', () => json([job()]));
	api.on('POST', '/api/research/jobs/job1/apply', (request) => {
		expect(request.postDataJSON()).toEqual({ selected: [0], edits: { '0': 'Reviewed steel' } });
		state = 'applied';
		return json({ state });
	});
	await page.goto('/research');
	await expect(page.getByText(/Research ready/)).toBeVisible();
	await expect(page.getByRole('button', { name: 'Apply selected to Homebox' })).toBeDisabled();
	await page.getByLabel('Specifications', { exact: true }).fill('Reviewed steel');
	await page.getByLabel('Adopt Specifications').check();
	await page.getByRole('button', { name: 'Apply selected to Homebox' }).click();
	await expect(page.getByText('Applied', { exact: true })).toBeVisible();
});
