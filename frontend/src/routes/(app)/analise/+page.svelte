<script lang="ts">
	import { api, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';
	import {
		ROTULO_DA_SITUACAO,
		ROTULO_DO_DOCUMENTO,
		ROTULO_DO_PAGAMENTO,
		formatarPrazo,
		formatarTamanho
	} from '$lib/isolada';

	type Ciclo = components['schemas']['IsolatedCycleOut'];
	type Oferta = components['schemas']['DisciplineOfferingOut'];
	type Requerimento = components['schemas']['IsolatedRequestOut'];
	type Documento = components['schemas']['RequestDocumentOut'];
	type Situacao = components['schemas']['IsolatedRequestStatus'];

	let ciclos = $state<Ciclo[]>([]);
	let ofertas = $state<Oferta[]>([]);
	let requerimentos = $state<Requerimento[]>([]);
	let documentos = $state<Documento[]>([]);

	let carregando = $state(true);
	let carregandoDocumentos = $state(false);
	let decidindo = $state(false);
	let erro = $state('');
	let aviso = $state('');

	// Filtros do servidor, e não da tela: a fila é paginada e o edital
	// inteiro passa por aqui, então filtrar em memória mostraria só o que
	// coube na página.
	let cicloId = $state<number | null>(null);
	let filtroDeSituacao = $state<Situacao | ''>('');

	// Um requerimento aberto por vez: os anexos são uma chamada por
	// requerimento e a decisão é sobre um candidato só.
	let abertoId = $state<number | null>(null);
	let linkDaGru = $state('');
	let motivo = $state('');

	const ciclo = $derived(ciclos.find((c) => c.id === cicloId) ?? null);
	const aberto = $derived(requerimentos.find((r) => r.id === abertoId) ?? null);

	/** Vagas restantes por oferta, para a linha de cada disciplina. */
	const ofertaPorId = $derived.by(() => {
		const mapa: Record<number, Oferta> = {};
		for (const oferta of ofertas) mapa[oferta.id] = oferta;
		return mapa;
	});

	/**
	 * Ofertas que o docente ainda não classificou.
	 *
	 * Só vira aviso enquanto o edital está ativo: sem a lista do docente
	 * `defer()` recusa com `offering_not_ranked` e ninguém é matriculado —
	 * o custo do silêncio é a disciplina ficar vazia. Depois do
	 * encerramento a informação é histórica e não pede ação de ninguém.
	 */
	const semClassificacao = $derived(
		ciclo !== null && ciclo.is_active ? ofertas.filter((o) => o.needs_ranking) : []
	);

	async function carregarCiclos() {
		const { data, error } = await api.GET('/academic/isolated/cycles/');
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar os editais do programa.');
			carregando = false;
			return;
		}
		ciclos = data ?? [];
		// O servidor devolve do semestre mais recente para o mais antigo, e é
		// esse o edital em análise.
		cicloId = ciclos[0]?.id ?? null;
		if (cicloId === null) carregando = false;
	}

	async function carregarOfertas(ciclo: number) {
		// `?cycle_id=`: a lista da secretaria ignora a janela de inscrição de
		// propósito — ela analisa depois que a inscrição fecha, e é aí que
		// precisa das vagas restantes.
		const { data, error } = await api.GET('/academic/isolated/offerings/', {
			params: { query: { cycle_id: ciclo } }
		});
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar as disciplinas do edital.');
			return;
		}
		ofertas = data ?? [];
	}

	async function carregarRequerimentos(ciclo: number, situacao: Situacao | '') {
		const resposta = await api.GET('/academic/isolated/requests/', {
			params: {
				query: { cycle_id: ciclo, ...(situacao === '' ? {} : { status: situacao }) }
			}
		});
		// A falha sai do objeto ANTES do `if`: a rota não declara resposta de
		// erro no OpenAPI e dentro do bloco o objeto inteiro vira `never`.
		const falha = resposta.error;
		if (falha) {
			erro = mensagemDeErro(falha, 'Não foi possível carregar os requerimentos.');
			return;
		}
		requerimentos = (resposta.data?.items ?? [])
			.slice()
			.sort((a, b) => a.person_name.localeCompare(b.person_name, 'pt-BR'));
	}

	async function carregar(ciclo: number, situacao: Situacao | '') {
		carregando = true;
		erro = '';
		await Promise.all([carregarOfertas(ciclo), carregarRequerimentos(ciclo, situacao)]);
		carregando = false;
	}

	async function abrir(requerimento: Requerimento) {
		if (abertoId === requerimento.id) {
			abertoId = null;
			return;
		}
		abertoId = requerimento.id;
		linkDaGru = requerimento.gru_url;
		motivo = '';
		aviso = '';
		erro = '';
		documentos = [];
		carregandoDocumentos = true;
		const { data, error } = await api.GET('/academic/isolated/requests/{request_id}/documents', {
			params: { path: { request_id: requerimento.id } }
		});
		carregandoDocumentos = false;
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar os anexos deste requerimento.');
			return;
		}
		documentos = data ?? [];
	}

	function substituir(atualizado: Requerimento) {
		requerimentos = requerimentos.map((r) => (r.id === atualizado.id ? atualizado : r));
	}

	async function deferir() {
		if (aberto === null || decidindo) return;
		erro = '';
		aviso = '';
		decidindo = true;
		const { data, error } = await api.POST('/academic/isolated/requests/{request_id}/defer', {
			params: { path: { request_id: aberto.id } },
			// Link vazio vira `null`: `HttpUrl` recusa string em branco (422) e
			// o servidor da UFMG é isento, sem guia a pagar.
			body: { note: '', gru_url: linkDaGru.trim() === '' ? null : linkDaGru.trim() }
		});
		decidindo = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível deferir o requerimento.');
			return;
		}
		substituir(data);
		aviso = `Requerimento de ${data.person_name} deferido.`;
		// A vaga saiu da oferta: sem recarregar, o saldo da tela mentiria na
		// próxima decisão.
		if (cicloId !== null) await carregarOfertas(cicloId);
	}

	async function indeferir() {
		if (aberto === null || decidindo) return;
		if (motivo.trim() === '') {
			erro = 'Escreva o motivo do indeferimento: é o texto que o candidato contesta no recurso.';
			return;
		}
		erro = '';
		aviso = '';
		decidindo = true;
		const { data, error } = await api.POST('/academic/isolated/requests/{request_id}/reject', {
			params: { path: { request_id: aberto.id } },
			body: { note: motivo }
		});
		decidindo = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível indeferir o requerimento.');
			return;
		}
		substituir(data);
		motivo = '';
		aviso = `Requerimento de ${data.person_name} indeferido.`;
	}

	async function cancelar() {
		if (aberto === null || decidindo) return;
		erro = '';
		aviso = '';
		decidindo = true;
		const { data, error } = await api.POST('/academic/isolated/requests/{request_id}/cancel', {
			params: { path: { request_id: aberto.id } },
			body: { note: motivo }
		});
		decidindo = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível cancelar o requerimento.');
			return;
		}
		substituir(data);
		motivo = '';
		aviso = `Requerimento de ${data.person_name} cancelado — a vaga volta para a fila.`;
		if (cicloId !== null) await carregarOfertas(cicloId);
	}

	$effect(() => {
		carregarCiclos();
	});

	// Relê edital e fila sempre que o ciclo ou o filtro mudam: as leituras
	// abaixo são o que registra a dependência do efeito.
	$effect(() => {
		if (cicloId !== null) carregar(cicloId, filtroDeSituacao);
	});
