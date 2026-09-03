<script lang="ts">
	import { resolve } from '$app/paths';
	import { api, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';
	import {
		ESPECIES_DE_REALOCACAO,
		NIVEIS,
		ROTULO_DO_NIVEL,
		ROTULO_DO_TIPO,
		alvoDoTipo,
		formatarMomento,
		rotuloDaVaga,
		type EspecieDeRealocacao,
		type Nivel
	} from '$lib/selecao';
	import { sessao } from '$lib/sessao.svelte';

	type Edital = components['schemas']['SelectionProcessOut'];
	type Vaga = components['schemas']['VacancyOut'];
	type Linha = components['schemas']['ResearchLineOut'];
	type Projeto = components['schemas']['CollectiveProjectOut'];
	type Classificacao = components['schemas']['RankingOut'];
	type Classificado = components['schemas']['RankedApplicationOut'];
	type Realocacao = components['schemas']['VacancyReallocationOut'];

	let editais = $state<Edital[]>([]);
	let vagas = $state<Vaga[]>([]);
	let linhas = $state<Linha[]>([]);
	let projetos = $state<Projeto[]>([]);
	let realocacoes = $state<Realocacao[]>([]);
	let classificacao = $state<Classificacao | null>(null);

	let carregando = $state(true);
	let calculando = $state(false);
	let erro = $state('');
	let aviso = $state('');

	let editalId = $state<number | ''>('');
	let nivel = $state<Nivel>('masters');
	let alvoId = $state<number | ''>('');

	const edital = $derived(editais.find((e) => e.id === editalId) ?? null);
	const porProjeto = $derived(edital !== null && alvoDoTipo(edital.kind) === 'projeto');

	// Calcular reescreve `final_rank`/`final_outcome` das inscrições: é
	// `change_application`, a mesma permissão de homologar. Realocar é o
	// único poder que a secretaria **não** tem — só a Comissão de Seleção
	// (`0006_papeis_da_selecao`). Converter em aluno soma as duas portas:
	// a inscrição muda de estado e nasce um `Student`.
	const podeCalcular = $derived(sessao.pode('selection.change_application'));
	const podeRealocar = $derived(sessao.pode('selection.add_vacancyreallocation'));
	const podeVerRealocacoes = $derived(sessao.pode('selection.view_vacancyreallocation'));
	const podeConverter = $derived(
		sessao.pode('selection.change_application') && sessao.pode('academic.add_student')
	);

	/**
	 * Os alvos possíveis do edital escolhido.
	 *
	 * Regular chaveia por projeto coletivo; Suplementar, por linha de
	 * pesquisa (P4) — mesma regra da grade de vagas em `selecao/editais`.
	 * Quem recusa a combinação errada continua sendo o servidor
	 * (`target_mismatch`).
	 */
	const alvos = $derived.by<{ id: number; nome: string }[]>(() => {
		if (edital === null) return [];
		return porProjeto
			? projetos.map((p) => ({ id: p.id, nome: p.name }))
			: linhas.map((l) => ({ id: l.id, nome: l.name }));
	});

	const escolhaCompleta = $derived(editalId !== '' && alvoId !== '');

	// --- carregamento ------------------------------------------------------

	async function carregarEditais() {
		const { data, error } = await api.GET('/selection/processes/');
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar os editais do programa.');
			return;
		}
		editais = data?.items ?? [];
	}

	async function carregarApoio() {
		const [pesquisa, coletivos] = await Promise.all([
			api.GET('/programs/research-lines/'),
			api.GET('/programs/collective-projects/')
		]);
		const falha = pesquisa.error ?? coletivos.error;
		if (falha) {
			erro = mensagemDeErro(falha, 'Não foi possível carregar linhas e projetos do programa.');
			return;
		}
		linhas = (pesquisa.data?.items ?? []).filter((l) => l.is_active);
		projetos = (coletivos.data?.items ?? []).filter((p) => p.is_active);
	}

	/** Vagas e histórico de realocação do edital — os dois são do edital
	 * inteiro, e não do recorte: a comissão move vaga entre níveis e entre
	 * alvos, então a grade toda precisa estar à mão. */
	async function carregarGradeDoEdital(processo: number) {
		const { data, error } = await api.GET('/selection/processes/{process_id}/vacancies/', {
			params: { path: { process_id: processo } }
		});
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar a grade de vagas do edital.');
			return;
		}
		vagas = data ?? [];
		await carregarRealocacoes(processo);
	}

	async function carregarRealocacoes(processo: number) {
		if (!podeVerRealocacoes) return;
		const { data, error } = await api.GET('/selection/processes/{process_id}/reallocations/', {
			params: { path: { process_id: processo } }
		});
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar o histórico de realocações.');
			return;
		}
		realocacoes = data ?? [];
	}

	/**
	 * A classificação já calculada do recorte, sem calcular nada.
	 *
	 * Chave ainda não classificada devolve a grade de vagas e a lista
	 * vazia — é exatamente o que a tela mostra antes do primeiro clique em
	 * "Calcular classificação".
	 */
	async function carregarClassificacao() {
		if (editalId === '' || alvoId === '') {
			classificacao = null;
			return;
		}
		const { data, error } = await api.GET('/selection/processes/{process_id}/ranking', {
			params: {
				path: { process_id: editalId },
				// A chave omitida fica **fora** da query, e não como
				// `project_id=`: o alvo é XOR, e string vazia não é `None`
				// para o Ninja.
				query: {
					level: nivel,
					...(porProjeto ? { project_id: alvoId } : { research_line_id: alvoId })
				}
			}
		});
		if (error) {
			classificacao = null;
			erro = mensagemDeErro(error, 'Não foi possível carregar a classificação deste recorte.');
			return;
		}
		classificacao = data ?? null;
	}

	async function trocarEdital() {
		alvoId = '';
		vagas = [];
		realocacoes = [];
		classificacao = null;
		fecharFormularios();
		erro = '';
		aviso = '';
		carregando = true;
		if (editalId !== '') await carregarGradeDoEdital(editalId);
		carregando = false;
	}

	async function trocarRecorte() {
		fecharFormularios();
		erro = '';
		aviso = '';
		carregando = true;
		await carregarClassificacao();
		carregando = false;
	}

	function fecharFormularios() {
		convertendo = null;
		formDaRealocacao = false;
		alunoCriado = null;
	}

	// --- cálculo -----------------------------------------------------------

	async function calcular() {
		if (editalId === '' || alvoId === '' || calculando) return;
		erro = '';
		aviso = '';
		// O link do aluno recém-criado acompanha o aviso: sem zerar aqui,
		// ele sobraria colado num aviso que não é dele.
		alunoCriado = null;
		calculando = true;
		const { data, error } = await api.POST('/selection/processes/{process_id}/ranking', {
			params: { path: { process_id: editalId } },
			body: {
				level: nivel,
				project_id: porProjeto ? alvoId : null,
				research_line_id: porProjeto ? null : alvoId
			}
		});
		calculando = false;
		if (error || !data) {
			// `final_record_not_signed` e `ranking_locked` são os dois casos
			// corriqueiros, e o servidor já explica os dois em português.
			erro = mensagemDeErro(error, 'Não foi possível calcular a classificação deste recorte.');
			return;
		}
		classificacao = data;
		const empatados = data.applications.filter((c) => c.tie_unresolved).length;
		aviso =
			empatados > 0
				? `Classificação calculada: ${data.applications.length} candidato(s), ${empatados} em empate que o edital não resolveu.`
				: `Classificação calculada: ${data.applications.length} candidato(s).`;
	}

	// --- realocação de vaga (comissão) -------------------------------------

	let formDaRealocacao = $state(false);
	let realocando = $state(false);
	let especie = $state<EspecieDeRealocacao>('level_transfer');
	let vagaOrigem = $state<number | ''>('');
	let vagaDestino = $state<number | ''>('');
	let quantidade = $state(1);
	let motivo = $state('');
	let decididoEm = $state('');
	let oficio = $state('');

	function abrirRealocacao() {
		especie = 'level_transfer';
		vagaOrigem = '';
		vagaDestino = '';
		quantidade = 1;
		motivo = '';
		decididoEm = new Date().toISOString().slice(0, 10);
		oficio = '';
		convertendo = null;
		formDaRealocacao = true;
	}

	async function salvarRealocacao(event: SubmitEvent) {
		event.preventDefault();
		if (editalId === '' || vagaOrigem === '' || vagaDestino === '' || realocando) return;
		erro = '';
		aviso = '';
		alunoCriado = null;
		realocando = true;
		const { data, error } = await api.POST('/selection/processes/{process_id}/reallocations/', {
			params: { path: { process_id: editalId } },
			body: {
				kind: especie,
				from_vacancy_id: vagaOrigem,
				to_vacancy_id: vagaDestino,
				quantity: quantidade,
				reason: motivo,
				decided_on: decididoEm,
				decided_by_note: oficio
			}
		});
		realocando = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível registrar a realocação de vaga.');
			return;
		}
		formDaRealocacao = false;
		// A realocação zera a classificação dos alvos que ela tocou: a
		// posição saiu de uma grade que acabou de mudar. Recarregar é o que
		// mostra a lista vazia de novo, pedindo o recálculo.
		await carregarGradeDoEdital(editalId);
		await carregarClassificacao();
		aviso = `Realocação registrada: ${data.quantity} vaga(s) de ${data.from_vacancy.level_label} · ${data.from_vacancy.target_label} para ${data.to_vacancy.level_label} · ${data.to_vacancy.target_label}. Recalcule a classificação dos alvos envolvidos.`;
	}

	// --- conversão em aluno (secretaria) -----------------------------------

	let convertendo = $state<number | null>(null);
	let convertendoAgora = $state(false);
	let matricula = $state('');
	let ingresso = $state('');
	let projetoDoAluno = $state<number | ''>('');
	let alunoCriado = $state<number | null>(null);

	/**
	 * No Regular o projeto do vínculo é o próprio alvo da classificação; no
	 * Suplementar, a inscrição só tem linha de pesquisa e é agora que a
	 * secretaria escolhe o projeto **dentro dela**. Em ambos o campo é
	 * obrigatório — quem confere se ele casa com o alvo é o servidor
	 * (`project_target_mismatch`).
	 */
	const projetosPossiveis = $derived.by<Projeto[]>(() => {
		if (edital === null || alvoId === '') return [];
		return porProjeto
			? projetos.filter((p) => p.id === alvoId)
			: projetos.filter((p) => p.research_line_id === alvoId);
	});

	function abrirConversao(candidato: Classificado) {
		formDaRealocacao = false;
		alunoCriado = null;
		matricula = '';
		ingresso = new Date().toISOString().slice(0, 10);
		projetoDoAluno = projetosPossiveis.length === 1 ? projetosPossiveis[0].id : '';
		convertendo = candidato.id;
	}

	async function converter(event: SubmitEvent) {
		event.preventDefault();
		if (convertendo === null || projetoDoAluno === '' || convertendoAgora) return;
		erro = '';
		aviso = '';
		convertendoAgora = true;
		const { data, error } = await api.POST('/selection/applications/{application_id}/enroll', {
			params: { path: { application_id: convertendo } },
			body: {
				registration_number: matricula,
				admission_date: ingresso,
				project_id: projetoDoAluno
			}
		});
		convertendoAgora = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível converter este classificado em aluno.');
			return;
		}
		convertendo = null;
		alunoCriado = data.student_id;
		aviso = `${data.application.full_name} virou aluno com matrícula ${data.registration_number}.`;
		// Recarrega o recorte inteiro: a primeira matrícula tranca a chave
		// (`ranking_locked`), e é a resposta do servidor que diz isso.
		await carregarClassificacao();
	}

	$effect(() => {
		carregando = true;
		Promise.all([carregarEditais(), carregarApoio()]).then(() => {
			carregando = false;
		});
	});
