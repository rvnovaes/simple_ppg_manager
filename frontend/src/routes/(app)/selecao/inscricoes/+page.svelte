<script lang="ts">
	import { api, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';
	// `formatarTamanho` não é vocabulário da isolada — é só bytes em KB, e
	// escrever a mesma linha aqui faria a mesma conta em dois lugares.
	import { formatarTamanho } from '$lib/isolada';
	import {
		COTAS_POR_TIPO,
		NIVEIS,
		ROTULO_DA_COTA,
		ROTULO_DA_SITUACAO_DA_INSCRICAO,
		ROTULO_DO_DOCUMENTO_DA_INSCRICAO,
		ROTULO_DO_NIVEL,
		SITUACOES_DA_INSCRICAO,
		alvoDoTipo,
		formatarCpf,
		formatarMomento,
		type Cota,
		type Nivel,
		type SituacaoDaInscricao,
		type TipoDeDocumentoDaInscricao
	} from '$lib/selecao';
	import { sessao } from '$lib/sessao.svelte';

	type Inscricao = components['schemas']['ApplicationOut'];
	type Detalhe = components['schemas']['ApplicationDetailOut'];
	type Edital = components['schemas']['SelectionProcessOut'];
	type Linha = components['schemas']['ResearchLineOut'];
	type Projeto = components['schemas']['CollectiveProjectOut'];

	let inscricoes = $state<Inscricao[]>([]);
	let editais = $state<Edital[]>([]);
	let linhas = $state<Linha[]>([]);
	let projetos = $state<Projeto[]>([]);

	let carregando = $state(true);
	let carregandoDetalhe = $state(false);
	let decidindo = $state(false);
	let erro = $state('');
	let aviso = $state('');

	// A conferência é da secretaria: Coordenação e Comissão veem a fila, mas
	// só quem tem `change_application` decide, e só quem tem
	// `download_applicationdocument` abre o anexo (as duas checagens que
	// valem são as do backend; aqui é para a tela não oferecer o que dá 403).
	const podeDecidir = $derived(sessao.pode('selection.change_application'));
	const podeBaixar = $derived(sessao.pode('selection.download_applicationdocument'));

	// --- filtros -----------------------------------------------------------

	// Todos os filtros são do servidor, e não da tela: a lista é paginada
	// (100 por página) e filtrar em memória mostraria só o que coube na
	// primeira página.
	let filtroEdital = $state<number | ''>('');
	let filtroSituacao = $state<SituacaoDaInscricao | ''>('');
	let filtroNivel = $state<Nivel | ''>('');
	let filtroCota = $state<Cota | ''>('');
	// O alvo é XOR no model (projeto OU linha), então a caixa é uma só e a
	// chave carrega de qual dos dois se trata.
	let filtroAlvo = $state<string>('');
	let busca = $state('');

	const edital = $derived(editais.find((e) => e.id === filtroEdital) ?? null);

	/**
	 * As cotas oferecidas pelo edital escolhido — as seis quando nenhum foi.
	 *
	 * Espelho de `CATEGORIAS_POR_TIPO`: filtrar por cota racial num edital
	 * suplementar nunca acharia nada, e a caixa não deve oferecer isso.
	 */
	const cotas = $derived<Cota[]>(
		edital === null
			? [...COTAS_POR_TIPO.regular, ...COTAS_POR_TIPO.supplementary]
			: COTAS_POR_TIPO[edital.kind]
	);

	const nomeDaLinha = $derived.by(() => {
		const mapa: Record<number, string> = {};
		for (const linha of linhas) mapa[linha.id] = linha.name;
		return mapa;
	});

	/** Projetos e linhas na mesma caixa; o edital escolhido restringe ao
	 * alvo que ele usa (projeto no Regular, linha no Suplementar). */
	const alvos = $derived.by<{ chave: string; nome: string }[]>(() => {
		const porProjeto = projetos.map((p) => ({
			chave: `p:${p.id}`,
			nome: `${p.name} · ${nomeDaLinha[p.research_line_id] ?? '—'}`
		}));
		const porLinha = linhas.map((l) => ({ chave: `l:${l.id}`, nome: l.name }));
		if (edital === null) return [...porProjeto, ...porLinha];
		return alvoDoTipo(edital.kind) === 'projeto' ? porProjeto : porLinha;
	});

	type Filtros = {
		process_id?: number;
		status?: SituacaoDaInscricao;
		level?: Nivel;
		quota_category?: Cota;
		project_id?: number;
		research_line_id?: number;
		search?: string;
	};

	/**
	 * Os filtros só são lidos aqui, nunca dentro do `$effect` de montagem:
	 * lê-los lá os tornaria dependência do efeito, e cada troca dispararia
	 * dois carregamentos (mesma armadilha da tela de bancas).
	 */
	function filtros(): Filtros {
		const [tipo, id] = filtroAlvo === '' ? ['', ''] : filtroAlvo.split(':');
		return {
			...(filtroEdital === '' ? {} : { process_id: filtroEdital }),
			...(filtroSituacao === '' ? {} : { status: filtroSituacao }),
			...(filtroNivel === '' ? {} : { level: filtroNivel }),
			...(filtroCota === '' ? {} : { quota_category: filtroCota }),
			...(tipo === 'p' ? { project_id: Number(id) } : {}),
			...(tipo === 'l' ? { research_line_id: Number(id) } : {}),
			...(busca.trim() === '' ? {} : { search: busca.trim() })
		};
	}

	async function carregarInscricoes(query: Filtros = {}) {
		const { data, error } = await api.GET('/selection/applications/', { params: { query } });
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar as inscrições do programa.');
			return;
		}
		inscricoes = data?.items ?? [];
	}

	async function carregarApoio() {
		const [respEditais, respLinhas, respProjetos] = await Promise.all([
			api.GET('/selection/processes/'),
			api.GET('/programs/research-lines/'),
			api.GET('/programs/collective-projects/')
		]);
		const falha = respEditais.error ?? respLinhas.error ?? respProjetos.error;
		if (falha) {
			erro = mensagemDeErro(falha, 'Não foi possível carregar editais e alvos.');
			return;
		}
		editais = respEditais.data?.items ?? [];
		linhas = respLinhas.data?.items ?? [];
		projetos = respProjetos.data?.items ?? [];
	}

	async function refiltrar() {
		erro = '';
		aviso = '';
		// Fecha o detalhe: a inscrição aberta pode não caber no filtro novo, e
		// o painel ficaria pendurado numa linha que sumiu da lista.
		abertoId = null;
		detalhe = null;
		carregando = true;
		await carregarInscricoes(filtros());
		carregando = false;
	}

	/** Trocar de edital pode trocar a natureza do alvo e as cotas — a
	 * escolha antiga viraria filtro que não acha nada. */
	async function trocarEdital() {
		filtroAlvo = '';
		filtroCota = '';
		await refiltrar();
	}

	function buscar(event: SubmitEvent) {
		event.preventDefault();
		refiltrar();
	}

	// --- detalhe -----------------------------------------------------------

	// Uma inscrição aberta por vez: o detalhe é uma chamada por inscrição (é
	// ele que traz os anexos) e a decisão é sobre um candidato só.
	let abertoId = $state<number | null>(null);
	let detalhe = $state<Detalhe | null>(null);
	let nota = $state('');

	async function abrir(inscricao: Inscricao) {
		if (abertoId === inscricao.id) {
			abertoId = null;
			detalhe = null;
			return;
		}
		abertoId = inscricao.id;
		detalhe = null;
		nota = '';
		erro = '';
		aviso = '';
		carregandoDetalhe = true;
		const { data, error } = await api.GET('/selection/applications/{application_id}/', {
			params: { path: { application_id: inscricao.id } }
		});
		carregandoDetalhe = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível abrir esta inscrição.');
			return;
		}
		detalhe = data;
	}

	/** A decisão devolve o detalhe atualizado: a linha da lista é trocada
	 * pelos mesmos campos, sem recarregar a fila inteira. */
	function substituir(atualizada: Detalhe) {
		detalhe = atualizada;
		inscricoes = inscricoes.map((i) => (i.id === atualizada.id ? { ...i, ...atualizada } : i));
	}

	async function homologar() {
		if (detalhe === null || decidindo) return;
		erro = '';
		aviso = '';
		decidindo = true;
		const { data, error } = await api.POST('/selection/applications/{application_id}/homologate', {
			params: { path: { application_id: detalhe.id } },
			body: { note: nota.trim() }
		});
		decidindo = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível homologar a inscrição.');
			return;
		}
		substituir(data);
		nota = '';
		aviso = `Inscrição ${data.protocol} homologada.`;
	}

	async function indeferir() {
		if (detalhe === null || decidindo) return;
		// Validação de UX; a que vale é a do model (`rejection_requires_note`),
		// e é ela que responde se alguém contornar a tela.
		if (nota.trim() === '') {
			erro = 'Escreva o motivo do indeferimento: é o que o candidato tem direito de saber.';
			return;
		}
		erro = '';
		aviso = '';
		decidindo = true;
		const { data, error } = await api.POST('/selection/applications/{application_id}/reject', {
			params: { path: { application_id: detalhe.id } },
			body: { note: nota.trim() }
		});
		decidindo = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível indeferir a inscrição.');
			return;
		}
		substituir(data);
		nota = '';
		aviso = `Inscrição ${data.protocol} indeferida.`;
	}

	function rotuloDoDocumento(tipo: string): string {
		return ROTULO_DO_DOCUMENTO_DA_INSCRICAO[tipo as TipoDeDocumentoDaInscricao] ?? tipo;
	}

	$effect(() => {
		carregando = true;
		Promise.all([carregarApoio(), carregarInscricoes()]).then(() => {
			carregando = false;
		});
	});
