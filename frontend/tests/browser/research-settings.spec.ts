import { test, expect } from './fixtures/test';
import { json } from './fixtures/api';

test('research switch reuses the sole existing profile and reloads saved settings without a probe', async ({
	page,
	api,
}, testInfo) => {
	let enabled = false;
	api.on('GET', '/api/settings/research', () =>
		json({
			enabled,
			profile_name: enabled ? 'existing' : null,
			profiles: [{ name: 'existing', model: 'gpt-4.1', eligible: true, reason: null }],
		})
	);
	api.on('PUT', '/api/settings/research', (request) => {
		expect(request.postDataJSON()).toEqual({ enabled: true, profile_name: 'existing' });
		enabled = true;
		return json({
			enabled: true,
			profile_name: 'existing',
			profiles: [{ name: 'existing', model: 'gpt-4.1', eligible: true, reason: null }],
		});
	});
	await page.goto('/settings');
	await expect(page.getByRole('switch', { name: 'Enable product research' })).not.toBeChecked();
	// State only changes after server readback, not optimistically on the click.
	await page.getByRole('switch', { name: 'Enable product research' }).click();
	await expect(page.getByRole('switch', { name: 'Enable product research' })).toBeChecked();
	await expect(
		page.getByText('Research settings saved. No provider request was made.')
	).toBeVisible();
	await page.reload();
	await expect(page.getByRole('switch', { name: 'Enable product research' })).toBeChecked();
	await page
		.locator('#product-research')
		.screenshot({ path: testInfo.outputPath('research-settings.png') });
	expect(api.requests.filter((request) => request.method() === 'POST')).toHaveLength(0);
});

test('readback disagreement is not reported as a successful settings save', async ({
	page,
	api,
}) => {
	const state = {
		enabled: false,
		profile_name: 'existing',
		profiles: [{ name: 'existing', model: 'gpt-4.1', eligible: true, reason: null }],
	};
	api.on('GET', '/api/settings/research', () => json(state));
	api.on('PUT', '/api/settings/research', () => json({ ...state, enabled: true }));
	await page.goto('/settings');
	await page.getByRole('switch', { name: 'Enable product research' }).click();
	await expect(
		page.getByText('Save outcome could not be verified.', { exact: false })
	).toBeVisible();
	await expect(
		page.getByText('Research settings saved. No provider request was made.')
	).toHaveCount(0);
});

test('multiple research profiles require a choice and failed save requires readback', async ({
	page,
	api,
}) => {
	const profiles = [
		{ name: 'first', model: 'gpt-4.1', eligible: true, reason: null },
		{ name: 'second', model: 'gpt-4.1-mini', eligible: true, reason: null },
		{
			name: 'local',
			model: 'ollama/local',
			eligible: false,
			reason: 'Use an existing key, an unprefixed OpenAI model name and no custom API base.',
		},
	];
	api.on('GET', '/api/settings/research', () =>
		json({ enabled: false, profile_name: null, profiles })
	);
	api.on('PUT', '/api/settings/research', (request) => {
		expect(request.postDataJSON()).toEqual({ enabled: true, profile_name: 'second' });
		return json({ detail: 'Synthetic storage failure' }, 500);
	});
	await page.goto('/settings');
	await expect(page.getByRole('switch', { name: 'Enable product research' })).toBeDisabled();
	await expect(page.getByText('local: Use an existing key', { exact: false })).toBeVisible();
	await page.getByLabel('Research profile', { exact: true }).selectOption('second');
	expect(api.requests.filter((request) => request.method() === 'PUT')).toHaveLength(0);
	await page.getByRole('switch', { name: 'Enable product research' }).click();
	await expect(
		page.getByText('Save outcome could not be verified.', { exact: false })
	).toBeVisible();
	await expect(page.getByRole('switch', { name: 'Enable product research' })).toHaveCount(0);
	await page.getByRole('button', { name: 'Reload research settings' }).click();
	await expect(page.getByRole('switch', { name: 'Enable product research' })).not.toBeChecked();
	expect(api.requests.filter((request) => request.method() === 'POST')).toHaveLength(0);
});
