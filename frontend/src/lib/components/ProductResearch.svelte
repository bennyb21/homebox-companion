<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';

	import { onDestroy, onMount } from 'svelte';
	import { resolve } from '$app/paths';
	import { request } from '$lib/api/client';
	import Button from '$lib/components/Button.svelte';
	import DiagnosticDetails from '$lib/components/DiagnosticDetails.svelte';
	import ResearchProposals from '$lib/components/ResearchProposals.svelte';
	import ResearchNotice from '$lib/components/ResearchNotice.svelte';
	import { prepareProposals, researchSources, type ResearchProposal } from '$lib/api/research';
	import ResearchProfileSummary from '$lib/components/ResearchProfileSummary.svelte';
	import { researchOutcome, type ResearchResult, type ResearchItemPatch } from '$lib/api/research';
	import { fileToDataUrl } from '$lib/services/serialize';
	import { createUuidV4 } from '$lib/utils/uuid';
	import type { DeepReadonly, ReviewItem } from '$lib/types';
	let {
		item,
		onadopt,
	}: {
		item: DeepReadonly<ReviewItem>;
		onadopt: (patch: Record<string, string>, itemPatch: ResearchItemPatch) => void;
	} = $props();
	type Proposal = ResearchProposal;
	type Review = { id: string; result: ResearchResult; proposals: Proposal[] };
	let enabled = $state(false);
	let busy = $state(false);
	let message = $state<import('$lib/i18n/messages').MessageKey | ''>('');
	let review = $state<Review | null>(null);
	let selected = $state<number[]>([]);
	let controller: AbortController | null = null;
	let base = '';
	let revision = '';
	const fileIds = new WeakMap<File, string>();
	function fileId(file: File) {
		if (!fileIds.has(file)) fileIds.set(file, createUuidV4());
		return fileIds.get(file);
	}
	function snapshot() {
		return JSON.stringify([
			item.reviewId,
			item.entity_type_id,
			item.template_id,
			item.name,
			item.description,
			item.manufacturer,
			item.model_number,
			item.serial_number,
			item.custom_fields,
			item.originalFile && fileId(item.originalFile),
			item.additionalImages?.map(fileId),
			item.compressedDataUrl,
			item.compressedAdditionalDataUrls,
		]);
	}
	function cancel() {
		const wasBusy = busy;
		controller?.abort();
		controller = null;
		busy = false;
		review = null;
		message = wasBusy
			? 'Suggestions discarded. An already dispatched request may still cost money.'
			: 'Suggestions discarded.';
	}
	onDestroy(() => controller?.abort());
	onMount(() => {
		const active = new AbortController();
		controller = active;
		void request<{ enabled: boolean }>('/research/capabilities', { signal: active.signal })
			.then((result) => {
				if (!active.signal.aborted) enabled = result.enabled;
			})
			.catch(() => {
				if (!active.signal.aborted) message = 'Research unavailable. Save remains available.';
			});
	});
	async function lookup() {
		if (busy || !enabled) return;
		busy = true;
		review = null;
		selected = [];
		message = '';
		base = snapshot();
		revision = createUuidV4();
		controller?.abort();
		const active = new AbortController();
		controller = active;
		try {
			const primary = item.originalFile
				? await fileToDataUrl(item.originalFile)
				: item.compressedDataUrl;
			const additional = item.additionalImages?.length
				? await Promise.all(item.additionalImages.map(fileToDataUrl))
				: [...(item.compressedAdditionalDataUrls || [])];
			if (active.signal.aborted || base !== snapshot()) {
				message = 'Draft changed; research was not sent.';
				return;
			}
			const result = await request<Review>('/research/lookups', {
				method: 'POST',
				signal: active.signal,
				skipAuthRetry: true,
				body: JSON.stringify({
					draft_id: item.reviewId,
					revision,
					entity_type_id: item.entity_type_id,
					template_id: item.template_id,
					context: {
						title: item.name || '',
						description: item.description || '',
						manufacturer: item.manufacturer || '',
						model_number: item.model_number || '',
						serial_number: item.serial_number || '',
						technical_fields: item.custom_fields || {},
						images: [...(primary ? [primary] : []), ...additional],
					},
					current_values: item.custom_fields || {},
				}),
			});
			if (active.signal.aborted || base !== snapshot()) {
				message = 'Draft changed; research was not applied.';
				return;
			}
			review = { ...result, proposals: prepareProposals(result.proposals) };
		} catch {
			if (!active.signal.aborted)
				message =
					'Research failed or outcome unknown. Save remains available; do not blindly repeat a paid request.';
		} finally {
			if (controller === active) {
				busy = false;
				controller = null;
			}
		}
	}
	async function adopt() {
		if (!review || busy || snapshot() !== base) {
			message = 'Draft changed; compare again before adoption.';
			return;
		}
		busy = true;
		const active = new AbortController();
		controller = active;
		try {
			const result = await request<{
				patch: Record<string, string>;
				item_patch: ResearchItemPatch;
			}>(`/research/lookups/${review.id}/apply`, {
				method: 'POST',
				signal: active.signal,
				skipAuthRetry: true,
				body: JSON.stringify({
					draft_id: item.reviewId,
					revision,
					selected,
					edits: Object.fromEntries(selected.map((i) => [String(i), review!.proposals[i].value])),
					current_values: item.custom_fields || {},
				}),
			});
			if (!active.signal.aborted && snapshot() === base) {
				onadopt(result.patch, result.item_patch);
				review = null;
				message = 'Selected fields adopted into this draft. Saving remains a separate action.';
			}
		} catch {
			message = 'Review expired or changed. No fields adopted.';
		} finally {
			if (controller === active) {
				busy = false;
				controller = null;
			}
		}
	}
