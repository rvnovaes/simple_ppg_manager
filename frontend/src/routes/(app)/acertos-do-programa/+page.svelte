<script lang="ts">
	import { api, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';

	type Periodo = components['schemas']['AcademicTermOut'];
	type Solicitacao = components['schemas']['EnrollmentAdjustmentRequestOut'];
	type Situacao = components['schemas']['AdjustmentStatus'];

	// `status` sai do backend como string (não como enum) no corpo da
	// resposta — mesmo mapa das telas do aluno e do orientador.
	const SITUACOES: Record<string, string> = {
		open: 'Aberta',
		approved: 'Aprovada',
		rejected: 'Recusada'
	};

	const ACOES: Record<string, string> = { add: 'Incluir', drop: 'Excluir' };

	let solicitacoes = $state<Solicitacao[]>([]);
	let periodos = $state<Periodo[]>([]);
	let carregando = $state(true);
	let erro = $state('');

	// Filtros do servidor, não da tela: a listagem é paginada e o programa
	// inteiro passa por aqui, então filtrar em memória mostraria só o que
	// coube na página.
	let filtroDeSituacao = $state<Situacao | ''>('');
	let filtroDePeriodo = $state<number | ''>('');

	const rotuloDoPeriodo = $derived.by(() => {
		const rotulos: Record<number, string> = {};
		for (const periodo of periodos) rotulos[periodo.id] = periodo.label;
		return rotulos;
	});

	function maisRecentePrimeiro(a: Periodo, b: Periodo): number {
		return b.year - a.year || b.half - a.half;
	}

	function maisNovaPrimeiro(a: Solicitacao, b: Solicitacao): number {
		return b.created_at.localeCompare(a.created_at);
	}

	function dataCurta(iso: string | null): string {
		return iso === null ? '—' : new Date(iso).toLocaleDateString('pt-BR');
	}

	async function carregarPeriodos() {
		const { data, error } = await api.GET('/programs/terms/');
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar os períodos letivos.');
			return;
		}
		periodos = (data?.items ?? []).slice().sort(maisRecentePrimeiro);
	}

	async function carregarSolicitacoes(situacao: Situacao | '', periodo: number | '') {
		carregando = true;
		erro = '';
		const query = {
			...(situacao === '' ? {} : { status: situacao }),
			...(periodo === '' ? {} : { term_id: periodo })
		};
		const { data, error } = await api.GET('/academic/enrollment-requests/', {
			params: { query }
		});
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar as solicitações do programa.');
		} else {
			solicitacoes = (data?.items ?? []).slice().sort(maisNovaPrimeiro);
		}
		carregando = false;
	}

	$effect(() => {
		carregarPeriodos();
	});

	// Relê a lista sempre que um filtro muda: as duas leituras abaixo são o
	// que registra a dependência do efeito.
	$effect(() => {
		carregarSolicitacoes(filtroDeSituacao, filtroDePeriodo);
	});
</script>

<svelte:head>
	<title>Acerto de matrícula · PPGM</title>
</svelte:head>

<header>
	<p class="etiqueta">Acompanhamento</p>
	<h1 class="text-grafite mt-1 text-2xl font-semibold tracking-tight">Acerto de matrícula</h1>
	<p class="text-cinza mt-2 text-sm">
		Todas as solicitações de acerto de matrícula e sua situação. As aprovadas ainda precisam ser
		replicadas manualmente no sistema da UFMG. Esta tela é somente leitura: quem decide é o
		orientador do aluno.
	</p>
</header>

<div class="mt-6 flex flex-wrap items-end gap-3">
	<div>
		<label class="etiqueta mb-1 block" for="filtro-situacao">Situação</label>
		<select id="filtro-situacao" class="campo" bind:value={filtroDeSituacao}>
			<option value="">Todas</option>
			<option value="open">Aberta</option>
			<option value="approved">Aprovada</option>
			<option value="rejected">Recusada</option>
		</select>
	</div>
	<div>
		<label class="etiqueta mb-1 block" for="filtro-periodo">Período letivo</label>
		<select id="filtro-periodo" class="campo" bind:value={filtroDePeriodo}>
			<option value="">Todos</option>
			{#each periodos as periodo (periodo.id)}
				<option value={periodo.id}>{periodo.label}</option>
			{/each}
		</select>
	</div>
</div>

{#if erro}
	<p class="aviso-erro mt-6" role="alert">{erro}</p>
{/if}

{#if carregando}
	<p class="etiqueta mt-6">Carregando…</p>
{:else if solicitacoes.length === 0}
	<div class="border-borda bg-papel mt-6 border border-dashed p-10 text-center">
		<p class="text-grafite text-[0.9375rem]">
			{filtroDeSituacao === '' && filtroDePeriodo === ''
				? 'Nenhuma solicitação de acerto no programa.'
				: 'Nenhuma solicitação para este filtro.'}
		</p>
	</div>
{:else}
	<ul class="mt-6 space-y-px">
		{#each solicitacoes as solicitacao (solicitacao.id)}
			<li
				class="bg-papel regua-tinta px-5 py-4"
				style:border-left-color={solicitacao.status === 'rejected'
					? 'var(--color-carimbo)'
					: 'var(--color-tinta)'}
			>
				<div class="flex flex-wrap items-center justify-between gap-4">
					<p class="text-grafite text-[0.9375rem] font-medium">{solicitacao.student_name}</p>
					<span class="etiqueta">{SITUACOES[solicitacao.status] ?? solicitacao.status}</span>
				</div>
				<p class="text-cinza mt-1 text-sm">
					Orientador: {solicitacao.advisor_name ?? 'sem orientador'} · Período: {rotuloDoPeriodo[
						solicitacao.term_id
					] ?? '—'} · Aberta em {dataCurta(solicitacao.created_at)} · Decidida em {dataCurta(
						solicitacao.decided_at
					)}
				</p>
				<ul class="mt-2 space-y-1">
					{#each solicitacao.items as item (item.id)}
						<li class="text-cinza text-sm">
							<span class="text-grafite font-mono">{item.discipline_code}</span>
							{item.discipline_name} — {ACOES[item.action] ?? item.action}
						</li>
					{/each}
				</ul>
				{#if solicitacao.justification}
					<p class="text-cinza mt-2 text-sm">Justificativa: {solicitacao.justification}</p>
				{/if}
				{#if solicitacao.decision_note}
					<p class="text-cinza mt-2 text-sm">
						{solicitacao.status === 'rejected' ? 'Motivo da recusa' : 'Observação do orientador'}:
						{solicitacao.decision_note}
					</p>
				{/if}
			</li>
		{/each}
	</ul>
{/if}
