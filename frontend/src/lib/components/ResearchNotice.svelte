<script lang="ts">
	import { t } from '$lib/i18n/index.svelte';
</script>

<details class="text-caption text-neutral-400">
	<summary class="min-h-touch cursor-pointer py-3"
		>{t('OpenAI research · API costs may apply')}</summary
	>
	<p>
		{t(
			'Product information and associated photos are sent to OpenAI. Only selected suggestions change your data.'
		)}
	</p>
</details>
