<script lang="ts">
	import { api, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';
	import Icone from '$lib/Icone.svelte';
	import {
		NIVEIS,
		PAPEIS_DA_BANCA,
		ROTULO_DO_NIVEL,
		alvoDoTipo,
		rotuloDoExaminador,
		type Nivel
	} from '$lib/selecao';
	import { sessao } from '$lib/sessao.svelte';

	type Banca = components['schemas']['BoardOut'];
	type Edital = components['schemas']['SelectionProcessOut'];
	type Professor = components['schemas']['TeacherOut'];
	type Linha = components['schemas']['ResearchLineOut'];
	type Projeto = components['schemas']['CollectiveProjectOut'];

	let bancas = $state<Banca[]>([]);
	let editais = $state<Edital[]>([]);
	let professores = $state<Professor[]>([]);
	let linhas = $state<Linha[]>([]);
	let projetos = $state<Projeto[]>([]);

	let carregando = $state(true);
	let erro = $state('');
	let aviso = $state('');
	let salvando = $state(false);

	// Coordenação e Comissão de Seleção só leem: sem a permissão de escrita
	// o formulário nem existe na tela (a checagem que vale é a do backend).
	const podeCriar = $derived(sessao.pode('selection.add_board'));
	const podeEditar = $derived(sessao.pode('selection.change_board'));

	// --- filtros -----------------------------------------------------------

	let filtroEdital = $state<number | ''>('');
	let filtroNivel = $state<Nivel | ''>('');

	/**
	 * A banca NÃO pende de edital em rascunho: ela se compõe depois de o
	 * edital estar publicado. Por isso o filtro lista todos os editais, e a
	 * consulta vai ao servidor — `list_boards` já aceita `process_id` e
	 * `level`, e filtrar lá evita trazer banca de edital antigo.
	 */
	async function carregarBancas(filtros: { process_id?: number; level?: Nivel } = {}) {
		const { data, error } = await api.GET('/selection/boards/', { params: { query: filtros } });
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar as bancas do programa.');
			return;
		}
		bancas = data?.items ?? [];
	}

	async function carregarApoio() {
		const [respEditais, respProfessores, respLinhas, respProjetos] = await Promise.all([
			api.GET('/selection/processes/'),
			api.GET('/academic/teachers/'),
			api.GET('/programs/research-lines/'),
			api.GET('/programs/collective-projects/')
		]);
		const falha =
			respEditais.error ?? respProfessores.error ?? respLinhas.error ?? respProjetos.error;
		if (falha) {
			erro = mensagemDeErro(falha, 'Não foi possível carregar editais, professores e alvos.');
			return;
		}
		editais = respEditais.data?.items ?? [];
		professores = respProfessores.data?.items ?? [];
		linhas = (respLinhas.data?.items ?? []).filter((l) => l.is_active);
		projetos = (respProjetos.data?.items ?? []).filter((p) => p.is_active);
	}

	async function carregar() {
		carregando = true;
		erro = '';
		await Promise.all([carregarApoio(), carregarBancas()]);
		carregando = false;
	}

	/**
	 * Os filtros só são lidos aqui, e nunca dentro do `$effect` de
	 * montagem: lê-los lá os tornaria dependência do efeito, e cada troca
	 * de filtro dispararia dois carregamentos (o do efeito e este).
	 */
	function filtros(): { process_id?: number; level?: Nivel } {
		return {
			...(filtroEdital === '' ? {} : { process_id: filtroEdital }),
			...(filtroNivel === '' ? {} : { level: filtroNivel })
		};
	}

	async function refiltrar() {
		erro = '';
		aviso = '';
		carregando = true;
		await carregarBancas(filtros());
		carregando = false;
	}

	// Descredenciado não compõe banca (`teacher_not_accredited`): ele nem
	// aparece na lista de escolha. Quem já está numa banca antiga continua
	// visível na listagem — a banca é histórico.
	const credenciados = $derived(professores.filter((p) => p.accredited_until === null));

	// --- agrupamento linha → alvo -----------------------------------------

	// O Regular chaveia a banca por projeto coletivo e o Suplementar por
	// linha de pesquisa (P4). Como todo projeto pertence a uma linha, a
	// listagem cabe numa árvore só: linha → alvo → banca.
	const linhaDoProjeto = $derived.by(() => {
		const mapa: Record<number, number> = {};
		for (const projeto of projetos) mapa[projeto.id] = projeto.research_line_id;
		return mapa;
	});

	const nomeDaLinha = $derived.by(() => {
		const mapa: Record<number, string> = {};
		for (const linha of linhas) mapa[linha.id] = linha.name;
		return mapa;
	});

	function linhaDaBanca(banca: Banca): number | null {
		if (banca.research_line_id !== null) return banca.research_line_id;
		if (banca.project_id !== null) return linhaDoProjeto[banca.project_id] ?? null;
		return null;
	}

	type Grupo = {
		chave: string;
		linha: string;
		alvos: { chave: string; alvo: string; bancas: Banca[] }[];
	};

	// Objeto simples e não `Map`: o lint `svelte/prefer-svelte-reactivity`
	// recusa `Map` mutável, e aqui não há reatividade a ganhar — o valor é
	// remontado inteiro a cada mudança de `bancas`.
	const grupos = $derived.by<Grupo[]>(() => {
		const porLinha: Record<string, Record<string, Banca[]>> = {};
		for (const banca of bancas) {
			const id = linhaDaBanca(banca);
			const linha = id === null ? 'Sem linha' : (nomeDaLinha[id] ?? 'Sem linha');
			const alvo = banca.target_label || '—';
			const alvos = (porLinha[linha] ??= {});
			(alvos[alvo] ??= []).push(banca);
		}
		const emOrdem = (a: string, b: string) => a.localeCompare(b, 'pt-BR');
		return Object.keys(porLinha)
			.sort(emOrdem)
			.map((linha) => ({
				chave: linha,
				linha,
				alvos: Object.keys(porLinha[linha])
					.sort(emOrdem)
					.map((alvo) => ({
						chave: `${linha}·${alvo}`,
						alvo,
						bancas: [...porLinha[linha][alvo]].sort(
							(x, y) => NIVEIS.indexOf(x.level) - NIVEIS.indexOf(y.level)
						)
					}))
			}));
	});

	// --- formulário --------------------------------------------------------

	let formAberto = $state(false);
	let emEdicao = $state<Banca | null>(null);

	let editalDoForm = $state<number | ''>('');
	let nivel = $state<Nivel>('masters');
	let alvoId = $state<number | ''>('');
	let membros = $state<Record<string, number | ''>>({
		president: '',
		member_1: '',
		member_2: '',
		alternate: ''
	});

	const edital = $derived(editais.find((e) => e.id === editalDoForm) ?? null);

	const alvos = $derived.by<{ id: number; nome: string }[]>(() => {
		if (edital === null) return [];
		return alvoDoTipo(edital.kind) === 'projeto'
			? projetos.map((p) => ({
					id: p.id,
					nome: `${p.name} · ${nomeDaLinha[p.research_line_id] ?? '—'}`
				}))
			: linhas.map((l) => ({ id: l.id, nome: l.name }));
	});

	// Validação de UX do membro repetido. A que vale é a do model
	// (`duplicate_board_member`): esta só evita a viagem até o servidor.
	const escolhidos = $derived(
		PAPEIS_DA_BANCA.map(({ campo }) => membros[campo]).filter((id) => id !== '')
	);
	const membroRepetido = $derived(escolhidos.some((id, i) => escolhidos.indexOf(id) !== i));
	const completo = $derived(
		editalDoForm !== '' && alvoId !== '' && escolhidos.length === PAPEIS_DA_BANCA.length
	);

	function abrirNova() {
		emEdicao = null;
		editalDoForm = filtroEdital === '' ? (editais[0]?.id ?? '') : filtroEdital;
		nivel = filtroNivel === '' ? 'masters' : filtroNivel;
		alvoId = '';
		membros = { president: '', member_1: '', member_2: '', alternate: '' };
		erro = '';
		aviso = '';
		formAberto = true;
	}

	function editar(banca: Banca) {
		emEdicao = banca;
		editalDoForm = banca.process_id;
		nivel = banca.level;
		alvoId = banca.research_line_id ?? banca.project_id ?? '';
		membros = {
			president: banca.president.id,
			member_1: banca.member_1.id,
			member_2: banca.member_2.id,
			alternate: banca.alternate.id
		};
		erro = '';
		aviso = '';
		formAberto = true;
	}

	function fechar() {
		formAberto = false;
		emEdicao = null;
	}

	/** Trocar de edital pode trocar a natureza do alvo — a escolha antiga
	 * deixaria um id de projeto onde o servidor espera linha. */
	function trocarEditalDoForm() {
		alvoId = '';
	}

	async function salvar(event: SubmitEvent) {
		event.preventDefault();
		if (!completo || membroRepetido || edital === null || alvoId === '') return;
		erro = '';
		aviso = '';
		salvando = true;
		const porProjeto = alvoDoTipo(edital.kind) === 'projeto';
		const composicao = {
			level: nivel,
			project_id: porProjeto ? alvoId : null,
			research_line_id: porProjeto ? null : alvoId,
			president_id: membros.president as number,
			member_1_id: membros.member_1 as number,
			member_2_id: membros.member_2 as number,
			alternate_id: membros.alternate as number
		};
		const alvo = emEdicao;
		const { data, error } = alvo
			? await api.PATCH('/selection/boards/{board_id}/', {
					params: { path: { board_id: alvo.id } },
					body: composicao
				})
			: await api.POST('/selection/boards/', {
					body: { ...composicao, process_id: edital.id }
				});
		salvando = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível salvar a banca.');
			return;
		}
		aviso = alvo ? 'Banca atualizada.' : 'Banca designada.';
		fechar();
		// Recarrega em vez de emendar a lista: a banca recém-salva pode não
		// caber no filtro em vigor, e o agrupamento é por linha do alvo.
		await carregarBancas(filtros());
	}

	$effect(() => {
		carregar();
	});
