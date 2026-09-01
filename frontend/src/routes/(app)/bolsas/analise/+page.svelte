<script lang="ts">
	import { api, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';
	import Icone from '$lib/Icone.svelte';
	import {
		ESTADOS_DO_RECURSO,
		NIVEIS,
		QUESTIONARIO,
		RESULTADOS_DO_RECURSO,
		SECOES,
		formatarNota,
		rotuloDoItem,
		type CampoDoQuestionario,
		type EstadoDoRecurso,
		type Nivel,
		type ResultadoDoRecurso
	} from '$lib/bolsas';
	import { sessao } from '$lib/sessao.svelte';

	type Edicao = components['schemas']['ScholarshipEditionOut'];
	type LinhaDaFila = components['schemas']['ScholarshipApplicationQueueOut'];
	type Item = components['schemas']['BaremeItemOut'];
	type Lancamento = components['schemas']['BaremeEntryOut'];
	type TotalDoItem = components['schemas']['ApplicationItemTotalOut'];
	type Observacao = components['schemas']['ItemReviewOut'];
	type Recurso = components['schemas']['ScholarshipAppealOut'];

	let edicoes = $state<Edicao[]>([]);
	let edicaoId = $state<number | null>(null);
	const edicao = $derived(edicoes.find((e) => e.id === edicaoId) ?? null);

	let nivel = $state<Nivel>('masters');
	let fila = $state<LinhaDaFila[]>([]);
	let carregando = $state(true);
	let buscando = $state(false);
	let erro = $state('');
	let aviso = $state('');
	let salvando = $state(false);

	// O candidato aberto. A fila continua carregada por trás: voltar não
	// refaz a busca, e é assim que a comissão percorre a lista.
	let selecionadaId = $state<number | null>(null);
	const selecionada = $derived(fila.find((linha) => linha.id === selecionadaId) ?? null);

	let itens = $state<Item[]>([]);
	let lancamentos = $state<Lancamento[]>([]);
	let totais = $state<TotalDoItem[]>([]);
	let observacoes = $state<Observacao[]>([]);
	let recurso = $state<Recurso | null>(null);

	/**
	 * Quem pode o quê sai do papel, e cada leitura tem a sua.
	 *
	 * `review_baremeentry` é exclusiva da Comissão de Bolsas
	 * (`scholarships.0008_papeis_da_bolsa`): a Coordenação, que tem leitura
	 * de todo o app, abre esta tela e não vê nenhum formulário. As duas
	 * leituras de apoio — linha de pesquisa e professor — são de outros
	 * apps, e a Comissão não as tem: os dois filtros só aparecem para quem
	 * pode listar o catálogo.
	 */
	const podeAvaliar = $derived(sessao.pode('scholarships.review_baremeentry'));
	const podeJulgar = $derived(sessao.pode('scholarships.change_scholarshipappeal'));
	const podeVerObservacoes = $derived(sessao.pode('scholarships.view_itemreview'));
	const podeVerRecurso = $derived(sessao.pode('scholarships.view_scholarshipappeal'));
	// Abrir um candidato é ler o material dele: o porteiro é o mesmo do
	// download do comprovante (`_garantir_acesso_a_inscricao`), e a
	// Coordenação não o tem — ela acompanha a fila, não a papelada.
	const podeAbrirCandidato = $derived(sessao.pode('scholarships.download_applicationdocument'));
	const podeVerLinhas = $derived(sessao.pode('programs.view_researchline'));
	const podeVerDocentes = $derived(sessao.pode('academic.view_teacher'));

	// A janela da análise é do servidor: `committee_can_review` resolve
	// `under_review` e `appeals_under_review` num bool só, e `appeal_open`
	// diz se o recurso ainda pode ser julgado. A tela não repete a máquina
	// de estados — só evita o clique que voltaria 409.
	const analiseAberta = $derived(edicao?.committee_can_review ?? false);
	const recursosAbertos = $derived(edicao?.appeal_open ?? false);

	// --- filtros da fila -------------------------------------------------------
	//
	// Os do legado, na mesma ordem: nível (obrigatório), linha, orientador,
	// ano de entrada, cada uma das oito respostas do questionário, estado do
	// recurso e o "somente candidatos com itens a analisar".

	type Linha = components['schemas']['ResearchLineOut'];
	type Docente = components['schemas']['TeacherOut'];

	let linhas = $state<Linha[]>([]);
	let docentes = $state<Docente[]>([]);

	let linhaId = $state<number | null>(null);
	let orientadorId = $state<number | null>(null);
	let anoDeEntrada = $state('');
	let estadoDoRecurso = $state<EstadoDoRecurso | ''>('');
	let somentePendentes = $state(false);

	/** As oito perguntas que a fila filtra; `cadastro_unico` é desempate. */
	const PERGUNTAS_FILTRAVEIS = QUESTIONARIO.filter((p) => p.campo !== 'cadastro_unico');

	type Tri = '' | 'sim' | 'nao';
	let respostas = $state<Record<CampoDoQuestionario, Tri>>(filtrosEmBranco());

	function filtrosEmBranco(): Record<CampoDoQuestionario, Tri> {
		return {
			has_paid_activity: '',
			affirmative_action: '',
			socioeconomic_vulnerability: '',
			cadastro_unico: '',
			substitute_teacher: '',
			basic_education_or_collective_health: '',
			public_service: '',
			private_service: '',
			other_non_public_scholarship: ''
		};
	}

	/** Filtro em branco não vai na consulta: `undefined` some da query. */
	function resposta(campo: CampoDoQuestionario): boolean | undefined {
		const escolha = respostas[campo];
		return escolha === '' ? undefined : escolha === 'sim';
	}

	function limparFiltros() {
		linhaId = null;
		orientadorId = null;
		anoDeEntrada = '';
		estadoDoRecurso = '';
		somentePendentes = false;
		respostas = filtrosEmBranco();
	}

	// --- carregamento ----------------------------------------------------------

	async function carregarEdicoes() {
		const { data, error } = await api.GET('/scholarships/editions/');
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar as edições do edital de bolsas.');
			return;
		}
		edicoes = data?.items ?? [];
		edicaoId = edicoes[0]?.id ?? null;
	}

	async function carregarCatalogos() {
		if (podeVerLinhas) {
			const { data } = await api.GET('/programs/research-lines/', {
				params: { query: { limit: 200 } }
			});
			linhas = data?.items ?? [];
		}
		if (podeVerDocentes) {
			const { data } = await api.GET('/academic/teachers/', {
				params: { query: { limit: 500 } }
			});
			docentes = data?.items ?? [];
		}
	}

	async function carregarBarema(alvo: number) {
		const { data, error } = await api.GET('/scholarships/editions/{edition_id}/bareme/', {
			params: { path: { edition_id: alvo } }
		});
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar o barema desta edição.');
			return;
		}
		itens = data ?? [];
	}

	async function buscar() {
		if (edicaoId === null) return;
		buscando = true;
		erro = '';
		const { data, error } = await api.GET('/scholarships/editions/{edition_id}/applications/', {
			params: {
				path: { edition_id: edicaoId },
				query: {
					level: nivel,
					// A fila é paginada no servidor; a comissão trabalha a
					// edição inteira de uma vez, então o limite é alto e a
					// contagem aparece na tela.
					limit: 200,
					research_line_id: linhaId ?? undefined,
					advisor_id: orientadorId ?? undefined,
					admission_year: anoDeEntrada === '' ? undefined : Number(anoDeEntrada),
					has_paid_activity: resposta('has_paid_activity'),
					affirmative_action: resposta('affirmative_action'),
					socioeconomic_vulnerability: resposta('socioeconomic_vulnerability'),
					substitute_teacher: resposta('substitute_teacher'),
					basic_education_or_collective_health: resposta('basic_education_or_collective_health'),
					public_service: resposta('public_service'),
					private_service: resposta('private_service'),
					other_non_public_scholarship: resposta('other_non_public_scholarship'),
					appeal: estadoDoRecurso === '' ? undefined : estadoDoRecurso,
					pending_review: somentePendentes ? true : undefined
				}
			}
		});
		buscando = false;
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar a fila de análise.');
			return;
		}
		fila = data?.items ?? [];
	}

	async function carregar() {
		carregando = true;
		erro = '';
		await Promise.all([carregarEdicoes(), carregarCatalogos()]);
		if (edicaoId !== null) await Promise.all([carregarBarema(edicaoId), buscar()]);
		carregando = false;
	}

	async function trocarDeEdicao(alvo: number) {
		edicaoId = alvo;
		fecharCandidato();
		fila = [];
		itens = [];
		erro = '';
		aviso = '';
		await Promise.all([carregarBarema(alvo), buscar()]);
	}

	async function trocarDeNivel(alvo: Nivel) {
		nivel = alvo;
		fecharCandidato();
		await buscar();
	}

	// --- um candidato ----------------------------------------------------------

	function fecharCandidato() {
		selecionadaId = null;
		lancamentos = [];
		totais = [];
		observacoes = [];
		recurso = null;
		fecharFormularios();
	}

	function fecharFormularios() {
		avaliando = null;
		itemComentado = null;
		julgando = false;
	}

	async function abrirCandidato(linha: LinhaDaFila) {
		erro = '';
		aviso = '';
		fecharFormularios();
		selecionadaId = linha.id;
		await carregarCandidato(linha.id);
	}

	async function carregarCandidato(alvo: number) {
		const [lista, soma, notas] = await Promise.all([
			api.GET('/scholarships/applications/{application_id}/entries/', {
				params: { path: { application_id: alvo } }
			}),
			api.GET('/scholarships/applications/{application_id}/item-totals/', {
				params: { path: { application_id: alvo } }
			}),
			podeVerObservacoes
				? api.GET('/scholarships/applications/{application_id}/item-reviews/', {
						params: { path: { application_id: alvo } }
					})
				: null
		]);
		const falha = lista.error ?? soma.error ?? notas?.error;
		if (falha) {
			erro = mensagemDeErro(falha, 'Não foi possível carregar os lançamentos deste candidato.');
			return;
		}
		lancamentos = lista.data ?? [];
		totais = soma.data ?? [];
		observacoes = notas?.data ?? [];
		await carregarRecurso(alvo);
	}

	/**
	 * O recurso do candidato — ou nenhum.
	 *
	 * 404 aqui não é falha: "não recorreu" é o caso normal, e é ele que faz
	 * a tela não desenhar o painel do julgamento. Por isso o código HTTP sai
	 * para uma const ANTES do `if`: dentro dele o objeto inteiro é estreitado
	 * e `resposta.response` viraria `never`.
	 */
	async function carregarRecurso(alvo: number) {
		if (!podeVerRecurso) return;
		const resposta = await api.GET('/scholarships/applications/{application_id}/appeal', {
			params: { path: { application_id: alvo } }
		});
		const codigo = resposta.response.status;
		const falha = resposta.error;
		if (falha || !resposta.data) {
			recurso = null;
			if (codigo !== 404) {
				erro = mensagemDeErro(falha, 'Não foi possível carregar o recurso deste candidato.');
			}
			return;
		}
		recurso = resposta.data;
	}

	/**
	 * Depois de cada escrita: os totais e as duas notas do cabeçalho são
	 * derivados no servidor, e a fila é quem os traz. Recarregar as duas
	 * coisas é o que mantém "Candidato × Comissão" honesto na tela.
	 */
	async function recarregarCandidato() {
		if (selecionadaId === null) return;
		const alvo = selecionadaId;
		await Promise.all([carregarCandidato(alvo), buscar()]);
		selecionadaId = alvo;
	}

	// --- avaliação de um lançamento --------------------------------------------

	let avaliando = $state<number | null>(null);
	let nota = $state('');
	let observacaoDaNota = $state('');

	function abrirAvaliacao(lancamento: Lancamento) {
		fecharFormularios();
		erro = '';
		aviso = '';
		avaliando = lancamento.id;
		// Sem nota ainda, o campo abre com o que o candidato pediu: é o
		// caso mais comum ("confere") e o que menos digita.
		nota = String(lancamento.committee_score ?? lancamento.candidate_score);
		observacaoDaNota = lancamento.committee_note;
	}

	/**
	 * Nota diferente da do candidato exige observação — regra do model
	 * (`note_required`), repetida aqui só para o clique não se perder.
	 */
	const notaDivergente = $derived.by(() => {
		const alvo = lancamentos.find((l) => l.id === avaliando);
		if (alvo === undefined || nota === '') return false;
		return Number(nota) !== Number(alvo.candidate_score);
	});
	const faltaObservacao = $derived(notaDivergente && observacaoDaNota.trim() === '');

	async function salvarAvaliacao(event: SubmitEvent) {
		event.preventDefault();
		if (avaliando === null) return;
		erro = '';
		aviso = '';
		salvando = true;
		const { error } = await api.PATCH('/scholarships/entries/{entry_id}/review', {
			params: { path: { entry_id: avaliando } },
			body: { committee_score: nota, committee_note: observacaoDaNota }
		});
		salvando = false;
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível registrar a avaliação.');
			return;
		}
		avaliando = null;
		aviso = 'Avaliação registrada.';
		await recarregarCandidato();
	}

	// --- observação sobre o item inteiro ---------------------------------------

	let itemComentado = $state<number | null>(null);
	let textoDaObservacao = $state('');

	function observacaoDoItem(itemId: number): Observacao | undefined {
		return observacoes.find((o) => o.item_id === itemId);
	}

	function abrirObservacao(item: Item) {
		fecharFormularios();
		erro = '';
		aviso = '';
		itemComentado = item.id;
		textoDaObservacao = observacaoDoItem(item.id)?.note ?? '';
	}

	async function salvarObservacao(event: SubmitEvent) {
		event.preventDefault();
		if (itemComentado === null || selecionadaId === null) return;
		erro = '';
		aviso = '';
		salvando = true;
		const { error } = await api.PUT('/scholarships/applications/{application_id}/item-review', {
			params: { path: { application_id: selecionadaId } },
			body: { item_id: itemComentado, note: textoDaObservacao }
		});
		salvando = false;
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível gravar a observação do item.');
			return;
		}
		itemComentado = null;
		aviso = 'Observação gravada.';
		await recarregarCandidato();
	}

	// --- julgamento do recurso -------------------------------------------------

	let julgando = $state(false);
	let resultado = $state<ResultadoDoRecurso>('denied');
	let fundamentacao = $state('');

	function abrirJulgamento() {
		fecharFormularios();
		erro = '';
		aviso = '';
		julgando = true;
		resultado = 'denied';
		fundamentacao = '';
	}

	async function julgarRecurso(event: SubmitEvent) {
		event.preventDefault();
		if (recurso === null) return;
		erro = '';
		aviso = '';
		salvando = true;
		const { error } = await api.PATCH('/scholarships/appeals/{appeal_id}/judge', {
			params: { path: { appeal_id: recurso.id } },
			body: { outcome: resultado, reasoning: fundamentacao }
		});
		salvando = false;
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível julgar o recurso.');
			return;
		}
		julgando = false;
		aviso = 'Recurso julgado.';
		await recarregarCandidato();
	}

	// --- o corpo da análise, na ordem do barema --------------------------------

	const itensDoNivel = $derived(
		selecionada === null ? [] : itens.filter((i) => i.level === selecionada?.level)
	);

	/**
	 * Seção → item → lançamentos daquele item, como o edital escreve.
	 *
	 * Só entram os itens em que o candidato lançou alguma coisa: esta é a
	 * tela de quem analisa o que foi entregue, e não a de quem lança — o
	 * item vazio aqui seria linha em branco em toda inscrição.
	 */
	const secoesDaAnalise = $derived(
		SECOES.map(({ valor, rotulo }) => ({
			valor,
			rotulo,
			linhas: itensDoNivel
				.filter((i) => i.section === valor)
				.map((item) => ({
					item,
					total: totais.find((t) => t.item_id === item.id) ?? null,
					lancamentos: lancamentos.filter((l) => l.item_id === item.id)
				}))
				.filter((linha) => linha.lancamentos.length > 0)
		})).filter((s) => s.linhas.length > 0)
	);

	$effect(() => {
		carregar();
	});