</script>

<svelte:head>
	<title>Inscrições · PPGM</title>
</svelte:head>

<header>
	<p class="etiqueta">Processo seletivo</p>
	<h1 class="text-grafite mt-1 text-2xl font-semibold tracking-tight">Inscrições</h1>
	<p class="text-cinza mt-2 text-sm">
		As inscrições recebidas pelo formulário público. Confira os anexos e homologue — ou indefira,
		dizendo o motivo.
	</p>
</header>

<div class="mt-6 flex flex-wrap items-end gap-3">
	<div>
		<label class="etiqueta mb-1 block" for="filtro-edital">Edital</label>
		<select id="filtro-edital" class="campo w-64" bind:value={filtroEdital} onchange={trocarEdital}>
			<option value="">Todos</option>
			{#each editais as opcao (opcao.id)}
				<option value={opcao.id}>{opcao.title}</option>
			{/each}
		</select>
	</div>
	<div>
		<label class="etiqueta mb-1 block" for="filtro-situacao">Situação</label>
		<select
			id="filtro-situacao"
			class="campo w-44"
			bind:value={filtroSituacao}
			onchange={refiltrar}
		>
			<option value="">Todas</option>
			{#each SITUACOES_DA_INSCRICAO as opcao (opcao)}
				<option value={opcao}>{ROTULO_DA_SITUACAO_DA_INSCRICAO[opcao]}</option>
			{/each}
		</select>
	</div>
	<div>
		<label class="etiqueta mb-1 block" for="filtro-nivel">Nível</label>
		<select id="filtro-nivel" class="campo w-40" bind:value={filtroNivel} onchange={refiltrar}>
			<option value="">Todos</option>
			{#each NIVEIS as opcao (opcao)}
				<option value={opcao}>{ROTULO_DO_NIVEL[opcao]}</option>
			{/each}
		</select>
	</div>
	<div>
		<label class="etiqueta mb-1 block" for="filtro-cota">Categoria</label>
		<select id="filtro-cota" class="campo w-52" bind:value={filtroCota} onchange={refiltrar}>
			<option value="">Todas</option>
			{#each cotas as opcao (opcao)}
				<option value={opcao}>{ROTULO_DA_COTA[opcao]}</option>
			{/each}
		</select>
	</div>
	<div>
		<label class="etiqueta mb-1 block" for="filtro-alvo">
			{edital !== null && alvoDoTipo(edital.kind) === 'linha' ? 'Linha de pesquisa' : 'Alvo'}
		</label>
		<select id="filtro-alvo" class="campo w-64" bind:value={filtroAlvo} onchange={refiltrar}>
			<option value="">Todos</option>
			{#each alvos as opcao (opcao.chave)}
				<option value={opcao.chave}>{opcao.nome}</option>
			{/each}
		</select>
	</div>
	<form class="flex items-end gap-2" onsubmit={buscar}>
		<div>
			<label class="etiqueta mb-1 block" for="filtro-busca">Nome, protocolo ou CPF</label>
			<input id="filtro-busca" class="campo w-64" bind:value={busca} placeholder="Buscar…" />
		</div>
		<button class="botao-discreto" type="submit">Buscar</button>
	</form>
</div>

{#if erro}
	<p class="aviso-erro mt-6" role="alert">{erro}</p>
{/if}

{#if aviso}
	<p class="etiqueta mt-6" role="status">{aviso}</p>
{/if}

{#if carregando}
	<p class="etiqueta mt-6">Carregando…</p>
{:else if inscricoes.length === 0}
	<div class="border-borda bg-papel mt-6 border border-dashed p-10 text-center">
		<p class="text-grafite text-[0.9375rem]">Nenhuma inscrição com estes filtros.</p>
		<p class="text-cinza mt-1 text-sm">
			As inscrições chegam pelo formulário público do edital, enquanto a janela estiver aberta.
		</p>
	</div>
{:else}
	<ul class="mt-6 space-y-px">
		{#each inscricoes as inscricao (inscricao.id)}
			<li
				class="bg-papel regua-tinta px-5 py-4"
				style:border-left-color={inscricao.status === 'rejected' ||
				inscricao.status === 'eliminated'
					? 'var(--color-carimbo)'
					: 'var(--color-tinta)'}
			>
				<div class="flex flex-wrap items-center justify-between gap-4">
					<div class="min-w-0">
						<p class="text-grafite text-[0.9375rem] font-medium">{inscricao.full_name}</p>
						<p class="text-cinza mt-0.5 text-sm">
							<span class="font-mono">{inscricao.protocol}</span>
							· {formatarCpf(inscricao.cpf)} · {inscricao.email}
						</p>
					</div>
					<div class="flex items-center gap-4">
						<span class="etiqueta">{inscricao.status_label}</span>
						<button class="botao-discreto" type="button" onclick={() => abrir(inscricao)}>
							{abertoId === inscricao.id ? 'Fechar' : 'Conferir'}
						</button>
					</div>
				</div>
				<p class="text-cinza mt-1 text-sm">
					{inscricao.process_title} · {inscricao.level_label} · {inscricao.target_label || '—'} · {inscricao.quota_category_label}
					· inscrita em {formatarMomento(inscricao.submitted_at)}
				</p>
				{#if inscricao.decision_note}
					<p class="text-cinza mt-2 text-sm">Decisão: {inscricao.decision_note}</p>
				{/if}

				{#if abertoId === inscricao.id}
					<div class="border-borda mt-4 border-t pt-4">
						{#if carregandoDetalhe}
							<p class="etiqueta">Carregando…</p>
						{:else if detalhe !== null}
							<h2 class="etiqueta">Documentos anexados</h2>
							{#if detalhe.documents.length === 0}
								<p class="text-cinza mt-2 text-sm">Nenhum documento anexado.</p>
							{:else}
								<ul class="mt-2 space-y-px">
									{#each detalhe.documents as documento (documento.id)}
										<li class="border-borda flex items-center justify-between gap-4 border-b py-2">
											<div class="min-w-0">
												<p class="text-grafite text-[0.9375rem]">
													{rotuloDoDocumento(documento.kind)}
												</p>
												<p class="text-cinza mt-0.5 truncate text-sm">
													{documento.filename} · {formatarTamanho(documento.size)} · {formatarMomento(
														documento.uploaded_at
													)}
												</p>
											</div>
											{#if podeBaixar}
												<!-- Endereço da API, e não rota da SPA: o anexo sai pelo
												Django (o MEDIA não é servido direto, ver
												`ApplicationDocumentOut`) e a leitura é auditada, então
												`resolve()` não se aplica. Continua relativo — origem
												única (ADR-004). -->
												<!-- eslint-disable svelte/no-navigation-without-resolve -->
												<a
													class="botao-discreto shrink-0"
													href="/api/v1/selection/applications/documents/{documento.id}/download"
												>
													Abrir
												</a>
												<!-- eslint-enable svelte/no-navigation-without-resolve -->
											{/if}
										</li>
									{/each}
								</ul>
							{/if}
							{#if detalhe.missing_documents.length > 0}
								<p class="text-cinza mt-2 text-sm">
									Falta anexar: {detalhe.missing_documents.map(rotuloDoDocumento).join(', ')}.
								</p>
							{/if}

							<dl class="mt-4 grid gap-x-6 gap-y-1 sm:grid-cols-2 lg:grid-cols-4">
								<div>
									<dt class="etiqueta">Nascimento</dt>
									<dd class="text-grafite text-[0.8125rem]">
										{new Date(`${detalhe.birth_date}T00:00`).toLocaleDateString('pt-BR')}
									</dd>
								</div>
								<div>
									<dt class="etiqueta">Telefone</dt>
									<dd class="text-grafite text-[0.8125rem]">{detalhe.phone_number || '—'}</dd>
								</div>
								<div>
									<dt class="etiqueta">Decidida em</dt>
									<dd class="text-grafite text-[0.8125rem]">
										{formatarMomento(detalhe.decided_at)}
									</dd>
								</div>
								<div>
									<dt class="etiqueta">Situação</dt>
									<dd class="text-grafite text-[0.8125rem]">{detalhe.status_label}</dd>
								</div>
							</dl>

							{#if podeDecidir && detalhe.status === 'submitted'}
								<h2 class="etiqueta mt-6">Decisão</h2>
								<label class="mt-2 block">
									<span class="etiqueta">Nota (obrigatória no indeferimento)</span>
									<input class="campo mt-1 w-full" bind:value={nota} disabled={decidindo} />
								</label>
								<div class="mt-4 flex flex-wrap gap-3">
									<button class="botao" type="button" disabled={decidindo} onclick={homologar}>
										{decidindo ? 'Registrando…' : 'Homologar'}
									</button>
									<button
										class="botao-discreto"
										type="button"
										disabled={decidindo}
										onclick={indeferir}
									>
										Indeferir
									</button>
								</div>
							{:else if detalhe.status !== 'submitted'}
								<!-- Homologar e indeferir só valem sobre a inscrição ainda não
								decidida (409 `application_not_submitted`): passado esse ponto a
								tela mostra o que foi decidido, e não botões que dão erro. -->
								<p class="text-cinza mt-6 text-sm">
									Esta inscrição já foi decidida em {formatarMomento(detalhe.decided_at)}.
								</p>
							{/if}
						{/if}
					</div>
				{/if}
			</li>
		{/each}
	</ul>
{/if}
