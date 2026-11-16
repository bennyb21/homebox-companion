import { test, expect } from './fixtures/test';
import { json } from './fixtures/api';
import { detectedItems } from './fixtures/data';
import { selectLocation, analyzePhotos } from './helpers/scan';
import { uploadSyntheticPhoto } from '../fullstack/synthetic-photo';

test('research editor actions wait for profile readback instead of silently losing clicks', async ({
	page,
	api,
}) => {
	const gate = api.gate();
	api.on('GET', '/api/llm/profiles', async () => {
		await gate.promise;
		return json({
			profiles: [{ name: 'default', model: 'gpt-6-luna', status: 'primary', has_api_key: true }],
		});
	});
	api.on('GET', '/api/settings/research', () =>
		json({
			enabled: true,
			profile_name: 'default',
			profiles: [{ name: 'default', model: 'gpt-6-luna', eligible: true }],
		})
	);
	await page.goto('/settings');
	const edit = page.getByRole('button', { name: 'Edit selected profile', exact: true });
	await expect(edit).toBeDisabled();
	gate.release();
	await expect(edit).toBeEnabled();
	await edit.click();
	await expect(page.getByRole('dialog')).toBeVisible();
});

test('profile change during research-settings load cannot leave an obsolete canonical model', async ({
	page,
	api,
}) => {
	const gate = api.gate();
	let reads = 0;
	let profile = {
		name: 'default',
		model: 'gpt-6-luna',
		status: 'primary',
		has_api_key: true,
		research_assigned: true,
	};
	api.on('GET', '/api/llm/profiles', () => json({ profiles: [profile] }));
	api.on('GET', '/api/settings/research', async () => {
		const snapshot = { ...profile, eligible: true };
		if (++reads === 1) await gate.promise;
		return json({ enabled: true, profile_name: 'default', profiles: [snapshot] });
	});
	api.on('PUT', '/api/llm/profiles/default', (r) => {
		profile = { ...profile, ...r.postDataJSON() };
		return json(profile);
	});
	await page.goto('/settings');
	await page.getByRole('button', { name: 'Edit profile', exact: true }).click();
	await page.getByLabel('Model', { exact: true }).fill('gpt-6-terra');
	const changed = page.evaluate(
		() =>
			new Promise<void>((resolve) =>
				window.addEventListener('model-profiles-changed', () => resolve(), { once: true })
			)
	);
	await page.getByRole('dialog').getByRole('button', { name: 'Save', exact: true }).click();
	await changed;
	gate.release();
	await expect(
		page
			.locator('#product-research')
			.getByText('Research uses: default — gpt-6-terra', { exact: true })
	).toBeVisible();
	expect(api.requests.filter((r) => r.method() === 'POST')).toHaveLength(0);
});

test('lookup edit link edits the canonical profile and returns to the untouched item draft', async ({
	page,
	api,
}) => {
	api.on('POST', '/api/tools/vision/detect', () => json(detectedItems(['Synthetic item'])));
	api.on('GET', '/api/research/capabilities', () => json({ enabled: true }));
	api.on('GET', '/api/settings/research', () =>
		json({
			enabled: true,
			profile_name: 'default',
			profiles: [{ name: 'default', model: 'gpt-6-luna', eligible: true }],
		})
	);
	api.on('GET', '/api/llm/profiles', () =>
		json({
			profiles: [
				{
					name: 'default',
					model: 'gpt-6-luna',
					status: 'primary',
					has_api_key: true,
					research_assigned: true,
				},
				{ name: 'Recherche', model: 'gpt-6-terra', status: 'off', has_api_key: true },
			],
		})
	);
	await selectLocation(page);
	await uploadSyntheticPhoto(page);
	await analyzePhotos(page);
	await page.getByLabel('Name', { exact: true }).fill('Keep my unsaved item');
	await page.getByRole('button', { name: 'Research product data', exact: true }).click();
	await page.getByRole('link', { name: 'Edit active research profile' }).click();
	await expect(page.getByRole('dialog').getByLabel('Name', { exact: true })).toHaveValue('default');
	await expect(page.getByRole('dialog').getByLabel('Status', { exact: true })).toHaveValue(
		'primary'
	);
	await page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).click();
	await page.getByRole('link', { name: 'Return to item draft' }).click();
	await expect(page.getByLabel('Name', { exact: true })).toHaveValue('Keep my unsaved item');
	expect(
		api.requests.filter((r) => r.method() === 'POST' && r.url().includes('/research/'))
	).toHaveLength(0);
	expect(
		api.requests.filter((r) => r.method() === 'POST' && r.url().includes('/vision/detect'))
	).toHaveLength(1);
});

test('research section can edit an ineligible profile without assigning it', async ({
	page,
	api,
}) => {
	api.on('GET', '/api/settings/research', () =>
		json({
			enabled: false,
			profile_name: 'Recherche',
			profiles: [
				{
					name: 'Recherche',
					model: 'gpt-6-terra',
					eligible: false,
					reason: 'Exact model is unverified.',
				},
			],
		})
	);
	api.on('GET', '/api/llm/profiles', () =>
		json({
			profiles: [{ name: 'Recherche', model: 'gpt-6-terra', status: 'off', has_api_key: true }],
		})
	);
	await page.goto('/settings');
	await page
		.locator('#product-research')
		.getByRole('button', { name: 'Edit selected profile', exact: true })
		.click();
	await expect(page.getByRole('dialog').getByLabel('Model', { exact: true })).toHaveValue(
		'gpt-6-terra'
	);
	await expect(page.getByRole('dialog').getByLabel('Status', { exact: true })).toHaveValue('off');
	expect(api.requests.filter((r) => r.method() !== 'GET')).toHaveLength(0);
});
