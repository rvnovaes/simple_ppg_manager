<script lang="ts">
	import '../app.css';

	let { children } = $props();
</script>

<svelte:head>
	<title>PPGM</title>
</svelte:head>

{@render children()}
