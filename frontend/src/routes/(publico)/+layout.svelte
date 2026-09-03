<script lang="ts">
	import { resolve } from '$app/paths';

	/*
	 * Moldura das telas abertas ao público.
	 *
	 * Grupo próprio, e não `(app)`, porque aqui NÃO há sessão: quem se
	 * inscreve no processo seletivo não tem conta (as rotas por trás são as
	 * `# público` de `apps/selection/router.py`). Nada de menu, nada de
	 * `sessao.carregar()` — só o cabeçalho que diz onde a pessoa está e o
	 * par de links entre inscrever-se e consultar o protocolo.
	 */

	let { children } = $props();
</script>

<div class="bg-fundo flex min-h-screen flex-col">
	<header class="border-borda bg-papel border-b">
		<div class="mx-auto flex max-w-4xl flex-wrap items-center gap-x-6 gap-y-2 px-6 py-4">
			<p class="regua-tinta text-grafite pl-3 text-sm font-semibold tracking-tight">
				Processo seletivo
			</p>
			<nav class="ml-auto flex items-center gap-5 text-sm">
				<a class="text-cinza hover:text-tinta" href={resolve('/selecao/inscricao')}>Inscrição</a>
				<a class="text-cinza hover:text-tinta" href={resolve('/selecao/protocolo')}>
					Consultar protocolo
				</a>
			</nav>
		</div>
	</header>

	<main class="mx-auto w-full max-w-4xl flex-1 px-6 py-10">
		{@render children()}
	</main>

	<footer class="border-borda mt-6 border-t">
		<p class="text-cinza mx-auto max-w-4xl px-6 py-5 text-xs">
			Guarde o protocolo: é por ele que a situação da inscrição se consulta.
		</p>
	</footer>
</div>
