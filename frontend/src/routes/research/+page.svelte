<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { request } from '$lib/api/client';
	import Button from '$lib/components/Button.svelte';
	import DiagnosticDetails from '$lib/components/DiagnosticDetails.svelte';
	import ResearchProfileSummary from '$lib/components/ResearchProfileSummary.svelte';
	import { researchOutcome, type ResearchResult } from '$lib/api/research';
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
			research: ResearchResult;
			proposals: Proposal[];
		};
	};
	let items = $state<{ id: string; name: string }[]>([]);
	let jobs = $state<Job[]>([]);
	let selected = $state<Record<string, number[]>>({});
	let itemId = $state('');
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
					? {
							body: JSON.stringify({
								selected: selected[job.id] || [],
								edits: Object.fromEntries(
									(selected[job.id] || []).map((i) => [String(i), job.result!.proposals[i].value])
								),
							}),
						}
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
		message =
			'New paid attempt selected. Review the item and possible additional costs before enqueueing.';
	}
</script>

<AppContainer>
	<div class="space-y-4">
		<h1 class="text-h1 text-neutral-100">Product research jobs</h1>
		<ResearchProfileSummary returnTo="research" />
		<p>
			Product information and associated photos are sent to OpenAI and may incur API costs. No
			automatic changes to Homebox. Unknown outcomes may already have incurred costs. Cancelling
			cannot refund an already dispatched search.
		</p>
		<label
			>Saved item<select aria-label="Saved item" class="input mt-2" bind:value={itemId}
				><option value="">Select item</option>{#each items as item (item.id)}<option value={item.id}
						>{item.name}</option
					>{/each}</select
			></label
		>

		<Button variant="secondary" size="sm" type="button" onclick={create} disabled={busy || !itemId}
			>Research this item</Button
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
				{#if job.result?.research}<p>
						{researchOutcome(job.result.research.status, job.result.research.diagnostic)}
					</p>{/if}
				{#if job.result?.research.diagnostic}<DiagnosticDetails
						diagnostic={job.result.research.diagnostic}
					/>{/if}
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
					<p>AI suggestions; not independently verified. {job.result.research.ambiguity || ''}</p>
					<p>Provider citations:</p>
					<!-- eslint-disable svelte/no-navigation-without-resolve -- Server-validated external citations -->
					{#each job.result.research.sources ?? [] as source (source.url)}<a
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
							<p>Current: {proposal.current || '(empty)'}</p>
							<label
								>Proposed {proposal.name}<textarea
									class="input mt-2"
									maxlength="1200"
									bind:value={proposal.value}></textarea></label
							>
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
						<Button
							variant="secondary"
							size="sm"
							type="button"
							disabled={busy}
							onclick={() => action(job, 'cancel')}>Discard suggestions</Button
						>
					{/if}
				{/if}
			</section>
		{/each}
	</div>
</AppContainer>
