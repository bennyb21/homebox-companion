import { test, expect } from './fixtures/test';
import { json, verifiedAttachment, type MockApi } from './fixtures/api';
import { detectedItems, fieldPreferences } from './fixtures/data';
import { uploadSyntheticPhoto } from '../fullstack/synthetic-photo';
import type { Page } from '@playwright/test';

const report = process.env.HBC_UI_REPORT_DIR;
async function screenshot(page: Page, name: string) {
	await page.screenshot({
		path: report ? `${report}/${name}.png` : test.info().outputPath(`${name}.png`),
		fullPage: true,
	});
	await page.screenshot({
		path: report
			? `${report}/${name}-viewport.png`
			: test.info().outputPath(`${name}-viewport.png`),
	});
}
function researchFixture(api: MockApi) {
	api.on('GET', '/api/capture-profiles', () =>
		json([{ id: 'native-type', name: 'Automotive Parts', defaultTemplateId: 'native-template' }])
	);
	api.on('GET', '/api/research/capabilities', () => json({ enabled: true }));
	api.on('GET', '/api/settings/research', () =>
		json({
			enabled: true,
			profile_name: 'Capture Original',
			profiles: [{ name: 'Capture Original', model: 'gpt-exact-ID', eligible: true }],
		})
	);
	api.on('POST', '/api/tools/vision/detect', () =>
		json({
			...detectedItems(['Original item']),
			items: detectedItems(['Original item']).items.map((item) => ({
				...item,
				entity_type_id: 'native-type',
				template_id: 'native-template',
				custom_fields: { 'Part number': 'AB-123', Specifications: '' },
			})),
		})
	);
}
const proposals = () => [
	{ name: 'Part number', current: 'AB-123', value: 'AB-123', source_urls: [], evidence: '' },
	{ name: 'Manufacturer', current: '', value: 'SKF', source_urls: [], evidence: '' },
	{
		name: 'Specifications',
		current: '',
		value:
			'Technische Angaben: Stahl, verzinkt. Für die beschriebene Produktfamilie; konkrete Bauform noch unklar.',
		source_urls: ['https://example.com/spec'],
		evidence: '',
	},
	{ name: 'Model', current: 'Original', value: 'AB-123-X', source_urls: [], evidence: '' },
];
const result = () => ({
	status: 'matched',
	ambiguity: 'Zwei Bauformen möglich – Kennzeichnung vergleichen.',
	sources: [{ url: 'https://example.com/spec', title: 'Herstellerunterlagen' }],
	diagnostic: { code: 'matched', stage: 'parse', message: 'Successful provider payload' },
});
async function capture(page: Page, de: boolean) {
	await page.goto('/location');
	await page.getByRole('button', { name: /Storage/ }).click();
	await page
		.getByRole('button', { name: de ? 'Aktuellen Standort wählen' : 'Select current location' })
		.click();
	await page
		.getByRole('button', { name: de ? 'Weiter zur Erfassung' : 'Continue to Capture' })
		.click();
	await uploadSyntheticPhoto(page);
	await page
		.getByRole('button', { name: de ? 'Mit KI analysieren' : 'Analyze with AI', exact: true })
		.click();
	await expect(page.getByLabel('Name', { exact: true })).toBeVisible();
}

