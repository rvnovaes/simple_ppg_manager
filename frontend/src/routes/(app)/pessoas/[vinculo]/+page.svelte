<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import Icone from '$lib/Icone.svelte';
	import { api, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';
	import { sessao } from '$lib/sessao.svelte';

	type Pessoa = components['schemas']['PersonOut'];
	type Vinculo = components['schemas']['PersonBond'];

	// O slug da URL é português porque é o que a pessoa lê na barra de
	// endereço; o `bond` é o valor do contrato da API. Manter os dois
	// separados evita traduzir enum no backend só para a URL ficar bonita.
	const RECORTES: Record<string, { bond: Vinculo; titulo: string; vazio: string; origem: string }> =
		{
			candidatos: {
				bond: 'candidate',
				titulo: 'Candidatos',
				vazio: 'Ninguém se inscreveu em disciplina isolada ainda.',
				origem:
					'A pessoa entra nesta lista ao se inscrever em disciplina isolada, pelo próprio cadastro do edital. Quem já virou aluno continua aqui: o requerimento não deixa de existir quando a matrícula sai.'
			},
			administrativo: {
				bond: 'staff',
				titulo: 'Administrativo',
				vazio: 'Ninguém com papel de Secretaria ou Coordenação.',
				origem:
					'A lista sai do papel da conta — Secretaria ou Coordenação. Papel é permissão, e quem o atribui é o sysadmin da plataforma; não há campo de "cargo" na pessoa.'
			}
		};

	// Professores e alunos têm tela própria, com o cadastro do vínculo. Uma
	// segunda listagem só deles seria a mesma tela pela metade.
	const REDIRECIONADOS: Record<string, '/professores' | '/alunos'> = {
		professores: '/professores',
		alunos: '/alunos'
	};

	const slug = $derived(page.params.vinculo ?? '');
	const recorte = $derived(RECORTES[slug]);

	let pessoas = $state<Pessoa[]>([]);
	let carregando = $state(true);
	let erro = $state('');
	let arquivando = $state<number | null>(null);

	const podeArquivar = $derived(sessao.pode('people.change_person'));

	async function carregar(bond: Vinculo) {
		carregando = true;
		erro = '';
		const { data, error } = await api.GET('/people/', { params: { query: { bond } } });
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar a lista.');
		} else {
			pessoas = data?.items ?? [];
		}
		carregando = false;
	}

	async function arquivar(pessoa: Pessoa) {
		erro = '';
		arquivando = pessoa.id;
		const { data, error } = await api.POST('/people/{person_id}/archive', {
			params: { path: { person_id: pessoa.id } }
		});
		arquivando = null;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível arquivar a pessoa.');
			return;
		}
		pessoas = pessoas.map((p) => (p.id === data.id ? data : p));
	}

	$effect(() => {
		const destino = REDIRECIONADOS[slug];
		if (destino) {
			goto(resolve(destino), { replaceState: true });
			return;
		}
		if (recorte) carregar(recorte.bond);
	});
</script>

<svelte:head>
	<title>{recorte?.titulo ?? 'Pessoas'} · PPGD Manager</title>
</svelte:head>

{#if !recorte && !REDIRECIONADOS[slug]}
	<p class="aviso-erro" role="alert">Lista de pessoas desconhecida: {slug}</p>
{:else if recorte}
	<header class="flex flex-wrap items-end justify-between gap-4">
		<div>
			<p class="etiqueta">Pessoas</p>
			<h1 class="text-grafite mt-1 text-2xl font-semibold tracking-tight">{recorte.titulo}</h1>
		</div>
		<p class="text-cinza font-mono text-sm">{pessoas.length} registros</p>
	</header>

	<p class="text-cinza mt-3 max-w-2xl text-sm">{recorte.origem}</p>

	{#if erro}
		<p class="aviso-erro mt-6" role="alert">{erro}</p>
	{/if}

	<section class="mt-8">
		{#if carregando}
			<p class="etiqueta">Carregando…</p>
		{:else if pessoas.length === 0}
			<div class="border-borda bg-papel border border-dashed p-10 text-center">
				<p class="text-grafite text-[0.9375rem]">{recorte.vazio}</p>
			</div>
		{:else}
			<ul class="space-y-px">
				{#each pessoas as pessoa (pessoa.id)}
					<!--
						A régua de tinta marca cada registro oficial — mesmo traço do
						cartão de acesso. Arquivado perde a tinta e ganha opacidade.
					-->
					<li
						class="bg-papel regua-tinta flex flex-wrap items-center justify-between gap-4 px-5 py-4"
						class:opacity-55={pessoa.status === 'archived'}
						style:border-left-color={pessoa.status === 'archived'
							? 'var(--color-borda)'
							: 'var(--color-tinta)'}
					>
						<div class="min-w-0">
							<p class="text-grafite truncate text-[0.9375rem] font-medium">{pessoa.full_name}</p>
							<p class="text-cinza mt-0.5 truncate font-mono text-[0.8125rem]">
								{pessoa.primary_email}{pessoa.phone_number ? ` · ${pessoa.phone_number}` : ''}
							</p>
						</div>

						<div class="flex shrink-0 items-center gap-4">
							<span class="etiqueta">
								{pessoa.status === 'archived' ? 'Arquivada' : 'Ativa'}
							</span>
							<div class="flex items-center gap-1">
								<a
									class="botao-icone"
									href={resolve('/(app)/pessoas/[vinculo]/[id]', {
										vinculo: slug,
										id: String(pessoa.id)
									})}
									title="Detalhes de {pessoa.full_name}"
								>
									<Icone nome="olho" rotulo="Detalhes" />
								</a>
								{#if podeArquivar}
									<!-- Arquivar é o "excluir" desta tela: a pessoa continua sendo
									quem assinou o que já assinou. Arquivada, o botão fica
									desabilitado em vez de sumir — some daria a impressão de que a
									ação não existe. -->
									<button
										class="botao-icone botao-icone-perigo"
										type="button"
										disabled={pessoa.status === 'archived' || arquivando === pessoa.id}
										title={pessoa.status === 'archived'
											? 'Já arquivada'
											: `Arquivar ${pessoa.full_name}`}
										onclick={() => arquivar(pessoa)}
									>
										<Icone nome="arquivo" rotulo="Arquivar" />
									</button>
								{/if}
							</div>
						</div>
					</li>
				{/each}
			</ul>
		{/if}
	</section>
{/if}
