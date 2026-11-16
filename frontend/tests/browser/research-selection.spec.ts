import { test, expect } from './fixtures/test';
import { json } from './fixtures/api';
import { detectedItems } from './fixtures/data';
import { uploadSyntheticPhoto } from '../fullstack/synthetic-photo';

for (const locale of ['en-US', 'de-DE']) {
	test.describe(locale, () => {
		test.use({ locale });
		for (const mode of ['draft', 'saved']) {
			test(`${mode} select all preserves edits and only applies explicitly`, async ({
				page,
				api,
			}) => {
				const de = locale === 'de-DE';
				const proposals = [
					{ name: 'Teilenummer', current: 'P-1', value: 'P-1', source_urls: [], evidence: '' },
					{
						name: 'Manufacturer',
						target: 'manufacturer',
						current: '',
						value: 'Example Maker',
						source_urls: [],
						evidence: '',
					},
					{
						name: 'Description',
						target: 'description',
						current: 'Old text',
						value: 'Technical description',
						source_urls: [],
						evidence: '',
					},
				];
				const result = { status: 'matched', sources: [], ambiguity: '' };
				let applied = false;
				let releaseApply!: () => void;
				const applyGate = new Promise<void>((resolve) => (releaseApply = resolve));
				const appliedBodies: unknown[] = [];
				const applyPath =
					mode === 'draft'
						? '/api/research/lookups/select-all/apply'
						: '/api/research/jobs/select-all/apply';
				api.on('POST', applyPath, async (request) => {
					appliedBodies.push(request.postDataJSON());
					await applyGate;
					applied = true;
					return json(
						mode === 'draft'
							? {
									patch: { Teilenummer: 'P-1' },
									item_patch: {
										manufacturer: 'Example Maker',
										description: 'Manually edited description',
									},
								}
							: { state: 'applied' }
					);
				});
				if (mode === 'saved') {
					api.on('GET', '/api/items', () => json([{ id: 'item1', name: 'Synthetic item' }]));
					api.on('GET', '/api/research/jobs', () =>
						json([
							{
								id: 'select-all',
								item: 'item1',
								state: applied ? 'applied' : 'matched',
								result: { research: result, proposals },
							},
						])
					);
					await page.goto('/research');
				} else {
					api.on('GET', '/api/research/capabilities', () => json({ enabled: true }));
					api.on('POST', '/api/tools/vision/detect', () =>
						json({
							...detectedItems(['Synthetic item']),
							items: detectedItems(['Synthetic item']).items.map((item) => ({
								...item,
								entity_type_id: '00000000-0000-4000-8000-000000000010',
								template_id: '00000000-0000-4000-8000-000000000020',
							})),
						})
					);
					api.on('POST', '/api/research/lookups', () =>
						json({ id: 'select-all', result, proposals })
					);
					await page.goto('/location');
					await page.getByRole('button', { name: /Storage/ }).click();
					await page
						.getByRole('button', {
							name: de ? 'Aktuellen Standort wählen' : 'Select current location',
						})
						.click();
					await page
						.getByRole('button', { name: de ? 'Weiter zur Erfassung' : 'Continue to Capture' })
						.click();
					await uploadSyntheticPhoto(page);
					await page
						.getByRole('button', {
							name: de ? 'Mit KI analysieren' : 'Analyze with AI',
							exact: true,
						})
						.click();
					await page
						.getByRole('button', {
							name: de ? 'Diesen Gegenstand recherchieren' : 'Research this item',
							exact: true,
						})
						.click();
				}
				const panel =
					mode === 'draft'
						? page.locator('#product-research')
						: page.locator('section').filter({
								has: page.getByRole('heading', { name: 'Synthetic item', exact: true }),
							});
				const master = panel.getByRole('checkbox', {
					name: de ? 'Alles auswählen' : 'Select all',
					exact: true,
				});
				await expect(master).toBeVisible();
				await expect(master).not.toBeChecked();
				await expect(panel.locator('[data-proposal-index="0"]')).not.toBeVisible();
				const writes = () => api.requests.filter((request) => request.method() !== 'GET').length;
				const before = writes();
				await master.check();
				for (const index of [0, 1, 2])
					await expect(
						panel.locator(`[data-proposal-index="${index}"] input[type="checkbox"]`)
					).toBeChecked();
				await expect(panel.locator('[data-proposal-index="0"]')).not.toBeVisible();
				await master.uncheck();
				for (const index of [0, 1, 2])
					await expect(
						panel.locator(`[data-proposal-index="${index}"] input[type="checkbox"]`)
					).not.toBeChecked();
				await panel.locator('[data-proposal-index="1"] input[type="checkbox"]').check();
				await expect(master).toHaveJSProperty('indeterminate', true);
				await master.click();
				await expect(master).toBeChecked();
				await expect(master).toHaveJSProperty('indeterminate', false);
				await panel
					.getByLabel(de ? 'Beschreibung' : 'Description', { exact: true })
					.fill('Manually edited description');
				await panel.locator('[data-proposal-index="1"] input[type="checkbox"]').uncheck();
				await expect(master).toHaveJSProperty('indeterminate', true);
				await master.click();
				expect(writes()).toBe(before);
				expect(appliedBodies).toEqual([]);
				await page.setViewportSize({ width: 390, height: 900 });
				await panel.screenshot({
					path: test.info().outputPath(`select-all-${mode}-${locale}.png`),
				});
				const button =
					mode === 'draft'
						? de
							? 'Ausgewählte Felder übernehmen'
							: 'Adopt selected fields'
						: de
							? 'Auswahl in Homebox übernehmen'
							: 'Apply selected to Homebox';
				await panel.getByRole('button', { name: button, exact: true }).click();
				await expect(master).toBeDisabled();
				await expect.poll(() => appliedBodies.length).toBe(1);
				expect(appliedBodies[0]).toMatchObject({
					selected: [0, 1, 2],
					edits: { '0': 'P-1', '1': 'Example Maker', '2': 'Manually edited description' },
				});
				releaseApply();
				await expect(master).toHaveCount(0);
				expect(writes()).toBe(before + 1);
			});
		}
	});
}
