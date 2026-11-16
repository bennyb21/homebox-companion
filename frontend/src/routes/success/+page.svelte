<script lang="ts">
	import AttachmentRecovery from '$lib/components/AttachmentRecovery.svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { onMount } from 'svelte';
	import Check from '@lucide/svelte/icons/check';
	import Camera from '@lucide/svelte/icons/camera';
	import MapPin from '@lucide/svelte/icons/map-pin';
	import Eye from '@lucide/svelte/icons/eye';
	import { resetLocationState } from '$lib/stores/locations.svelte';
	import { scanWorkflow } from '$lib/workflows/scan.svelte';
	import { routeGuards } from '$lib/utils/routeGuard';
	import { getInitPromise } from '$lib/services/bootstrap';
	import { captureSessionScope } from '$lib/services/sessionPersistence';
	import Button from '$lib/components/Button.svelte';
	import CreatedItemsModal from '$lib/components/CreatedItemsModal.svelte';

	const workflow = scanWorkflow;
	let initialized = $state(false);
	let hasRecovery = $state(false);
	let recovering = $state(false);
	let recoveryError = $state('');

	// Never inspect another identity's draft while authentication is unresolved.
	$effect(() => {
		const scope = JSON.stringify(captureSessionScope());
		if (!initialized || result || scope === 'null') return;
		let obsolete = false;
		hasRecovery = false;
		void workflow.hasRecoverableSession().then((found) => {
			if (!obsolete && scope === JSON.stringify(captureSessionScope())) hasRecovery = found;
		});
		return () => {
			obsolete = true;
		};
	});

	async function resumeSession() {
		if (recovering || !captureSessionScope()) return;
		recovering = true;
		const scope = JSON.stringify(captureSessionScope());
		const recovered = await workflow.recover();
		recovering = false;
		if (scope !== JSON.stringify(captureSessionScope())) return;
		if (recovered) await goto(resolve('/summary'));
		else recoveryError = 'Could not restore this session. Keep the saved draft and try again.';
	}

	// Get submission result
	const result = $derived(workflow.submissionResult);
	const hasIncompleteItems = $derived(
		Object.values(workflow.state.itemStatuses).some((status) => status === 'partial_success')
	);
	const submissionErrors = $derived(workflow.state.submissionErrors);

	// Animation state - stop ping after a few cycles
	let showPing = $state(true);

	// Modal state
	let showItemsModal = $state(false);

	// Apply route guard: requires authentication only
	onMount(() => {
		let disposed = false;
		let pingTimeout: ReturnType<typeof setTimeout> | undefined;
		void initialize();
		return () => {
			disposed = true;
			clearTimeout(pingTimeout);
		};

		async function initialize() {
			// Wait for auth initialization to complete to avoid race conditions
			// where we check isAuthenticated before initializeAuth clears expired tokens
			await getInitPromise();

			if (disposed || !routeGuards.success()) return;
			initialized = true;

			// Stop the ping animation after 3 seconds
			pingTimeout = setTimeout(() => {
				showPing = false;
			}, 3000);
		}
	});

	function scanMore() {
		// Keep location, start new scan
		if (!workflow.startNew()) return;
		goto(resolve('/capture'));
	}

	function startOver() {
		// Reset everything including location selection UI
		if (!workflow.reset()) return;
		resetLocationState();
		goto(resolve('/location'));
	}

	function handleParentSelected(id: string, name: string) {
		// Do not change the retained context if the discard prompt is declined.
		if (!workflow.startNew()) return;
		workflow.setParentItem(id, name);
		goto(resolve('/capture'));
	}
</script>

<svelte:head>
	<title>Submission - Homebox Companion</title>
</svelte:head>

