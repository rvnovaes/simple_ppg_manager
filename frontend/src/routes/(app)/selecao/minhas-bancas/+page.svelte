<!--
	Marcador de rota, e não tela: existe para que o item "Minhas bancas" do menu
	possa usar `resolve()` — a rota tipada do SvelteKit só conhece o que já
	está em `routes/`, e link sem `resolve()` é erro de lint
	(`svelte/no-navigation-without-resolve`). A story **f3-tela-minhas-bancas**
	substitui este arquivo pela tela de verdade.
-->
<svelte:head>
	<title>Minhas bancas · PPGD Manager</title>
</svelte:head>

<header>
	<p class="etiqueta">Processo seletivo</p>
	<h1 class="text-grafite mt-1 text-2xl font-semibold tracking-tight">Minhas bancas</h1>
</header>

<div class="border-borda bg-papel mt-6 border border-dashed p-10 text-center">
	<p class="text-grafite text-[0.9375rem]">Esta tela ainda não foi construída.</p>
	<p class="text-cinza mt-1 text-sm">
		Ela entra na story f3-tela-minhas-bancas do processo seletivo.
	</p>
</div>
