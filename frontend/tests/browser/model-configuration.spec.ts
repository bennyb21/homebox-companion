import { expect, test } from './fixtures/test';
import { json } from './fixtures/api';
import { config } from './fixtures/data';

test('dedicated research profile reuses a key and persists exact reasoning without a paid test', async ({
	page,
	api,
}) => {
	const profiles: Record<string, unknown>[] = [
		{
			name: 'capture',
			model: 'gpt-4.1',
			status: 'primary',
			has_api_key: true,
			api_base: null,
			credential_source: 'own',
			credential_profile_name: null,
			research_reasoning_effort: null,
			research_assigned: false,
			can_share_credential: true,
		},
	];
	const writes: Record<string, unknown>[] = [];
	api.on('GET', '/api/llm/profiles', () =>
		json({
			profiles,
			reasoning_options: { 'gpt-6-luna': ['none', 'low', 'medium', 'high', 'xhigh', 'max'] },
			environment_credential_available: true,
		})
	);
	api.on('POST', '/api/llm/profiles', (request) => {
		const payload = request.postDataJSON();
		writes.push(payload);
		profiles.push({ ...payload, has_api_key: true, research_assigned: true });
		return json(profiles[1], 201);
	});
	await page.goto('/settings');
	const section = page
		.locator('section')
		.filter({ has: page.getByRole('heading', { name: 'AI Models', exact: true }) });
	await section.getByRole('button', { name: 'Add', exact: true }).click();
	await page.getByLabel('Name', { exact: true }).fill('research');
	await page.getByLabel('Model', { exact: true }).fill('gpt-6-luna');
	await page.getByLabel('Status', { exact: true }).selectOption('research');
	await page.getByLabel('Credential source', { exact: true }).selectOption('profile');
	await page.getByLabel('Credential profile', { exact: true }).selectOption('capture');
	await page.getByLabel('Research reasoning effort', { exact: true }).selectOption('high');
	await expect(page.getByText(/reasoning tokens share the 2400/i)).not.toBeVisible();
	await page.getByText('Reasoning and request limits', { exact: true }).click();
	await expect(page.getByText(/reasoning tokens share the 2400/i)).toBeVisible();
	await page
		.getByRole('dialog')
		.screenshot({ path: test.info().outputPath('research-profile-editor.png') });
	await page.getByRole('dialog').getByRole('button', { name: 'Save', exact: true }).click();
	await expect(page.getByRole('dialog')).not.toBeVisible();
	expect(writes).toEqual([
		expect.objectContaining({
			name: 'research',
			model: 'gpt-6-luna',
			status: 'research',
			credential_source: 'profile',
			credential_profile_name: 'capture',
			research_reasoning_effort: 'high',
		}),
	]);
	expect(writes[0]).not.toHaveProperty('api_key');
	await page.reload();
	await expect(section.getByText('research', { exact: true }).first()).toBeVisible();
	expect(profiles[0].status).toBe('primary');
});

test('profile edits retain masked keys and refresh the effective model and source', async ({
	page,
	api,
}) => {
	let profile = {
		name: 'capture',
		model: 'gpt-4.1',
		status: 'primary',
		has_api_key: true,
		api_base: null,
		credential_source: 'own',
		credential_profile_name: null,
		research_reasoning_effort: null,
		research_assigned: true,
	};
	const writes: Record<string, unknown>[] = [];
	api.on('GET', '/api/llm/profiles', () =>
		json({
			profiles: [profile],
			reasoning_options: { 'gpt-6-luna': ['none', 'low', 'medium', 'high', 'xhigh', 'max'] },
		})
	);
	api.on('GET', '/api/config', () =>
		json({
			...config(),
			llm_model: profile.model,
			llm_model_source: 'profile',
			llm_profile_name: 'capture',
			llm_credential_source: 'own',
			llm_has_api_key: true,
			research_model: profile.model,
			research_enabled: true,
		})
	);
	api.on('PUT', '/api/llm/profiles/capture', (request) => {
		const payload = request.postDataJSON();
		writes.push(payload);
		profile = { ...profile, ...payload };
		return json(profile);
	});
	await page.goto('/settings');
	await page.getByRole('button', { name: 'Show Details', exact: true }).click();
	await expect(page.getByText(/saved Primary profile \(capture\)/)).toBeVisible();
	await page.getByRole('button', { name: 'Edit profile', exact: true }).click();
	await expect(page.getByLabel('API Key', { exact: true })).toHaveValue('');
	await page.getByLabel('Model', { exact: true }).fill('gpt-6-luna');
	await page.getByLabel('Research reasoning effort', { exact: true }).selectOption('high');
	await page.getByRole('dialog').getByRole('button', { name: 'Save', exact: true }).click();
	await expect(page.getByRole('dialog')).not.toBeVisible();
	expect(writes[0]).not.toHaveProperty('api_key');
	await expect(page.getByText('+ Research', { exact: true })).toBeVisible();
	const about = page
		.locator('section')
		.filter({ has: page.getByRole('heading', { name: 'About', exact: true }) });
	await expect(about.getByText('gpt-6-luna', { exact: true })).toBeVisible();
	await page.getByRole('button', { name: 'Edit profile', exact: true }).click();
	await expect(page.getByLabel('Research reasoning effort', { exact: true })).toHaveValue('high');
	await page.getByLabel('Research reasoning effort', { exact: true }).selectOption('');
	await page.getByRole('dialog').getByRole('button', { name: 'Save', exact: true }).click();
	expect(writes[1].research_reasoning_effort).toBeNull();
});