{#if !result}
	<section aria-label="Submission recovery" class="mx-auto max-w-lg space-y-4 px-4 py-8">
		<h2 class="text-h1 text-neutral-100">Submission status unavailable</h2>
		<p class="text-body text-neutral-300">
			This page cannot confirm that items or photos were saved. Check Homebox before creating them
			again.
		</p>
		{#if initialized && captureSessionScope()}
			{#if hasRecovery}
				<p class="text-body text-warning-300">
					A retained session is available in this collection. Resume it to review warnings, known
					items and original photos. Resuming does not upload or recreate anything.
				</p>
				<Button variant="primary" full disabled={recovering} onclick={resumeSession}
					>Resume Session</Button
				>
			{:else}
				<p class="text-body-sm text-neutral-400">
					No retained session is currently available here.
				</p>
				<Button variant="secondary" full onclick={() => goto(resolve('/location'))}
					>Choose Location</Button
				>
			{/if}
			{#if workflow.state.locationId}
				<Button variant="secondary" full onclick={scanMore}>Scan More Items</Button>
			{/if}
		{:else}
			<p class="text-body-sm text-neutral-400">Waiting for the verified Homebox connection…</p>
		{/if}
		{#if recoveryError}<p role="alert" class="text-body-sm text-warning-300">
				{recoveryError}
			</p>{/if}
	</section>
{:else}
	<div class="animate-in flex min-h-[60vh] flex-col items-center justify-center px-4 text-center">
		<!-- Success animation with animated checkmark -->
		<div class="relative mb-8 size-28">
			<!-- Ping animation (stops after 3 seconds) -->
			{#if showPing}
				<div class="absolute inset-0 animate-ping rounded-full bg-success-500/20"></div>
			{/if}
			<!-- Outer glow ring - scales in -->
			<div class="success-scale absolute inset-0 rounded-full bg-success-500/10"></div>
			<!-- Inner circle - scales in with slight delay -->
			<div
				class="success-scale absolute inset-2 rounded-full bg-success-500/20 animation-delay-100"
			></div>
			<!-- Checkmark icon with draw animation -->
			<div
				class="success-scale absolute inset-0 flex items-center justify-center animation-delay-150"
			>
				<Check class="checkmark-draw text-success-500 size-14" strokeWidth={2.5} />
			</div>
		</div>

		<!-- Heading -->
		<h2 class="mb-3 text-h1 text-neutral-100">
			{hasIncompleteItems ? 'Items need attention' : 'Success!'}
		</h2>

		{#if hasIncompleteItems}
			<div
				class="mb-6 w-full max-w-sm rounded-xl border border-warning-500/30 bg-warning-500/10 p-4 text-left text-body-sm text-warning-300"
				role="status"
			>
				<p>
					Some items were created with incomplete details or attachments. Review and finish them in
					Homebox; they will not be created again by Retry Failed Items.
				</p>
				{#if submissionErrors.length > 0}
					<ul class="mt-2 list-inside list-disc space-y-2">
						{#each submissionErrors as error, index (index)}
							<li>{error}</li>
						{/each}
					</ul>
				{/if}
			</div>
		{/if}

		<!-- Specific feedback with count and location -->
		{#if result}
			<p class="mb-6 text-body text-neutral-300">
				{result.itemCount} item{result.itemCount !== 1 ? 's' : ''} added to {result.locationName}
			</p>

			<!-- Statistics card -->
			<div class="mb-8 w-full max-w-sm rounded-2xl border border-neutral-700 bg-neutral-900 p-4">
				<div class="grid grid-cols-2 gap-4 text-center">
					<div>
						<div class="text-2xl font-bold text-primary-400">
							{result.itemCount}
						</div>
						<div class="text-caption text-neutral-500">
							Item{result.itemCount !== 1 ? 's' : ''}
						</div>
					</div>
					{#if !hasIncompleteItems}
						<div>
							<div class="text-2xl font-bold text-primary-400">
								{result.photoCount}
							</div>
							<div class="text-caption text-neutral-500">
								Photo{result.photoCount !== 1 ? 's' : ''}
							</div>
						</div>
					{/if}
				</div>
			</div>
		{:else}
			<p class="mb-8 text-body text-neutral-400">Items have been added to your inventory</p>
		{/if}

		<AttachmentRecovery />

		<!-- Action buttons -->
		<div class="w-full max-w-sm space-y-3">
			<!-- Scan more (with location context) -->
			<Button variant="primary" full onclick={scanMore}>
				<Camera size={20} strokeWidth={1.5} />
				<span>
					{#if workflow.state.parentItemName}
						Scan More in {workflow.state.parentItemName}
					{:else if result?.locationName}
						Scan More in {result.locationName}
					{:else}
						Scan More Items
					{/if}
				</span>
			</Button>

			<!-- Change location -->
			<Button variant="secondary" full onclick={startOver}>
				<MapPin size={20} strokeWidth={1.5} />
				<span>Choose New Location</span>
			</Button>

			<!-- See Items (view created items with details) -->
			{#if result?.createdItems && result.createdItems.length > 0}
				<Button variant="secondary" full onclick={() => (showItemsModal = true)}>
					<Eye size={20} strokeWidth={1.5} />
					<span>See Items</span>
				</Button>
			{/if}
		</div>
	</div>
{/if}

{#if showItemsModal && result?.createdItems}
	<CreatedItemsModal
		items={result.createdItems}
		bind:open={showItemsModal}
		onclose={() => (showItemsModal = false)}
		onScanSubItems={handleParentSelected}
	/>
{/if}
