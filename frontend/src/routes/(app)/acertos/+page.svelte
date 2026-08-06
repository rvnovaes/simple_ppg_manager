<script lang="ts">
	import { api, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';

	type Aluno = components['schemas']['StudentOut'];
	type Disciplina = components['schemas']['DisciplineOut'];
	type Periodo = components['schemas']['AcademicTermOut'];
	type Solicitacao = components['schemas']['EnrollmentAdjustmentRequestOut'];
	type Acao = components['schemas']['Action'];

	// `status` sai do backend como string (não como enum), então o rótulo é
	// mapeado aqui — mesmo padrão do rotulo() de alunos/+page.svelte.
	const SITUACOES: Record<string, string> = {
		open: 'Aberta',
		approved: 'Aprovada',
		rejected: 'Recusada'
	};

	const ACOES: Record<string, string> = { add: 'Incluir', drop: 'Excluir' };

	let vinculos = $state<Aluno[]>([]);
	let disciplinas = $state<Disciplina[]>([]);
	let periodos = $state<Periodo[]>([]);
	let solicitacoes = $state<Solicitacao[]>([]);
	let carregando = $state(true);
	let erro = $state('');

	// O vínculo que abre acerto: só o regular (ADR-007). O primeiro da lista
	// serve de fallback para a tela explicar por que não dá, em vez de dizer
	// que a conta não tem vínculo nenhum.
	const vinculo = $derived(vinculos.find((v) => v.modality === 'regular') ?? vinculos[0] ?? null);

	// Motivo que impede abrir o acerto — o mesmo que o backend devolveria em
	// 409, mas dito antes do formulário preenchido, não depois.
	const impedimento = $derived.by(() => {
		if (carregando) return '';
		if (vinculo === null) return 'Sua conta não tem vínculo de aluno neste programa.';
		if (vinculo.modality !== 'regular')
			return 'O acerto de matrícula é do vínculo regular. Disciplina isolada e eletiva duram um semestre e não são ajustadas por aqui.';
		if (vinculo.advisor_id === null)
			return 'Você ainda não tem orientador cadastrado, e é ele quem decide o acerto. Procure a secretaria antes de abrir a solicitação.';
		return '';
	});

	const rotuloDoPeriodo = $derived.by(() => {
		const rotulos: Record<number, string> = {};
		for (const periodo of periodos) rotulos[periodo.id] = periodo.label;
		return rotulos;
	});

	function porCodigo(a: Disciplina, b: Disciplina): number {
		return a.code.localeCompare(b.code, 'pt-BR');
	}

	function maisRecentePrimeiro(a: Periodo, b: Periodo): number {
		return b.year - a.year || b.half - a.half;
	}

	async function carregar() {
		carregando = true;
		erro = '';
		const [respVinculos, respDisciplinas, respPeriodos, respSolicitacoes] = await Promise.all([
			api.GET('/academic/students/me'),
			api.GET('/programs/disciplines/', { params: { query: { is_active: true } } }),
			api.GET('/programs/terms/'),
			api.GET('/academic/enrollment-requests/')
		]);
		const falha =
			respVinculos.error ?? respDisciplinas.error ?? respPeriodos.error ?? respSolicitacoes.error;
		if (falha) {
			erro = mensagemDeErro(falha, 'Não foi possível carregar seus acertos de matrícula.');
		} else {
			vinculos = respVinculos.data ?? [];
			disciplinas = (respDisciplinas.data?.items ?? []).slice().sort(porCodigo);
			periodos = (respPeriodos.data?.items ?? []).slice().sort(maisRecentePrimeiro);
			solicitacoes = respSolicitacoes.data?.items ?? [];
		}
		carregando = false;
	}

	// ------------------------------------------------------------ formulário

	let formAberto = $state(false);
	let periodoEscolhido = $state<number | ''>('');
	let justificativa = $state('');
	let salvando = $state(false);
	// Disciplina -> ação pedida. Fora do mapa = não entra na solicitação.
	let escolhas = $state<Record<number, Acao>>({});

	const itens = $derived(
		Object.entries(escolhas).map(([id, action]) => ({ discipline_id: Number(id), action }))
	);

	function abrirForm() {
		periodoEscolhido = periodos.find((p) => p.is_active)?.id ?? periodos[0]?.id ?? '';
		justificativa = '';
		escolhas = {};
		formAberto = true;
	}

	function fecharForm() {
		formAberto = false;
	}

	function marcar(disciplina: Disciplina, acao: Acao) {
		const atual = escolhas[disciplina.id];
		// Clicar de novo na mesma ação desmarca — é o jeito de tirar uma
		// disciplina do pedido sem um terceiro botão "nenhuma".
		if (atual === acao) {
			const resto = { ...escolhas };
			delete resto[disciplina.id];
			escolhas = resto;
		} else {
			escolhas = { ...escolhas, [disciplina.id]: acao };
		}
	}

	async function enviar(event: SubmitEvent) {
		event.preventDefault();
		if (vinculo === null || periodoEscolhido === '' || itens.length === 0) return;
		erro = '';
		salvando = true;
		const { data, error } = await api.POST('/academic/enrollment-requests/', {
			body: {
				student_id: vinculo.id,
				term_id: periodoEscolhido,
				justification: justificativa.trim(),
				items: itens
			}
		});
		salvando = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível abrir a solicitação.');
			return;
		}
		solicitacoes = [data, ...solicitacoes];
		fecharForm();
	}

	$effect(() => {
		carregar();
	});
