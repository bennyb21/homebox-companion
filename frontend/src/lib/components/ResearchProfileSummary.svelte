<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';

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
<div class="flex flex-wrap items-center gap-x-3 text-caption text-neutral-400">
	<span class="wrap-break-word"
		>{active
			? `${active.name} · ${active.model}`
			: unavailable
				? t('Research profile could not be loaded.')
				: settings
					? t('No research profile selected.')
					: t('Loading research profile…')}</span
	>
	<a
		class="inline-flex min-h-touch items-center text-primary-400 underline"
		href={`${resolve('/settings')}?return=${returnTo}#product-research`}>{t('Research settings')}</a
	>
</div>
