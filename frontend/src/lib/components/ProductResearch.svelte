<script lang="ts">
	import { onDestroy } from 'svelte';
	import { request } from '$lib/api/client';
	import type { DeepReadonly, ReviewItem } from '$lib/types';
	let {
		item,
		onadopt,
	}: { item: DeepReadonly<ReviewItem>; onadopt: (patch: Record<string, string>) => void } =
		$props();
	type Proposal = {
		name: string;
		current: string;
		value: string;
		source_urls: string[];
		evidence: string;
	};
	type Review = {
		id: string;
		result: { status: string; sources: { url: string; title: string }[] };
		proposals: Proposal[];
	};
	let opened = $state(false);
	let enabled = $state(false);
	let busy = $state(false);
	let manufacturer = $state('');
	let identifier = $state('');
	let kind = $state('part_number');
	let confirmed = $state(false);
	let message = $state('');
	let review = $state<Review | null>(null);
	let selected = $state<number[]>([]);
	let controller: AbortController | null = null;
	let base = '';
	let revision = '';
	function snapshot() {
		return JSON.stringify([
			item.reviewId,
			item.entity_type_id,
			item.template_id,
			item.custom_fields,
		]);
	}
	function cancel() {
		controller?.abort();
		controller = null;
		busy = false;
		review = null;
		message = 'Research cancelled. Any already dispatched search may still cost money.';
	}
	onDestroy(() => controller?.abort());
	async function open() {
		opened = !opened;
		if (!opened) {
			cancel();
			return;
		}
		manufacturer = item.manufacturer || item.custom_fields?.Manufacturer || '';
		identifier =
			item.custom_fields?.['Part number'] ||
			item.custom_fields?.Teilenummer ||
			item.model_number ||
			'';
		kind =
			item.custom_fields?.['Part number'] || item.custom_fields?.Teilenummer
				? 'part_number'
				: 'model_number';
		try {
			enabled = (await request<{ enabled: boolean }>('/research/capabilities')).enabled;
		} catch {
			message = 'Research unavailable. You can continue saving normally.';
		}
	}
	async function lookup() {
		if (busy) return;
		busy = true;
		review = null;
		selected = [];
		message = '';
		base = snapshot();
		revision = crypto.randomUUID();
		const active = new AbortController();
		controller = active;
		try {
			const result = await request<Review>('/research/lookups', {
				method: 'POST',
				signal: active.signal,
				skipAuthRetry: true,
				body: JSON.stringify({
					draft_id: item.reviewId,
					revision,
					entity_type_id: item.entity_type_id,
					template_id: item.template_id,
					identity: {
						identifier_exact: identifier,
						identifier_kind: kind,
						identity_confirmed: confirmed,
						...(manufacturer ? { manufacturer } : {}),
					},
					current_values: item.custom_fields || {},
				}),
			});
			if (active.signal.aborted || base !== snapshot()) {
				message = 'Draft changed; research was not applied.';
				return;
			}
			review = result;
			message = result.result.status;
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
			const result = await request<{ patch: Record<string, string> }>(
				`/research/lookups/${review.id}/apply`,
				{
					method: 'POST',
					signal: active.signal,
					skipAuthRetry: true,
					body: JSON.stringify({
						draft_id: item.reviewId,
						revision,
						selected,
						current_values: item.custom_fields || {},
					}),
				}
			);
			if (!active.signal.aborted && snapshot() === base) {
				onadopt(result.patch);
				review = null;
				message = 'Selected fields adopted into this draft. Save still requires confirmation.';
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

<!-- eslint-disable svelte/no-navigation-without-resolve -- Server-validated external citations, not application routes -->
<div class="space-y-3">
	<button type="button" onclick={open}>Product research</button>
	{#if opened}
		<p>
			Optional paid product research. No automatic inventory changes. Never enter serial numbers or
			personal notes.
		</p>
		{#if !enabled}<p>
				Research is disabled or unavailable. Capture and save remain available.
			</p>{/if}
		{#if !item.template_id}<p>
				Select a supported native text template to adopt research fields.
			</p>{/if}
		<label>Manufacturer (optional)<input bind:value={manufacturer} maxlength="80" /></label>
		<label
			>Identifier kind<select bind:value={kind}
				><option value="part_number">Part number</option><option value="model_number"
					>Model number</option
				></select
			></label
		>
		<label>Exact part/model number<input bind:value={identifier} maxlength="120" /></label>
		<label
			><input type="checkbox" bind:checked={confirmed} />I confirm this is a public part/model
			number, not a serial number</label
		>
		<button
			type="button"
			disabled={!enabled || !confirmed || !identifier || !item.template_id || busy}
			onclick={lookup}>Research this product</button
		>
		{#if busy}<button type="button" onclick={cancel}>Cancel research</button>{/if}
		<p role="status">{message}</p>
		{#if review}
			{#each review.result.sources as source (source.url)}<a
					href={source.url}
					target="_blank"
					rel="noopener noreferrer">{source.title}</a
				>{/each}
			{#each review.proposals as proposal, index (index)}
				<div>
					<label
						><input type="checkbox" bind:group={selected} value={index} />Adopt {proposal.name}</label
					>
					<p>Current: {proposal.current || '(empty)'} → Proposal: {proposal.value}</p>
					<p>{proposal.evidence}</p>
					{#each proposal.source_urls as url (url)}<a
							href={url}
							target="_blank"
							rel="noopener noreferrer">{url}</a
						>{/each}
				</div>
			{/each}
			<button type="button" disabled={!selected.length || busy} onclick={adopt}
				>Adopt selected fields</button
			>
		{/if}
	{/if}
</div>
