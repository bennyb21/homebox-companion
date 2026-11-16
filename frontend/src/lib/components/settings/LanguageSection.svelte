<script lang="ts">
	import { t, uiLanguage, setUiLanguage, type Locale } from '$lib/i18n/index.svelte';
	let stored = $state(true);
</script>

<section class="card space-y-3">
	<label for="ui-language" class="block text-h3 text-neutral-100">{t('UI language')}</label>
	<select
		id="ui-language"
		class="input"
		value={uiLanguage.current}
		onchange={(event) => {
			stored = setUiLanguage(event.currentTarget.value as Locale);
		}}
	>
		<option value="de" lang="de">Deutsch</option>
		<option value="en" lang="en">English</option>
	</select>
	<p class="text-caption text-neutral-400">
		{t('Stored only in this browser. Does not change AI output language or inventory content.')}
	</p>
	{#if !stored}<p role="status">
			{t('Your browser could not store this choice. It applies until this page is reloaded.')}
		</p>{/if}
</section>