</script>

<svelte:head>
	<title>Meus acertos · PPGD Manager</title>
</svelte:head>

<header class="flex flex-wrap items-end justify-between gap-4">
	<div>
		<p class="etiqueta">Matrícula</p>
		<h1 class="text-grafite mt-1 text-2xl font-semibold tracking-tight">Meus acertos</h1>
	</div>
	{#if !formAberto && impedimento === '' && !carregando}
		<button class="botao-discreto" type="button" onclick={abrirForm}>Nova solicitação</button>
	{/if}
</header>

{#if erro}
	<p class="aviso-erro mt-6" role="alert">{erro}</p>
{/if}

{#if carregando}
	<p class="etiqueta mt-6">Carregando…</p>
{:else}
	{#if impedimento}
		<div class="border-borda bg-papel mt-6 border border-dashed p-5">
			<p class="etiqueta">Não é possível abrir uma solicitação</p>
			<p class="text-grafite mt-2 text-[0.9375rem]">{impedimento}</p>
		</div>
	{/if}

	{#if formAberto && impedimento === ''}
		<form class="border-borda bg-papel mt-6 border p-5" onsubmit={enviar}>
			<p class="etiqueta">Nova solicitação</p>

			<div class="mt-4 grid gap-4 sm:grid-cols-[minmax(0,14rem)_1fr]">
				<div>
					<label class="etiqueta mb-2 block" for="acerto-periodo">Período letivo</label>
					<select id="acerto-periodo" class="campo" bind:value={periodoEscolhido} required>
						<option value="">Selecione…</option>
						{#each periodos as periodo (periodo.id)}
							<option value={periodo.id}>{periodo.label}</option>
						{/each}
					</select>
				</div>
				<div>
					<label class="etiqueta mb-2 block" for="acerto-justificativa">
						Justificativa (opcional)
					</label>
					<input
						id="acerto-justificativa"
						class="campo"
						bind:value={justificativa}
						placeholder="Choque de horário, troca de linha de pesquisa…"
					/>
				</div>
			</div>

			<p class="etiqueta mt-6">Disciplinas ({itens.length} selecionada(s))</p>
			{#if disciplinas.length === 0}
				<p class="text-cinza mt-2 text-sm">
					O catálogo do programa ainda não tem disciplina ativa. Procure a secretaria.
				</p>
			{:else}
				<ul class="mt-2 space-y-px">
					{#each disciplinas as disciplina (disciplina.id)}
						<li
							class="border-borda flex flex-wrap items-center justify-between gap-4 border-b px-1 py-3"
						>
							<div class="min-w-0">
								<p class="text-grafite font-mono text-[0.9375rem]">{disciplina.code}</p>
								<p class="text-cinza mt-0.5 truncate text-sm">{disciplina.name}</p>
							</div>
							<div class="flex shrink-0 items-center gap-2">
								<button
									class="botao-discreto"
									type="button"
									aria-pressed={escolhas[disciplina.id] === 'add'}
									style:border-color={escolhas[disciplina.id] === 'add'
										? 'var(--color-tinta)'
										: undefined}
									onclick={() => marcar(disciplina, 'add')}
								>
									Incluir
								</button>
								<button
									class="botao-discreto"
									type="button"
									aria-pressed={escolhas[disciplina.id] === 'drop'}
									style:border-color={escolhas[disciplina.id] === 'drop'
										? 'var(--color-carimbo)'
										: undefined}
									onclick={() => marcar(disciplina, 'drop')}
								>
									Excluir
								</button>
							</div>
						</li>
					{/each}
				</ul>
			{/if}

			<div class="mt-6 flex items-center gap-2">
				<button
					class="botao"
					type="submit"
					disabled={salvando || itens.length === 0 || periodoEscolhido === ''}
				>
					{salvando ? 'Enviando…' : 'Enviar ao orientador'}
				</button>
				<button class="botao-discreto" type="button" onclick={fecharForm}>Cancelar</button>
			</div>
		</form>
	{/if}

	<h2 class="etiqueta mt-10">Minhas solicitações</h2>
	{#if solicitacoes.length === 0}
		<div class="border-borda bg-papel mt-2 border border-dashed p-10 text-center">
			<p class="text-grafite text-[0.9375rem]">Você ainda não abriu nenhuma solicitação.</p>
		</div>
	{:else}
		<ul class="mt-2 space-y-px">
			{#each solicitacoes as solicitacao (solicitacao.id)}
				<li
					class="bg-papel regua-tinta px-5 py-4"
					style:border-left-color={solicitacao.status === 'rejected'
						? 'var(--color-carimbo)'
						: 'var(--color-tinta)'}
				>
					<div class="flex flex-wrap items-center justify-between gap-4">
						<p class="text-grafite text-[0.9375rem] font-medium">
							{rotuloDoPeriodo[solicitacao.term_id] ?? 'Período —'}
						</p>
						<span class="etiqueta">{SITUACOES[solicitacao.status] ?? solicitacao.status}</span>
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
					{#if solicitacao.status === 'rejected' && solicitacao.decision_note}
						<p class="aviso-erro mt-3">Motivo da recusa: {solicitacao.decision_note}</p>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}
{/if}