</script>

<svelte:head>
	<title>Bancas · PPGD Manager</title>
</svelte:head>

<header class="flex flex-wrap items-end justify-between gap-4">
	<div>
		<p class="etiqueta">Processo seletivo</p>
		<h1 class="text-grafite mt-1 text-2xl font-semibold tracking-tight">Bancas</h1>
	</div>
	<div class="flex flex-wrap items-center gap-4">
		<div class="flex items-center gap-2">
			<label class="etiqueta" for="filtro-edital">Edital</label>
			<select id="filtro-edital" class="campo w-64" bind:value={filtroEdital} onchange={refiltrar}>
				<option value="">Todos</option>
				{#each editais as opcao (opcao.id)}
					<option value={opcao.id}>{opcao.title}</option>
				{/each}
			</select>
		</div>
		<div class="flex items-center gap-2">
			<label class="etiqueta" for="filtro-nivel">Nível</label>
			<select id="filtro-nivel" class="campo w-40" bind:value={filtroNivel} onchange={refiltrar}>
				<option value="">Todos</option>
				{#each NIVEIS as opcao (opcao)}
					<option value={opcao}>{ROTULO_DO_NIVEL[opcao]}</option>
				{/each}
			</select>
		</div>
		{#if podeCriar}
			<button class="botao-discreto" type="button" onclick={abrirNova}>Nova banca</button>
		{/if}
	</div>
</header>

{#if erro}
	<p class="aviso-erro mt-6" role="alert">{erro}</p>
{/if}
{#if aviso}
	<p class="etiqueta mt-6" role="status">{aviso}</p>
{/if}

{#if formAberto}
	<form class="border-borda bg-papel mt-8 border p-5" onsubmit={salvar}>
		<p class="etiqueta">{emEdicao ? 'Editar banca' : 'Nova banca'}</p>

		<div class="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
			<div>
				<label class="etiqueta mb-2 block" for="banca-edital">Edital</label>
				<!-- Mudar a banca de edital seria criar outra banca: o PATCH não
				aceita `process_id`, e aqui o campo fica travado na edição. -->
				<select
					id="banca-edital"
					class="campo"
					bind:value={editalDoForm}
					onchange={trocarEditalDoForm}
					disabled={emEdicao !== null}
					required
				>
					<option value="" disabled>Escolha o edital</option>
					{#each editais as opcao (opcao.id)}
						<option value={opcao.id}>{opcao.title}</option>
					{/each}
				</select>
			</div>
			<div>
				<label class="etiqueta mb-2 block" for="banca-nivel">Nível</label>
				<select id="banca-nivel" class="campo" bind:value={nivel}>
					{#each NIVEIS as opcao (opcao)}
						<option value={opcao}>{ROTULO_DO_NIVEL[opcao]}</option>
					{/each}
				</select>
			</div>
			<div>
				<label class="etiqueta mb-2 block" for="banca-alvo">
					{edital !== null && alvoDoTipo(edital.kind) === 'linha'
						? 'Linha de pesquisa'
						: 'Projeto coletivo'}
				</label>
				<select id="banca-alvo" class="campo" bind:value={alvoId} required>
					<option value="" disabled>Escolha o alvo</option>
					{#each alvos as opcao (opcao.id)}
						<option value={opcao.id}>{opcao.nome}</option>
					{/each}
				</select>
			</div>
		</div>

		<div class="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
			{#each PAPEIS_DA_BANCA as papel (papel.campo)}
				<div>
					<label class="etiqueta mb-2 block" for="banca-{papel.campo}">{papel.rotulo}</label>
					<select id="banca-{papel.campo}" class="campo" bind:value={membros[papel.campo]} required>
						<option value="" disabled>Escolha o examinador</option>
						{#each credenciados as professor (professor.id)}
							<option value={professor.id}>
								{rotuloDoExaminador({
									full_name: professor.person.full_name,
									category: professor.category,
									home_institution: professor.home_institution
								})}
							</option>
						{/each}
					</select>
				</div>
			{/each}
		</div>

		{#if membroRepetido}
			<p class="aviso-erro mt-4" role="alert">
				Um professor não pode ocupar dois lugares na mesma banca.
			</p>
		{/if}

		<div class="mt-6 flex gap-2">
			<button class="botao" type="submit" disabled={salvando || membroRepetido || !completo}>
				{salvando ? 'Salvando…' : 'Salvar'}
			</button>
			<button class="botao-discreto" type="button" onclick={fechar}>Cancelar</button>
		</div>
	</form>
{/if}

<section class="mt-10">
	{#if carregando}
		<p class="etiqueta">Carregando…</p>
	{:else if grupos.length === 0}
		<div class="border-borda bg-papel border border-dashed p-10 text-center">
			<p class="text-grafite text-[0.9375rem]">Nenhuma banca designada com estes filtros.</p>
			<p class="text-cinza mt-1 text-sm">
				{podeCriar
					? 'Use "Nova banca" para designar os examinadores de um nível e alvo do edital.'
					: 'A secretaria designa as bancas do edital.'}
			</p>
		</div>
	{:else}
		<div class="space-y-8">
			{#each grupos as grupo (grupo.chave)}
				<div>
					<h2 class="text-grafite text-[0.9375rem] font-semibold tracking-tight">{grupo.linha}</h2>
					<div class="mt-3 space-y-6">
						{#each grupo.alvos as bloco (bloco.chave)}
							<div>
								<p class="etiqueta">{bloco.alvo}</p>
								<ul class="mt-2 space-y-px">
									{#each bloco.bancas as banca (banca.id)}
										<li class="bg-papel regua-tinta px-5 py-4">
											<div class="flex flex-wrap items-start justify-between gap-4">
												<div class="min-w-0">
													<p class="text-grafite text-[0.9375rem] font-medium">
														{banca.level_label} · {banca.process_title}
													</p>
													<dl class="mt-2 grid gap-x-6 gap-y-1 sm:grid-cols-2 lg:grid-cols-4">
														{#each PAPEIS_DA_BANCA as papel (papel.campo)}
															<div>
																<dt class="etiqueta">{papel.rotulo}</dt>
																<dd class="text-grafite text-[0.8125rem]">
																	{rotuloDoExaminador({
																		full_name: banca[papel.campo].full_name,
																		category: banca[papel.campo].category,
																		home_institution: banca[papel.campo].home_institution
																	})}
																</dd>
															</div>
														{/each}
													</dl>
												</div>
												<div class="flex shrink-0 items-center gap-3">
													{#if banca.in_use}
														<span class="etiqueta">Ata congelada</span>
													{/if}
													{#if podeEditar}
														<!-- Composição só muda enquanto todas as atas da banca
														são rascunho (409 `board_in_use`): com ata congelada o
														botão fica desabilitado, e não sumido — sumir daria a
														impressão de que a ação não existe. -->
														<button
															class="botao-icone"
															type="button"
															disabled={banca.in_use}
															title={banca.in_use
																? 'Banca com ata congelada ou assinada'
																: 'Editar banca'}
															onclick={() => editar(banca)}
														>
															<Icone nome="lapis" rotulo="Editar" />
														</button>
													{/if}
												</div>
											</div>
										</li>
									{/each}
								</ul>
							</div>
						{/each}
					</div>
				</div>
			{/each}
		</div>
	{/if}
</section>