</script>

<!-- eslint-disable svelte/no-navigation-without-resolve -- Provider links are validated HTTP(S) display metadata -->
<div id="product-research" class="space-y-3">
	<ResearchNotice />
	<Button
		variant="secondary"
		size="sm"
		type="button"
		disabled={!enabled || !item.template_id || busy}
		onclick={lookup}>{t('Research this item')}</Button
	>
	{#if !enabled}<p>
			{t('Research is disabled or unavailable. Capture and save remain available.')}
		</p>{/if}
	{#if !item.template_id}<p>
			{t('Select a supported native text template to adopt research fields.')}
		</p>{/if}
	<ResearchProfileSummary />
	<a href={resolve('/research')}>{t('Review saved research jobs')}</a>
	{#if busy}<Button variant="secondary" size="sm" type="button" onclick={cancel}
			>{t('Cancel research')}</Button
		>{/if}
	<p role="status" class="wrap-break-word text-body-sm text-neutral-200">
		{message
			? t(message)
			: review
				? researchOutcome(review.result.status, review.result.diagnostic)
				: ''}
	</p>
	{#if review?.result.diagnostic && review.result.status !== 'matched'}<DiagnosticDetails
			diagnostic={review.result.diagnostic}
		/>{/if}
	{#if review}
		{#if review.result.ambiguity}<p>{review.result.ambiguity}</p>{/if}
		<p>
			{researchSources(review.result, review.proposals).length
				? t('Sources:')
				: t('No usable provider citations were returned.')}
			{#each researchSources(review.result, review.proposals) as source (source.url)}
				<a href={source.url} target="_blank" rel="noopener noreferrer">{source.title}</a>{/each}
		</p>
		<ResearchProposals bind:proposals={review.proposals} bind:selected disabled={busy} />
		{#if review.proposals.length}<Button
				variant="secondary"
				size="sm"
				type="button"
				disabled={!selected.length || busy}
				onclick={adopt}>{t('Adopt selected fields')}</Button
			>{/if}
		<Button variant="secondary" size="sm" type="button" onclick={cancel}
			>{t('Discard suggestions')}</Button
		>
	{/if}
</div>
