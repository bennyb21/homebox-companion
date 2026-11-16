<script lang="ts">
	import type { ResearchDiagnostic } from '$lib/api/research';
	let { diagnostic }: { diagnostic: ResearchDiagnostic } = $props();
	// Deliberately select only contract fields, never arbitrary metadata/provider bodies.
	const safeDetails = $derived(
		JSON.stringify(
			{
				code: diagnostic.code,
				stage: diagnostic.stage,
				http_status: diagnostic.http_status,
				request_id: diagnostic.request_id,
				dispatch_started: diagnostic.dispatch_started,
			},
			null,
			2
		)
	);
</script>

<div class="space-y-2 wrap-break-word text-body-sm text-neutral-300">
	{#if diagnostic.message}<p>{diagnostic.message}</p>{/if}
	<p>Code: <code class="break-all text-neutral-200">{diagnostic.code}</code></p>
	<details>
		<summary class="min-h-touch cursor-pointer py-3 text-primary-400">Diagnostic details</summary>
		<p class="mb-2 text-caption text-neutral-400">
			Safe support details only. Select and copy if needed.
		</p>
		<textarea
			class="input font-mono text-caption"
			aria-label="Safe diagnostic details"
			readonly
			rows="7"
			value={safeDetails}></textarea>
	</details>
</div>
