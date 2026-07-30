<script lang="ts">
	import '../app.css';

	let { children } = $props();
</script>

<svelte:head>
	<title>PPGD Manager</title>
</svelte:head>

{@render children()}
