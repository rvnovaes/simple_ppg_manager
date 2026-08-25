<script lang="ts">
	import { api, comoFormData, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';
	import Icone from '$lib/Icone.svelte';
	import {
		COTAS_POR_TIPO,
		NIVEIS,
		PLACEHOLDERS_DE_CONVOCACAO,
		ROTULO_DA_COTA,
		ROTULO_DA_SITUACAO_DO_EDITAL,
		ROTULO_DO_NIVEL,
		ROTULO_DO_TIPO,
		alvoDoTipo,
		formatarMomento,
		isoParaLocal,
		localParaIso,
		type Cota,
		type Nivel,
		type Tipo
	} from '$lib/selecao';
	import { sessao } from '$lib/sessao.svelte';

	type Edital = components['schemas']['SelectionProcessOut'];
	type Etapa = components['schemas']['SelectionStageOut'];
	type Vaga = components['schemas']['VacancyOut'];
	type Linha = components['schemas']['ResearchLineOut'];
	type Projeto = components['schemas']['CollectiveProjectOut'];

	let editais = $state<Edital[]>([]);
	let etapas = $state<Etapa[]>([]);
	let vagas = $state<Vaga[]>([]);
	let linhas = $state<Linha[]>([]);
	let projetos = $state<Projeto[]>([]);

	let carregando = $state(true);
	let erro = $state('');
	let aviso = $state('');
	let salvando = $state(false);

	let editalId = $state<number | null>(null);
	const edital = $derived(editais.find((e) => e.id === editalId) ?? null);

	// Só o rascunho aceita etapa e vaga (409 `process_not_editable` no
	// backend). A tela esconde os controles em vez de deixar a secretaria
	// descobrir isso pelo erro — mas quem decide continua sendo o servidor.
	const emRascunho = $derived(edital?.status === 'draft');

	// Coordenação e Comissão de Seleção só leem: sem a permissão de escrita
	// o formulário nem existe na tela.
	const podeCriarEdital = $derived(sessao.pode('selection.add_selectionprocess'));
	const podeEditarEdital = $derived(sessao.pode('selection.change_selectionprocess'));
	const podeCriarEtapa = $derived(sessao.pode('selection.add_selectionstage'));
	const podeEditarEtapa = $derived(sessao.pode('selection.change_selectionstage'));
	const podeCriarVaga = $derived(sessao.pode('selection.add_vacancy'));
	const podeEditarVaga = $derived(sessao.pode('selection.change_vacancy'));

	// --- carregamento ----------------------------------------------------

	async function carregarEditais(selecionar?: number) {
		const { data, error } = await api.GET('/selection/processes/');
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar os editais do programa.');
			return;
		}
		editais = data?.items ?? [];
		editalId = selecionar ?? editais[0]?.id ?? null;
	}

	async function carregarGrade(alvo: number) {
		const [listaDeEtapas, listaDeVagas] = await Promise.all([
			api.GET('/selection/processes/{process_id}/stages/', {
				params: { path: { process_id: alvo } }
			}),
			api.GET('/selection/processes/{process_id}/vacancies/', {
				params: { path: { process_id: alvo } }
			})
		]);
		const falha = listaDeEtapas.error ?? listaDeVagas.error;
		if (falha) {
			erro = mensagemDeErro(falha, 'Não foi possível carregar etapas e vagas do edital.');
			return;
		}
		etapas = listaDeEtapas.data ?? [];
		vagas = listaDeVagas.data ?? [];
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

	async function carregar() {
		carregando = true;
		erro = '';
		await Promise.all([carregarEditais(), carregarApoio()]);
		if (editalId !== null) await carregarGrade(editalId);
		carregando = false;
	}

	async function trocarDeEdital(alvo: number) {
		editalId = alvo;
		etapas = [];
		vagas = [];
		erro = '';
		aviso = '';
		formDoEdital = false;
		formDaEtapa = false;
		formDoTemplate = false;
		await carregarGrade(alvo);
	}

	/** Reflete no estado local o edital que a API devolveu. */
	function substituirEdital(salvo: Edital) {
		const conhecido = editais.some((e) => e.id === salvo.id);
		editais = conhecido ? editais.map((e) => (e.id === salvo.id ? salvo : e)) : [salvo, ...editais];
		editalId = salvo.id;
	}

	// --- formulário do edital --------------------------------------------

	let formDoEdital = $state(false);
	let editandoEdital = $state<Edital | null>(null);
	let tipo = $state<Tipo>('regular');
	let ano = $state(new Date().getFullYear() + 1);
	let titulo = $state('');
	let inscricaoAbre = $state('');
	let inscricaoFecha = $state('');

	function abrirNovoEdital() {
		editandoEdital = null;
		tipo = 'regular';
		ano = new Date().getFullYear() + 1;
		titulo = '';
		inscricaoAbre = '';
		inscricaoFecha = '';
		erro = '';
		aviso = '';
		formDoEdital = true;
	}

	function editarEdital(alvo: Edital) {
		editandoEdital = alvo;
		tipo = alvo.kind;
		ano = alvo.year;
		titulo = alvo.title;
		inscricaoAbre = isoParaLocal(alvo.submission_opens_at);
		inscricaoFecha = isoParaLocal(alvo.submission_closes_at);
		erro = '';
		aviso = '';
		formDoEdital = true;
	}

	/**
	 * O mesmo que `SelectionProcess.clean()` cobra.
	 *
	 * Validação de UX, e não a que vale: o 400 `invalid_submission_window`
	 * do backend continua sendo a palavra final (Seção 8).
	 */
	function janelaForaDeOrdem(): string {
		if (!(new Date(inscricaoAbre).getTime() < new Date(inscricaoFecha).getTime()))
			return 'As inscrições precisam encerrar depois de abrir.';
		return '';
	}

	async function salvarEdital(event: SubmitEvent) {
		event.preventDefault();
		erro = '';
		aviso = '';
		const desordem = janelaForaDeOrdem();
		if (desordem !== '') {
			erro = desordem;
			return;
		}
		salvando = true;
		const corpo = {
			kind: tipo,
			year: ano,
			title: titulo,
			submission_opens_at: localParaIso(inscricaoAbre),
			submission_closes_at: localParaIso(inscricaoFecha)
		};
		const alvo = editandoEdital;
		const resposta = alvo
			? await api.PATCH('/selection/processes/{process_id}/', {
					params: { path: { process_id: alvo.id } },
					body: corpo
				})
			: await api.POST('/selection/processes/', {
					// O template nasce em branco e é escrito depois, na seção
					// própria; o schema gerado o declara obrigatório porque tem
					// default no Ninja, então ele viaja vazio.
					body: { ...corpo, convocation_subject: '', convocation_body: '' }
				});
		salvando = false;
		// A falha sai para uma const ANTES do `if`: dentro dele o objeto
		// inteiro é estreitado e `resposta.error` viraria `never`.
		const falha = resposta.error;
		if (falha || !resposta.data) {
			erro = mensagemDeErro(falha, 'Não foi possível salvar o edital.');
			return;
		}
		substituirEdital(resposta.data);
		formDoEdital = false;
		editandoEdital = null;
		await carregarGrade(resposta.data.id);
	}

	// --- publicar, encerrar e PDF ----------------------------------------

	let confirmandoPublicacao = $state(false);
	let confirmandoEncerramento = $state(false);

	async function publicar() {
		if (edital === null) return;
		erro = '';
		aviso = '';
		salvando = true;
		const { data, error } = await api.POST('/selection/processes/{process_id}/publish', {
			params: { path: { process_id: edital.id } }
		});
		salvando = false;
		confirmandoPublicacao = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível publicar o edital.');
			return;
		}
		substituirEdital(data);
		aviso = 'Edital publicado. Etapas e grade de vagas ficam congeladas a partir de agora.';
	}

	async function encerrar() {
		if (edital === null) return;
		erro = '';
		aviso = '';
		salvando = true;
		const { data, error } = await api.POST('/selection/processes/{process_id}/close', {
			params: { path: { process_id: edital.id } }
		});
		salvando = false;
		confirmandoEncerramento = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível encerrar o edital.');
			return;
		}
		substituirEdital(data);
		aviso = 'Edital encerrado.';
	}

	async function enviarPdf(event: Event) {
		const campo = event.currentTarget as HTMLInputElement;
		const arquivo = campo.files?.[0];
		if (edital === null || !arquivo) return;
		erro = '';
		aviso = '';
		salvando = true;
		const { data, error } = await api.POST('/selection/processes/{process_id}/notice-file', {
			params: { path: { process_id: edital.id } },
			// O tipo gerado declara `file: string` (binary no OpenAPI); o cast
			// é o preço de mandar o File de verdade pelo FormData.
			body: { file: arquivo as unknown as string },
			bodySerializer: comoFormData
		});
		salvando = false;
		// Limpa sempre: com o nome do arquivo preso no campo, reenviar o mesmo
		// arquivo depois de corrigir algo não dispara o `change`.
		campo.value = '';
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível anexar o PDF do edital.');
			return;
		}
		substituirEdital(data);
		aviso = 'PDF do edital anexado.';
	}

	// --- etapas ------------------------------------------------------------

	let formDaEtapa = $state(false);
	let editandoEtapa = $state<Etapa | null>(null);
	let nomeDaEtapa = $state('');
	let ordemDaEtapa = $state(1);
	let sessaoDaEtapa = $state('');
	let localDaEtapa = $state('');
	let desempateDaEtapa = $state('');

	function abrirNovaEtapa() {
		editandoEtapa = null;
		nomeDaEtapa = '';
		ordemDaEtapa = (etapas.at(-1)?.order ?? 0) + 1;
		sessaoDaEtapa = '';
		localDaEtapa = '';
		desempateDaEtapa = '';
		erro = '';
		formDaEtapa = true;
	}

	function editarEtapa(alvo: Etapa) {
		editandoEtapa = alvo;
		nomeDaEtapa = alvo.name;
		ordemDaEtapa = alvo.order;
		sessaoDaEtapa = alvo.session_at === null ? '' : isoParaLocal(alvo.session_at);
		localDaEtapa = alvo.location;
		desempateDaEtapa = alvo.tiebreak_rank === null ? '' : String(alvo.tiebreak_rank);
		erro = '';
		formDaEtapa = true;
	}

	async function salvarEtapa(event: SubmitEvent) {
		event.preventDefault();
		if (editalId === null) return;
		erro = '';
		aviso = '';
		salvando = true;
		// `null` explícito, e não campo ausente: é assim que a etapa deixa de
		// ter sessão marcada ou sai da ordem de desempate (o PATCH do backend
		// usa `exclude_unset`, sem `exclude_none`).
		const corpo = {
			name: nomeDaEtapa,
			order: ordemDaEtapa,
			session_at: sessaoDaEtapa === '' ? null : localParaIso(sessaoDaEtapa),
			location: localDaEtapa,
			tiebreak_rank: desempateDaEtapa === '' ? null : Number(desempateDaEtapa)
		};
		const alvo = editandoEtapa;
		const resposta = alvo
			? await api.PATCH('/selection/processes/{process_id}/stages/{stage_id}/', {
					params: { path: { process_id: editalId, stage_id: alvo.id } },
					body: corpo
				})
			: await api.POST('/selection/processes/{process_id}/stages/', {
					params: { path: { process_id: editalId } },
					body: corpo
				});
		salvando = false;
		const falha = resposta.error;
		if (falha || !resposta.data) {
			erro = mensagemDeErro(falha, 'Não foi possível salvar a etapa.');
			return;
		}
		const salva = resposta.data;
		etapas = (alvo ? etapas.map((e) => (e.id === salva.id ? salva : e)) : [...etapas, salva]).sort(
			(a, b) => a.order - b.order
		);
		formDaEtapa = false;
		editandoEtapa = null;
		await sincronizarContagens();
	}

	let removendoEtapa = $state<number | null>(null);

	async function removerEtapa(alvo: Etapa) {
		if (editalId === null) return;
		erro = '';
		aviso = '';
		salvando = true;
		const { error } = await api.DELETE('/selection/processes/{process_id}/stages/{stage_id}/', {
			params: { path: { process_id: editalId, stage_id: alvo.id } }
		});
		salvando = false;
		removendoEtapa = null;
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível remover a etapa.');
			return;
		}
		etapas = etapas.filter((e) => e.id !== alvo.id);
		await sincronizarContagens();
	}

	// --- grade de vagas ----------------------------------------------------

	// Alvo da grade: o Regular chaveia por projeto coletivo, o Suplementar
	// por linha de pesquisa (P4). É o servidor que recusa a combinação errada
	// (`target_mismatch`); aqui a lista só decide quais linhas desenhar.
	type Alvo = { id: number; nome: string };

	const alvos = $derived.by<Alvo[]>(() => {
		if (edital === null) return [];
		return alvoDoTipo(edital.kind) === 'projeto'
			? projetos.map((p) => ({ id: p.id, nome: p.name }))
			: linhas.map((l) => ({ id: l.id, nome: l.name }));
	});

	const cotas = $derived<Cota[]>(edital === null ? [] : COTAS_POR_TIPO[edital.kind]);

	function vagaDe(alvo: Alvo, nivel: Nivel, cota: Cota): Vaga | undefined {
		return vagas.find(
			(v) =>
				v.level === nivel &&
				v.quota_category === cota &&
				(v.project_id === alvo.id || v.research_line_id === alvo.id)
		);
	}

	function quantidadeDe(alvo: Alvo, nivel: Nivel, cota: Cota): number {
		return vagaDe(alvo, nivel, cota)?.quantity ?? 0;
	}

	const totalDeVagas = $derived(vagas.reduce((soma, v) => soma + v.quantity, 0));

	/**
	 * Grava uma célula da grade.
	 *
	 * Célula vazia que continua zerada não vira linha no banco — só o que a
	 * secretaria de fato ofertou existe como `Vacancy`. Zerar uma vaga que já
	 * existe, por outro lado, é PATCH para 0: o model aceita de propósito,
	 * porque a linha realocada precisa continuar visível na grade.
	 */
	async function salvarCelula(alvo: Alvo, nivel: Nivel, cota: Cota, valor: number) {
		if (editalId === null || edital === null) return;
		const existente = vagaDe(alvo, nivel, cota);
		if (existente === undefined && valor === 0) return;
		if (existente !== undefined && existente.quantity === valor) return;
		erro = '';
		aviso = '';
		salvando = true;
		const porProjeto = alvoDoTipo(edital.kind) === 'projeto';
		const resposta =
			existente === undefined
				? await api.POST('/selection/processes/{process_id}/vacancies/', {
						params: { path: { process_id: editalId } },
						body: {
							level: nivel,
							project_id: porProjeto ? alvo.id : null,
							research_line_id: porProjeto ? null : alvo.id,
							quota_category: cota,
							quantity: valor
						}
					})
				: await api.PATCH('/selection/processes/{process_id}/vacancies/{vacancy_id}/', {
						params: { path: { process_id: editalId, vacancy_id: existente.id } },
						body: { quantity: valor }
					});
		salvando = false;
		const falha = resposta.error;
		if (falha || !resposta.data) {
			erro = mensagemDeErro(falha, 'Não foi possível salvar a vaga.');
			// Sem o recarregamento a célula ficaria mostrando o número recusado.
			await carregarGrade(editalId);
			return;
		}
		const salva = resposta.data;
		vagas = existente ? vagas.map((v) => (v.id === salva.id ? salva : v)) : [...vagas, salva];
		await sincronizarContagens();
	}

	function aoSairDaCelula(alvo: Alvo, nivel: Nivel, cota: Cota, event: Event) {
		const campo = event.currentTarget as HTMLInputElement;
		const valor = Number(campo.value);
		if (!Number.isInteger(valor) || valor < 0) {
			campo.value = String(quantidadeDe(alvo, nivel, cota));
			return;
		}
		salvarCelula(alvo, nivel, cota, valor);
	}

	/**
	 * `stage_count`/`vacancy_count` do edital são anotados pelo servidor.
	 *
	 * Recontar aqui é o que mantém o aviso de "falta etapa/vaga para
	 * publicar" honesto depois de mexer na grade, sem recarregar a página.
	 */
	async function sincronizarContagens() {
		if (editalId === null) return;
		const { data } = await api.GET('/selection/processes/{process_id}/', {
			params: { path: { process_id: editalId } }
		});
		if (data) editais = editais.map((e) => (e.id === data.id ? data : e));
	}

	// --- template da convocação -------------------------------------------

	let formDoTemplate = $state(false);
	let assunto = $state('');
	let corpoDoEmail = $state('');

	function abrirTemplate(alvo: Edital) {
		assunto = alvo.convocation_subject;
		corpoDoEmail = alvo.convocation_body;
		erro = '';
		aviso = '';
		formDoTemplate = true;
	}

	async function salvarTemplate(event: SubmitEvent) {
		event.preventDefault();
		if (edital === null) return;
		erro = '';
		aviso = '';
		salvando = true;
		const { data, error } = await api.PATCH('/selection/processes/{process_id}/', {
			params: { path: { process_id: edital.id } },
			body: { convocation_subject: assunto, convocation_body: corpoDoEmail }
		});
		salvando = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível salvar o template da convocação.');
			return;
		}
		substituirEdital(data);
		formDoTemplate = false;
		aviso = 'Template da convocação salvo.';
	}

	// O que falta para publicar, na mesma ordem em que `publish_process`
	// cobra. A recusa que vale é a do backend (`process_incomplete`) — isto
	// aqui só evita que a secretaria descubra clicando.
	const pendenciasParaPublicar = $derived.by<string[]>(() => {
		if (edital === null) return [];
		const faltas: string[] = [];
		if (edital.stage_count === 0) faltas.push('nenhuma etapa cadastrada');
		if (edital.vacancy_count === 0) faltas.push('nenhuma vaga na grade');
		if (edital.convocation_body.trim() === '') faltas.push('template da convocação em branco');
		return faltas;
	});

	$effect(() => {
		carregar();
	});
