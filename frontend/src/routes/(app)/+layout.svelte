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
						href={resolve(sessao.rotaInicial)}
						class="text-tinta text-[0.9375rem] font-semibold tracking-tight"
					>
						PPGD Manager
					</a>
					<nav class="flex items-center gap-4">
						<!-- Todo item é condicional: o Candidato da isolada não tem
						permissão sobre pessoa, professor nem aluno, e link que só leva
						a 403 é pior do que link ausente. -->
						{#if sessao.pode('people.view_person')}
							<a class="text-grafite hover:text-tinta text-sm" href={resolve('/pessoas')}>
								Pessoas
							</a>
						{/if}
						{#if sessao.pode('programs.view_researchline')}
							<a class="text-grafite hover:text-tinta text-sm" href={resolve('/estrutura')}>
								Estrutura
							</a>
						{/if}
						{#if sessao.pode('academic.view_teacher')}
							<a class="text-grafite hover:text-tinta text-sm" href={resolve('/professores')}>
								Professores
							</a>
						{/if}
						{#if sessao.pode('academic.view_student')}
							<a class="text-grafite hover:text-tinta text-sm" href={resolve('/alunos')}>Alunos</a>
						{/if}
						{#if sessao.pode('academic.add_isolatedenrollmentrequest')}
							<a class="text-grafite hover:text-tinta text-sm" href={resolve('/inscricao')}>
								Inscrição
							</a>
							<!-- Por papel, e não por permissão: os quatro papéis têm
							`view_isolatedenrollmentrequest`, mas esta tela é a do próprio
							candidato — a fila da secretaria é outra (US-019). -->
							{#if sessao.temPapel('Candidato')}
								<a class="text-grafite hover:text-tinta text-sm" href={resolve('/acompanhamento')}>
									Acompanhamento
								</a>
							{/if}
						{/if}
						<!-- Por permissão, e não por papel: `rank_disciplineoffering` é
						exclusiva do Docente (academic.0011) e é exatamente o que esta
						tela exige. -->
						{#if sessao.pode('academic.rank_disciplineoffering')}
							<a class="text-grafite hover:text-tinta text-sm" href={resolve('/classificacao')}>
								Classificação
							</a>
						{/if}
						<!-- Por papel: `change_isolatedenrollmentrequest` também é do
						Candidato (é com ela que ele monta o próprio requerimento), e a
						análise do edital é trabalho da secretaria. Coordenação fica de
						fora porque esta tela só tem controles de decisão. -->
						{#if sessao.temPapel('Secretaria')}
							<a class="text-grafite hover:text-tinta text-sm" href={resolve('/analise')}>
								Análise
							</a>
						{/if}
						{#if sessao.pode('academic.change_enrollmentadjustmentrequest')}
							<a class="text-grafite hover:text-tinta text-sm" href={resolve('/orientandos')}>
								Orientandos
							</a>
						{/if}
						{#if sessao.pode('academic.add_enrollmentadjustmentrequest')}
							<a class="text-grafite hover:text-tinta text-sm" href={resolve('/acertos')}>
								Acertos
							</a>
						{/if}
						{#if sessao.temPapel('Secretaria', 'Coordenação')}
							<a
								class="text-grafite hover:text-tinta text-sm"
								href={resolve('/acertos-do-programa')}
							>
								Acertos do programa
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