</script>

<svelte:head>
	<title>Resultado · PPGM</title>
</svelte:head>

<header>
	<p class="etiqueta">Processo seletivo</p>
	<h1 class="text-grafite mt-1 text-2xl font-semibold tracking-tight">Resultado</h1>
	<p class="text-cinza mt-2 text-sm">
		A classificação é sempre de um nível e de um alvo: quem disputa entre si é quem concorre à mesma
		grade de vagas. Calcular de novo é o fluxo previsto — depois de retificar uma ata ou de realocar
		vaga, a lista muda.
	</p>
</header>

<div class="mt-6 flex flex-wrap items-end gap-3">
	<div>
		<label class="etiqueta mb-1 block" for="filtro-edital">Edital</label>
		<select id="filtro-edital" class="campo w-72" bind:value={editalId} onchange={trocarEdital}>
			<option value="">Escolha um edital</option>
			{#each editais as opcao (opcao.id)}
				<option value={opcao.id}>
					{opcao.year} · {ROTULO_DO_TIPO[opcao.kind]} · {opcao.title}
				</option>
			{/each}
		</select>
	</div>
	<div>
		<label class="etiqueta mb-1 block" for="filtro-nivel">Nível</label>
		<select id="filtro-nivel" class="campo w-44" bind:value={nivel} onchange={trocarRecorte}>
			{#each NIVEIS as opcao (opcao)}
				<option value={opcao}>{ROTULO_DO_NIVEL[opcao]}</option>
			{/each}
		</select>
	</div>
	<div>
		<label class="etiqueta mb-1 block" for="filtro-alvo">
			{porProjeto ? 'Projeto coletivo' : 'Linha de pesquisa'}
		</label>
		<select
			id="filtro-alvo"
			class="campo w-72"
			bind:value={alvoId}
			onchange={trocarRecorte}
			disabled={editalId === ''}
		>
			<option value="">Escolha o alvo</option>
			{#each alvos as opcao (opcao.id)}
				<option value={opcao.id}>{opcao.nome}</option>
			{/each}
		</select>
	</div>
</div>

{#if erro}
	<p class="aviso-erro mt-6" role="alert">{erro}</p>
{/if}

{#if aviso}
	<p class="border-borda bg-papel text-grafite mt-6 border px-4 py-3 text-sm" role="status">
		{aviso}
		{#if alunoCriado !== null}
			<a class="underline" href={resolve('/(app)/alunos/[id]', { id: String(alunoCriado) })}>
				Abrir a ficha do aluno
			</a>
		{/if}
	</p>
{/if}

{#if carregando}
	<p class="etiqueta mt-6">Carregando…</p>
{:else if !escolhaCompleta}
	<div class="border-borda bg-papel mt-6 border border-dashed p-10 text-center">
		<p class="text-grafite text-[0.9375rem]">Escolha o edital, o nível e o alvo.</p>
		<p class="text-cinza mt-1 text-sm">
			A grade de vagas é por nível × alvo × cota, e a classificação segue a mesma chave.
		</p>
	</div>
{:else if classificacao !== null}
	{@const grade = classificacao}
	<section class="bg-papel regua-tinta mt-6 px-5 py-4">
		<div class="flex flex-wrap items-center justify-between gap-4">
			<div>
				<h2 class="text-grafite text-[0.9375rem] font-medium">
					{grade.level_label} · {grade.target_label}
				</h2>
				<p class="text-cinza mt-0.5 text-sm">
					{grade.total_seats} vaga(s):
					{#each grade.seats as vaga, i (vaga.quota_category)}{i > 0 ? ' · ' : ''}{vaga.quantity}
						{vaga.quota_category_label}{/each}
					{#if grade.seats.length === 0}nenhuma linha de vaga cadastrada neste recorte{/if}
				</p>
				<p class="text-cinza mt-0.5 text-sm">
					{grade.computed_at
						? `Última classificação em ${formatarMomento(grade.computed_at)}.`
						: 'Este recorte ainda não foi classificado.'}
				</p>
			</div>
			{#if podeCalcular}
				<button
					class="botao"
					type="button"
					disabled={calculando || grade.locked}
					onclick={calcular}
				>
					{calculando ? 'Calculando…' : 'Calcular classificação'}
				</button>
			{/if}
		</div>

		{#if grade.locked}
			<p class="text-cinza mt-3 text-sm">
				Alguém deste recorte já foi matriculado: a lista virou matrícula e não se recalcula mais.
			</p>
		{/if}
	</section>

	{#if grade.applications.length === 0}
		<div class="border-borda bg-papel mt-6 border border-dashed p-10 text-center">
			<p class="text-grafite text-[0.9375rem]">Nenhum candidato classificado neste recorte.</p>
			<p class="text-cinza mt-1 text-sm">
				A classificação só roda com a ata da última etapa assinada, e só entra nela quem foi
				aprovado por ela.
			</p>
		</div>
	{:else}
		<ul class="mt-6 space-y-px">
			{#each grade.applications as candidato (candidato.id)}
				<li
					class="bg-papel regua-tinta px-5 py-4"
					style:border-left-color={candidato.tie_unresolved
						? 'var(--color-carimbo)'
						: 'var(--color-tinta)'}
				>
					<div class="flex flex-wrap items-center justify-between gap-4">
						<div class="min-w-0">
							<p class="text-grafite text-[0.9375rem]">
								<span class="font-mono">{candidato.final_rank ?? '—'}º</span>
								{candidato.full_name}
								<span class="text-cinza font-mono text-xs">· {candidato.protocol}</span>
							</p>
							<p class="text-cinza mt-0.5 text-sm">
								Nota {candidato.final_score ?? '—'} · {candidato.quota_category_label} · {candidato.final_outcome_label ||
									'sem desfecho'} · {candidato.status_label}
							</p>
							{#if candidato.tie_unresolved}
								<p class="text-carimbo mt-0.5 text-sm">
									Empate que o edital não resolveu: a nota, os desempates e a idade coincidem. A
									ordem entre estes candidatos saiu do número da inscrição, que não é critério
									nenhum — decida fora do sistema.
								</p>
							{/if}
						</div>
						<div class="flex shrink-0 items-center gap-3">
							{#if candidato.student_id !== null}
								<a
									class="text-cinza text-sm underline"
									href={resolve('/(app)/alunos/[id]', {
										id: String(candidato.student_id)
									})}
								>
									Matriculado — ver ficha
								</a>
							{:else if podeConverter && candidato.final_outcome.startsWith('classified')}
								<button
									class="botao-discreto"
									type="button"
									onclick={() => abrirConversao(candidato)}
								>
									Converter em aluno
								</button>
							{/if}
						</div>
					</div>

					{#if convertendo === candidato.id}
						<form class="border-borda mt-4 border-t pt-4" onsubmit={converter}>
							<p class="etiqueta">Converter {candidato.full_name} em aluno</p>
							<p class="text-cinza mt-1 text-sm">
								A matrícula vem de fora — quem a emite é o sistema da UFMG. O projeto é obrigatório
								mesmo no Regular: é ele que o vínculo do aluno guarda.
							</p>
							<div class="mt-3 grid gap-4 sm:grid-cols-3">
								<div>
									<label class="etiqueta mb-1 block" for="matricula-{candidato.id}">
										Nº de matrícula
									</label>
									<input
										id="matricula-{candidato.id}"
										class="campo"
										type="text"
										bind:value={matricula}
										required
									/>
								</div>
								<div>
									<label class="etiqueta mb-1 block" for="ingresso-{candidato.id}">
										Data de admissão
									</label>
									<input
										id="ingresso-{candidato.id}"
										class="campo"
										type="date"
										bind:value={ingresso}
										required
									/>
								</div>
								<div>
									<label class="etiqueta mb-1 block" for="projeto-{candidato.id}">
										Projeto coletivo
									</label>
									<select
										id="projeto-{candidato.id}"
										class="campo"
										bind:value={projetoDoAluno}
										required
									>
										<option value="">Escolha o projeto</option>
										{#each projetosPossiveis as projeto (projeto.id)}
											<option value={projeto.id}>{projeto.name}</option>
										{/each}
									</select>
								</div>
							</div>
							<div class="mt-4 flex items-center gap-2">
								<button class="botao" type="submit" disabled={convertendoAgora}>
									{convertendoAgora ? 'Convertendo…' : 'Converter em aluno'}
								</button>
								<button class="botao-discreto" type="button" onclick={() => (convertendo = null)}>
									Cancelar
								</button>
							</div>
						</form>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}

	{#if podeVerRealocacoes}
		<section class="mt-10">
			<div class="flex flex-wrap items-center justify-between gap-4">
				<div>
					<h2 class="etiqueta">Realocação de vaga</h2>
					<p class="text-cinza mt-1 text-sm">
						Mover vaga depois do edital publicado é decisão da Comissão de Seleção, sempre com o
						número do ofício ou da ata. A classificação dos alvos envolvidos é zerada — a secretaria
						recalcula antes de publicar a lista de novo.
					</p>
				</div>
				{#if podeRealocar && !formDaRealocacao}
					<button class="botao-discreto" type="button" onclick={abrirRealocacao}>
						Registrar realocação
					</button>
				{/if}
			</div>

			{#if formDaRealocacao}
				<form class="border-borda bg-papel mt-4 border p-5" onsubmit={salvarRealocacao}>
					<div class="grid gap-4 sm:grid-cols-2">
						<div class="sm:col-span-2">
							<label class="etiqueta mb-1 block" for="realocacao-especie">Espécie</label>
							<select id="realocacao-especie" class="campo" bind:value={especie} required>
								{#each ESPECIES_DE_REALOCACAO as opcao (opcao.valor)}
									<option value={opcao.valor}>{opcao.rotulo}</option>
								{/each}
							</select>
							<p class="text-cinza mt-1 text-sm">
								{ESPECIES_DE_REALOCACAO.find((e) => e.valor === especie)?.explicacao}
							</p>
						</div>
						<div>
							<label class="etiqueta mb-1 block" for="realocacao-origem">Vaga de origem</label>
							<select id="realocacao-origem" class="campo" bind:value={vagaOrigem} required>
								<option value="">Escolha a origem</option>
								{#each vagas as vaga (vaga.id)}
									<option value={vaga.id}>{rotuloDaVaga(vaga)}</option>
								{/each}
							</select>
						</div>
						<div>
							<label class="etiqueta mb-1 block" for="realocacao-destino">Vaga de destino</label>
							<select id="realocacao-destino" class="campo" bind:value={vagaDestino} required>
								<option value="">Escolha o destino</option>
								{#each vagas as vaga (vaga.id)}
									<option value={vaga.id}>{rotuloDaVaga(vaga)}</option>
								{/each}
							</select>
						</div>
						<div>
							<label class="etiqueta mb-1 block" for="realocacao-quantidade">Quantidade</label>
							<input
								id="realocacao-quantidade"
								class="campo"
								type="number"
								min="1"
								bind:value={quantidade}
								required
							/>
						</div>
						<div>
							<label class="etiqueta mb-1 block" for="realocacao-data">Decidida em</label>
							<input
								id="realocacao-data"
								class="campo"
								type="date"
								bind:value={decididoEm}
								required
							/>
						</div>
						<div>
							<label class="etiqueta mb-1 block" for="realocacao-oficio">Ofício ou ata</label>
							<input
								id="realocacao-oficio"
								class="campo"
								type="text"
								bind:value={oficio}
								required
							/>
						</div>
						<div class="sm:col-span-2">
							<label class="etiqueta mb-1 block" for="realocacao-motivo">Motivo</label>
							<textarea id="realocacao-motivo" class="campo" rows="2" bind:value={motivo} required
							></textarea>
						</div>
					</div>
					<div class="mt-4 flex items-center gap-2">
						<button class="botao" type="submit" disabled={realocando}>
							{realocando ? 'Registrando…' : 'Registrar realocação'}
						</button>
						<button class="botao-discreto" type="button" onclick={() => (formDaRealocacao = false)}>
							Cancelar
						</button>
					</div>
				</form>
			{/if}

			{#if realocacoes.length === 0}
				<p class="text-cinza mt-4 text-sm">Nenhuma vaga foi realocada neste edital.</p>
			{:else}
				<ul class="mt-4 space-y-px">
					{#each realocacoes as linha (linha.id)}
						<li class="bg-papel regua-tinta px-5 py-4">
							<p class="text-grafite text-[0.9375rem]">
								{linha.quantity} vaga(s) · {linha.from_vacancy.level_label} · {linha.from_vacancy
									.target_label} · {linha.from_vacancy.quota_category_label}
								→ {linha.to_vacancy.level_label} · {linha.to_vacancy.target_label}
							</p>
							<p class="text-cinza mt-0.5 text-sm">
								{linha.kind_label} · decidida em {linha.decided_on} · {linha.decided_by_note}
							</p>
							<p class="text-cinza mt-0.5 text-sm">{linha.reason}</p>
						</li>
					{/each}
				</ul>
			{/if}
		</section>
	{/if}
{/if}
