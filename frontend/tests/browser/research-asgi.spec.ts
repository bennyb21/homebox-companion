import { test, expect } from './fixtures/test';
import { json } from './fixtures/api';
import { detectedItems } from './fixtures/data';
import { researchAsgi } from './helpers/research-asgi';
import { selectLocation, analyzePhotos } from './helpers/scan';
import { uploadSyntheticPhoto } from '../fullstack/synthetic-photo';

const type = '00000000-0000-4000-8000-000000000010';
const template = '00000000-0000-4000-8000-000000000020';

for (const [scenario, code] of [
	['matched', 'matched'],
	['incomplete', 'response_incomplete'],
	['refused', 'response_refused'],
	['no_results', 'no_results'],
	['malformed', 'malformed_json'],
	['unsupported', 'request_rejected'],
]) {
	test(`real ASGI/SDK lookup renders ${scenario} without replay`, async ({ page, api }) => {
		const bridge = await researchAsgi(api);
		try {
			await bridge.scenario(scenario);
			api.on('POST', '/api/tools/vision/detect', () =>
				json({
					...detectedItems(['Synthetic part']),
					items: detectedItems(['Synthetic part']).items.map((item) => ({
						...item,
						entity_type_id: type,
						template_id: template,
						custom_fields: { 'Model number': 'MODEL-A', Specifications: '' },
					})),
				})
			);
			await selectLocation(page);
			await uploadSyntheticPhoto(page);
			await analyzePhotos(page);
			await expect(
				page.getByRole('button', { name: 'Research this item', exact: true })
			).toBeVisible();
			await expect(
				page.getByText('Research uses: default — gpt-6-luna', { exact: true })
			).toBeVisible();
			await expect(page.getByLabel('Exact part/model number')).toHaveCount(0);
			await page.getByLabel('Name', { exact: true }).fill('QUERY-CONFIDENTIALITY-CANARY');
			await page.getByRole('button', { name: 'Research this item', exact: true }).click();
			await expect(page.getByText(code, { exact: true })).toBeVisible();
			if (scenario === 'matched') {
				await expect(page.getByRole('link', { name: 'Synthetic', exact: true })).toHaveAttribute(
					'href',
					'https://example.com/model'
				);
				await page.getByLabel('Adopt Specifications').check();
				await page.getByRole('button', { name: 'Adopt selected fields', exact: true }).click();
				await expect(page.getByLabel('Specifications', { exact: true })).toHaveValue(
					'Steel, 12 mm'
				);
			} else {
				await expect(
					page.getByRole('button', { name: 'Adopt selected fields', exact: true })
				).toHaveCount(0);
				await page.getByText('Diagnostic details', { exact: true }).click();
				const details = page.getByRole('textbox', { name: 'Safe diagnostic details' });
				await expect(details).toHaveValue(/req_0123456789abcdef/);
				await expect(details).not.toHaveValue(/CONFIDENTIALITY-CANARY/);
			}
			const evidence = await bridge.inspect();
			expect(evidence.wire).toHaveLength(1);
			expect(evidence.wire[0]).toMatchObject({ method: 'POST', model: 'gpt-6-luna', scenario });
			expect(evidence.network_attempts).toBe(0);
			expect(evidence.inventory_writes).toBe(0);
			await test.info().attach('ASGI wire evidence', {
				body: JSON.stringify(evidence),
				contentType: 'application/json',
			});
		} finally {
			await bridge.close();
		}
	});
}

for (const width of [390, 1280]) {
	test(`real ASGI profile editing preserves draft and verified selection at ${width}px`, async ({
		page,
		api,
	}) => {
		const bridge = await researchAsgi(api);
		try {
			await page.setViewportSize({ width, height: 844 });
			api.on('POST', '/api/tools/vision/detect', () => json(detectedItems(['Synthetic item'])));
			await selectLocation(page);
			await expect(
				page.getByRole('switch', { name: 'One item per photo', exact: true })
			).not.toBeChecked();
			await page.evaluate(async () => {
				await Promise.all(
					document.getAnimations().map((animation) => animation.finished.catch(() => {}))
				);
			});
			await page.screenshot({ path: test.info().outputPath(`capture-asgi-${width}.png`) });
			await uploadSyntheticPhoto(page);
			await analyzePhotos(page);
			await page.getByLabel('Name', { exact: true }).fill('Retain unsaved synthetic item');
			await expect(
				page.getByRole('button', { name: 'Research this item', exact: true })
			).toBeVisible();
			await page.getByRole('link', { name: 'Edit active research profile' }).click();
			const dialog = page.getByRole('dialog');
			await expect(dialog.getByLabel('Name', { exact: true })).toHaveValue('default');
			await expect(dialog.getByLabel('Status', { exact: true })).toHaveValue('primary');
			await dialog.getByLabel('Model', { exact: true }).fill('gpt-6.1-terra');
			const save = dialog.getByRole('button', { name: 'Save', exact: true });
			await save.scrollIntoViewIfNeeded();
			const bounds = await save.boundingBox();
			expect(bounds!.y).toBeGreaterThan(0);
			expect(bounds!.y + bounds!.height).toBeLessThan(844);
			await page.screenshot({ path: test.info().outputPath(`editor-asgi-${width}.png`) });
			await save.click();
			await expect(dialog).toHaveCount(0);
			const section = page.locator('#product-research');
			await expect(
				section.getByText('Research uses: default — gpt-6.1-terra', { exact: true })
			).toBeVisible();
			await section
				.getByRole('combobox', { name: 'Research profile', exact: true })
				.selectOption('Off research');
			await section.getByRole('button', { name: 'Save research profile', exact: true }).click();
			await expect(
				section.getByText('Research uses: Off research — gpt-6.1-terra', { exact: true })
			).toBeVisible();
			const toggle = section.getByRole('switch', { name: 'Enable product research', exact: true });
			await toggle.click();
			await expect(toggle).not.toBeChecked();
			await toggle.click();
			await expect(toggle).toBeChecked();
			await section.evaluate((el) =>
				window.scrollTo({ top: window.scrollY + el.getBoundingClientRect().top - 80 })
			);
			await page.screenshot({ path: test.info().outputPath(`settings-asgi-${width}.png`) });
			const readback = JSON.parse((await bridge.request('GET', '/api/settings/research')).body);
			expect(readback).toMatchObject({ enabled: true, profile_name: 'Off research' });
			const profiles = JSON.parse((await bridge.request('GET', '/api/llm/profiles')).body).profiles;
			expect(profiles.find((p: { name: string }) => p.name === 'default').status).toBe('primary');
			await page.getByRole('link', { name: 'Return to item draft' }).click();
			await expect(page.getByLabel('Name', { exact: true })).toHaveValue(
				'Retain unsaved synthetic item'
			);
			await expect(
				page.getByText('Research uses: Off research — gpt-6.1-terra', { exact: true })
			).toBeVisible();
			const evidence = await bridge.inspect();
			expect(evidence.wire).toEqual([]);
			expect(evidence.inventory_writes).toBe(0);
			expect(api.requests.filter((r) => r.url().includes('/vision/detect'))).toHaveLength(1);
			await test.info().attach('ASGI state evidence', {
				body: JSON.stringify(evidence),
				contentType: 'application/json',
			});
		} finally {
			await bridge.close();
		}
	});
}

