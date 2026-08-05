<script lang="ts">
	import { api, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';
	import { sessao } from '$lib/sessao.svelte';

	type Disciplina = components['schemas']['DisciplineOut'];

	let disciplinas = $state<Disciplina[]>([]);
	let carregando = $state(true);
	let erro = $state('');

	// Filtros da lista. O backend também os aceita como query string
	// (search/is_active), mas filtrar em memória evita uma ida ao servidor a
	// cada tecla digitada.
	let busca = $state('');
	let filtroAtivas = $state<'' | 'sim' | 'nao'>('');

	// Coordenação, docente e discente só leem: sem a permissão de escrita o
	// formulário nem existe na tela (a checagem que vale é a do backend).
	const podeCriar = $derived(sessao.pode('programs.add_discipline'));
	const podeEditar = $derived(sessao.pode('programs.change_discipline'));

	const visiveis = $derived.by(() => {
		const termo = busca.trim().toLocaleLowerCase('pt-BR');
		return disciplinas.filter((d) => {
			if (filtroAtivas === 'sim' && !d.is_active) return false;
			if (filtroAtivas === 'nao' && d.is_active) return false;
			if (termo === '') return true;
			return (
				d.code.toLocaleLowerCase('pt-BR').includes(termo) ||
				d.name.toLocaleLowerCase('pt-BR').includes(termo)
			);
		});
	});

	function porCodigo(a: Disciplina, b: Disciplina): number {
		return a.code.localeCompare(b.code, 'pt-BR');
	}

	async function carregar() {
		carregando = true;
		erro = '';
		const { data, error } = await api.GET('/programs/disciplines/');
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar o catálogo de disciplinas.');
		} else {
			disciplinas = (data?.items ?? []).slice().sort(porCodigo);
		}
		carregando = false;
	}

	let emEdicao = $state<Disciplina | null>(null);
	let formAberto = $state(false);
	let codigo = $state('');
	let nome = $state('');
	let ativa = $state(true);
	let salvando = $state(false);

	function abrirNova() {
		emEdicao = null;
		codigo = '';
		nome = '';
		ativa = true;
		formAberto = true;
	}

	function editar(disciplina: Disciplina) {
		emEdicao = disciplina;
		codigo = disciplina.code;
		nome = disciplina.name;
		ativa = disciplina.is_active;
		formAberto = true;
	}

	function fecharForm() {
		formAberto = false;
		emEdicao = null;
	}

	async function salvar(event: SubmitEvent) {
		event.preventDefault();
		erro = '';
		salvando = true;
		const corpo = { code: codigo.trim(), name: nome.trim(), is_active: ativa };
		const alvo = emEdicao;
		const { data, error } = alvo
			? await api.PATCH('/programs/disciplines/{discipline_id}/', {
					params: { path: { discipline_id: alvo.id } },
					body: corpo
				})
			: await api.POST('/programs/disciplines/', { body: corpo });
		salvando = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível salvar a disciplina.');
			return;
		}
		disciplinas = (
			alvo ? disciplinas.map((d) => (d.id === data.id ? data : d)) : [...disciplinas, data]
		).sort(porCodigo);
		fecharForm();
	}

	$effect(() => {
		carregar();
	});
</script>

<svelte:head>
	<title>Disciplinas · PPGD Manager</title>
</svelte:head>

<header class="flex flex-wrap items-end justify-between gap-4">
	<div>
		<p class="etiqueta">Cadastro</p>
		<h1 class="text-grafite mt-1 text-2xl font-semibold tracking-tight">Catálogo de disciplinas</h1>
	</div>
	<div class="flex items-center gap-4">
		<p class="text-cinza font-mono text-sm">{visiveis.length} de {disciplinas.length}</p>
		{#if podeCriar}
			<button class="botao-discreto" type="button" onclick={abrirNova}>Nova disciplina</button>
		{/if}
	</div>
</header>

{#if erro}
	<p class="aviso-erro mt-6" role="alert">{erro}</p>
{/if}

{#if formAberto}
	<form class="border-borda bg-papel mt-6 border p-5" onsubmit={salvar}>
		<p class="etiqueta">{emEdicao ? 'Editar disciplina' : 'Nova disciplina'}</p>
		<div class="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-[minmax(0,14rem)_1fr_auto_auto]">
			<div>
				<label class="etiqueta mb-2 block" for="disciplina-codigo">Código</label>
				<input id="disciplina-codigo" class="campo font-mono" bind:value={codigo} required />
			</div>
			<div>
				<label class="etiqueta mb-2 block" for="disciplina-nome">Nome</label>
				<input id="disciplina-nome" class="campo" bind:value={nome} required />
			</div>
			<label class="text-grafite flex items-end gap-2 pb-3 text-sm">
				<input type="checkbox" bind:checked={ativa} />
				Ativa
			</label>
			<div class="flex items-end gap-2">
				<button class="botao" type="submit" disabled={salvando}>
					{salvando ? 'Salvando…' : 'Salvar'}
				</button>
				<button class="botao-discreto" type="button" onclick={fecharForm}>Cancelar</button>
			</div>
		</div>
	</form>
{/if}

<div class="mt-8 grid gap-4 sm:grid-cols-[1fr_auto]">
	<div>
		<label class="etiqueta mb-2 block" for="disciplina-busca">Buscar por código ou nome</label>
		<input id="disciplina-busca" class="campo" bind:value={busca} placeholder="DIR001, Direito…" />
	</div>
	<div>
		<label class="etiqueta mb-2 block" for="disciplina-filtro-ativas">Situação</label>
		<select id="disciplina-filtro-ativas" class="campo" bind:value={filtroAtivas}>
			<option value="">Todas</option>
			<option value="sim">Ativas</option>
			<option value="nao">Inativas</option>
		</select>
	</div>
</div>

{#if carregando}
	<p class="etiqueta mt-6">Carregando…</p>
{:else if disciplinas.length === 0}
	<div class="border-borda bg-papel mt-6 border border-dashed p-10 text-center">
		<p class="text-grafite text-[0.9375rem]">Nenhuma disciplina cadastrada ainda.</p>
		<p class="text-cinza mt-1 text-sm">
			{podeCriar
				? 'O catálogo alimenta o acerto de matrícula: sem disciplina, o aluno não tem o que pedir.'
				: 'Peça à secretaria para cadastrar a primeira.'}
		</p>
	</div>
{:else if visiveis.length === 0}
	<div class="border-borda bg-papel mt-6 border border-dashed p-10 text-center">
		<p class="text-grafite text-[0.9375rem]">Nenhuma disciplina para esse filtro.</p>
	</div>
{:else}
	<ul class="mt-6 space-y-px">
		{#each visiveis as disciplina (disciplina.id)}
			<li
				class="bg-papel regua-tinta flex flex-wrap items-center justify-between gap-4 px-5 py-4"
				class:opacity-55={!disciplina.is_active}
				style:border-left-color={disciplina.is_active ? 'var(--color-tinta)' : 'var(--color-borda)'}
			>
				<div class="min-w-0">
					<p class="text-grafite font-mono text-[0.9375rem] font-medium">{disciplina.code}</p>
					<p class="text-cinza mt-0.5 truncate text-sm">{disciplina.name}</p>
				</div>
				<div class="flex shrink-0 items-center gap-4">
					<span class="etiqueta">{disciplina.is_active ? 'Ativa' : 'Inativa'}</span>
					{#if podeEditar}
						<button class="botao-discreto" type="button" onclick={() => editar(disciplina)}>
							Editar
						</button>
					{/if}
				</div>
			</li>
		{/each}
	</ul>
{/if}
