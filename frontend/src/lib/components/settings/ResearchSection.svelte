<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { request } from '$lib/api/client';
	import Button from '$lib/components/Button.svelte';
	import Switch from '$lib/components/Switch.svelte';
	let {
		onedit,
		oncreate,
		editorReady,
	}: { onedit: (name: string) => void; oncreate: () => void; editorReady: boolean } = $props();

	type ResearchSettings = {
		enabled: boolean;
		profile_name: string | null;
		profiles: { name: string; model: string; eligible: boolean; reason: string | null }[];
	};
	let settings = $state<ResearchSettings | null>(null);
	let selected = $state('');
	let busy = $state(false);
	let reloadPending = false;
	let message = $state('');
	let error = $state('');
	const controller = new AbortController();
	const eligible = $derived(settings?.profiles.filter((profile) => profile.eligible) ?? []);

	onMount(() => {
		void load();
		const changed = () => {
			if (busy) reloadPending = true;
			else void load();
		};
		window.addEventListener('model-profiles-changed', changed);
		return () => window.removeEventListener('model-profiles-changed', changed);
	});
	onDestroy(() => controller.abort());

	async function readSettings() {
		const result = await request<ResearchSettings>('/settings/research', {
			signal: controller.signal,
		});
		if (controller.signal.aborted) return;
		settings = result;
		const choices = result.profiles.filter((profile) => profile.eligible);
		selected = result.profiles.some((profile) => profile.name === result.profile_name)
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
			if (!controller.signal.aborted) {
				busy = false;
				if (reloadPending) {
					reloadPending = false;
					void load();
				}
			}
		}
	}

	async function save(enabled: boolean) {
		if (busy || !settings || (enabled && !eligible.some((p) => p.name === selected))) return;
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
			window.dispatchEvent(new Event('research-assignment-changed'));
		} catch {
			if (!controller.signal.aborted) {
				settings = null;
				error = 'Save outcome could not be verified. Reload research settings before trying again.';
			}
		} finally {
			if (!controller.signal.aborted) {
				busy = false;
				if (reloadPending) {
					reloadPending = false;
					void load();
				}
			}
		}
	}
</script>

<section id="product-research" class="card space-y-3" aria-labelledby="research-settings-heading">
	<h2 id="research-settings-heading" class="text-h3 text-neutral-100">Product research</h2>
	<p class="text-body-sm text-neutral-400">
		Choose which model researches public product information. Enabling and saving settings make no
		provider request. Each search is a separate, explicit action.
	</p>
	{#if settings}
		<Switch
			label="Enable product research"
			checked={settings.enabled}
			disabled={busy || (!settings.enabled && !eligible.some((p) => p.name === selected))}
			onchange={(enabled) => void save(enabled)}
		/>
		<p class="text-body-sm text-neutral-200">
			{settings.enabled ? 'Research uses' : 'Saved research profile'}: {settings.profile_name ||
				'Not selected'}{settings.profile_name
				? ` — ${settings.profiles.find((p) => p.name === settings?.profile_name)?.model || 'Model unavailable'}`
				: ''}
		</p>
		<label class="block" for="research-profile">Research profile</label>
		<select id="research-profile" class="input mt-2" bind:value={selected} disabled={busy}>
			<option value="">Choose an existing OpenAI profile</option>
			{#each settings.profiles as profile (profile.name)}
				<option value={profile.name}
					>{profile.name} — {profile.model}{profile.eligible ? '' : ' (not eligible)'}</option
				>
			{/each}
		</select>
		<div class="flex flex-wrap gap-2">
			<Button
				variant="secondary"
				size="sm"
				disabled={busy || !selected || !editorReady}
				onclick={() => onedit(selected)}>Edit selected profile</Button
			>
			<Button variant="secondary" size="sm" disabled={busy || !editorReady} onclick={oncreate}
				>Create research profile</Button
			>
		</div>
		<p class="text-caption text-neutral-400">
			Editing or testing a profile does not select it for research. Save your selection here.
			Editing a shared Primary profile also changes its capture model; create a research-only
			profile for a different model.
		</p>
		{#if eligible.length === 0}<p>
				No eligible profile yet. Edit a profile or create one using an existing credential.
			</p>{/if}
		{#each settings.profiles.filter((profile) => !profile.eligible) as profile (profile.name)}
			<!-- Server-provided eligibility is shared with settings validation. -->
			<p class="text-body-sm text-neutral-400">{profile.name}: {profile.reason}</p>
		{/each}
		{#if settings.enabled}
			{#if selected && selected !== settings.profile_name}
				<Button
					variant="secondary"
					size="sm"
					disabled={busy || !eligible.some((p) => p.name === selected)}
					onclick={() => save(true)}>Save research profile</Button
				>
			{/if}
		{/if}
		<details class="text-caption text-neutral-400">
			<summary class="min-h-touch cursor-pointer py-3">About eligibility and credentials</summary>
			<p>
				Eligibility uses available model metadata, not a live test. Model access and search quality
				are not verified. Existing Primary/Fallback profiles keep their capture role. Research-only
				profiles can reference the same stored credential; no key is copied.
			</p>
		</details>
	{/if}
	{#if error}<p role="alert">{error}</p>{/if}
	{#if message}<p role="status">{message}</p>{/if}
	<Button variant="secondary" size="sm" disabled={busy} onclick={load}
		>Reload research settings</Button
	>
</section>