test('real ASGI named Off tests distinguish metadata access, empty research and ambiguity', async ({
	page,
	api,
}) => {
	const bridge = await researchAsgi(api);
	try {
		await page.goto('/settings');
		const unknown = page.getByRole('group', { name: 'Profile Unverified', exact: true });
		await unknown.getByRole('button', { name: 'Check API access', exact: true }).click();
		await expect(page.getByText('connection_verified', { exact: true })).toBeVisible();
		let evidence = await bridge.inspect();
		expect(evidence.wire).toEqual([
			{
				method: 'GET',
				model: 'gpt-6-terra',
				endpoint: 'https://api.openai.com/v1/models/gpt-6-terra',
			},
		]);
		for (const scenario of ['no_results', 'ambiguous']) {
			await bridge.scenario(scenario);
			await page
				.getByRole('group', { name: 'Profile Off research', exact: true })
				.getByRole('button', { name: 'Run research test', exact: true })
				.click();
			const dialog = page.getByRole('dialog');
			await dialog.getByLabel('Identifier kind', { exact: true }).selectOption('model_number');
			await dialog.getByLabel('Exact part/model number', { exact: true }).fill('MODEL-A');
			const response = page.waitForResponse(
				(r) =>
					r.url().includes('/llm/profiles/Off%20research/test') && r.request().method() === 'POST'
			);
			await dialog.getByRole('button', { name: 'Run paid research test', exact: true }).click();
			const body = await (await response).json();
			expect(body.success).toBe(scenario === 'no_results');
			expect(body.research_result.status).toBe(scenario);
			if (scenario === 'no_results') {
				await expect(page.getByText('no_results', { exact: true })).toBeVisible();
			} else {
				expect(body.research_result.claims).toEqual([]);
				await expect(
					page.getByText('Research did not produce a validated result.', { exact: true })
				).toBeVisible();
				await expect(page.getByText(/No adoptable research result/)).toBeVisible();
			}
		}
		await expect(
			page
				.locator('#product-research')
				.getByText('Research uses: default — gpt-6-luna', { exact: true })
		).toBeVisible();
		const profiles = JSON.parse((await bridge.request('GET', '/api/llm/profiles')).body).profiles;
		expect(profiles.find((p: { name: string }) => p.name === 'Off research')).toMatchObject({
			status: 'off',
			research_assigned: false,
			credential_profile_name: 'default',
		});
		evidence = await bridge.inspect();
		expect(evidence.wire.filter((r) => r.method === 'POST')).toHaveLength(2);
		expect(
			evidence.wire.filter((r) => r.method === 'POST').every((r) => r.model === 'gpt-6.1-terra')
		).toBe(true);
		expect(evidence.network_attempts).toBe(0);
		await test.info().attach('ASGI wire evidence', {
			body: JSON.stringify(evidence),
			contentType: 'application/json',
		});
	} finally {
		await bridge.close();
	}
});

test('real ASGI saved job preserves safe diagnostic and never replays on refresh', async ({
	page,
	api,
}) => {
	const bridge = await researchAsgi(api);
	try {
		await bridge.scenario('incomplete');
		api.on('GET', '/api/items', () => json([{ id: 'item-1', name: 'Synthetic saved item' }]));
		await page.goto('/research');
		await page.getByRole('combobox', { name: 'Saved item', exact: true }).selectOption('item-1');
		await expect(page.getByLabel('Exact part/model number')).toHaveCount(0);
		await page.getByRole('button', { name: 'Research this item', exact: true }).click();
		await expect(async () => {
			await page.getByRole('button', { name: 'Refresh jobs' }).click();
			await expect(page.getByText('response_incomplete', { exact: true })).toBeVisible();
		}).toPass();
		await page.reload();
		await expect(page.getByText('response_incomplete', { exact: true })).toBeVisible();
		const evidence = await bridge.inspect();
		expect(evidence.wire).toHaveLength(1);
		expect(evidence.inventory_writes).toBe(0);
		expect(evidence.network_attempts).toBe(0);
		await test.info().attach('ASGI wire evidence', {
			body: JSON.stringify(evidence),
			contentType: 'application/json',
		});
	} finally {
		await bridge.close();
	}
});
