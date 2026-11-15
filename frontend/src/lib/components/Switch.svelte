<script lang="ts">
	let {
		checked,
		disabled = false,
		label,
		onchange,
	}: {
		checked: boolean;
		disabled?: boolean;
		label: string;
		onchange: (checked: boolean) => void;
	} = $props();
</script>

<button
	type="button"
	role="switch"
	aria-checked={checked}
	aria-label={label}
	{disabled}
	class="flex min-h-touch items-center gap-3 rounded-lg py-2 text-left text-body-sm text-neutral-200 outline-offset-4 focus-visible:outline-2 focus-visible:outline-primary-400 disabled:cursor-not-allowed disabled:opacity-50"
	onclick={() => onchange(!checked)}
>
	<span
		aria-hidden="true"
		class="flex h-7 w-12 shrink-0 items-center rounded-full border p-1 transition-colors {checked
			? 'border-primary-400 bg-primary-500'
			: 'border-neutral-500 bg-neutral-700'}"
	>
		<span
			class="block rounded-full bg-neutral-100 shadow-sm transition-transform size-5 motion-reduce:transition-none {checked
				? 'translate-x-5'
				: 'translate-x-0'}"
		></span>
	</span>
	<span>{label}</span>
</button>
