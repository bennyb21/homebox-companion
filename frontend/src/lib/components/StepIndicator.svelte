<script lang="ts">
	import Check from '@lucide/svelte/icons/check';
	import ConfirmDialog from './ConfirmDialog.svelte';
	import { resetLocationState } from '$lib/stores/locations.svelte';
	let discardOpen = $state(false);
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { scanWorkflow } from '$lib/workflows/scan.svelte';
	const names = ['Location', 'Capture', 'Review', 'Summary'];
	async function visit(step: number) {
		if (!(await scanWorkflow.visitStep(step))) return;
		const routes = [
			resolve('/location'),
			resolve('/capture'),
			resolve('/review'),
			resolve('/summary'),
		];
		// eslint-disable-next-line svelte/no-navigation-without-resolve -- All routes resolved above.
		await goto(routes[step - 1]);
	}

	interface Props {
		currentStep: number;
		totalSteps?: number;
	}

	let { currentStep, totalSteps = 4 }: Props = $props();

	const steps = $derived(Array.from({ length: totalSteps }, (_, i) => i + 1));
</script>

<div class="mb-6 flex items-center justify-center gap-2">
	{#each steps as step (step)}
		{@const index = step - 1}
		{#if index > 0}
			<!-- Connecting line between steps -->
			<span
				class="h-[3px] max-w-12 flex-1 rounded-full transition-colors duration-300"
				class:bg-success-600={step < currentStep}
				class:bg-primary-600={step === currentStep}
				class:bg-neutral-700={step > currentStep}
			></span>
		{/if}
		<!-- Step circle -->
		<button
			type="button"
			aria-label={`Step ${step}: ${names[step - 1]}`}
			aria-current={step === currentStep ? 'step' : undefined}
			disabled={step === currentStep || !scanWorkflow.canVisitStep(step)}
			onclick={() => visit(step)}
			class="flex items-center justify-center rounded-full text-body-sm font-semibold shadow-sm transition-all duration-300 size-10 {step ===
			currentStep
				? 'bg-primary-600 text-neutral-100 ring-4 ring-primary-500/20'
				: step < currentStep
					? 'bg-success-600 text-neutral-100'
					: 'border border-neutral-700 bg-neutral-800 text-neutral-400'}"
		>
			{#if step < currentStep}
				<Check size={20} strokeWidth={2.5} />
			{:else}
				{step}
			{/if}
		</button>
	{/each}
</div>
{#if !scanWorkflow.captureLocked && !scanWorkflow.isAnalyzing && scanWorkflow.state.images.length > 0}
	<button
		type="button"
		class="mb-4 text-caption text-neutral-400 underline"
		onclick={() => {
			discardOpen = true;
		}}>Discard entire draft</button
	>
{/if}
<ConfirmDialog
	open={discardOpen}
	title="Discard entire draft?"
	message="This removes all unsaved photos, results, manual edits and undo history from this capture session. It never deletes items in Homebox."
	confirmLabel="Discard draft"
	onCancel={() => {
		discardOpen = false;
	}}
	onConfirm={async () => {
		if (scanWorkflow.captureLocked || scanWorkflow.isAnalyzing) return;
		await scanWorkflow.clearPersistedSession();
		scanWorkflow.reset(false);
		resetLocationState();
		discardOpen = false;
		await goto(resolve('/location'));
	}}
/>
