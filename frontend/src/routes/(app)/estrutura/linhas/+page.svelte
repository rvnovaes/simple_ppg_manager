<script lang="ts">
	import { api, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';
	import { sessao } from '$lib/sessao.svelte';
	import SeletorMultiplo from '$lib/SeletorMultiplo.svelte';

	type Linha = components['schemas']['ResearchLineOut'];
	type Projeto = components['schemas']['CollectiveProjectOut'];
	type Professor = components['schemas']['TeacherOut'];

	let linhas = $state<Linha[]>([]);
	let projetos = $state<Projeto[]>([]);
	let professores = $state<Professor[]>([]);
	let carregando = $state(true);
	let erro = $state('');

	// Coordenação só lê: sem a permissão de escrita, o formulário nem existe
	// na tela (a checagem que vale continua sendo a do backend).
	const podeCriarLinha = $derived(sessao.pode('programs.add_researchline'));
	const podeEditarLinha = $derived(sessao.pode('programs.change_researchline'));
	const podeCriarProjeto = $derived(sessao.pode('programs.add_collectiveproject'));
	const podeEditarProjeto = $derived(sessao.pode('programs.change_collectiveproject'));
	// A lista de professores é de `academic`, com permissão própria: quem
	// não a tem vê o projeto sem equipe, e o formulário sem o bloco.
	const podeVerProfessores = $derived(sessao.pode('academic.view_teacher'));

	const nomeDoProfessor = $derived.by(() => {
		const nomes: Record<number, string> = {};
		for (const professor of professores) nomes[professor.id] = professor.person.full_name;
		return nomes;
	});

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
		const [respLinhas, respProjetos, respProfessores] = await Promise.all([
			api.GET('/programs/research-lines/'),
			api.GET('/programs/collective-projects/'),
			podeVerProfessores ? api.GET('/academic/teachers/') : Promise.resolve(null)
		]);
		const falha = respLinhas.error ?? respProjetos.error ?? respProfessores?.error;
		if (falha) {
			erro = mensagemDeErro(falha, 'Não foi possível carregar as linhas de pesquisa.');
		} else {
			linhas = respLinhas.data?.items ?? [];
			projetos = respProjetos.data?.items ?? [];
			professores = respProfessores?.data?.items ?? [];
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
	let projetoProfessores = $state<number[]>([]);
	let salvandoProjeto = $state(false);

	function abrirNovoProjeto(linhaId: number | null = null) {
		projetoEmEdicao = null;
		projetoNome = '';
		projetoLinhaId = linhaId ?? linhas[0]?.id ?? null;
		projetoAtivo = true;
		projetoProfessores = [];
		formProjetoAberto = true;
	}

	function editarProjeto(projeto: Projeto) {
		projetoEmEdicao = projeto;
		projetoNome = projeto.name;
		projetoLinhaId = projeto.research_line_id;
		projetoAtivo = projeto.is_active;
		projetoProfessores = [...projeto.teacher_ids];
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
					// Quem não enxerga a lista não mexe no vínculo: sem o campo, o
					// PATCH preserva os professores que já estavam.
					body: { ...corpo, ...(podeVerProfessores ? { teacher_ids: projetoProfessores } : {}) }
				})
			: await api.POST('/programs/collective-projects/', {
					body: { ...corpo, teacher_ids: projetoProfessores }
				});
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

	$effect(() => {
		carregar();
	});
</script>

<svelte:head>
	<title>Linhas de pesquisa · PPGM</title>
</svelte:head>

<header class="flex flex-wrap items-end justify-between gap-4">
	<div>
		<p class="etiqueta">Estrutura</p>
		<h1 class="text-grafite mt-1 text-2xl font-semibold tracking-tight">Linhas de pesquisa</h1>
	</div>
	<p class="text-cinza font-mono text-sm">
		{linhas.length} linhas · {projetos.length} projetos
	</p>
</header>

{#if erro}
	<p class="aviso-erro mt-6" role="alert">{erro}</p>
{/if}

<section class="mt-10">
	<div class="flex flex-wrap items-center justify-end gap-3">
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
			{#if podeVerProfessores}
				<fieldset class="mt-5">
					<legend class="etiqueta mb-2">Professores</legend>
					{#if professores.length === 0}
						<p class="text-cinza text-sm">Nenhum professor credenciado ainda.</p>
					{:else}
						<SeletorMultiplo
							id="projeto-professores"
							opcoes={professores.map((p) => ({ id: p.id, rotulo: p.person.full_name }))}
							bind:selecionados={projetoProfessores}
							placeholder="Buscar professor pelo nome…"
							vazio="Nenhum professor no projeto ainda."
						/>
					{/if}
				</fieldset>
			{/if}
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
									<div class="min-w-0">
										<p class="text-grafite truncate text-sm">{projeto.name}</p>
										{#if projeto.teacher_ids.length > 0}
											<p class="text-cinza mt-0.5 truncate text-[0.8125rem]">
												{projeto.teacher_ids
													.map((id) => nomeDoProfessor[id] ?? `#${id}`)
													.join(' · ')}
											</p>
										{/if}
									</div>
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
