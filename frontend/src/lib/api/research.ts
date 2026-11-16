import { t } from '$lib/i18n/index.svelte';
export interface ResearchProposal {
	name: string;
	current: string;
	value: string;
	source_urls: string[];
	evidence: string;
	unchanged?: boolean;
	multiline?: boolean;
}

/** Preserve server ordering: apply APIs address proposals by their original index. */
export function prepareProposals(proposals: ResearchProposal[]): ResearchProposal[] {
	return proposals.map((proposal) => ({
		...proposal,
		unchanged: proposal.current === proposal.value,
		multiline:
			/description|beschreibung|specification|spezifikation|technical|technische/i.test(
				proposal.name
			) ||
			proposal.value.includes('\n') ||
			proposal.value.length > 160,
	}));
}

export interface ResearchItemPatch {
	name?: string;
	description?: string;
	manufacturer?: string;
	model_number?: string;
}

export interface ResearchDiagnostic {
	code: string;
	stage: 'configuration' | 'provider_resolution' | 'dispatch' | 'response' | 'parse';
	message?: string;
	http_status?: number;
	request_id?: string;
	dispatch_started?: boolean;
}

export interface ResearchResult {
	ambiguity?: string;
	status: string;
	sources?: { url: string; title: string }[];
	diagnostic?: ResearchDiagnostic | null;
}

export interface ResearchSettings {
	enabled: boolean;
	profile_name: string | null;
	profiles: { name: string; model: string; eligible: boolean; reason?: string | null }[];
}

export function researchSources(result: ResearchResult, proposals: ResearchProposal[]) {
	const sources = new Map((result.sources ?? []).map((source) => [source.url, source]));
	for (const proposal of proposals) {
		for (const url of proposal.source_urls ?? []) {
			if (!sources.has(url)) sources.set(url, { url, title: url });
		}
	}
	return [...sources.values()];
}

export function researchJobState(state: string): string {
	switch (state) {
		case 'queued':
			return t('Queued');
		case 'running':
			return t('Running');
		case 'dispatching':
			return t('Sending request');
		case 'needs_auth':
			return t('Authorization required');
		case 'cancelled':
			return t('Cancelled');
		case 'applied':
			return t('Applied');
		case 'apply_unknown':
			return t('Apply outcome unknown');
		default:
			return researchOutcome(state);
	}
}

export function researchOutcome(status: string, diagnostic?: ResearchDiagnostic | null): string {
	if (status === 'failed' && diagnostic?.code === 'response_incomplete')
		return researchOutcome('incomplete');
	if (status === 'failed' && diagnostic?.code === 'response_refused')
		return researchOutcome('refused');
	switch (status) {
		case 'matched':
			return t('Research ready. Compare sources and choose which fields to adopt.');
		case 'incomplete':
			return t(
				'Research incomplete. The response did not finish within its limits. No fields are ready to adopt.'
			);
		case 'refused':
			return t('The provider declined this research request. No fields were changed.');
		case 'no_results':
		case 'not_found':
			return t('No supported product match found. This does not prove the product does not exist.');
		case 'unknown_outcome':
			return t(
				'Outcome unknown. This request may already have incurred costs. Check provider activity before deciding on another paid attempt. No automatic retry.'
			);
		case 'failed':
			return t(
				'Research could not be completed. Review the diagnostic below; if none is available, the cause is unknown. Saving your item is still available.'
			);
		default:
			return t(
				'No adoptable research result. Review the status and diagnostics before deciding on another paid attempt.'
			);
	}
}
