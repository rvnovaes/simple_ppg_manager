<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { sessao } from '$lib/sessao.svelte';

	let { children } = $props();

	// Guarda das telas internas: sem sessão, volta para o login.
	$effect(() => {
		if (sessao.usuario === null && !sessao.carregando) {
			goto(resolve('/login'), { replaceState: true });
		}
	});

	$effect(() => {
		if (sessao.usuario === null && sessao.carregando) sessao.carregar();
	});

	async function sair() {
		await sessao.sair();
		await goto(resolve('/login'));
	}
</script>

{#if sessao.carregando}
	<p class="etiqueta p-8">Carregando…</p>
{:else if sessao.usuario}
	<div class="min-h-screen">
		<header class="border-borda bg-papel border-b">
			<div class="mx-auto flex max-w-5xl items-center justify-between gap-4 px-6 py-4">
				<div class="flex items-center gap-6">
					<a
						href={resolve('/pessoas')}
						class="text-tinta text-[0.9375rem] font-semibold tracking-tight"
					>
						PPGD Manager
					</a>
					<nav class="flex items-center gap-4">
						<a class="text-grafite hover:text-tinta text-sm" href={resolve('/pessoas')}>Pessoas</a>
						<a class="text-grafite hover:text-tinta text-sm" href={resolve('/estrutura')}>
							Estrutura
						</a>
						<a class="text-grafite hover:text-tinta text-sm" href={resolve('/professores')}>
							Professores
						</a>
						<a class="text-grafite hover:text-tinta text-sm" href={resolve('/alunos')}>Alunos</a>
						{#if sessao.pode('academic.add_enrollmentadjustmentrequest')}
							<a class="text-grafite hover:text-tinta text-sm" href={resolve('/acertos')}>
								Acertos
							</a>
						{/if}
						{#if sessao.pode('programs.view_discipline')}
							<a class="text-grafite hover:text-tinta text-sm" href={resolve('/disciplinas')}>
								Disciplinas
							</a>
						{/if}
					</nav>
				</div>
				<div class="flex items-center gap-4">
					<span class="etiqueta hidden sm:inline">{sessao.usuario.username}</span>
					<button class="botao-discreto" type="button" onclick={sair}>Sair</button>
				</div>
			</div>
		</header>

		<main class="mx-auto max-w-5xl px-6 py-10">
			{@render children()}
		</main>
	</div>
{/if}