</script>

<svelte:head>
	<title>Análise das inscrições · PPGM</title>
</svelte:head>

<header>
	<p class="etiqueta">Disciplina isolada</p>
	<h1 class="text-grafite mt-1 text-2xl font-semibold tracking-tight">Análise das inscrições</h1>
	<p class="text-cinza mt-2 text-sm">
		Os requerimentos do edital com a classificação do docente, as vagas restantes e os documentos
		anexados. Defira seguindo a ordem do docente, até o limite de vagas.
	</p>
</header>

<div class="mt-6 flex flex-wrap items-end gap-3">
	<div>
		<label class="etiqueta mb-1 block" for="filtro-ciclo">Edital</label>
		<select id="filtro-ciclo" class="campo" bind:value={cicloId}>
			{#each ciclos as item (item.id)}
				<option value={item.id}>{item.term_label}{item.is_active ? '' : ' (encerrado)'}</option>
			{/each}
		</select>
	</div>
	<div>
		<label class="etiqueta mb-1 block" for="filtro-situacao">Situação</label>
		<select id="filtro-situacao" class="campo" bind:value={filtroDeSituacao}>
			<option value="">Todas</option>
			<option value="submitted">Inscrito</option>
			<option value="deferred">Deferido</option>
			<option value="rejected">Indeferido</option>
			<option value="cancelled">Cancelado</option>
			<option value="enrolled">Matriculado</option>
			<option value="draft">Rascunho</option>
		</select>
	</div>
</div>

{#if erro}
	<p class="aviso-erro mt-6" role="alert">{erro}</p>
{/if}

{#if aviso}
	<p class="etiqueta mt-6" role="status">{aviso}</p>
{/if}

{#if ciclo !== null}
	<p class="text-cinza mt-4 text-sm">
		Inscrições até {formatarPrazo(ciclo.submission_closes_at)} · recursos até {formatarPrazo(
			ciclo.appeal_closes_at
		)} · pagamento até {formatarPrazo(ciclo.payment_closes_at)}.
	</p>
{/if}

{#if semClassificacao.length > 0}
	<section class="border-carimbo bg-papel mt-6 border-l-2 p-5" role="alert">
		<p class="etiqueta">Falta a classificação do docente</p>
		<p class="text-grafite mt-2 text-[0.9375rem]">
			Estas disciplinas não têm lista do docente e nenhum candidato delas pode ser deferido:
		</p>
		<ul class="mt-2 space-y-1">
			{#each semClassificacao as oferta (oferta.id)}
				<li class="text-cinza text-sm">
					<span class="text-grafite font-mono">{oferta.discipline_code}</span>
					{oferta.discipline_name} — {oferta.teacher_name}
				</li>
			{/each}
		</ul>
	</section>
{/if}

{#if carregando}
	<p class="etiqueta mt-6">Carregando…</p>
{:else if ciclos.length === 0}
	<div class="border-borda bg-papel mt-6 border border-dashed p-10 text-center">
		<p class="text-grafite text-[0.9375rem]">Nenhum edital de disciplina isolada cadastrado.</p>
	</div>
{:else if requerimentos.length === 0}
	<div class="border-borda bg-papel mt-6 border border-dashed p-10 text-center">
		<p class="text-grafite text-[0.9375rem]">
			{filtroDeSituacao === ''
				? 'Nenhum requerimento neste edital.'
				: 'Nenhum requerimento nesta situação.'}
		</p>
	</div>
{:else}
	<ul class="mt-6 space-y-px">
		{#each requerimentos as requerimento (requerimento.id)}
			<li
				class="bg-papel regua-tinta px-5 py-4"
				style:border-left-color={requerimento.status === 'rejected' ||
				requerimento.status === 'cancelled'
					? 'var(--color-carimbo)'
					: 'var(--color-tinta)'}
			>
				<div class="flex flex-wrap items-center justify-between gap-4">
					<p class="text-grafite text-[0.9375rem] font-medium">{requerimento.person_name}</p>
					<div class="flex items-center gap-4">
						<span class="etiqueta">
							{ROTULO_DA_SITUACAO[requerimento.status] ?? requerimento.status} · taxa {ROTULO_DO_PAGAMENTO[
								requerimento.payment_status
							] ?? requerimento.payment_status}
						</span>
						<button class="botao-discreto" type="button" onclick={() => abrir(requerimento)}>
							{abertoId === requerimento.id ? 'Fechar' : 'Analisar'}
						</button>
					</div>
				</div>
				<p class="text-cinza mt-1 text-sm">
					Inscrito em {formatarPrazo(requerimento.submitted_at)}
					{#if requerimento.is_ufmg_staff}· servidor da UFMG (isento){/if}
					{#if requerimento.appealed_at !== null}· recurso em {formatarPrazo(
							requerimento.appealed_at
						)}{/if}
				</p>
				<ul class="mt-2 space-y-1">
					{#each requerimento.items as item (item.id)}
						<li class="text-cinza text-sm">
							<span class="text-grafite font-mono">{item.discipline_code}</span>
							{item.discipline_name} — {item.rank === null
								? 'sem classificação'
								: `classificação ${item.rank}`}
							{#if ofertaPorId[item.offering_id]}
								· {ofertaPorId[item.offering_id].seats_available} de {ofertaPorId[item.offering_id]
									.seats} vagas livres
							{/if}
						</li>
					{/each}
				</ul>
				{#if requerimento.decision_note}
					<p class="text-cinza mt-2 text-sm">Decisão: {requerimento.decision_note}</p>
				{/if}
				{#if requerimento.appeal_note}
					<p class="text-cinza mt-2 text-sm">Recurso: {requerimento.appeal_note}</p>
				{/if}

				{#if abertoId === requerimento.id}
					<div class="border-borda mt-4 border-t pt-4">
						<h2 class="etiqueta">Documentos anexados</h2>
						{#if carregandoDocumentos}
							<p class="etiqueta mt-2">Carregando…</p>
						{:else if documentos.length === 0}
							<p class="text-cinza mt-2 text-sm">Nenhum documento anexado.</p>
						{:else}
							<ul class="mt-2 space-y-px">
								{#each documentos as documento (documento.id)}
									<li class="border-borda flex items-center justify-between gap-4 border-b py-2">
										<div class="min-w-0">
											<p class="text-grafite text-[0.9375rem]">
												{ROTULO_DO_DOCUMENTO[documento.kind] ?? documento.kind_label}
											</p>
											<p class="text-cinza mt-0.5 truncate text-sm">
												{documento.filename} · {formatarTamanho(documento.size)} · {formatarPrazo(
													documento.uploaded_at
												)}
											</p>
										</div>
										<!-- Endereço da API, e não rota da SPA: o download é
										resposta do Django (o MEDIA não é servido direto, ver
										`RequestDocumentOut`), então `resolve()` não se aplica.
										Continua relativo — origem única (ADR-004). -->
										<!-- eslint-disable svelte/no-navigation-without-resolve -->
										<a
											class="botao-discreto shrink-0"
											href="/api/v1/academic/isolated/documents/{documento.id}/download"
										>
											Abrir
										</a>
										<!-- eslint-enable svelte/no-navigation-without-resolve -->
									</li>
								{/each}
							</ul>
						{/if}
						{#if requerimento.missing_documents.length > 0}
							<p class="text-cinza mt-2 text-sm">
								Falta anexar: {requerimento.missing_documents
									.map((tipo) => ROTULO_DO_DOCUMENTO[tipo] ?? tipo)
									.join(', ')}.
							</p>
						{/if}

						<h2 class="etiqueta mt-6">Decisão</h2>
						<div class="mt-2 grid gap-3 sm:grid-cols-2">
							<label class="block">
								<span class="etiqueta">Link da GRU</span>
								<input
									class="campo mt-1 w-full"
									type="url"
									placeholder="https://…"
									bind:value={linkDaGru}
									disabled={decidindo}
								/>
							</label>
							<label class="block">
								<span class="etiqueta">Motivo (indeferimento e cancelamento)</span>
								<input class="campo mt-1 w-full" bind:value={motivo} disabled={decidindo} />
							</label>
						</div>
						<p class="text-cinza mt-2 text-sm">
							O link da GRU vai junto com o deferimento — deferir sem dizer como pagar deixa o
							candidato parado. Servidor da UFMG é isento e para ele o campo fica vazio.
						</p>
						<div class="mt-4 flex flex-wrap gap-3">
							<button class="botao" type="button" disabled={decidindo} onclick={deferir}>
								{decidindo ? 'Registrando…' : 'Deferir'}
							</button>
							<button class="botao-discreto" type="button" disabled={decidindo} onclick={indeferir}>
								Indeferir
							</button>
							<button class="botao-discreto" type="button" disabled={decidindo} onclick={cancelar}>
								Cancelar inscrição
							</button>
						</div>
					</div>
				{/if}
			</li>
		{/each}
	</ul>
{/if}
