<script lang="ts">
	import { api, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';

	type Periodo = components['schemas']['AcademicTermOut'];
	type Solicitacao = components['schemas']['EnrollmentAdjustmentRequestOut'];

	const ACOES: Record<string, string> = { add: 'Incluir', drop: 'Excluir' };

	let solicitacoes = $state<Solicitacao[]>([]);
	let periodos = $state<Periodo[]>([]);
	let carregando = $state(true);
	let erro = $state('');
	let aviso = $state('');

	const rotuloDoPeriodo = $derived.by(() => {
		const rotulos: Record<number, string> = {};
		for (const periodo of periodos) rotulos[periodo.id] = periodo.label;
		return rotulos;
	});

	function maisAntigaPrimeiro(a: Solicitacao, b: Solicitacao): number {
		return a.created_at.localeCompare(b.created_at);
	}

	async function carregar() {
		carregando = true;
		erro = '';
		// A listagem já vem escopada por papel no backend: para o docente, são
		// só as dos orientandos dele. O filtro de status é do servidor, não da
		// tela — a lista pendente não deve depender do tamanho da página.
		const [respSolicitacoes, respPeriodos] = await Promise.all([
			api.GET('/academic/enrollment-requests/', { params: { query: { status: 'open' } } }),
			api.GET('/programs/terms/')
		]);
		const falha = respSolicitacoes.error ?? respPeriodos.error;
		if (falha) {
			erro = mensagemDeErro(falha, 'Não foi possível carregar as solicitações dos orientandos.');
		} else {
			solicitacoes = (respSolicitacoes.data?.items ?? []).slice().sort(maisAntigaPrimeiro);
			periodos = respPeriodos.data?.items ?? [];
		}
		carregando = false;
	}

	// ------------------------------------------------------------- decisão

	let decisao = $state<{ id: number; tipo: 'approve' | 'reject' } | null>(null);
	let nota = $state('');
	let erroDaNota = $state('');
	let salvando = $state(false);

	function abrirDecisao(solicitacao: Solicitacao, tipo: 'approve' | 'reject') {
		decisao = { id: solicitacao.id, tipo };
		nota = '';
		erroDaNota = '';
		erro = '';
		aviso = '';
	}

	function fecharDecisao() {
		decisao = null;
		nota = '';
		erroDaNota = '';
	}

	async function decidir(solicitacao: Solicitacao, event: SubmitEvent) {
		event.preventDefault();
		if (decisao === null || salvando) return;
		const motivo = nota.trim();
		// Recusa sem motivo é 400 no backend (rejection_requires_note); barrar
		// aqui evita a ida e volta com o formulário já preenchido.
		if (decisao.tipo === 'reject' && motivo === '') {
			erroDaNota = 'A recusa precisa de um motivo — é o que o aluno vai ler.';
			return;
		}
		salvando = true;
		erro = '';
		const params = { path: { request_id: solicitacao.id } };
		const { error } =
			decisao.tipo === 'approve'
				? await api.POST('/academic/enrollment-requests/{request_id}/approve', {
						params,
						body: { note: motivo }
					})
				: await api.POST('/academic/enrollment-requests/{request_id}/reject', {
						params,
						body: { note: motivo }
					});
		salvando = false;
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível registrar a decisão.');
			// Decidida por outro caminho enquanto a tela estava aberta: recarregar
			// é o que devolve a lista à verdade do servidor.
			fecharDecisao();
			await carregar();
			return;
		}
		// Decidida deixa de ser pendente, então sai da lista na hora — sem
		// refresh manual da página.
		solicitacoes = solicitacoes.filter((s) => s.id !== solicitacao.id);
		aviso =
			decisao.tipo === 'approve'
				? `Solicitação de ${solicitacao.student_name} aprovada.`
				: `Solicitação de ${solicitacao.student_name} recusada.`;
		fecharDecisao();
	}

	$effect(() => {
		carregar();
	});
</script>

<svelte:head>
	<title>Acertos dos orientandos · PPGD Manager</title>
</svelte:head>

<header>
	<p class="etiqueta">Orientação</p>
	<h1 class="text-grafite mt-1 text-2xl font-semibold tracking-tight">Acertos dos orientandos</h1>
	<p class="text-cinza mt-2 text-sm">
		Solicitações de acerto de matrícula ainda sem decisão. Depois de aprovadas, a secretaria replica
		a mudança no sistema da UFMG.
	</p>
</header>

{#if erro}
	<p class="aviso-erro mt-6" role="alert">{erro}</p>
{/if}

{#if aviso}
	<p class="etiqueta mt-6" role="status">{aviso}</p>
{/if}

{#if carregando}
	<p class="etiqueta mt-6">Carregando…</p>
{:else if solicitacoes.length === 0}
	<div class="border-borda bg-papel mt-6 border border-dashed p-10 text-center">
		<p class="text-grafite text-[0.9375rem]">Nenhuma solicitação pendente dos seus orientandos.</p>
	</div>
{:else}
	<ul class="mt-6 space-y-px">
		{#each solicitacoes as solicitacao (solicitacao.id)}
			<li class="bg-papel regua-tinta px-5 py-4">
				<div class="flex flex-wrap items-center justify-between gap-4">
					<p class="text-grafite text-[0.9375rem] font-medium">{solicitacao.student_name}</p>
					<span class="etiqueta">{rotuloDoPeriodo[solicitacao.term_id] ?? 'Período —'}</span>
				</div>
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

				{#if decisao?.id === solicitacao.id}
					<form class="mt-4" onsubmit={(event) => decidir(solicitacao, event)}>
						<label class="etiqueta mb-2 block" for="decisao-nota-{solicitacao.id}">
							{decisao.tipo === 'approve' ? 'Observação (opcional)' : 'Motivo da recusa'}
						</label>
						<input
							id="decisao-nota-{solicitacao.id}"
							class="campo"
							bind:value={nota}
							placeholder={decisao.tipo === 'approve'
								? 'Combinado em orientação…'
								: 'Explique ao aluno por que o acerto não foi aceito'}
						/>
						{#if erroDaNota}
							<p class="aviso-erro mt-2" role="alert">{erroDaNota}</p>
						{/if}
						<div class="mt-3 flex items-center gap-2">
							<button class="botao" type="submit" disabled={salvando}>
								{#if salvando}
									Enviando…
								{:else}
									{decisao.tipo === 'approve' ? 'Confirmar aprovação' : 'Confirmar recusa'}
								{/if}
							</button>
							<button class="botao-discreto" type="button" onclick={fecharDecisao}>Cancelar</button>
						</div>
					</form>
				{:else}
					<div class="mt-4 flex items-center gap-2">
						<button
							class="botao-discreto"
							type="button"
							onclick={() => abrirDecisao(solicitacao, 'approve')}
						>
							Aprovar
						</button>
						<button
							class="botao-discreto"
							type="button"
							onclick={() => abrirDecisao(solicitacao, 'reject')}
						>
							Recusar
						</button>
					</div>
				{/if}
			</li>
		{/each}
	</ul>
{/if}
