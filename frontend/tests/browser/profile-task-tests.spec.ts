import { test, expect } from './fixtures/test';
import { json } from './fixtures/api';

for (const width of [1280, 390]) {
	test(`explicit profile tests persist diagnostics without activating an Off profile at ${width}px`, async ({
		page,
		api,
	}) => {
		await page.setViewportSize({ width, height: 844 });
		const profiles = [
			{
				name: 'default',
				model: 'gpt-6-luna',
				status: 'primary',
				research_assigned: true,
				has_api_key: true,
				api_base: null,
			},
			{
				name: 'Recherche',
				model: 'gpt-6-terra',
				status: 'off',
				research_assigned: false,
				has_api_key: true,
				api_base: null,
			},
		];
		api.on('GET', '/api/llm/profiles', () => json({ profiles }));
		api.on('GET', '/api/settings/research', () =>
			json({
				enabled: true,
				profile_name: 'default',
				profiles: profiles.map((p) => ({ ...p, eligible: true })),
			})
		);
		const tests: Record<string, unknown>[] = [];
		api.on('POST', '/api/llm/profiles/Recherche/test', (r) => {
			const body = r.postDataJSON();
			tests.push(body);
			return json(
				body.test_kind === 'research'
					? {
							success: true,
							message: 'Research pipeline completed.',
							research_result: {
								status: 'no_results',
								sources: [],
								diagnostic: {
									code: 'no_evidence',
									stage: 'parse',
									message: 'No supported product match.',
									request_id: 'req_test',
								},
							},
						}
					: {
							success: false,
							message: 'Exact model could not be resolved. Check its identifier.',
							diagnostic: {
								code: 'provider_resolution_failed',
								stage: 'provider_resolution',
								dispatch_started: false,
							},
						}
			);
		});
		await page.goto('/settings');
		const researchSection = page.locator('#product-research');
		const researchSwitch = researchSection.getByRole('switch', { name: 'Enable product research' });
		await expect(researchSwitch).toBeChecked();
		expect((await researchSwitch.boundingBox())!.height).toBeGreaterThanOrEqual(44);
		await researchSection.screenshot({
			path: test.info().outputPath(`research-settings-${width}.png`),
		});
		const row = page.getByRole('group', { name: 'Profile Recherche', exact: true });
		await row.getByRole('button', { name: 'Check API access', exact: true }).click();
		await expect(
			page.getByText('Exact model could not be resolved. Check its identifier.', { exact: true })
		).toBeVisible();
		await page.waitForTimeout(5500); // Regression: the old result vanished after five seconds.
		await expect(page.getByText('provider_resolution_failed', { exact: true })).toBeVisible();
		expect(tests).toEqual([{ test_kind: 'connection' }]);
		await row.getByRole('button', { name: 'Run research test', exact: true }).click();
		await expect(page.getByRole('dialog')).toContainText('may incur API costs');
		await expect(page.getByRole('dialog')).toContainText('Recherche — gpt-6-terra');
		await expect(
			page.getByRole('dialog').getByLabel('Identifier kind', { exact: true })
		).toHaveCount(0);
		await page
			.getByRole('dialog')
			.getByLabel('Product context', { exact: true })
			.fill('Example Maker pump MODEL-A, label PART-02');
		expect(tests).toEqual([{ test_kind: 'connection' }]);
		await page
			.getByRole('dialog')
			.getByRole('button', { name: 'Run paid research test', exact: true })
			.click();
		await expect(page.getByText(/No supported product match found/)).toBeVisible();
		expect(tests).toEqual([
			{ test_kind: 'connection' },
			{
				test_kind: 'research',
				context: { description: 'Example Maker pump MODEL-A, label PART-02' },
			},
		]);
		await expect(
			page
				.locator('#product-research')
				.getByText('Research uses: default — gpt-6-luna', { exact: true })
		).toBeVisible();
		expect(
			api.requests.filter(
				(r) => ['POST', 'PUT', 'DELETE'].includes(r.method()) && !r.url().endsWith('/test')
			)
		).toHaveLength(0);
		await page.getByText('Diagnostic details', { exact: true }).click();
		await page.getByRole('textbox', { name: 'Safe diagnostic details' }).scrollIntoViewIfNeeded();
		await page.screenshot({ path: test.info().outputPath(`profile-result-${width}.png`) });
	});
}
