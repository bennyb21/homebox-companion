import { test, expect } from './fixtures/test';
import { json } from './fixtures/api';
import { detectedItems } from './fixtures/data';
import { selectLocation, analyzePhotos } from './helpers/scan';
import { uploadSyntheticPhoto } from '../fullstack/synthetic-photo';

test('whole-item explicit research sends photos and supports edited selective adoption', async ({
	page,
	api,
}) => {
	const calls: Record<string, any>[] = [];
	api.on('POST', '/api/tools/vision/detect', () =>
		json({
			...detectedItems(['Spacer']),
			items: detectedItems(['Spacer']).items.map((item) => ({
				...item,
				entity_type_id: '00000000-0000-4000-8000-000000000010',
				template_id: '00000000-0000-4000-8000-000000000020',
				model_number: '0112-S90-6-10-032-N-B',
				custom_fields: { Specifications: '', Material: 'Aluminum', Account: 'private' },
			})),
		})
	);
	api.on('GET', '/api/research/capabilities', () => json({ enabled: true }));
	api.on('POST', '/api/research/lookups', (req) => {
		calls.push(req.postDataJSON());
		return json({
			id: 'review-1',
			result: {
				status: 'matched',
				ambiguity: 'Observed prefix differs; review the proposed correction.',
				sources: [{ url: 'https://example.com/product', title: 'Provider citation' }],
			},
			proposals: [
				{
					name: 'Specifications',
					current: '',
					value: '10 mm',
					source_urls: [],
					evidence: 'AI suggestion; not independently verified.',
				},
			],
		});
	});
	api.on('POST', '/api/research/lookups/review-1/apply', (req) => {
		const body = req.postDataJSON();
		return json({ patch: { Specifications: body.edits['0'] }, item_patch: {} });
	});
	await selectLocation(page);
	await uploadSyntheticPhoto(page);
	await analyzePhotos(page);
	await expect(page.getByRole('button', { name: 'Research this item', exact: true })).toBeVisible();
	expect(calls).toHaveLength(0);
	await expect(page.getByLabel('Exact part/model number', { exact: true })).toHaveCount(0);
	await page.getByRole('button', { name: 'Research this item', exact: true }).click();
	await expect(
		page.locator('#product-research').getByLabel('Specifications', { exact: true })
	).toHaveValue('10 mm');
	expect(calls).toHaveLength(1);
	expect(calls[0].context.model_number).toBe('0112-S90-6-10-032-N-B');
	expect(calls[0].context.images[0]).toMatch(/^data:image\//);
	await expect(
		page.getByText('Observed prefix differs; review the proposed correction.')
	).toBeVisible();
	await expect(page.getByRole('link', { name: 'Provider citation', exact: true })).toHaveAttribute(
		'href',
		'https://example.com/product'
	);
	await page
		.locator('#product-research')
		.getByLabel('Specifications', { exact: true })
		.fill('Reviewed 10 mm');
	await page.getByLabel('Adopt Specifications', { exact: true }).check();
	await page.getByRole('button', { name: 'Adopt selected fields', exact: true }).click();
	await expect(page.locator('#review-cf-Specifications')).toHaveValue('Reviewed 10 mm');
	expect(calls).toHaveLength(1);
	await page.getByRole('button', { name: 'Research this item', exact: true }).click();
	await expect(
		page.locator('#product-research').getByLabel('Specifications', { exact: true })
	).toBeVisible();
	await page.getByRole('button', { name: 'Discard suggestions', exact: true }).click();
	await expect(
		page.locator('#product-research').getByLabel('Specifications', { exact: true })
	).toHaveCount(0);
	await expect(page.locator('#review-cf-Specifications')).toHaveValue('Reviewed 10 mm');
	expect(
		api.requests.filter(
			(r) => ['POST', 'PUT', 'PATCH'].includes(r.method()) && /\/api\/items/.test(r.url())
		)
	).toHaveLength(0);
});

test('saved item research has no targeted number form and only queues on click', async ({
	page,
	api,
}) => {
	const queued: unknown[] = [];
	api.on('GET', '/api/items', () => json([{ id: 'item1', name: 'Saved spacer' }]));
	api.on('GET', '/api/research/jobs', () => json([]));
	api.on('POST', '/api/research/jobs', (req) => {
		queued.push(req.postDataJSON());
		return json({ id: 'new', state: 'queued' });
	});
	await page.goto('/research');
	await expect(page.getByRole('combobox', { name: 'Saved item', exact: true })).toBeVisible();
	await expect(page.getByLabel('Exact part/model number', { exact: true })).toHaveCount(0);
	const choice = await page
		.getByRole('combobox', { name: 'Saved item', exact: true })
		.locator('option')
		.nth(1)
		.getAttribute('value');
	await page.getByRole('combobox', { name: 'Saved item', exact: true }).selectOption(choice!);
	expect(queued).toHaveLength(0);
	await page.getByRole('button', { name: 'Research this item', exact: true }).click();
	await expect.poll(() => queued.length).toBe(1);
	expect(queued[0]).toMatchObject({ item_id: choice });
	expect(queued[0]).not.toHaveProperty('identity');
});
