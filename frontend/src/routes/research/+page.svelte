<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { request } from '$lib/api/client';
	import Button from '$lib/components/Button.svelte';
	import { createUuidV4 } from '$lib/utils/uuid';
	import { getInitPromise } from '$lib/services/bootstrap';
	import AppContainer from '$lib/components/AppContainer.svelte';
	type Proposal = {
		name: string;
		current: string;
		value: string;
		evidence: string;
		source_urls: string[];
	};
	type Job = {
		id: string;
		item: string;
		state: string;
		result: null | {
			research: { sources: { url: string; title: string }[] };
			proposals: Proposal[];
		};
	};
	let items = $state<{ id: string; name: string }[]>([]);
	let jobs = $state<Job[]>([]);
	let selected = $state<Record<string, number[]>>({});
	let itemId = $state('');
	let identifier = $state('');
	let manufacturer = $state('');
	let kind = $state('part_number');
	let confirmed = $state(false);
	let busy = $state(false);
	let message = $state('');
	let idempotency = createUuidV4();
	let lastPayload = '';
	const controller = new AbortController();
	onDestroy(() => controller.abort());
	async function refresh() {
		jobs = await request<Job[]>('/research/jobs', { signal: controller.signal });
	}
	onMount(() => {
		void (async () => {
			try {
				await getInitPromise();
				items = await request('/items', { signal: controller.signal });
				await refresh();
			} catch {
				message = 'Research jobs unavailable. Capture/save is unaffected.';
			}
		})();
	});
	async function create() {
		if (busy) return;
		busy = true;
		const payload = {
			item_id: itemId,
			identity: {
				identifier_exact: identifier,
				identifier_kind: kind,
				identity_confirmed: confirmed,
				...(manufacturer ? { manufacturer } : {}),
			},
		};
		const digest = JSON.stringify(payload);
		if (lastPayload && lastPayload !== digest) idempotency = createUuidV4();
		lastPayload = digest;
		try {
			await request('/research/jobs', {
				method: 'POST',
				signal: controller.signal,
				skipAuthRetry: true,
				body: JSON.stringify({ ...payload, idempotency_key: idempotency }),
			});
			await refresh();
			message = 'Job queued. Refresh to see progress; browser may be closed.';
		} catch {
			message =
				'Request failed or outcome unknown. Refresh before retrying; identical submissions reuse their key.';
		} finally {
			busy = false;
		}
	}
	async function action(job: Job, action: string) {
		if (busy) return;
		busy = true;
		try {
			await request(`/research/jobs/${job.id}/${action}`, {
				method: 'POST',
				signal: controller.signal,
				skipAuthRetry: true,
				...(action === 'apply'
					? { body: JSON.stringify({ selected: selected[job.id] || [] }) }
					: {}),
			});
			await refresh();
		} catch {
			message =
				'Job changed or rights expired. No automatic retry. For an uncertain write, inspect Homebox.';
		} finally {
			busy = false;
		}
	}
	function newDecision() {
		idempotency = createUuidV4();
		confirmed = false;
		message =
			'New paid attempt selected. Confirm the identifier and possible additional costs before enqueueing.';
	}
</script>

<AppContainer>
	<div class="space-y-4">
		<h1>Product research jobs</h1>
		<p>
			Optional paid research for saved items. No automatic changes to Homebox. Unknown outcomes may
			already have incurred costs. Cancelling cannot refund an already dispatched search.
		</p>
		<label
			>Saved item<select class="input mt-2" bind:value={itemId}
				><option value="">Select item</option>{#each items as item (item.id)}<option value={item.id}
						>{item.name}</option
					>{/each}</select
			></label
		>
		<label class="block text-body-sm text-neutral-200"
			>Manufacturer (optional)<input
				class="input mt-2"
				bind:value={manufacturer}
				maxlength="80"
			/></label
		>
		<label
			>Identifier kind<select class="input mt-2" bind:value={kind}
				><option value="part_number">Part number</option><option value="model_number"
					>Model number</option
				></select
			></label
		>
		<label class="block text-body-sm text-neutral-200"
			>Exact part/model number<input
				class="input mt-2"
				bind:value={identifier}
				maxlength="120"
			/></label
		>
		<label
			><input type="checkbox" bind:checked={confirmed} />I confirm this public part/model number
			(not serial) and authorize one paid research attempt</label
		>
		<Button
			variant="secondary"
			size="sm"
			type="button"
			onclick={create}
			disabled={busy || !confirmed || !itemId || !identifier}>Queue research</Button
		>
		<Button variant="secondary" size="sm" type="button" onclick={newDecision} disabled={busy}
			>Start a new paid attempt</Button
		>
		<Button
			variant="secondary"
			size="sm"
			type="button"
			onclick={() =>
				refresh().catch(() => {
					message = 'Refresh failed';
				})}>Refresh jobs</Button
		>
		<p role="status">{message}</p>
		{#each jobs as job (job.id)}
			<section>
				<h2>{items.find((item) => item.id === job.item)?.name || job.item}</h2>
				<p>{job.state}</p>
				{#if job.state === 'needs_auth'}<Button
						variant="secondary"
						size="sm"
						type="button"
						disabled={busy}
						onclick={() => action(job, 'resume')}>Reauthorize queued job</Button
					>{/if}
				{#if ['queued', 'running', 'dispatching', 'needs_auth'].includes(job.state)}<Button
						variant="secondary"
						size="sm"
						type="button"
						disabled={busy}
						onclick={() => action(job, 'cancel')}>Cancel job</Button
					>{/if}
				{#if job.state === 'unknown_outcome' || job.state === 'apply_unknown'}<p>
						Outcome unknown. Inspect provider billing or Homebox before explicitly starting another
						attempt. No automatic retry.
					</p>{/if}
				{#if job.result}
					<!-- eslint-disable svelte/no-navigation-without-resolve -- Server-validated external citations -->
					{#each job.result.research.sources as source (source.url)}<a
							href={source.url}
							target="_blank"
							rel="noopener noreferrer">{source.title}</a
						>{/each}
					{#if job.state === 'matched'}
						{#each job.result.proposals as proposal, index (index)}
							<label
								><input
									type="checkbox"
									checked={(selected[job.id] || []).includes(index)}
									onchange={(event) => {
										selected[job.id] = event.currentTarget.checked
											? [...(selected[job.id] || []), index]
											: (selected[job.id] || []).filter((i) => i !== index);
									}}
								/>Adopt {proposal.name}</label
							>
							<p>Current: {proposal.current || '(empty)'} → Proposal: {proposal.value}</p>
							<p>{proposal.evidence}</p>
							{#each proposal.source_urls as url (url)}<a
									href={url}
									target="_blank"
									rel="noopener noreferrer">{url}</a
								>{/each}
						{/each}
						<Button
							variant="secondary"
							size="sm"
							type="button"
							disabled={busy || !selected[job.id]?.length}
							onclick={() => action(job, 'apply')}>Apply selected to Homebox</Button
						>
					{/if}
				{/if}
			</section>
		{/each}
	</div>
</AppContainer>
