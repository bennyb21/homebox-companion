export interface ResearchDiagnostic {
	code: string;
	stage: 'configuration' | 'provider_resolution' | 'dispatch' | 'response' | 'parse';
	message?: string;
	http_status?: number;
	request_id?: string;
	dispatch_started?: boolean;
}

export interface ResearchResult {
	status: string;
	sources?: { url: string; title: string }[];
	diagnostic?: ResearchDiagnostic | null;
}

export interface ResearchSettings {
	enabled: boolean;
	profile_name: string | null;
	profiles: { name: string; model: string; eligible: boolean; reason?: string | null }[];
}

export function researchOutcome(status: string, diagnostic?: ResearchDiagnostic | null): string {
	if (status === 'failed' && diagnostic?.code === 'response_incomplete')
		return researchOutcome('incomplete');
	if (status === 'failed' && diagnostic?.code === 'response_refused')
		return researchOutcome('refused');
	switch (status) {
		case 'matched':
			return 'Research ready. Compare sources and choose which fields to adopt.';
		case 'incomplete':
			return 'Research incomplete. The response did not finish within its limits. No fields are ready to adopt.';
		case 'refused':
			return 'The provider declined this research request. No fields were changed.';
		case 'no_results':
		case 'not_found':
			return 'No supported product match found. This does not prove the product does not exist.';
		case 'unknown_outcome':
			return 'Outcome unknown. This request may already have incurred costs. Check provider activity before deciding on another paid attempt. No automatic retry.';
		case 'failed':
			return 'Research could not be completed. Review the diagnostic below; if none is available, the cause is unknown. Saving your item is still available.';
		default:
			return 'No adoptable research result. Review the status and diagnostics before deciding on another paid attempt.';
	}
}