</script>

<svelte:head>
	<title>Editais do processo seletivo · PPGD Manager</title>
</svelte:head>

<header class="flex flex-wrap items-end justify-between gap-4">
	<div>
		<p class="etiqueta">Processo seletivo</p>
		<h1 class="text-grafite mt-1 text-2xl font-semibold tracking-tight">Editais</h1>
	</div>
	{#if podeCriarEdital}
		<button class="botao-discreto" type="button" onclick={abrirNovoEdital}>Novo edital</button>
	{/if}
</header>

{#if erro}
	<p class="aviso-erro mt-6" role="alert">{erro}</p>
{/if}
{#if aviso}
	<p class="border-borda bg-papel text-grafite mt-6 border px-4 py-3 text-sm" role="status">
		{aviso}
	</p>
{/if}

{#if formDoEdital}
	<form class="border-borda bg-papel mt-6 border p-5" onsubmit={salvarEdital}>
		<p class="etiqueta">{editandoEdital ? 'Corrigir edital' : 'Novo edital'}</p>
		<div class="mt-4 grid gap-4 sm:grid-cols-2">
			<div>
				<label class="etiqueta mb-2 block" for="edital-tipo">Tipo</label>
				<select id="edital-tipo" class="campo" bind:value={tipo} required>
					{#each Object.entries(ROTULO_DO_TIPO) as [valor, rotulo] (valor)}
						<option value={valor}>{rotulo}</option>
					{/each}
				</select>
				<p class="text-cinza mt-1 text-sm">
					{tipo === 'regular'
						? 'Vagas por projeto coletivo; ampla concorrência e cota racial.'
						: 'Ações afirmativas: vagas por linha de pesquisa, sem ampla concorrência.'}
				</p>
			</div>
			<div>
				<label class="etiqueta mb-2 block" for="edital-ano">Ano de ingresso</label>
				<input id="edital-ano" class="campo" type="number" min="2000" bind:value={ano} required />
			</div>
			<div class="sm:col-span-2">
				<label class="etiqueta mb-2 block" for="edital-titulo">Título</label>
				<input id="edital-titulo" class="campo" type="text" bind:value={titulo} required />
			</div>
			<div>
				<label class="etiqueta mb-2 block" for="edital-abre">Inscrições abrem em</label>
				<input
					id="edital-abre"
					class="campo"
					type="datetime-local"
					bind:value={inscricaoAbre}
					required
				/>
			</div>
			<div>
				<label class="etiqueta mb-2 block" for="edital-fecha">Inscrições encerram em</label>
				<input
					id="edital-fecha"
					class="campo"
					type="datetime-local"
					bind:value={inscricaoFecha}
					required
				/>
			</div>
		</div>
		<div class="mt-4 flex items-center gap-2">
			<button class="botao" type="submit" disabled={salvando}>
				{salvando ? 'Salvando…' : 'Salvar edital'}
			</button>
			<button class="botao-discreto" type="button" onclick={() => (formDoEdital = false)}>
				Cancelar
			</button>
		</div>
	</form>
{/if}

{#if carregando}
	<p class="etiqueta mt-6">Carregando…</p>
{:else if editais.length === 0}
	<div class="border-borda bg-papel mt-6 border border-dashed p-10 text-center">
		<p class="text-grafite text-[0.9375rem]">Nenhum edital de seleção cadastrado ainda.</p>
		<p class="text-cinza mt-1 text-sm">
			{podeCriarEdital
				? 'O edital reúne etapas, grade de vagas e o texto da convocação. Sem ele ninguém se inscreve.'
				: 'A secretaria ainda não abriu o edital deste ano.'}
		</p>
	</div>
{:else}
	<div class="mt-8 grid gap-4 sm:grid-cols-[1fr_auto]">
		<div>
			<label class="etiqueta mb-2 block" for="edital-selecao">Edital</label>
			<select
				id="edital-selecao"
				class="campo"
				value={editalId}
				onchange={(e) => trocarDeEdital(Number(e.currentTarget.value))}
			>
				{#each editais as opcao (opcao.id)}
					<option value={opcao.id}>
						{opcao.year} · {ROTULO_DO_TIPO[opcao.kind]} · {opcao.title} ({ROTULO_DA_SITUACAO_DO_EDITAL[
							opcao.status
						]})
					</option>
				{/each}
			</select>
		</div>
		{#if edital && podeEditarEdital}
			<div class="flex flex-wrap items-end gap-2">
				{#if emRascunho}
					<button class="botao-discreto" type="button" onclick={() => editarEdital(edital)}>
						Corrigir edital
					</button>
				{/if}
				<button class="botao-discreto" type="button" onclick={() => abrirTemplate(edital)}>
					Template da convocação
				</button>
				{#if edital.status === 'draft'}
					<button
						class="botao-discreto"
						type="button"
						disabled={pendenciasParaPublicar.length > 0}
						onclick={() => (confirmandoPublicacao = true)}
					>
						Publicar
					</button>
				{:else if edital.status === 'published'}
					<button
						class="botao-discreto"
						type="button"
						onclick={() => (confirmandoEncerramento = true)}
					>
						Encerrar
					</button>
				{/if}
			</div>
		{/if}
	</div>

	{#if edital}
		<section class="border-borda bg-papel mt-6 border p-5">
			<div class="flex flex-wrap items-center justify-between gap-4">
				<p class="etiqueta">{ROTULO_DO_TIPO[edital.kind]} · {edital.year}</p>
				<span class="etiqueta">
					{ROTULO_DA_SITUACAO_DO_EDITAL[edital.status]}{edital.submission_open
						? ' · Inscrições abertas'
						: ''}
				</span>
			</div>
			<h2 class="text-grafite mt-2 text-lg font-semibold tracking-tight">{edital.title}</h2>
			<dl class="text-grafite mt-4 grid gap-3 text-sm sm:grid-cols-2">
				<div>
					<dt class="etiqueta">Inscrições</dt>
					<dd>
						{formatarMomento(edital.submission_opens_at)} até {formatarMomento(
							edital.submission_closes_at
						)}
					</dd>
				</div>
				<div>
					<dt class="etiqueta">Publicação</dt>
					<dd>
						{formatarMomento(edital.published_at)}{edital.closed_at
							? ` · encerrado em ${formatarMomento(edital.closed_at)}`
							: ''}
					</dd>
				</div>
				<div>
					<dt class="etiqueta">Etapas e vagas</dt>
					<dd>{edital.stage_count} etapa(s) · {edital.vacancy_count} linha(s) de vaga</dd>
				</div>
				<div>
					<dt class="etiqueta">PDF do edital</dt>
					<dd class="flex flex-wrap items-center gap-3">
						{#if edital.notice_url}
							<!-- O PDF é URL de MEDIA servida pelo Nginx, e não rota da SPA:
							`resolve()` não se aplica. Continua relativa — origem única
							(ADR-004). -->
							<!-- eslint-disable svelte/no-navigation-without-resolve -->
							<a class="underline" href={edital.notice_url} target="_blank" rel="noopener">
								<Icone nome="documento" tamanho={14} rotulo="Abrir PDF" />
								{edital.notice_filename}
							</a>
							<!-- eslint-enable svelte/no-navigation-without-resolve -->
						{:else}
							<span class="text-cinza">Nenhum arquivo anexado.</span>
						{/if}
						{#if podeEditarEdital}
							<!-- Anexar o PDF continua valendo com o edital publicado:
							trocar o documento é retificação, e não mexe em etapa ou vaga. -->
							<input
								class="campo w-auto text-sm"
								type="file"
								accept="application/pdf,.pdf"
								aria-label="Anexar PDF do edital"
								disabled={salvando}
								onchange={enviarPdf}
							/>
						{/if}
					</dd>
				</div>
			</dl>
			{#if edital.status === 'draft' && pendenciasParaPublicar.length > 0}
				<p class="text-cinza mt-4 text-sm">
					Falta para publicar: {pendenciasParaPublicar.join(', ')}.
				</p>
			{/if}
		</section>

		{#if confirmandoPublicacao}
			<section class="border-borda bg-papel mt-4 border p-5" role="alertdialog">
				<p class="etiqueta">Publicar {edital.title}</p>
				<p class="text-grafite mt-3 text-sm">
					Depois de publicado, o edital não aceita mais mudança de etapa nem de grade de vagas —
					corrigir vaga passa a ser realocação registrada. As inscrições abrem na data marcada.
				</p>
				<div class="mt-4 flex items-center gap-2">
					<button class="botao" type="button" disabled={salvando} onclick={publicar}>
						{salvando ? 'Publicando…' : 'Publicar mesmo assim'}
					</button>
					<button
						class="botao-discreto"
						type="button"
						onclick={() => (confirmandoPublicacao = false)}
					>
						Cancelar
					</button>
				</div>
			</section>
		{/if}

		{#if confirmandoEncerramento}
			<section class="border-borda bg-papel mt-4 border p-5" role="alertdialog">
				<p class="etiqueta">Encerrar {edital.title}</p>
				<p class="text-grafite mt-3 text-sm">
					O edital sai do ar e não recebe mais inscrição. Não há como reabrir pela tela.
				</p>
				<div class="mt-4 flex items-center gap-2">
					<button class="botao" type="button" disabled={salvando} onclick={encerrar}>
						{salvando ? 'Encerrando…' : 'Encerrar mesmo assim'}
					</button>
					<button
						class="botao-discreto"
						type="button"
						onclick={() => (confirmandoEncerramento = false)}
					>
						Cancelar
					</button>
				</div>
			</section>
		{/if}

		{#if formDoTemplate}
			<form class="border-borda bg-papel mt-4 border p-5" onsubmit={salvarTemplate}>
				<p class="etiqueta">Template da convocação</p>
				<p class="text-cinza mt-2 text-sm">
					É o e-mail que cada candidato recebe ao ser convocado para uma etapa. Escreva os campos
					variáveis entre chaves:
					{#each PLACEHOLDERS_DE_CONVOCACAO as marca, i (marca.chave)}<span
							><code class="font-mono">{'{' + marca.chave + '}'}</code>
							({marca.explicacao}){i < PLACEHOLDERS_DE_CONVOCACAO.length - 1 ? ', ' : '.'}</span
						>{/each}
				</p>
				<div class="mt-4 grid gap-4">
					<div>
						<label class="etiqueta mb-2 block" for="convocacao-assunto">Assunto</label>
						<input
							id="convocacao-assunto"
							class="campo"
							type="text"
							bind:value={assunto}
							required
						/>
					</div>
					<div>
						<label class="etiqueta mb-2 block" for="convocacao-corpo">Corpo do e-mail</label>
						<textarea id="convocacao-corpo" class="campo" rows="10" bind:value={corpoDoEmail}
						></textarea>
					</div>
				</div>
				<div class="mt-4 flex items-center gap-2">
					<button class="botao" type="submit" disabled={salvando}>
						{salvando ? 'Salvando…' : 'Salvar template'}
					</button>
					<button class="botao-discreto" type="button" onclick={() => (formDoTemplate = false)}>
						Cancelar
					</button>
				</div>
			</form>
		{/if}

		<section class="mt-8">
			<div class="flex flex-wrap items-end justify-between gap-4">
				<h2 class="text-grafite text-lg font-semibold tracking-tight">Etapas</h2>
				{#if podeCriarEtapa && emRascunho}
					<button class="botao-discreto" type="button" onclick={abrirNovaEtapa}>Nova etapa</button>
				{/if}
			</div>

			{#if formDaEtapa}
				<form class="border-borda bg-papel mt-4 border p-5" onsubmit={salvarEtapa}>
					<p class="etiqueta">{editandoEtapa ? 'Editar etapa' : 'Nova etapa'}</p>
					<div class="mt-4 grid gap-4 sm:grid-cols-2">
						<div>
							<label class="etiqueta mb-2 block" for="etapa-nome">Nome</label>
							<input id="etapa-nome" class="campo" type="text" bind:value={nomeDaEtapa} required />
						</div>
						<div>
							<label class="etiqueta mb-2 block" for="etapa-ordem">Ordem</label>
							<input
								id="etapa-ordem"
								class="campo"
								type="number"
								min="1"
								bind:value={ordemDaEtapa}
								required
							/>
						</div>
						<div>
							<label class="etiqueta mb-2 block" for="etapa-sessao">Data e hora da sessão</label>
							<input
								id="etapa-sessao"
								class="campo"
								type="datetime-local"
								bind:value={sessaoDaEtapa}
							/>
						</div>
						<div>
							<label class="etiqueta mb-2 block" for="etapa-local">Local</label>
							<input id="etapa-local" class="campo" type="text" bind:value={localDaEtapa} />
						</div>
						<div>
							<label class="etiqueta mb-2 block" for="etapa-desempate">
								Ordem de desempate (opcional)
							</label>
							<input
								id="etapa-desempate"
								class="campo"
								type="number"
								min="1"
								bind:value={desempateDaEtapa}
							/>
							<p class="text-cinza mt-1 text-sm">
								1 é o primeiro critério a desempatar. Deixe em branco se esta etapa não desempata.
							</p>
						</div>
					</div>
					<div class="mt-4 flex items-center gap-2">
						<button class="botao" type="submit" disabled={salvando}>
							{salvando ? 'Salvando…' : 'Salvar etapa'}
						</button>
						<button class="botao-discreto" type="button" onclick={() => (formDaEtapa = false)}>
							Cancelar
						</button>
					</div>
				</form>
			{/if}

			{#if etapas.length === 0}
				<div class="border-borda bg-papel mt-4 border border-dashed p-10 text-center">
					<p class="text-grafite text-[0.9375rem]">Nenhuma etapa neste edital.</p>
					<p class="text-cinza mt-1 text-sm">
						Sem etapa não há o que avaliar, e o edital não pode ser publicado.
					</p>
				</div>
			{:else}
				<ul class="mt-4 space-y-px">
					{#each etapas as etapa (etapa.id)}
						<li
							class="bg-papel regua-tinta flex flex-wrap items-center justify-between gap-4 px-5 py-4"
						>
							<div class="min-w-0">
								<p class="text-grafite text-[0.9375rem] font-medium">
									{etapa.order}. {etapa.name}
								</p>
								<p class="text-cinza mt-0.5 truncate text-sm">
									{formatarMomento(etapa.session_at)}{etapa.location ? ` · ${etapa.location}` : ''}
								</p>
							</div>
							<div class="flex shrink-0 items-center gap-4">
								{#if etapa.tiebreak_rank !== null}
									<span class="etiqueta">{etapa.tiebreak_rank}º desempate</span>
								{/if}
								{#if podeEditarEtapa && emRascunho}
									<button class="botao-discreto" type="button" onclick={() => editarEtapa(etapa)}>
										Editar
									</button>
									<button
										class="botao-discreto"
										type="button"
										onclick={() => (removendoEtapa = etapa.id)}
									>
										Remover
									</button>
								{/if}
							</div>
							{#if removendoEtapa === etapa.id}
								<div class="w-full" role="alertdialog">
									<p class="text-grafite text-sm">
										Remover a etapa “{etapa.name}” do edital? Só é possível enquanto ele está em
										rascunho.
									</p>
									<div class="mt-3 flex items-center gap-2">
										<button
											class="botao"
											type="button"
											disabled={salvando}
											onclick={() => removerEtapa(etapa)}
										>
											{salvando ? 'Removendo…' : 'Remover'}
										</button>
										<button
											class="botao-discreto"
											type="button"
											onclick={() => (removendoEtapa = null)}
										>
											Cancelar
										</button>
									</div>
								</div>
							{/if}
						</li>
					{/each}
				</ul>
			{/if}
		</section>

		<section class="mt-8">
			<div class="flex flex-wrap items-end justify-between gap-4">
				<h2 class="text-grafite text-lg font-semibold tracking-tight">Grade de vagas</h2>
				<span class="etiqueta">{totalDeVagas} vaga(s) no edital</span>
			</div>
			<p class="text-cinza mt-2 text-sm">
				{alvoDoTipo(edital.kind) === 'projeto'
					? 'Uma tabela por projeto coletivo: o edital Regular chaveia as vagas por projeto.'
					: 'Uma tabela por linha de pesquisa: o edital Suplementar chaveia as vagas por linha.'}
				{#if !emRascunho}
					O edital não está mais em rascunho — a grade só pode ser lida.
				{/if}
			</p>

			{#if alvos.length === 0}
				<div class="border-borda bg-papel mt-4 border border-dashed p-10 text-center">
					<p class="text-grafite text-[0.9375rem]">
						{alvoDoTipo(edital.kind) === 'projeto'
							? 'Nenhum projeto coletivo ativo no programa.'
							: 'Nenhuma linha de pesquisa ativa no programa.'}
					</p>
					<p class="text-cinza mt-1 text-sm">Cadastre em Estrutura antes de montar a grade.</p>
				</div>
			{:else}
				{#each alvos as alvo (alvo.id)}
					<div class="border-borda bg-papel mt-4 overflow-x-auto border p-5">
						<p class="etiqueta">{alvo.nome}</p>
						<table class="text-grafite mt-3 w-full text-sm">
							<thead>
								<tr>
									<th class="etiqueta py-2 text-left">Nível</th>
									{#each cotas as cota (cota)}
										<th class="etiqueta py-2 text-left">{ROTULO_DA_COTA[cota]}</th>
									{/each}
								</tr>
							</thead>
							<tbody>
								{#each NIVEIS as nivel (nivel)}
									<tr class="border-borda border-t">
										<th class="py-2 text-left font-medium">{ROTULO_DO_NIVEL[nivel]}</th>
										{#each cotas as cota (cota)}
											<td class="py-2 pr-3">
												{#if podeCriarVaga && podeEditarVaga && emRascunho}
													<input
														class="campo w-20"
														type="number"
														min="0"
														aria-label="{ROTULO_DO_NIVEL[nivel]} · {ROTULO_DA_COTA[
															cota
														]} · {alvo.nome}"
														value={quantidadeDe(alvo, nivel, cota)}
														disabled={salvando}
														onchange={(e) => aoSairDaCelula(alvo, nivel, cota, e)}
													/>
												{:else}
													{quantidadeDe(alvo, nivel, cota)}
												{/if}
											</td>
										{/each}
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/each}
			{/if}
		</section>
	{/if}
{/if}
