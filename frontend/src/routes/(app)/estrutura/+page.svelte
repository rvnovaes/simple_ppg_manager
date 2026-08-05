<script lang="ts">
	import { api, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';
	import { sessao } from '$lib/sessao.svelte';

	type Linha = components['schemas']['ResearchLineOut'];
	type Projeto = components['schemas']['CollectiveProjectOut'];
	type Periodo = components['schemas']['AcademicTermOut'];

	let linhas = $state<Linha[]>([]);
	let projetos = $state<Projeto[]>([]);
	let periodos = $state<Periodo[]>([]);
	let carregando = $state(true);
	let erro = $state('');

	// Coordenação só lê: sem a permissão de escrita, o formulário nem existe
	// na tela (a checagem que vale continua sendo a do backend).
	const podeCriarLinha = $derived(sessao.pode('programs.add_researchline'));
	const podeEditarLinha = $derived(sessao.pode('programs.change_researchline'));
	const podeCriarProjeto = $derived(sessao.pode('programs.add_collectiveproject'));
	const podeEditarProjeto = $derived(sessao.pode('programs.change_collectiveproject'));
	const podeCriarPeriodo = $derived(sessao.pode('programs.add_academicterm'));
	const podeEditarPeriodo = $derived(sessao.pode('programs.change_academicterm'));

	// Linha 1 -> N projetos: o agrupamento é o desenho da tela, não um detalhe.
	const projetosPorLinha = $derived.by(() => {
		const grupos: Record<number, Projeto[]> = {};
		for (const linha of linhas) grupos[linha.id] = [];
		for (const projeto of projetos) {
			grupos[projeto.research_line_id]?.push(projeto);
		}
		return grupos;
	});

	function porNome<T extends { name: string }>(a: T, b: T): number {
		return a.name.localeCompare(b.name, 'pt-BR');
	}

	async function carregar() {
		carregando = true;
		erro = '';
		const [respLinhas, respProjetos, respPeriodos] = await Promise.all([
			api.GET('/programs/research-lines/'),
			api.GET('/programs/collective-projects/'),
			api.GET('/programs/terms/')
		]);
		const falha = respLinhas.error ?? respProjetos.error ?? respPeriodos.error;
		if (falha) {
			erro = mensagemDeErro(falha, 'Não foi possível carregar a estrutura do programa.');
		} else {
			linhas = respLinhas.data?.items ?? [];
			projetos = respProjetos.data?.items ?? [];
			periodos = respPeriodos.data?.items ?? [];
		}
		carregando = false;
	}

	// ---------------------------------------------------------------- linhas

	let linhaEmEdicao = $state<Linha | null>(null);
	let formLinhaAberto = $state(false);
	let linhaNome = $state('');
	let linhaAtiva = $state(true);
	let salvandoLinha = $state(false);

	function abrirNovaLinha() {
		linhaEmEdicao = null;
		linhaNome = '';
		linhaAtiva = true;
		formLinhaAberto = true;
	}

	function editarLinha(linha: Linha) {
		linhaEmEdicao = linha;
		linhaNome = linha.name;
		linhaAtiva = linha.is_active;
		formLinhaAberto = true;
	}

	function fecharFormLinha() {
		formLinhaAberto = false;
		linhaEmEdicao = null;
	}

	async function salvarLinha(event: SubmitEvent) {
		event.preventDefault();
		erro = '';
		salvandoLinha = true;
		const corpo = { name: linhaNome, is_active: linhaAtiva };
		const alvo = linhaEmEdicao;
		const { data, error } = alvo
			? await api.PATCH('/programs/research-lines/{research_line_id}/', {
					params: { path: { research_line_id: alvo.id } },
					body: corpo
				})
			: await api.POST('/programs/research-lines/', { body: corpo });
		salvandoLinha = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível salvar a linha de pesquisa.');
			return;
		}
		linhas = alvo
			? linhas.map((l) => (l.id === data.id ? data : l))
			: [...linhas, data].sort(porNome);
		fecharFormLinha();
	}

	// -------------------------------------------------------------- projetos

	let projetoEmEdicao = $state<Projeto | null>(null);
	let formProjetoAberto = $state(false);
	let projetoNome = $state('');
	let projetoLinhaId = $state<number | null>(null);
	let projetoAtivo = $state(true);
	let salvandoProjeto = $state(false);

	function abrirNovoProjeto(linhaId: number | null = null) {
		projetoEmEdicao = null;
		projetoNome = '';
		projetoLinhaId = linhaId ?? linhas[0]?.id ?? null;
		projetoAtivo = true;
		formProjetoAberto = true;
	}

	function editarProjeto(projeto: Projeto) {
		projetoEmEdicao = projeto;
		projetoNome = projeto.name;
		projetoLinhaId = projeto.research_line_id;
		projetoAtivo = projeto.is_active;
		formProjetoAberto = true;
	}

	function fecharFormProjeto() {
		formProjetoAberto = false;
		projetoEmEdicao = null;
	}

	async function salvarProjeto(event: SubmitEvent) {
		event.preventDefault();
		if (projetoLinhaId === null) return;
		erro = '';
		salvandoProjeto = true;
		const corpo = {
			research_line_id: projetoLinhaId,
			name: projetoNome,
			is_active: projetoAtivo
		};
		const alvo = projetoEmEdicao;
		const { data, error } = alvo
			? await api.PATCH('/programs/collective-projects/{collective_project_id}/', {
					params: { path: { collective_project_id: alvo.id } },
					body: corpo
				})
			: await api.POST('/programs/collective-projects/', { body: corpo });
		salvandoProjeto = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível salvar o projeto coletivo.');
			return;
		}
		projetos = alvo
			? projetos.map((p) => (p.id === data.id ? data : p))
			: [...projetos, data].sort(porNome);
		fecharFormProjeto();
	}

	// ------------------------------------------------------- períodos letivos

	let periodoEmEdicao = $state<Periodo | null>(null);
	let formPeriodoAberto = $state(false);
	let periodoAno = $state(new Date().getFullYear());
	let periodoSemestre = $state<1 | 2>(1);
	let periodoInicio = $state('');
	let periodoFim = $state('');
	let periodoAtivo = $state(true);
	let salvandoPeriodo = $state(false);

	function abrirNovoPeriodo() {
		periodoEmEdicao = null;
		periodoAno = new Date().getFullYear();
		periodoSemestre = 1;
		periodoInicio = '';
		periodoFim = '';
		periodoAtivo = true;
		formPeriodoAberto = true;
	}

	function editarPeriodo(periodo: Periodo) {
		periodoEmEdicao = periodo;
		periodoAno = periodo.year;
		periodoSemestre = periodo.half === 2 ? 2 : 1;
		periodoInicio = periodo.starts_on;
		periodoFim = periodo.ends_on;
		periodoAtivo = periodo.is_active;
		formPeriodoAberto = true;
	}

	function fecharFormPeriodo() {
		formPeriodoAberto = false;
		periodoEmEdicao = null;
	}

	async function salvarPeriodo(event: SubmitEvent) {
		event.preventDefault();
		erro = '';
		salvandoPeriodo = true;
		const corpo = {
			year: periodoAno,
			half: periodoSemestre,
			starts_on: periodoInicio,
			ends_on: periodoFim,
			is_active: periodoAtivo
		};
		const alvo = periodoEmEdicao;
		const { data, error } = alvo
			? await api.PATCH('/programs/terms/{academic_term_id}/', {
					params: { path: { academic_term_id: alvo.id } },
					body: corpo
				})
			: await api.POST('/programs/terms/', { body: corpo });
		salvandoPeriodo = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível salvar o período letivo.');
			return;
		}
		periodos = alvo
			? periodos.map((p) => (p.id === data.id ? data : p))
			: [...periodos, data].sort((a, b) => b.year - a.year || b.half - a.half);
		fecharFormPeriodo();
	}

	$effect(() => {
		carregar();
	});
