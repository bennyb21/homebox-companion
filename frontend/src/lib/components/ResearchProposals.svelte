<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';

	import { autosize } from '$lib/actions/autosize';
	import { researchProposalLabel, type ResearchProposal } from '$lib/api/research';
	let {
		proposals = $bindable(),
		selected = $bindable(),
		disabled = false,
	}: {
		proposals: ResearchProposal[];
		selected: number[];
		disabled?: boolean;
	} = $props();
	// Classification is captured when results arrive, never from the edited value.
	const changed = $derived(
		proposals.map((p, index) => ({ p, index })).filter(({ p }) => !p.unchanged)
	);
	const unchanged = $derived(
		proposals.map((p, index) => ({ p, index })).filter(({ p }) => p.unchanged)
	);
	const prefix = $props.id();
	const selectedCount = $derived(proposals.filter((_, index) => selected.includes(index)).length);
	const allSelected = $derived(proposals.length > 0 && selectedCount === proposals.length);
</script>

{#snippet row(proposal: ResearchProposal, index: number)}
	<div class="space-y-1" data-proposal-index={index}>
		<div class="flex items-center gap-2">
			<input
				type="checkbox"
				id="{prefix}-select-{index}"
				aria-label={t('Adopt {p0}', { p0: researchProposalLabel(proposal) })}
				bind:group={selected}
				value={index}
				{disabled}
			/>
			<label
				id="{prefix}-label-{index}"
				for="{prefix}-value-{index}"
				class="text-body-sm font-medium text-neutral-200">{researchProposalLabel(proposal)}</label
			>
		</div>
		{#if proposal.current && proposal.current !== proposal.value}<p
				class="text-caption text-neutral-400"
			>
				{t('Current:')}
				{proposal.current}
			</p>{/if}
		{#if proposal.multiline}
			<textarea
				id="{prefix}-value-{index}"
				class="input max-h-72 resize-none overflow-y-auto"
				rows="2"
				use:autosize={proposal.value}
				maxlength="1200"
				bind:value={proposal.value}
				{disabled}></textarea>
		{:else}
			<input
				id="{prefix}-value-{index}"
				class="input"
				type="text"
				maxlength="1200"
				bind:value={proposal.value}
				{disabled}
			/>
		{/if}
	</div>
{/snippet}
<div class="space-y-3">
	{#if proposals.length}
		<label
			class="flex min-h-touch items-center gap-2 text-body-sm font-medium text-neutral-200"
			title={t('Select all proposals, including unchanged fields')}
		>
			<input
				type="checkbox"
				checked={allSelected}
				indeterminate={selectedCount > 0 && !allSelected}
				onchange={(event) => {
					selected = event.currentTarget.checked ? proposals.map((_, index) => index) : [];
				}}
				{disabled}
			/>
			{t('Select all')}
		</label>
	{/if}
	{#each changed as { p, index } (index)}{@render row(p, index)}{/each}
	{#if unchanged.length}
		<details>
			<summary class="min-h-touch cursor-pointer py-3 text-body-sm text-neutral-400"
				>{t('Unchanged fields (')}{unchanged.length})</summary
			>
			<div class="space-y-3">
				{#each unchanged as { p, index } (index)}{@render row(p, index)}{/each}
			</div>
		</details>
	{/if}
</div>
