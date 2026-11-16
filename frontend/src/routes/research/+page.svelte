<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';

	import { onMount, onDestroy } from 'svelte';
	import { request } from '$lib/api/client';
	import Button from '$lib/components/Button.svelte';
	import DiagnosticDetails from '$lib/components/DiagnosticDetails.svelte';
	import ResearchProposals from '$lib/components/ResearchProposals.svelte';
	import ResearchNotice from '$lib/components/ResearchNotice.svelte';
	import { prepareProposals, researchSources, type ResearchProposal } from '$lib/api/research';
	import ResearchProfileSummary from '$lib/components/ResearchProfileSummary.svelte';
	import { researchOutcome, researchJobState, type ResearchResult } from '$lib/api/research';
	import { createUuidV4 } from '$lib/utils/uuid';
	import { getInitPromise } from '$lib/services/bootstrap';
	import AppContainer from '$lib/components/AppContainer.svelte';
	type Proposal = ResearchProposal;
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
	let message = $state<import('$lib/i18n/messages').MessageKey | ''>('');
	let idempotency = createUuidV4();
	let lastPayload = '';
	const controller = new AbortController();
	onDestroy(() => controller.abort());
	async function refresh() {
		const received = await request<Job[]>('/research/jobs', { signal: controller.signal });
		jobs = received.map((job) => ({
			...job,
			result: job.result
				? { ...job.result, proposals: prepareProposals(job.result.proposals) }
				: null,
		}));
		selected = {};
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
		<h1 class="text-h1 text-neutral-100">{t('Product research jobs')}</h1>
		<ResearchProfileSummary returnTo="research" />
		<ResearchNotice />
		<label
			>{t('Saved item')}<select aria-label={t('Saved item')} class="input mt-2" bind:value={itemId}
				><option value="">{t('Select item')}</option>{#each items as item (item.id)}<option
						value={item.id}>{item.name}</option
					>{/each}</select
			></label
		>

		<Button variant="secondary" size="sm" type="button" onclick={create} disabled={busy || !itemId}
			>{t('Research this item')}</Button
		>
		<Button variant="secondary" size="sm" type="button" onclick={newDecision} disabled={busy}
			>{t('Start a new paid attempt')}</Button
		>
		<Button
			variant="secondary"
			size="sm"
			type="button"
			onclick={() =>
				refresh().catch(() => {
					message = 'Refresh failed';
				})}>{t('Refresh jobs')}</Button
		>
		<p role="status">{message ? t(message) : ''}</p>
		{#each jobs as job (job.id)}
			<section>
				<h2>{items.find((item) => item.id === job.item)?.name || job.item}</h2>
				{#if !job.result?.research || job.state !== job.result.research.status}<p>
						{researchJobState(job.state)}
					</p>{/if}
				{#if job.result?.research && !['applied', 'cancelled', 'apply_unknown'].includes(job.state)}<p
					>
						{researchOutcome(job.result.research.status, job.result.research.diagnostic)}
					</p>{/if}
				{#if job.result?.research.diagnostic && job.result.research.status !== 'matched'}<DiagnosticDetails
						diagnostic={job.result.research.diagnostic}
					/>{/if}
				{#if job.state === 'needs_auth'}<Button
						variant="secondary"
						size="sm"
						type="button"
						disabled={busy}
						onclick={() => action(job, 'resume')}>{t('Reauthorize queued job')}</Button
					>{/if}
				{#if ['queued', 'running', 'dispatching', 'needs_auth'].includes(job.state)}<Button
						variant="secondary"
						size="sm"
						type="button"
						disabled={busy}
						onclick={() => action(job, 'cancel')}>{t('Cancel job')}</Button
					>{/if}
				{#if job.state === 'unknown_outcome' || job.state === 'apply_unknown'}<p>
						{t(
							'Outcome unknown. Inspect provider billing or Homebox before explicitly starting another attempt. No automatic retry.'
						)}
					</p>{/if}
				{#if job.result}
					{#if job.result.research.ambiguity}<p>{job.result.research.ambiguity}</p>{/if}
					<p>{t('Sources:')}</p>
					<!-- eslint-disable svelte/no-navigation-without-resolve -- Server-validated external citations -->
					{#each researchSources(job.result.research, job.result.proposals) as source (source.url)}<a
							href={source.url}
							target="_blank"
							rel="noopener noreferrer">{source.title}</a
						>{/each}
					{#if job.state === 'matched'}
						<ResearchProposals
							bind:proposals={job.result.proposals}
							bind:selected={() => selected[job.id] || [], (value) => (selected[job.id] = value)}
							disabled={busy}
						/>
						<Button
							variant="secondary"
							size="sm"
							type="button"
							disabled={busy || !selected[job.id]?.length}
							onclick={() => action(job, 'apply')}>{t('Apply selected to Homebox')}</Button
						>
						<Button
							variant="secondary"
							size="sm"
							type="button"
							disabled={busy}
							onclick={() => action(job, 'cancel')}>{t('Discard suggestions')}</Button
						>
					{/if}
				{/if}
			</section>
		{/each}
	</div>
</AppContainer>