for (const locale of ['de-DE', 'en-US']) {
	test.describe(locale, () => {
		test.use({ locale });
		for (const width of [1280, 390]) {
			test(`settings switches without requests or losing unsaved values at ${width}`, async ({
				page,
				api,
			}) => {
				const de = locale === 'de-DE';
				await page.setViewportSize({ width, height: 900 });
				api.on('GET', '/api/settings/field-preferences', () =>
					json({
						...fieldPreferences(),
						output_language: 'French',
						name: 'Keep this English prompt unchanged',
					})
				);
				api.on('GET', '/api/settings/custom-fields', () =>
					json([{ name: 'Storage Location', ai_instruction: 'Original user instruction' }])
				);
				await page.goto('/settings');
				await expect(page.locator('html')).toHaveAttribute('lang', de ? 'de' : 'en');
				await page
					.getByRole('button', { name: de ? /^Allgemeine Einstellungen/ : /^General Settings/ })
					.click();
				await page.locator('#output_language').fill('French – unsaved');
				await page
					.getByRole('button', { name: de ? /^Standardfelder/ : /^Default Fields/ })
					.click();
				await page.locator('#name').fill('Unsaved prompt: Manufacturer Name bleibt exakt');
				await page
					.getByRole('button', { name: de ? 'Eigene Felder' : 'Custom Fields', exact: true })
					.click();
				await expect(page.getByLabel('Storage Location', { exact: true })).toHaveValue(
					'Original user instruction'
				);
				await page.waitForLoadState('networkidle');
				const requests = api.requests.length;
				await page.locator('#ui-language').selectOption(de ? 'en' : 'de');
				await expect(
					page.getByRole('heading', { name: de ? 'Settings' : 'Einstellungen', exact: true })
				).toBeVisible();
				await expect(page.locator('#output_language')).toHaveValue('French – unsaved');
				await expect(page.locator('#name')).toHaveValue(
					'Unsaved prompt: Manufacturer Name bleibt exakt'
				);
				await expect(page.getByLabel('Storage Location', { exact: true })).toHaveValue(
					'Original user instruction'
				);
				expect(api.requests).toHaveLength(requests);
				expect(api.requests.filter((r) => r.method() !== 'GET')).toHaveLength(0);
				await page.locator('#ui-language').selectOption(de ? 'de' : 'en');
				await page.evaluate(() => window.scrollTo(0, 0));
				await screenshot(page, `settings-${de ? 'de' : 'en'}-${width}`);
				await page.reload();
				await expect(page.locator('#ui-language')).toHaveValue(de ? 'de' : 'en');
			});
		}
		for (const platform of ['', ' @mobile'])
			test(`capture, compact research, draft language switch, summary and save${platform}`, async ({
				page,
				api,
			}) => {
				const de = locale === 'de-DE';
				researchFixture(api);
				api.on('POST', '/api/research/lookups', () =>
					json({ id: 'lookup1', result: result(), proposals: proposals() })
				);
				api.on('POST', '/api/research/lookups/lookup1/apply', (request) => {
					expect(request.postDataJSON()).toMatchObject({
						selected: [1, 3, 0],
						edits: { '0': 'AB-123-EDIT', '1': 'SKF', '3': 'Original' },
					});
					return json({
						patch: { 'Part number': 'AB-123-EDIT' },
						item_patch: { manufacturer: 'SKF', model_number: 'Original' },
					});
				});
				api.on('POST', '/api/items', (request) => {
					expect(request.postDataJSON().items[0].name).toBe('Manual unübersetzt');
					return json({ created: [{ id: 'created1', name: 'Manual unübersetzt' }], errors: [] });
				});
				api.on('POST', '/api/items/created1/attachments', verifiedAttachment);
				await capture(page, de);
				await page.getByLabel('Name', { exact: true }).fill('Manual unübersetzt');
				await page
					.getByRole('button', {
						name: de ? 'Diesen Gegenstand recherchieren' : 'Research this item',
						exact: true,
					})
					.click();
				const panel = page.locator('#product-research');
				await expect(panel.getByRole('link', { name: 'Herstellerunterlagen' })).toBeVisible();
				await expect(panel.getByText(result().ambiguity)).toBeVisible();
				await expect(panel.getByText('Successful provider payload')).toHaveCount(0);
				await expect(
					panel.getByText(de ? 'Technische Diagnose' : 'Diagnostic details', { exact: true })
				).toHaveCount(0);
				await expect(panel.locator('[data-proposal-index="0"]')).not.toBeVisible();
				await expect(panel.getByLabel('Manufacturer', { exact: true })).toHaveJSProperty(
					'tagName',
					'INPUT'
				);
				await expect(panel.getByLabel('Specifications', { exact: true })).toHaveJSProperty(
					'tagName',
					'TEXTAREA'
				);
				await panel.locator('[data-proposal-index="1"] input[type="checkbox"]').check();
				await panel.getByLabel('Model', { exact: true }).fill('Original');
				await expect(panel.getByLabel('Model', { exact: true })).toBeVisible();
				await panel.locator('[data-proposal-index="3"] input[type="checkbox"]').check();
				for (const width of [1280, 390]) {
					await page.setViewportSize({ width, height: 1000 });
					await panel.evaluate((el) =>
						window.scrollTo(0, window.scrollY + el.getBoundingClientRect().top - 80)
					);
					await page.screenshot({
						path: report
							? `${report}/draft-compact-${de ? 'de' : 'en'}-${width}.png`
							: test.info().outputPath(`draft-compact-${width}.png`),
					});
				}
				await panel
					.getByText(de ? 'Unveränderte Felder (1)' : 'Unchanged fields (1)', { exact: true })
					.click();
				await panel.getByLabel('Part number', { exact: true }).fill('AB-123-EDIT');
				await panel.locator('[data-proposal-index="0"] input[type="checkbox"]').check();
				for (const width of [1280, 390]) {
					await page.setViewportSize({ width, height: 1000 });
					await page.evaluate(() => window.scrollTo(0, 0));
					await screenshot(page, `draft-research-${de ? 'de' : 'en'}-${width}`);
					await panel
						.getByRole('button', {
							name: de ? 'Ausgewählte Felder übernehmen' : 'Adopt selected fields',
							exact: true,
						})
						.scrollIntoViewIfNeeded();
					await page.screenshot({
						path: report
							? `${report}/draft-controls-${de ? 'de' : 'en'}-${width}.png`
							: test.info().outputPath(`draft-controls-${width}.png`),
					});
					expect(
						await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)
					).toBe(true);
				}
				await panel
					.getByRole('button', {
						name: de ? 'Ausgewählte Felder übernehmen' : 'Adopt selected fields',
						exact: true,
					})
					.click();
				await expect(page.locator('[id="review-cf-Part number"]')).toHaveValue('AB-123-EDIT');
				await panel
					.getByRole('link', { name: de ? 'Recherche-Einstellungen' : 'Research settings' })
					.click();
				await page.locator('#ui-language').selectOption(de ? 'en' : 'de');
				await page
					.getByRole('link', { name: de ? 'Return to item draft' : 'Zurück zum Entwurf' })
					.click();
				await expect(page.getByLabel('Name', { exact: true })).toHaveValue('Manual unübersetzt');
				await page.getByLabel(de ? 'Asset ID' : 'Inventarnummer', { exact: true }).fill('invalid');
				await expect(
					page.getByText(
						de
							? 'Enter a numeric Homebox asset ID (for example, 032-303), or leave it blank.'
							: 'Numerische Homebox-Inventarnummer eingeben (z. B. 032-303) oder leer lassen.',
						{ exact: true }
					)
				).toBeVisible();
				await page.getByLabel(de ? 'Asset ID' : 'Inventarnummer', { exact: true }).fill('');

				await page
					.getByRole('button', { name: de ? 'Confirm' : 'Bestätigen', exact: true })
					.click();
				await expect(page.getByRole('heading', { name: 'Manual unübersetzt' })).toBeVisible();
				await page
					.getByRole('button', { name: de ? /Submit All Items/ : /Alle Gegenstände übertragen/ })
					.click();
				await expect(page).toHaveURL(/\/success$/);
				await expect(
					page.getByRole('heading', { name: de ? 'Success!' : 'Erfolgreich!', exact: true })
				).toBeVisible();
				await screenshot(page, `success-switched-${de ? 'en' : 'de'}`);
				expect(
					api.requests.filter((r) => r.method() === 'POST' && r.url().endsWith('/vision/detect'))
				).toHaveLength(1);
				expect(
					api.requests.filter((r) => r.method() === 'POST' && r.url().endsWith('/research/lookups'))
				).toHaveLength(1);
				expect(
					api.requests.filter((r) => r.method() === 'PUT' && r.url().includes('/settings/'))
				).toHaveLength(0);
			});
	});
}

