<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { request } from '$lib/api/client';
	import Button from '$lib/components/Button.svelte';

	type ResearchSettings = {
		enabled: boolean;
		profile_name: string | null;
		profiles: { name: string; model: string; eligible: boolean; reason: string | null }[];
	};
	let settings = $state<ResearchSettings | null>(null);
	let selected = $state('');
	let busy = $state(false);
	let message = $state('');
	let error = $state('');
	const controller = new AbortController();
	const eligible = $derived(settings?.profiles.filter((profile) => profile.eligible) ?? []);

	onMount(() => {
		void load();
	});
	onDestroy(() => controller.abort());

	async function readSettings() {
		const result = await request<ResearchSettings>('/settings/research', {
			signal: controller.signal,
		});
		if (controller.signal.aborted) return;
		settings = result;
		const choices = result.profiles.filter((profile) => profile.eligible);
		selected = choices.some((profile) => profile.name === result.profile_name)
			? result.profile_name!
			: choices.length === 1
				? choices[0].name
				: '';
		return result;
	}

	async function load() {
		if (busy) return;
		busy = true;
		error = '';
		settings = null;
		message = '';
		try {
			await readSettings();
		} catch {
			if (!controller.signal.aborted)
				error = 'Cannot load research settings. Retry before changing them.';
		} finally {
			if (!controller.signal.aborted) busy = false;
		}
	}

	async function save(enabled: boolean) {
		if (busy || !settings) return;
		busy = true;
		error = '';
		message = '';
		const profileName = selected || null;
		try {
			await request<ResearchSettings>('/settings/research', {
				method: 'PUT',
				signal: controller.signal,
				skipAuthRetry: true,
				body: JSON.stringify({ enabled, profile_name: profileName }),
			});
			const saved = await readSettings();
			if (saved && (saved.enabled !== enabled || saved.profile_name !== profileName)) {
				throw new Error('Settings readback differs from the requested state');
			}
			if (!controller.signal.aborted)
				message = 'Research settings saved. No provider request was made.';
		} catch {
			if (!controller.signal.aborted) {
				settings = null;
				error = 'Save outcome could not be verified. Reload research settings before trying again.';
			}
		} finally {
			if (!controller.signal.aborted) busy = false;
		}
	}
</script>

<section id="product-research" class="card space-y-3" aria-labelledby="research-settings-heading">
	<h2 id="research-settings-heading" class="text-h3 text-neutral-100">Product research</h2>
	<p class="text-body-sm text-neutral-400">
		Optional paid product searches, started explicitly for each item. Enabling makes no provider
		call. Reuses an existing profile and its stored key; no key is copied or requested here.
	</p>
	{#if settings}
		<label class="flex min-h-touch items-center gap-3">
			<input
				type="checkbox"
				role="switch"
				checked={settings.enabled}
				disabled={busy || (!settings.enabled && !selected)}
				onchange={(event) => {
					const enabled = event.currentTarget.checked;
					void save(enabled);
				}}
			/>
			Enable product research
		</label>
		{#if eligible.length > 1}
			<label class="block" for="research-profile">Research profile</label>
			<select id="research-profile" class="input mt-2" bind:value={selected} disabled={busy}>
				<option value="">Choose an existing OpenAI profile</option>
				{#each eligible as profile (profile.name)}<option value={profile.name}
						>{profile.name} — {profile.model}</option
					>{/each}
			</select>
		{:else if eligible.length === 1}
			<p>Existing profile: {eligible[0].name} — {eligible[0].model}</p>
		{:else}
			<p>
				No eligible existing profile. Edit an AI model profile below/above, keeping its stored API
				key, then reload research settings.
			</p>
		{/if}
		{#each settings.profiles.filter((profile) => !profile.eligible) as profile (profile.name)}
			<!-- Server-provided eligibility is shared with settings validation. -->
			<p class="text-body-sm text-neutral-400">{profile.name}: {profile.reason}</p>
		{/each}
		{#if settings.enabled}
			<p>Saved research profile: {settings.profile_name || '(none)'}</p>
			{#if selected && selected !== settings.profile_name}
				<Button variant="secondary" size="sm" disabled={busy} onclick={() => save(true)}
					>Save research profile</Button
				>
			{/if}
		{/if}
		<p class="text-caption text-neutral-400">
			Eligibility uses the installed model catalog, not a live test. API key validity, model access,
			billing and search quality are not verified.
		</p>
	{/if}
	{#if error}<p role="alert">{error}</p>{/if}
	{#if message}<p role="status">{message}</p>{/if}
	<Button variant="secondary" size="sm" disabled={busy} onclick={load}
		>Reload research settings</Button
	>
</section>
