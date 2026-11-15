import { test, expect } from './fixtures/test';
import { json } from './fixtures/api';
import { detectedItems } from './fixtures/data';
import { selectLocation, analyzePhotos, confirmItems } from './helpers/scan';
import { uploadSyntheticPhoto as uploadPhoto } from '../fullstack/synthetic-photo';

test('summary opens research for the selected draft without a paid request', async ({
	page,
	api,
}) => {
	api.on('POST', '/api/tools/vision/detect', () =>
		json(detectedItems(['First part', 'Second part']))
	);
	api.on('GET', '/api/research/capabilities', () => json({ enabled: false }));
	await selectLocation(page);
	await uploadPhoto(page);
	await analyzePhotos(page);
	await page.getByLabel('Name', { exact: true }).fill('Manual first part');
	await confirmItems(page, 2);
	await expect(
		page.getByRole('button', { name: 'Research product data', exact: true })
	).toHaveCount(2);
	await page.getByRole('button', { name: 'Research product data', exact: true }).first().click();
	await expect(page).toHaveURL(/\/review#product-research$/);
	await expect(page.getByLabel('Name', { exact: true })).toHaveValue('Manual first part');
	await expect(page.getByLabel('Exact part/model number')).toBeVisible();
	await expect(page.getByRole('link', { name: 'Research settings' })).toHaveAttribute(
		'href',
		'/settings#product-research'
	);
	await expect(
		page.getByRole('button', { name: 'Research this product', exact: true })
	).toBeDisabled();
	expect(
		api.requests.filter(
			(request) => request.method() === 'POST' && request.url().includes('/research/')
		)
	).toHaveLength(0);
	await page.getByRole('button', { name: 'Confirm', exact: true }).click();
	await expect(page).toHaveURL(/\/summary$/);
	await expect(page.getByRole('heading', { name: 'Manual first part', exact: true })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Second part', exact: true })).toBeVisible();
});

test('optional part-number-only research requires explicit field adoption', async ({
	page,
	api,
}) => {
	await page.addInitScript(() => Object.defineProperty(crypto, 'randomUUID', { value: undefined }));
	api.on('POST', '/api/tools/vision/detect', () =>
		json({
			...detectedItems(['Part']),
			items: detectedItems(['Part']).items.map((item) => ({
				...item,
				entity_type_id: 'native-type',
				template_id: 'native-template',
				custom_fields: { 'Part number': 'AB-123', Specifications: '' },
			})),
		})
	);
	api.on('GET', '/api/research/capabilities', () => json({ enabled: true }));
	api.on('POST', '/api/research/lookups', (request) => {
		expect(request.postDataJSON().identity).toMatchObject({
			identifier_exact: 'AB-123',
			identifier_kind: 'part_number',
			identity_confirmed: true,
		});
		expect(request.postDataJSON().identity.manufacturer).toBeUndefined();
		return json({
			id: 'lookup-1',
			result: {
				status: 'matched',
				sources: [{ url: 'https://example.com/spec', title: 'Synthetic source' }],
			},
			proposals: [
				{
					name: 'Specifications',
					current: '',
					value: 'Steel',
					source_urls: ['https://example.com/spec'],
					evidence: 'Cited model synthesis',
				},
			],
		});
	});
	api.on('POST', '/api/research/lookups/lookup-1/apply', (request) => {
		expect(request.postDataJSON().selected).toEqual([0]);
		return json({ patch: { Specifications: 'Steel' } });
	});
	await selectLocation(page);
	await uploadPhoto(page);
	await analyzePhotos(page);
	await page.getByRole('button', { name: 'Research product data', exact: true }).click();
	await expect(page.getByLabel('Exact part/model number')).toHaveValue('AB-123');
	await page
		.getByLabel('I confirm this is a public part/model number, not a serial number')
		.check();
	await page.getByRole('button', { name: 'Research this product', exact: true }).click();
	await expect(page.getByRole('link', { name: 'Synthetic source' })).toHaveAttribute(
		'href',
		'https://example.com/spec'
	);
	await expect(
		page.getByRole('button', { name: 'Adopt selected fields', exact: true })
	).toBeDisabled();
	await page.getByLabel('Adopt Specifications').check();
	await page.getByRole('button', { name: 'Adopt selected fields', exact: true }).click();
	await expect(page.getByLabel('Specifications', { exact: true })).toHaveValue('Steel');
	await expect(page.getByRole('button', { name: 'Confirm', exact: true })).toBeEnabled();
});