test.describe('German browser default and explicit English override', () => {
	test.use({ locale: 'de-CH' });
	test('persisted English overrides detection, German login remains usable without storage', async ({
		page,
		api,
	}) => {
		api.setAuthMode('legacy');
		await page.addInitScript(() => localStorage.setItem('hbc.ui-language', 'en'));
		await page.goto('/');
		await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
		await expect(page.locator('html')).toHaveAttribute('lang', 'en');
	});
	test('German login with blocked storage and no AI requests', async ({ page, api }) => {
		api.setAuthMode('legacy');
		await page.addInitScript(() => {
			const get = Storage.prototype.getItem;
			Storage.prototype.getItem = function (key) {
				if (key === 'hbc.ui-language') throw new Error('blocked');
				return get.call(this, key);
			};
		});
		await page.goto('/');
		await expect(page.getByRole('heading', { name: 'Willkommen zurück' })).toBeVisible();
		await expect(page.getByLabel('Passwort', { exact: true })).toBeVisible();
		await expect(page.locator('html')).toHaveAttribute('lang', 'de');
		await screenshot(page, 'login-de');
		expect(api.requests.filter((r) => r.method() !== 'GET')).toHaveLength(0);
	});
	test('stale draft adoption remains blocked and visible in German', async ({ page, api }) => {
		researchFixture(api);
		api.on('POST', '/api/research/lookups', () =>
			json({ id: 'lookup1', result: result(), proposals: proposals() })
		);
		await capture(page, true);
		await page
			.getByRole('button', { name: 'Diesen Gegenstand recherchieren', exact: true })
			.click();
		await page.locator('[data-proposal-index="1"] input[type="checkbox"]').check();
		await page.getByLabel('Name', { exact: true }).fill('Changed after research');
		await page.getByRole('button', { name: 'Ausgewählte Felder übernehmen', exact: true }).click();
		await expect(
			page.getByText('Entwurf geändert; vor der Übernahme erneut vergleichen.')
		).toBeVisible();
		expect(
			api.requests.filter((r) => r.method() === 'POST' && r.url().endsWith('/apply'))
		).toHaveLength(0);
	});
	test('saved jobs fold unchanged proposals, preserve indices, and hide success diagnostics', async ({
		page,
		api,
	}) => {
		researchFixture(api);
		let state = 'matched';
		api.on('GET', '/api/items', () => json([{ id: 'item1', name: 'Saved Original Name' }]));
		api.on('GET', '/api/research/jobs', () =>
			json([
				{
					id: 'job1',
					item: 'item1',
					state,
					result: { research: result(), proposals: proposals() },
				},
			])
		);
		api.on('POST', '/api/research/jobs/job1/apply', (request) => {
			expect(request.postDataJSON()).toEqual({ selected: [3], edits: { '3': 'Original' } });
			state = 'applied';
			return json({ state });
		});
		await page.goto('/research');
		await expect(page.getByRole('heading', { name: 'Rechercheaufträge' })).toBeVisible();
		await expect(page.locator('[data-proposal-index="0"]')).not.toBeVisible();
		await expect(page.getByText('Successful provider payload')).toHaveCount(0);
		await page.getByLabel('Model', { exact: true }).fill('Original');
		await page.locator('[data-proposal-index="3"] input[type="checkbox"]').check();
		for (const width of [1280, 390]) {
			await page.setViewportSize({ width, height: 900 });
			await screenshot(page, `saved-research-de-${width}`);
		}
		await page.getByRole('button', { name: 'Auswahl in Homebox übernehmen' }).click();
		await expect(page.getByText('Übernommen', { exact: true })).toBeVisible();
	});
	test('core research labels translate while same-named custom fields remain literal', async ({
		page,
		api,
	}) => {
		researchFixture(api);
		api.on('GET', '/api/items', () =>
			json([{ id: 'item1', name: 'Hydraulikpumpe Beispiel P-100' }])
		);
		const core = [
			{ name: 'Teilenummer', current: 'P-100-A', value: 'P-100-A', source_urls: [], evidence: '' },
			{
				name: 'Manufacturer',
				target: 'manufacturer',
				current: '',
				value: 'Beispiel',
				source_urls: [],
				evidence: '',
			},
			{
				name: 'Description',
				target: 'description',
				current: '',
				value:
					'Hydraulikpumpe für den Einsatz in einer Werkstattpresse. Gehäuse aus Stahl, Modellreihe P-100.',
				source_urls: [],
				evidence: '',
			},
			{
				name: 'Model number',
				target: 'model_number',
				current: 'P100',
				value: 'P-100',
				source_urls: [],
				evidence: '',
			},
			{
				name: 'Manufacturer',
				current: 'Custom preserved',
				value: 'Custom preserved',
				source_urls: [],
				evidence: '',
			},
		];
		let applied = false;
		api.on('GET', '/api/research/jobs', () =>
			json([
				{
					id: 'core1',
					item: 'item1',
					state: applied ? 'applied' : 'matched',
					result: { research: { ...result(), ambiguity: '' }, proposals: core },
				},
			])
		);
		api.on('POST', '/api/research/jobs/core1/apply', (request) => {
			expect(request.postDataJSON()).toEqual({
				selected: [1, 3],
				edits: { '1': 'Beispiel', '3': 'P-100-EDIT' },
			});
			applied = true;
			return json({ state: 'applied' });
		});
		await page.goto('/research');
		await expect(page.getByLabel('Hersteller', { exact: true })).toHaveValue('Beispiel');
		await expect(page.getByLabel('Beschreibung', { exact: true })).toHaveValue(core[2].value);
		await expect(page.getByLabel('Modellnummer', { exact: true })).toHaveValue('P-100');
		await expect(page.getByLabel('Manufacturer', { exact: true })).not.toBeVisible();
		await page.getByText('Unveränderte Felder (2)', { exact: true }).click();
		await expect(page.getByLabel('Manufacturer', { exact: true })).toHaveValue('Custom preserved');
		await page.getByText('Unveränderte Felder (2)', { exact: true }).click();
		await page.setViewportSize({ width: 390, height: 900 });
		await screenshot(page, 'core-research-de-390');
		const card = page
			.locator('section')
			.filter({
				has: page.getByRole('heading', { name: 'Hydraulikpumpe Beispiel P-100', exact: true }),
			});
		await card.evaluate((element) =>
			window.scrollTo(0, window.scrollY + element.getBoundingClientRect().top - 80)
		);
		await card.screenshot({
			path: report
				? `${report}/core-research-panel-de.png`
				: test.info().outputPath('core-research-panel-de.png'),
		});
		await page.getByLabel('Modellnummer', { exact: true }).fill('P-100-EDIT');
		await page.getByRole('checkbox', { name: 'Hersteller übernehmen', exact: true }).check();
		await page.getByRole('checkbox', { name: 'Modellnummer übernehmen', exact: true }).check();
		await page.getByRole('button', { name: 'Auswahl in Homebox übernehmen' }).click();
		await expect(page.getByText('Übernommen', { exact: true })).toBeVisible();
	});

	test('real error category, raw diagnostics and source ambiguity remain accessible', async ({
		page,
		api,
	}) => {
		researchFixture(api);
		api.on('GET', '/api/research/jobs', () =>
			json([
				{
					id: 'failed1',
					item: 'Broken',
					state: 'failed',
					result: {
						research: {
							status: 'failed',
							diagnostic: {
								code: 'response_incomplete',
								stage: 'response',
								request_id: 'req_synthetic',
								message: 'Raw provider diagnostic',
							},
						},
						proposals: [],
					},
				},
			])
		);
		await page.goto('/research');
		await expect(page.getByText(/Recherche unvollständig/)).toBeVisible();
		await expect(page.getByText('response_incomplete', { exact: true })).not.toBeVisible();
		await page.getByText('Technische Diagnose', { exact: true }).click();
		await expect(page.getByRole('textbox', { name: 'Sichere Diagnosedaten' })).toHaveValue(
			/req_synthetic/
		);
		await expect(page.getByText('Raw provider diagnostic')).toBeVisible();
		expect(api.requests.filter((r) => r.method() !== 'GET')).toHaveLength(0);
		await screenshot(page, 'research-error-de');
	});
	test('German chat sends user content unchanged', async ({ page, api }) => {
		await page.goto('/chat');
		await expect(page.getByText('Unterhaltung beginnen')).toBeVisible();
		await page
			.getByRole('textbox', { name: 'Chatnachricht' })
			.fill('Keep model AB-123 and Manufacturer as typed');
		await page.getByRole('button', { name: 'Nachricht senden' }).click();
		await expect(page.getByText('Hello', { exact: true })).toBeVisible();
		const request = api.requests.find(
			(r) => r.method() === 'POST' && r.url().endsWith('/chat/messages')
		)!;
		expect(request.postDataJSON().message).toBe('Keep model AB-123 and Manufacturer as typed');
		await screenshot(page, 'chat-de');
	});
});
