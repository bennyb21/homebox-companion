<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';

	/**
	 * Settings Page - Thin orchestrator for settings sections.
	 *
	 * This page delegates all state management and business logic to:
	 * - settingsService: Centralized state and API calls
	 * - Section components: UI rendering for each settings area
	 */
	import AlertTriangle from '@lucide/svelte/icons/alert-triangle';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { onMount, onDestroy } from 'svelte';
	import { authStore } from '$lib/stores/auth.svelte';
	import { getInitPromise } from '$lib/services/bootstrap';
	import { settingsService } from '$lib/workflows/settings.svelte';

	import LanguageSection from '$lib/components/settings/LanguageSection.svelte';
	import AccountSection from '$lib/components/settings/AccountSection.svelte';
	import AboutSection from '$lib/components/settings/AboutSection.svelte';
	import FieldPrefsSection from '$lib/components/settings/FieldPrefsSection.svelte';
	import LLMProfilesSection from '$lib/components/settings/LLMProfilesSection.svelte';
	import ResearchSection from '$lib/components/settings/ResearchSection.svelte';
	import LogsSection from '$lib/components/settings/LogsSection.svelte';
	let modelEditor: LLMProfilesSection;
	let editorReady = $state(false);
	let returnTo = $state<'review' | 'research' | null>(null);

	onMount(async () => {
		const requestedReturn = new URLSearchParams(window.location.search).get('return');
		if (requestedReturn === 'review' || requestedReturn === 'research') returnTo = requestedReturn;
		// Wait for auth initialization to complete to avoid race conditions
		// where we check isAuthenticated before initializeAuth clears expired tokens
		await getInitPromise();

		if (!authStore.isAuthenticated) {
			goto(resolve('/'));
			return;
		}

		await settingsService.initialize();
	});

	onDestroy(() => {
		// Clean up any pending timeouts
		settingsService.cleanup();
	});
</script>

<svelte:head>
	<title>{t('Settings - Homebox Companion')}</title>
</svelte:head>

<div class="animate-in space-y-6">
	<div>
		<h1 class="text-h1 font-bold text-neutral-100">{t('Settings')}</h1>
		<p class="mt-1 text-body-sm text-neutral-400">{t('App configuration and information')}</p>
	</div>

	{#if settingsService.errors.init}
		<div class="card border-error-500/30 bg-error-500/10">
			<div class="flex items-start gap-3">
				<AlertTriangle class="mt-0.5 shrink-0 text-error-500" size={20} strokeWidth={1.5} />
				<div>
					<p class="font-medium text-error-500">{t('Failed to load settings')}</p>
					<p class="mt-1 text-body-sm text-neutral-400">{settingsService.errors.init}</p>
					<button
						type="button"
						class="mt-2 text-body-sm text-primary-400 underline hover:text-primary-300"
						onclick={() => settingsService.initialize()}
					>
						{t('Try again')}
					</button>
				</div>
			</div>
		</div>
	{/if}

	<!-- eslint-disable svelte/no-navigation-without-resolve -- Both fixed return targets use resolve; no arbitrary redirect. -->
	{#if returnTo}<a
			class="inline-flex min-h-touch items-center text-primary-400 underline"
			href={returnTo === 'review' ? `${resolve('/review')}#product-research` : resolve('/research')}
			>{returnTo === 'review' ? t('Return to item draft') : t('Return to research jobs')}</a
		>{/if}
	<LanguageSection />
	<AccountSection />
	<AboutSection />
	<LLMProfilesSection bind:this={modelEditor} onavailability={(ready) => (editorReady = ready)} />
	<ResearchSection
		{editorReady}
		onedit={(name) => modelEditor?.openResearchEditor(name)}
		oncreate={() => modelEditor?.openResearchEditor()}
	/>
	<FieldPrefsSection />
	<LogsSection />

	<!-- Bottom spacing for nav -->
	<div class="h-4"></div>
</div>
