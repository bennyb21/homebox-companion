<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { resolve } from '$app/paths';
	import { request } from '$lib/api/client';
	import type { ResearchSettings } from '$lib/api/research';
	let { returnTo = 'review' }: { returnTo?: 'review' | 'research' } = $props();
	let settings = $state<ResearchSettings | null>(null);
	let unavailable = $state(false);
	const controller = new AbortController();
	const active = $derived(settings?.profiles.find((p) => p.name === settings?.profile_name));
	onMount(() => {
		void request<ResearchSettings>('/settings/research', { signal: controller.signal })
			.then((result) => {
				if (!controller.signal.aborted) settings = result;
			})
			.catch(() => {
				if (!controller.signal.aborted) unavailable = true;
			});
	});
	onDestroy(() => controller.abort());
</script>

<!-- eslint-disable svelte/no-navigation-without-resolve -- Base routes use resolve; query values are encoded and return targets are fixed. -->
<div class="space-y-2 rounded-lg border border-neutral-700 bg-neutral-800/50 p-3 text-body-sm">
	<p class="wrap-break-word font-medium text-neutral-100">
		{active
			? `Research uses: ${active.name} — ${active.model}`
			: unavailable
				? 'Research profile could not be loaded.'
				: settings
					? 'No research profile selected.'
					: 'Loading research profile…'}
	</p>
	{#if settings && !settings.enabled}<p class="text-neutral-400">
			Research is currently disabled.
		</p>{/if}
	<div class="flex flex-wrap gap-3">
		<a
			class="inline-flex min-h-touch items-center text-primary-400 underline"
			href={`${resolve('/settings')}?return=${returnTo}#product-research`}
			>Choose research profile</a
		>
		{#if active}<a
				class="inline-flex min-h-touch items-center text-primary-400 underline"
				href={`${resolve('/settings')}?editProfile=${encodeURIComponent(active.name)}&return=${returnTo}#product-research`}
				>Edit active research profile</a
			>{/if}
	</div>
</div>
