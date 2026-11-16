import { test, expect } from './fixtures/test';
import { json } from './fixtures/api';
import { selectLocation, analyzePhotos } from './helpers/scan';
import { detectedItems } from './fixtures/data';
import { uploadSyntheticPhoto } from '../fullstack/synthetic-photo';

for (const status of ['failed', 'incomplete', 'refused', 'no_results', 'unknown_outcome']) {
	const code =
		status === 'incomplete'
			? 'response_incomplete'
			: status === 'refused'
				? 'response_refused'
				: 'synthetic_' + status;
	test(`lookup explains ${status}, exposes canonical model, and never retries`, async ({
		page,
		api,
	}) => {
		const width = status === 'incomplete' ? 390 : 1280;
		await page.setViewportSize({ width, height: 844 });
		api.on('POST', '/api/tools/vision/detect', () =>
			json({
				...detectedItems(['Part']),
				items: detectedItems(['Part']).items.map((item) => ({
					...item,
					template_id: 'native-template',
					entity_type_id: 'native-type',
					custom_fields: { 'Part number': 'AB-123' },
				})),
			})
		);
		api.on('GET', '/api/research/capabilities', () => json({ enabled: true }));
		api.on('GET', '/api/settings/research', () =>
			json({
				enabled: true,
				profile_name: 'default',
				profiles: [{ name: 'default', model: 'gpt-6-luna', eligible: true }],
			})
		);
		api.on('POST', '/api/research/lookups', (request) => {
			expect(request.postDataJSON()).not.toHaveProperty('identity');
			expect(request.postDataJSON().context.images).toHaveLength(1);
			return json({
				id: 'lookup-1',
				result: {
					status: ['incomplete', 'refused'].includes(status) ? 'failed' : status,
					sources: [],
					diagnostic: {
						code,
						stage: 'response',
						message: 'Synthetic safe explanation.',
						request_id: 'req_synthetic',
						dispatch_started: true,
					},
				},
				proposals: [],
			});
		});
		await selectLocation(page);
		await uploadSyntheticPhoto(page);
		await analyzePhotos(page);
		await expect(
			page.getByRole('button', { name: 'Research this item', exact: true })
		).toBeVisible();
		await expect(
			page.getByText('Research uses: default — gpt-6-luna', { exact: true })
		).toBeVisible();
		await page
			.locator('#product-research')
			.evaluate((el) =>
				window.scrollTo({ top: window.scrollY + el.getBoundingClientRect().top - 80 })
			);
		await page.screenshot({ path: test.info().outputPath(`lookup-form-${status}-${width}.png`) });
		await page.getByRole('button', { name: 'Research this item', exact: true }).click();
		await expect(page.getByText('Synthetic safe explanation.', { exact: true })).toBeVisible();
		await expect(page.getByText(code, { exact: true })).toBeVisible();
		await expect(
			page.getByRole('button', { name: 'Adopt selected fields', exact: true })
		).toHaveCount(0);
		await page.getByText('Diagnostic details', { exact: true }).click();
		await expect(page.getByRole('textbox', { name: 'Safe diagnostic details' })).toHaveValue(
			/req_synthetic/
		);
		if (status === 'incomplete') await expect(page.getByText(/Research incomplete/)).toBeVisible();
		if (status === 'refused') await expect(page.getByText(/provider declined/)).toBeVisible();
		if (status === 'unknown_outcome')
			await expect(page.getByText(/may already have incurred costs/)).toBeVisible();
		expect(
			api.requests.filter((r) => r.method() === 'POST' && r.url().includes('/research/'))
		).toHaveLength(1);
		expect(
			await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
		).toBe(true);
		const details = page.getByRole('textbox', { name: 'Safe diagnostic details' });
		await details.evaluate((el) => el.scrollIntoView({ block: 'center' }));
		const bounds = await details.boundingBox();
		expect(bounds!.y).toBeGreaterThanOrEqual(56);
		expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(844 - 180);
		await page.screenshot({ path: test.info().outputPath(`lookup-${status}.png`) });
	});
}

for (const width of [1280, 390]) {
	test(`photo grouping is a visual keyboard switch at ${width}px`, async ({ page }) => {
		await page.setViewportSize({ width, height: 844 });
		await selectLocation(page);
		const toggle = page.getByRole('switch', { name: 'One item per photo', exact: true });
		await expect(toggle).not.toBeChecked();
		await expect(page.getByText('Multiple photos of one item', { exact: true })).toBeVisible();
		expect(await toggle.evaluate((el) => el.tagName)).toBe('BUTTON');
		expect((await toggle.boundingBox())!.height).toBeGreaterThanOrEqual(44);
		await toggle.focus();
		await page.keyboard.press('Space');
		await expect(toggle).toBeChecked();
		await page.keyboard.press('Space');
		await expect(toggle).not.toBeChecked();
		await page.screenshot({ path: test.info().outputPath(`capture-${width}.png`) });
	});
}

test('sole research profile stays editable and research-only creation reuses a key', async ({
	page,
	api,
}) => {
	const profile = {
		name: 'default',
		model: 'gpt-6-luna',
		status: 'primary',
		has_api_key: true,
		api_base: null,
		credential_source: 'own',
		can_share_credential: true,
		research_assigned: true,
	};
	api.on('GET', '/api/llm/profiles', () => json({ profiles: [profile] }));
	api.on('GET', '/api/settings/research', () =>
		json({
			enabled: true,
			profile_name: 'default',
			profiles: [{ ...profile, eligible: true, reason: null }],
		})
	);
	await page.goto('/settings');
	const section = page.locator('#product-research');
	await expect(
		section.getByRole('combobox', { name: 'Research profile', exact: true })
	).toHaveValue('default');
	await section.getByRole('button', { name: 'Edit selected profile', exact: true }).click();
	await expect(page.getByLabel('Model', { exact: true })).toHaveValue('gpt-6-luna');
	await expect(page.getByLabel('Status', { exact: true })).toHaveValue('primary');
	await page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).click();
	await section.getByRole('button', { name: 'Create research profile', exact: true }).click();
	await expect(page.getByLabel('Status', { exact: true })).toHaveValue('research');
	await expect(page.getByLabel('Credential source', { exact: true })).toHaveValue('profile');
	await expect(page.getByLabel('Credential profile', { exact: true })).toHaveValue('default');
	expect(api.requests.filter((r) => r.method() === 'POST')).toHaveLength(0);
});
