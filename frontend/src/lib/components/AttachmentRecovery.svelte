<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';

	import { onMount } from 'svelte';
	import { scanWorkflow as workflow } from '$lib/workflows/scan.svelte';
	import { getConfig } from '$lib/api/settings';
	import { fileToDataUrl } from '$lib/services/serialize';
	import Button from './Button.svelte';
	let homeboxUrl = $state<string | null>(null);
	let error = $state('');
	const rows = $derived(workflow.state.confirmedItems);
	const statuses = $derived(workflow.state.itemStatuses);
	onMount(() => {
		let disposed = false;
		void getConfig()
			.then((config) => {
				if (!disposed) homeboxUrl = config.homebox_url;
			})
			.catch(() => {});
		return () => {
			disposed = true;
		};
	});
	async function download(file: File) {
		try {
			const link = document.createElement('a');
			link.href = await fileToDataUrl(file);
			link.download = file.name;
			link.click();
		} catch {
			error = t('Could not download this retained photo. Keep this draft and try again.');
		}
	}
</script>

{#if Object.values(statuses).includes('partial_success')}
	<section
		aria-label={t('Retained photos')}
		class="mb-6 w-full rounded-xl border border-warning-500/30 bg-warning-500/10 p-4 text-left"
	>
		<h3 class="text-body font-semibold text-warning-300">
			{t('Retained photos — manual recovery')}
		</h3>
		<p class="mt-2 text-body-sm text-neutral-300">
			{t(
				'Check the existing item in Homebox before uploading these originals manually. An unconfirmed upload may already exist. No photo is automatically retried. Newly verified photos have a technical unique filename suffix.'
			)}
		</p>
		{#each rows as item, index (index)}
			{#if statuses[index] === 'partial_success'}
				{@const id = workflow.submissionCheckpoint.createdItemIds[index]}
				<div class="mt-4 space-y-2">
					<p class="text-body-sm text-neutral-100">{item.name}</p>
					{#if id}
						<p class="break-all text-caption text-neutral-300">{t('Homebox item:')} {id}</p>
						{#if homeboxUrl}
							<!-- eslint-disable svelte/no-navigation-without-resolve -- External Homebox URL, not an app route --><a
								class="text-primary-400 underline"
								href={`${homeboxUrl.replace(/\/$/, '')}/item/${encodeURIComponent(id)}`}
								target="_blank"
								rel="noopener noreferrer">{t('Review existing item in Homebox')}</a
							>{/if}
					{/if}
					{#each [item.originalFile, ...(item.additionalImages ?? [])].filter((file): file is File => !!file) as file, photoIndex (photoIndex)}
						<Button variant="secondary" full onclick={() => download(file)}
							>{t('Download original photo')} {photoIndex + 1}: {file.name}</Button
						>
					{/each}
					{#each workflow.submissionCheckpoint.photoAttempts[index] ?? [] as attempt, attemptIndex (attemptIndex)}
						<p class="text-caption text-neutral-300">
							{t('Photo')}
							{Number(attempt.slot) + 1}: {attempt.state} — {attempt.original_filename}
						</p>
					{/each}
				</div>
			{/if}
		{/each}
		{#if error}<p role="alert" class="text-body-sm text-warning-300">{error}</p>{/if}
	</section>
{/if}