</script>

<svelte:head>
	<title>Análise da comissão · PPGD Manager</title>
</svelte:head>

<header>
	<p class="etiqueta">Bolsas</p>
	<h1 class="text-grafite mt-1 text-2xl font-semibold tracking-tight">Análise da comissão</h1>
</header>

{#if erro}
	<p class="aviso-erro mt-6" role="alert">{erro}</p>
{/if}
{#if aviso}
	<p class="border-borda bg-papel text-grafite mt-6 border px-4 py-3 text-sm" role="status">
		{aviso}
	</p>
{/if}

{#if carregando}
	<p class="etiqueta mt-6">Carregando…</p>
{:else if edicoes.length === 0}
	<div class="border-borda bg-papel mt-6 border border-dashed p-10 text-center">
		<p class="text-grafite text-[0.9375rem]">Nenhum edital de bolsas neste programa.</p>
	</div>
{:else}
	<div class="mt-8 grid gap-4 sm:grid-cols-2">
		<div>
			<label class="etiqueta mb-2 block" for="analise-edicao">Edição</label>
			<select
				id="analise-edicao"
				class="campo"
				value={edicaoId}
				onchange={(e) => trocarDeEdicao(Number(e.currentTarget.value))}
			>
				{#each edicoes as opcao (opcao.id)}
					<option value={opcao.id}>{opcao.year} · {opcao.title} ({opcao.status_label})</option>
				{/each}
			</select>
		</div>
		<div>
			<!-- Obrigatório: a classificação corre por nível, e uma fila que
			mistura mestrado e doutorado não é a fila de ninguém. -->
			<label class="etiqueta mb-2 block" for="analise-nivel">Nível</label>
			<select
				id="analise-nivel"
				class="campo"
				value={nivel}
				onchange={(e) => trocarDeNivel(e.currentTarget.value as Nivel)}
			>
				{#each NIVEIS as opcao (opcao.valor)}
					<option value={opcao.valor}>{opcao.rotulo}</option>
				{/each}
			</select>
		</div>
	</div>

	{#if edicao && !analiseAberta}
		<p class="text-cinza mt-4 text-sm">
			Esta edição não está em análise ({edicao.status_label}): a fila é somente leitura até a
			secretaria abrir a fase.
		</p>
	{/if}

	{#if selecionada === null}
		<!-- Fila --------------------------------------------------------------- -->
		<section class="border-borda bg-papel mt-6 border p-5">
			<details class="group">
				<summary class="etiqueta cursor-pointer list-none marker:content-['']">
					Filtros <span aria-hidden="true" class="text-cinza text-[0.625rem]">▾</span>
				</summary>
				<div class="mt-4 grid gap-4 sm:grid-cols-2">
					{#if podeVerLinhas}
						<div>
							<label class="etiqueta mb-2 block" for="filtro-linha">Linha de pesquisa</label>
							<select
								id="filtro-linha"
								class="campo"
								value={linhaId ?? ''}
								onchange={(e) =>
									(linhaId = e.currentTarget.value === '' ? null : Number(e.currentTarget.value))}
							>
								<option value="">Todas</option>
								{#each linhas as linha (linha.id)}
									<option value={linha.id}>{linha.name}</option>
								{/each}
							</select>
						</div>
					{/if}
					{#if podeVerDocentes}
						<div>
							<label class="etiqueta mb-2 block" for="filtro-orientador">Orientador</label>
							<select
								id="filtro-orientador"
								class="campo"
								value={orientadorId ?? ''}
								onchange={(e) =>
									(orientadorId =
										e.currentTarget.value === '' ? null : Number(e.currentTarget.value))}
							>
								<option value="">Todos</option>
								{#each docentes as docente (docente.id)}
									<option value={docente.id}>{docente.person.full_name}</option>
								{/each}
							</select>
						</div>
					{/if}
					<div>
						<label class="etiqueta mb-2 block" for="filtro-ano">Ano de entrada</label>
						<input
							id="filtro-ano"
							class="campo"
							type="number"
							min="1990"
							step="1"
							bind:value={anoDeEntrada}
						/>
					</div>
					<div>
						<label class="etiqueta mb-2 block" for="filtro-recurso">Recurso</label>
						<select id="filtro-recurso" class="campo" bind:value={estadoDoRecurso}>
							<option value="">Qualquer</option>
							{#each ESTADOS_DO_RECURSO as opcao (opcao.valor)}
								<option value={opcao.valor}>{opcao.rotulo}</option>
							{/each}
						</select>
					</div>
					<fieldset class="sm:col-span-2">
						<legend class="etiqueta">Respostas do questionário</legend>
						<div class="mt-2 grid gap-3 sm:grid-cols-2">
							{#each PERGUNTAS_FILTRAVEIS as pergunta (pergunta.campo)}
								<div>
									<label class="text-grafite mb-1 block text-sm" for={`filtro-${pergunta.campo}`}>
										{pergunta.rotulo}
									</label>
									<select
										id={`filtro-${pergunta.campo}`}
										class="campo"
										bind:value={respostas[pergunta.campo]}
									>
										<option value="">Qualquer</option>
										<option value="sim">Sim</option>
										<option value="nao">Não</option>
									</select>
								</div>
							{/each}
						</div>
					</fieldset>
					<label class="text-grafite flex items-center gap-3 text-sm sm:col-span-2">
						<input type="checkbox" bind:checked={somentePendentes} />
						Somente candidatos com itens a analisar
					</label>
				</div>
				<div class="mt-4 flex flex-wrap items-center gap-2">
					<button class="botao" type="button" disabled={buscando} onclick={buscar}>
						{buscando ? 'Buscando…' : 'Aplicar filtros'}
					</button>
					<button class="botao-discreto" type="button" onclick={limparFiltros}>Limpar</button>
				</div>
			</details>

			<p class="etiqueta mt-6">{fila.length} candidato(s) nesta fila</p>
			{#if !podeAbrirCandidato}
				<p class="text-cinza mt-2 text-sm">
					Esta é a fila em leitura: abrir a inscrição de um candidato é ler o material dele, e isso
					é da Comissão de Bolsas e da Secretaria.
				</p>
			{/if}

			{#if fila.length === 0}
				<p class="text-cinza mt-4 text-sm">
					Nenhuma inscrição neste nível com os filtros escolhidos.
				</p>
			{:else}
				<div class="mt-4 overflow-x-auto">
					<table class="w-full text-sm">
						<thead>
							<tr class="border-borda border-b text-left">
								<th class="etiqueta py-2">Candidato</th>
								<th class="etiqueta py-2">Linha</th>
								<th class="etiqueta py-2">Orientador</th>
								<th class="etiqueta py-2 text-right">Entrada</th>
								<th class="etiqueta py-2 text-right">Candidato</th>
								<th class="etiqueta py-2 text-right">Comissão</th>
								<th class="etiqueta py-2">Faixa</th>
								<th class="etiqueta py-2">Situação</th>
								<th class="etiqueta py-2"><span class="sr-only">Ações</span></th>
							</tr>
						</thead>
						<tbody>
							{#each fila as linha (linha.id)}
								<tr class="border-borda text-grafite border-b">
									<td class="py-2 align-top">
										{linha.student_name}
										{#if linha.pending_docs.length > 0}
											<span class="text-cinza mt-1 block text-sm">
												Sim — não enviado: {linha.pending_docs.map((d) => d.kind_label).join(', ')}
											</span>
										{/if}
									</td>
									<td class="py-2 align-top">{linha.research_line ?? '—'}</td>
									<td class="py-2 align-top">{linha.advisor_name ?? '—'}</td>
									<td class="py-2 text-right align-top">{linha.admission_year ?? '—'}</td>
									<td class="py-2 text-right align-top">{formatarNota(linha.candidate_score)}</td>
									<td class="py-2 text-right align-top">{formatarNota(linha.committee_score)}</td>
									<td class="py-2 align-top">{linha.band ?? '—'}</td>
									<td class="py-2 align-top">
										{linha.fully_reviewed ? 'Todos itens analisados' : 'Itens a analisar'}
										{#if linha.appeal_state !== 'none'}
											<span class="text-cinza mt-1 block text-sm">
												Recurso: {ESTADOS_DO_RECURSO.find((e) => e.valor === linha.appeal_state)
													?.rotulo}
											</span>
										{/if}
									</td>
									<td class="py-2 text-right align-top">
										{#if podeAbrirCandidato}
											<button
												class="botao-discreto"
												type="button"
												onclick={() => abrirCandidato(linha)}
											>
												Analisar
											</button>
										{/if}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</section>
	{:else}
		<!-- Um candidato -------------------------------------------------------- -->
		<section class="border-borda bg-papel mt-6 border p-5">
			<div class="flex flex-wrap items-start justify-between gap-4">
				<div>
					<p class="etiqueta">{selecionada.level_label}</p>
					<h2 class="text-grafite mt-1 text-lg font-semibold tracking-tight">
						{selecionada.student_name}
					</h2>
				</div>
				<button class="botao-discreto" type="button" onclick={fecharCandidato}>
					Voltar à fila
				</button>
			</div>

			<!-- As duas notas lado a lado: o que foi pedido e o que foi
			concedido. As duas são derivadas no servidor, com o teto do item
			já aplicado sobre a soma dos lançamentos. -->
			<dl class="text-grafite mt-4 grid gap-3 text-sm sm:grid-cols-4">
				<div>
					<dt class="etiqueta">Candidato</dt>
					<dd class="text-lg">{formatarNota(selecionada.candidate_score)}</dd>
				</div>
				<div>
					<dt class="etiqueta">Comissão</dt>
					<dd class="text-lg">{formatarNota(selecionada.committee_score)}</dd>
				</div>
				<div>
					<dt class="etiqueta">Faixa de prioridade</dt>
					<dd>{selecionada.band ?? '—'}</dd>
				</div>
				<div>
					<dt class="etiqueta">Situação</dt>
					<dd>
						{selecionada.fully_reviewed ? 'Todos itens analisados' : 'Itens a analisar'}
					</dd>
				</div>
			</dl>
			{#if selecionada.pending_docs.length > 0}
				<p class="text-grafite mt-4 text-sm">
					Sim — não enviado: {selecionada.pending_docs.map((d) => d.kind_label).join(', ')}.
				</p>
			{/if}

			{#if secoesDaAnalise.length === 0}
				<p class="text-cinza mt-6 text-sm">Este candidato não lançou nenhum item do barema.</p>
			{/if}

			{#each secoesDaAnalise as secao (secao.valor)}
				<h3 class="text-grafite mt-6 text-[0.9375rem] font-semibold">{secao.rotulo}</h3>
				{#each secao.linhas as linha (linha.item.id)}
					<article class="border-borda mt-3 border p-4">
						<p class="text-grafite text-sm font-semibold">{rotuloDoItem(linha.item)}</p>

						<table class="mt-2 w-full text-sm">
							<thead>
								<tr class="border-borda border-b text-left">
									<th class="etiqueta py-2">Descrição</th>
									<th class="etiqueta py-2 text-right">{linha.item.unit_label}</th>
									<th class="etiqueta py-2 text-right">Candidato</th>
									<th class="etiqueta py-2 text-right">Comissão</th>
									<th class="etiqueta py-2">Comprovante</th>
									<th class="etiqueta py-2"><span class="sr-only">Ações</span></th>
								</tr>
							</thead>
							<tbody>
								{#each linha.lancamentos as lancamento (lancamento.id)}
									<tr class="border-borda text-grafite border-b align-top">
										<td class="py-2">
											{lancamento.description}
											{#if lancamento.committee_note}
												<!-- A observação da comissão em destaque sob o
												lançamento: é o que o candidato lê para recorrer. -->
												<span class="border-borda text-cinza mt-2 block border-l-2 pl-3 text-sm">
													{lancamento.committee_note}
												</span>
											{/if}
										</td>
										<td class="py-2 text-right">{formatarNota(lancamento.quantity)}</td>
										<td class="py-2 text-right">{formatarNota(lancamento.candidate_score)}</td>
										<td class="py-2 text-right">{formatarNota(lancamento.committee_score)}</td>
										<td class="py-2">
											<!-- Download pelo Django (rota auditada): não é rota da
											SPA, então `resolve()` não se aplica. -->
											<!-- eslint-disable svelte/no-navigation-without-resolve -->
											<a
												class="underline"
												href={`/api/v1/scholarships/entries/${lancamento.id}/proof/download`}
											>
												<Icone nome="documento" tamanho={14} rotulo="Baixar" />
												{lancamento.proof_filename}
											</a>
											<!-- eslint-enable svelte/no-navigation-without-resolve -->
										</td>
										<td class="py-2 text-right">
											{#if podeAvaliar && analiseAberta && avaliando !== lancamento.id}
												<button
													class="botao-discreto"
													type="button"
													onclick={() => abrirAvaliacao(lancamento)}
												>
													{lancamento.reviewed_at ? 'Reavaliar' : 'Avaliar'}
												</button>
											{/if}
										</td>
									</tr>
									{#if avaliando === lancamento.id}
										<tr>
											<td colspan="6" class="py-2">
												<form
													class="border-borda border border-dashed p-4"
													onsubmit={salvarAvaliacao}
												>
													<p class="etiqueta">Avaliação da comissão</p>
													<p class="text-cinza mt-1 text-sm">
														A comissão pontua o que o candidato lançou; descrição e quantidade não
														mudam por aqui.
													</p>
													<div class="mt-3 grid gap-4 sm:grid-cols-3">
														<div>
															<label class="etiqueta mb-2 block" for="avaliacao-nota">Nota</label>
															<input
																id="avaliacao-nota"
																class="campo"
																type="number"
																step="0.01"
																min="0"
																bind:value={nota}
																required
															/>
														</div>
														<div class="sm:col-span-2">
															<label class="etiqueta mb-2 block" for="avaliacao-observacao">
																Observação
															</label>
															<textarea
																id="avaliacao-observacao"
																class="campo"
																rows="2"
																bind:value={observacaoDaNota}></textarea>
														</div>
													</div>
													{#if faltaObservacao}
														<p class="text-cinza mt-2 text-sm">
															Nota diferente da do candidato exige observação: é ela que fundamenta
															o corte, e é dela que sai o recurso.
														</p>
													{/if}
													<div class="mt-4 flex flex-wrap items-center gap-2">
														<button
															class="botao"
															type="submit"
															disabled={salvando || faltaObservacao}
														>
															{salvando ? 'Salvando…' : 'Salvar avaliação'}
														</button>
														<button
															class="botao-discreto"
															type="button"
															onclick={() => (avaliando = null)}
														>
															Cancelar
														</button>
													</div>
												</form>
											</td>
										</tr>
									{/if}
								{/each}
							</tbody>
							<tfoot>
								<tr class="text-grafite">
									<!-- "Nota total" do item, com o TETO JÁ APLICADO — a conta
									vem do servidor (`item-totals`), porque o limite corta a soma
									dos lançamentos do item e não cada um deles. -->
									<td class="py-2 font-semibold" colspan="2">Nota total (limite aplicado)</td>
									<td class="py-2 text-right font-semibold">
										{formatarNota(linha.total?.candidate_total)}
									</td>
									<td class="py-2 text-right font-semibold">
										{formatarNota(linha.total?.committee_total)}
									</td>
									<td class="py-2" colspan="2"></td>
								</tr>
							</tfoot>
						</table>

						{#if podeVerObservacoes}
							{@const comentario = observacaoDoItem(linha.item.id)}
							{#if comentario && itemComentado !== linha.item.id}
								<p class="border-borda text-grafite mt-3 border-l-2 pl-3 text-sm">
									<span class="etiqueta block">Observação da comissão sobre o item</span>
									{comentario.note}
								</p>
							{/if}
							{#if podeAvaliar && analiseAberta && itemComentado !== linha.item.id}
								<button
									class="botao-discreto mt-3"
									type="button"
									onclick={() => abrirObservacao(linha.item)}
								>
									{comentario ? 'Editar observação do item' : 'Comentar o item'}
								</button>
							{/if}
						{/if}
						{#if itemComentado === linha.item.id}
							<form class="border-borda mt-3 border border-dashed p-4" onsubmit={salvarObservacao}>
								<label class="etiqueta mb-2 block" for="observacao-item">
									Observação sobre o item inteiro
								</label>
								<textarea
									id="observacao-item"
									class="campo"
									rows="3"
									bind:value={textoDaObservacao}
									required></textarea>
								<div class="mt-4 flex flex-wrap items-center gap-2">
									<button class="botao" type="submit" disabled={salvando}>
										{salvando ? 'Salvando…' : 'Salvar observação'}
									</button>
									<button
										class="botao-discreto"
										type="button"
										onclick={() => (itemComentado = null)}
									>
										Cancelar
									</button>
								</div>
							</form>
						{/if}
					</article>
				{/each}
			{/each}

			<!-- Recurso: julgado aqui, e não na tela do aluno ------------------- -->
			{#if podeVerRecurso && recurso}
				<section class="border-borda mt-8 border p-4">
					<p class="etiqueta">Recurso</p>
					<p class="text-grafite mt-2 text-sm whitespace-pre-line">{recurso.text}</p>
					<p class="text-cinza mt-2 text-sm">
						Interposto em {new Date(recurso.submitted_at).toLocaleDateString('pt-BR')}.
					</p>
					{#if recurso.judged}
						<p class="text-grafite mt-3 text-sm">
							<span class="etiqueta block">{recurso.outcome_label}</span>
							{recurso.reasoning}
						</p>
					{:else if podeJulgar && recursosAbertos && !julgando}
						<button class="botao-discreto mt-3" type="button" onclick={abrirJulgamento}>
							Julgar recurso
						</button>
					{:else if !recurso.judged && !recursosAbertos}
						<p class="text-cinza mt-3 text-sm">
							O julgamento só acontece com a fase de recursos aberta pela secretaria.
						</p>
					{/if}
					{#if julgando}
						<form class="border-borda mt-3 border border-dashed p-4" onsubmit={julgarRecurso}>
							<div class="grid gap-4 sm:grid-cols-3">
								<div>
									<label class="etiqueta mb-2 block" for="recurso-resultado">Resultado</label>
									<select id="recurso-resultado" class="campo" bind:value={resultado}>
										{#each RESULTADOS_DO_RECURSO as opcao (opcao.valor)}
											<option value={opcao.valor}>{opcao.rotulo}</option>
										{/each}
									</select>
								</div>
								<div class="sm:col-span-2">
									<label class="etiqueta mb-2 block" for="recurso-fundamentacao">
										Fundamentação
									</label>
									<textarea
										id="recurso-fundamentacao"
										class="campo"
										rows="3"
										bind:value={fundamentacao}
										required></textarea>
								</div>
							</div>
							<p class="text-cinza mt-2 text-sm">
								Deferir é decidir: refazer o lançamento atacado é o ato seguinte, pela avaliação
								acima.
							</p>
							<div class="mt-4 flex flex-wrap items-center gap-2">
								<button class="botao" type="submit" disabled={salvando}>
									{salvando ? 'Salvando…' : 'Registrar julgamento'}
								</button>
								<button class="botao-discreto" type="button" onclick={() => (julgando = false)}>
									Cancelar
								</button>
							</div>
						</form>
					{/if}
				</section>
			{/if}
		</section>
	{/if}
{/if}