test('research role conflicts surface inline and unknown models offer only provider default', async ({
	page,
	api,
}) => {
	api.on('GET', '/api/llm/profiles', () =>
		json({
			profiles: [
				{
					name: 'capture',
					model: 'unknown-exact-model',
					status: 'primary',
					has_api_key: true,
					api_base: null,
					credential_source: 'own',
				},
			],
			reasoning_options: {},
		})
	);
	api.on('PUT', '/api/llm/profiles/capture', () =>
		json({ detail: 'Keep capture configured: use the research selector instead' }, 400)
	);
	await page.goto('/settings');
	await page.getByRole('button', { name: 'Edit profile', exact: true }).click();
	await expect(
		page.getByLabel('Research reasoning effort', { exact: true }).locator('option')
	).toHaveCount(1);
	await expect(
		page.getByText('No verified reasoning options for this exact model. Leave unset.')
	).toBeVisible();
	await page.getByLabel('Status', { exact: true }).selectOption('research');
	await page.getByRole('dialog').getByRole('button', { name: 'Save', exact: true }).click();
	await expect(page.getByRole('dialog').getByRole('alert')).toContainText(
		'Keep capture configured'
	);
	await expect(page.getByLabel('Model', { exact: true })).toHaveValue('unknown-exact-model');
});

test('a profile save with inconsistent readback is not reported as verified', async ({
	page,
	api,
}) => {
	const profile = {
		name: 'capture',
		model: 'gpt-4.1',
		status: 'primary',
		has_api_key: true,
		api_base: null,
	};
	api.on('GET', '/api/llm/profiles', () => json({ profiles: [profile] }));
	api.on('PUT', '/api/llm/profiles/capture', () => json({ ...profile, model: 'gpt-6-luna' }));
	await page.goto('/settings');
	await page.getByRole('button', { name: 'Edit profile', exact: true }).click();
	await page.getByLabel('Model', { exact: true }).fill('gpt-6-luna');
	await page.getByRole('dialog').getByRole('button', { name: 'Save', exact: true }).click();
	await expect(page.getByRole('alert')).toContainText('readback differs');
});

for (const viewport of [
	{ width: 1280, height: 720 },
	{ width: 390, height: 844 },
]) {
	test(`research profile editor stays reachable at ${viewport.width}px`, async ({ page }) => {
		await page.setViewportSize(viewport);
		await page.goto('/settings');
		await page
			.locator('section')
			.filter({ has: page.getByRole('heading', { name: 'AI Models', exact: true }) })
			.getByRole('button', { name: 'Add', exact: true })
			.click();
		await page.getByLabel('Model', { exact: true }).fill('gpt-6-luna');
		await page.getByLabel('Status', { exact: true }).selectOption('research');
		const heading = page.getByRole('heading', { name: 'New Profile', exact: true });
		expect((await heading.boundingBox())?.y).toBeGreaterThanOrEqual(0);
		const save = page.getByRole('dialog').getByRole('button', { name: 'Save', exact: true });
		await save.scrollIntoViewIfNeeded();
		const box = await save.boundingBox();
		expect(box).not.toBeNull();
		expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height);
		expect((await heading.boundingBox())?.y).toBeGreaterThanOrEqual(0);
		await page.screenshot({
			path: test.info().outputPath(`profile-save-${viewport.width}.png`),
			animations: 'disabled',
		});
	});
}