</script>

<svelte:head>
	<title>Estrutura · PPGD Manager</title>
</svelte:head>

<header class="flex flex-wrap items-end justify-between gap-4">
	<div>
		<p class="etiqueta">Cadastro</p>
		<h1 class="text-grafite mt-1 text-2xl font-semibold tracking-tight">Estrutura do programa</h1>
	</div>
	<p class="text-cinza font-mono text-sm">
		{linhas.length} linhas · {projetos.length} projetos · {periodos.length} períodos
	</p>
</header>

{#if erro}
	<p class="aviso-erro mt-6" role="alert">{erro}</p>
{/if}

<section class="mt-10">
	<div class="flex flex-wrap items-center justify-between gap-3">
		<h2 class="text-grafite text-lg font-semibold tracking-tight">Linhas de pesquisa</h2>
		<div class="flex gap-2">
			{#if podeCriarProjeto && linhas.length > 0}
				<button class="botao-discreto" type="button" onclick={() => abrirNovoProjeto()}>
					Novo projeto
				</button>
			{/if}
			{#if podeCriarLinha}
				<button class="botao-discreto" type="button" onclick={abrirNovaLinha}>Nova linha</button>
			{/if}
		</div>
	</div>

	{#if formLinhaAberto}
		<form class="border-borda bg-papel mt-5 border p-5" onsubmit={salvarLinha}>
			<p class="etiqueta">{linhaEmEdicao ? 'Editar linha' : 'Nova linha'}</p>
			<div class="mt-4 grid gap-4 sm:grid-cols-[1fr_auto_auto]">
				<div>
					<label class="etiqueta mb-2 block" for="linha-nome">Nome</label>
					<input id="linha-nome" class="campo" bind:value={linhaNome} required />
				</div>
				<label class="text-grafite flex items-end gap-2 pb-3 text-sm">
					<input type="checkbox" bind:checked={linhaAtiva} />
					Ativa
				</label>
				<div class="flex items-end gap-2">
					<button class="botao" type="submit" disabled={salvandoLinha}>
						{salvandoLinha ? 'Salvando…' : 'Salvar'}
					</button>
					<button class="botao-discreto" type="button" onclick={fecharFormLinha}>Cancelar</button>
				</div>
			</div>
		</form>
	{/if}

	{#if formProjetoAberto}
		<form class="border-borda bg-papel mt-5 border p-5" onsubmit={salvarProjeto}>
			<p class="etiqueta">{projetoEmEdicao ? 'Editar projeto' : 'Novo projeto coletivo'}</p>
			<div class="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-[1fr_1fr_auto_auto]">
				<div>
					<label class="etiqueta mb-2 block" for="projeto-nome">Nome</label>
					<input id="projeto-nome" class="campo" bind:value={projetoNome} required />
				</div>
				<div>
					<label class="etiqueta mb-2 block" for="projeto-linha">Linha de pesquisa</label>
					<select id="projeto-linha" class="campo" bind:value={projetoLinhaId}>
						{#each linhas as linha (linha.id)}
							<option value={linha.id}>{linha.name}</option>
						{/each}
					</select>
				</div>
				<label class="text-grafite flex items-end gap-2 pb-3 text-sm">
					<input type="checkbox" bind:checked={projetoAtivo} />
					Ativo
				</label>
				<div class="flex items-end gap-2">
					<button class="botao" type="submit" disabled={salvandoProjeto || projetoLinhaId === null}>
						{salvandoProjeto ? 'Salvando…' : 'Salvar'}
					</button>
					<button class="botao-discreto" type="button" onclick={fecharFormProjeto}>Cancelar</button>
				</div>
			</div>
		</form>
	{/if}

	{#if carregando}
		<p class="etiqueta mt-6">Carregando…</p>
	{:else if linhas.length === 0}
		<div class="border-borda bg-papel mt-6 border border-dashed p-10 text-center">
			<p class="text-grafite text-[0.9375rem]">Nenhuma linha de pesquisa cadastrada ainda.</p>
			<p class="text-cinza mt-1 text-sm">
				{podeCriarLinha
					? 'Comece pela linha; os projetos coletivos penduram nela.'
					: 'Peça à secretaria para cadastrar a primeira.'}
			</p>
		</div>
	{:else}
		<ul class="mt-6 space-y-4">
			{#each linhas as linha (linha.id)}
				<li
					class="bg-papel regua-tinta px-5 py-4"
					class:opacity-55={!linha.is_active}
					style:border-left-color={linha.is_active ? 'var(--color-tinta)' : 'var(--color-borda)'}
				>
					<div class="flex flex-wrap items-center justify-between gap-4">
						<div class="min-w-0">
							<p class="text-grafite truncate text-[0.9375rem] font-medium">{linha.name}</p>
							<p class="text-cinza mt-0.5 font-mono text-[0.8125rem]">
								{projetosPorLinha[linha.id]?.length ?? 0} projetos
							</p>
						</div>
						<div class="flex shrink-0 items-center gap-4">
							<span class="etiqueta">{linha.is_active ? 'Ativa' : 'Inativa'}</span>
							{#if podeCriarProjeto}
								<button
									class="botao-discreto"
									type="button"
									onclick={() => abrirNovoProjeto(linha.id)}
								>
									Novo projeto
								</button>
							{/if}
							{#if podeEditarLinha}
								<button class="botao-discreto" type="button" onclick={() => editarLinha(linha)}>
									Editar
								</button>
							{/if}
						</div>
					</div>

					{#if (projetosPorLinha[linha.id]?.length ?? 0) > 0}
						<!-- Os projetos ficam recuados sob a linha: a hierarquia se lê sem legenda. -->
						<ul class="border-borda mt-4 space-y-px border-l pl-4">
							{#each projetosPorLinha[linha.id] ?? [] as projeto (projeto.id)}
								<li
									class="flex flex-wrap items-center justify-between gap-4 py-2"
									class:opacity-55={!projeto.is_active}
								>
									<p class="text-grafite min-w-0 truncate text-sm">{projeto.name}</p>
									<div class="flex shrink-0 items-center gap-4">
										<span class="etiqueta">{projeto.is_active ? 'Ativo' : 'Inativo'}</span>
										{#if podeEditarProjeto}
											<button
												class="botao-discreto"
												type="button"
												onclick={() => editarProjeto(projeto)}
											>
												Editar
											</button>
										{/if}
									</div>
								</li>
							{/each}
						</ul>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}
</section>

<section class="mt-14">
	<div class="flex flex-wrap items-center justify-between gap-3">
		<div>
			<h2 class="text-grafite text-lg font-semibold tracking-tight">Períodos letivos</h2>
			<p class="text-cinza mt-1 text-sm">
				Calendário institucional: vale para todos os programas, não só para este.
			</p>
		</div>
		{#if podeCriarPeriodo}
			<button class="botao-discreto" type="button" onclick={abrirNovoPeriodo}>Novo período</button>
		{/if}
	</div>

	{#if formPeriodoAberto}
		<form class="border-borda bg-papel mt-5 border p-5" onsubmit={salvarPeriodo}>
			<p class="etiqueta">{periodoEmEdicao ? 'Editar período' : 'Novo período letivo'}</p>
			<div class="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-6">
				<div>
					<label class="etiqueta mb-2 block" for="periodo-ano">Ano</label>
					<input
						id="periodo-ano"
						type="number"
						class="campo font-mono"
						bind:value={periodoAno}
						required
					/>
				</div>
				<div>
					<label class="etiqueta mb-2 block" for="periodo-semestre">Semestre</label>
					<select id="periodo-semestre" class="campo" bind:value={periodoSemestre}>
						<option value={1}>1</option>
						<option value={2}>2</option>
					</select>
				</div>
				<div>
					<label class="etiqueta mb-2 block" for="periodo-inicio">Início</label>
					<input
						id="periodo-inicio"
						type="date"
						class="campo font-mono"
						bind:value={periodoInicio}
						required
					/>
				</div>
				<div>
					<label class="etiqueta mb-2 block" for="periodo-fim">Fim</label>
					<input
						id="periodo-fim"
						type="date"
						class="campo font-mono"
						bind:value={periodoFim}
						required
					/>
				</div>
				<label class="text-grafite flex items-end gap-2 pb-3 text-sm">
					<input type="checkbox" bind:checked={periodoAtivo} />
					Ativo
				</label>
				<div class="flex items-end gap-2">
					<button class="botao" type="submit" disabled={salvandoPeriodo}>
						{salvandoPeriodo ? 'Salvando…' : 'Salvar'}
					</button>
					<button class="botao-discreto" type="button" onclick={fecharFormPeriodo}>Cancelar</button>
				</div>
			</div>
		</form>
	{/if}

	{#if carregando}
		<p class="etiqueta mt-6">Carregando…</p>
	{:else if periodos.length === 0}
		<div class="border-borda bg-papel mt-6 border border-dashed p-10 text-center">
			<p class="text-grafite text-[0.9375rem]">Nenhum período letivo cadastrado ainda.</p>
		</div>
	{:else}
		<ul class="mt-6 space-y-px">
			{#each periodos as periodo (periodo.id)}
				<li
					class="bg-papel regua-tinta flex flex-wrap items-center justify-between gap-4 px-5 py-4"
					class:opacity-55={!periodo.is_active}
					style:border-left-color={periodo.is_active ? 'var(--color-tinta)' : 'var(--color-borda)'}
				>
					<div class="min-w-0">
						<!-- O rótulo canônico "2026/1" é como o período é chamado no dia a dia. -->
						<p class="text-grafite font-mono text-[0.9375rem] font-medium">{periodo.label}</p>
						<p class="text-cinza mt-0.5 font-mono text-[0.8125rem]">
							{periodo.starts_on} → {periodo.ends_on}
						</p>
					</div>
					<div class="flex shrink-0 items-center gap-4">
						<span class="etiqueta">{periodo.is_active ? 'Ativo' : 'Inativo'}</span>
						{#if podeEditarPeriodo}
							<button class="botao-discreto" type="button" onclick={() => editarPeriodo(periodo)}>
								Editar
							</button>
						{/if}
					</div>
				</li>
			{/each}
		</ul>
	{/if}
</section>
