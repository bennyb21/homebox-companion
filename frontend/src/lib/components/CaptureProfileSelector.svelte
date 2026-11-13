<script lang="ts">
	import { onMount } from 'svelte';
	import { request } from '$lib/api/client';

	let {
		value,
		disabled = false,
		onChange,
	}: {
		value?: string | null;
		disabled?: boolean;
		onChange: (entityTypeId: string | null, templateId: string | null) => void;
	} = $props();
	let profiles = $state<{ id: string; name: string; defaultTemplateId?: string | null }[]>([]);
	let error = $state('');
	onMount(() => {
		const controller = new AbortController();
		request<typeof profiles>('/capture-profiles', { signal: controller.signal })
			.then((rows) => {
				profiles = rows;
			})
			.catch((err) => {
				if (!controller.signal.aborted) error = String(err);
			});
		return () => controller.abort();
	});
</script>

<label class="block text-body-sm text-neutral-200">
	Item type
	<select
		class="input mt-2"
		{disabled}
		value={value ?? ''}
		onchange={(event) => {
			if (event.currentTarget.value === '__auto__') {
				onChange('__auto__', null);
				return;
			}
			const selected = profiles.find((row) => row.id === event.currentTarget.value);
			onChange(selected?.id ?? null, selected?.defaultTemplateId ?? null);
		}}
	>
		<option value="">Default (no capture profile)</option>
		<option value="__auto__">Automatic suggestion</option>
		{#if value && value !== '__auto__' && !profiles.some((row) => row.id === value)}
			<option {value}>Unavailable selected type — select again</option>
		{/if}
		{#each profiles as profile (profile.id)}
			<option value={profile.id}>{profile.name}</option>
		{/each}
	</select>
</label>
<p class="text-caption text-neutral-400">
	Native text templates only. Automatic suggestions add one extraction call per object with fields;
	uncertain choices require an explicit type and retry. Manual selection takes precedence.
</p>
{#if error}<p role="alert" class="text-body-sm text-neutral-200">
		Could not load item types: {error}
	</p>{/if}
