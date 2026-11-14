import { test, expect } from './fixtures/test';
import { json } from './fixtures/api';
import { detectedItems } from './fixtures/data';
import { selectLocation, uploadPhoto, analyzePhotos } from './helpers/scan';

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
	await page.getByRole('button', { name: 'Product research', exact: true }).click();
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
