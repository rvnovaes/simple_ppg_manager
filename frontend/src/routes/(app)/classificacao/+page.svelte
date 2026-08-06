<script lang="ts">
	import { api, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';
	import { formatarPrazo } from '$lib/isolada';

	type Oferta = components['schemas']['DisciplineOfferingOut'];
	type Candidato = components['schemas']['IsolatedCandidateOut'];

	let ofertas = $state<Oferta[]>([]);
	let carregando = $state(true);
	let erro = $state('');
	let aviso = $state('');

	let ofertaId = $state<number | null>(null);
	let candidatos = $state<Candidato[]>([]);
	let carregandoCandidatos = $state(false);
	let salvando = $state(false);

	const oferta = $derived(ofertas.find((o) => o.id === ofertaId) ?? null);

	// Falta responder primeiro: é o que o docente veio fazer. Dentro de cada
	// grupo, a ordem do servidor (ciclo e código da disciplina) é preservada.
	const semClassificacao = $derived(ofertas.filter((o) => o.needs_ranking));
	const jaClassificadas = $derived(ofertas.filter((o) => !o.needs_ranking));

	/**
	 * Quantos desta fila cabem — é onde o corte cai.
	 *
	 * `seats_available` e não `seats`: quem já foi deferido pela secretaria
	 * ocupou vaga e saiu de `candidates()` (a lista aqui só tem inscrito). O
	 * saldo é a conta do servidor; a tela apenas desenha a linha.
	 */
	const corte = $derived(oferta === null ? 0 : oferta.seats_available);

	async function carregarOfertas() {
		carregando = true;
		erro = '';
		// `?mine=true`: a posse sai da sessão no backend, nunca de um
		// `teacher_id` daqui. Esta lista também ignora a janela de inscrição de
		// propósito — o docente classifica depois que ela fecha.
		const resposta = await api.GET('/academic/isolated/offerings/', {
			params: { query: { mine: true } }
		});
		const falha = resposta.error;
		if (falha) {
			erro = mensagemDeErro(falha, 'Não foi possível carregar suas disciplinas.');
			carregando = false;
			return;
		}
		ofertas = resposta.data ?? [];
		carregando = false;
	}

	async function abrir(escolhida: Oferta) {
		ofertaId = escolhida.id;
		aviso = '';
		erro = '';
		carregandoCandidatos = true;
		candidatos = [];
		const resposta = await api.GET('/academic/isolated/offerings/{offering_id}/candidates', {
			params: { path: { offering_id: escolhida.id } }
		});
		const falha = resposta.error;
		if (falha) {
			erro = mensagemDeErro(falha, 'Não foi possível carregar os candidatos desta disciplina.');
			carregandoCandidatos = false;
			return;
		}
		// A ordem que chega já é a resposta anterior do docente (sem posição por
		// último); a tela nunca reordena por conta própria.
		candidatos = resposta.data ?? [];
		carregandoCandidatos = false;
	}

	function fechar() {
		ofertaId = null;
		candidatos = [];
	}

	function mover(indice: number, destino: number) {
		if (destino < 0 || destino >= candidatos.length) return;
		const lista = candidatos.slice();
		const [movido] = lista.splice(indice, 1);
		lista.splice(destino, 0, movido);
		candidatos = lista;
		aviso = '';
	}

	async function salvar() {
		if (oferta === null || salvando) return;
		salvando = true;
		erro = '';
		aviso = '';
		// Substituição, e não acréscimo: o corpo é a classificação final da
		// oferta e a posição é o índice da lista (o backend numera 1..N).
		const { data, error } = await api.POST('/academic/isolated/offerings/{offering_id}/rank', {
			params: { path: { offering_id: oferta.id } },
			body: { item_ids: candidatos.map((candidato) => candidato.item_id) }
		});
		salvando = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível salvar a classificação.');
			return;
		}
		candidatos = data;
		aviso = `Classificação de ${oferta.discipline_code} salva.`;
		// A oferta deixa de "faltar classificar" no servidor; recarregar é o que
		// tira o destaque da lista sem refresh manual.
		await carregarOfertas();
	}

	$effect(() => {
		carregarOfertas();
	});
</script>

<svelte:head>
	<title>Classificação dos candidatos · PPGD Manager</title>
</svelte:head>

<header>
	<p class="etiqueta">Disciplina isolada</p>
	<h1 class="text-grafite mt-1 text-2xl font-semibold tracking-tight">Classificação</h1>
	<p class="text-cinza mt-2 text-sm">
		Ordene os inscritos de cada disciplina sua, do primeiro ao último. A secretaria defere seguindo
		esta ordem, até o limite de vagas.
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
{:else if ofertas.length === 0}
	<div class="border-borda bg-papel mt-6 border border-dashed p-10 text-center">
		<p class="text-grafite text-[0.9375rem]">
			Você não tem disciplina oferecida no edital vigente.
		</p>
	</div>
{:else if oferta === null}
	{#if semClassificacao.length > 0}
		<section class="mt-6">
			<h2 class="etiqueta">Falta classificar</h2>
			<ul class="mt-2 space-y-px">
				{#each semClassificacao as item (item.id)}
					<li
						class="bg-papel regua-tinta flex flex-wrap items-center justify-between gap-4 px-5 py-4"
					>
						<div class="min-w-0">
							<p class="text-grafite text-[0.9375rem] font-medium">
								<span class="font-mono">{item.discipline_code}</span>
								{item.discipline_name}
							</p>
							<p class="text-cinza mt-0.5 text-sm">
								{item.seats_available} de {item.seats} vagas livres
							</p>
						</div>
						<button class="botao" type="button" onclick={() => abrir(item)}>Classificar</button>
					</li>
				{/each}
			</ul>
		</section>
	{/if}

	{#if jaClassificadas.length > 0}
		<section class="mt-8">
			<h2 class="etiqueta">Já respondidas</h2>
			<ul class="mt-2 space-y-px">
				{#each jaClassificadas as item (item.id)}
					<li
						class="border-borda flex flex-wrap items-center justify-between gap-4 border-b px-1 py-3"
					>
						<div class="min-w-0">
							<p class="text-grafite text-[0.9375rem]">
								<span class="font-mono">{item.discipline_code}</span>
								{item.discipline_name}
							</p>
							<p class="text-cinza mt-0.5 text-sm">
								{item.seats_available} de {item.seats} vagas livres
							</p>
						</div>
						<button class="botao-discreto" type="button" onclick={() => abrir(item)}>
							Rever ordem
						</button>
					</li>
				{/each}
			</ul>
		</section>
	{/if}
{:else}
	<section class="mt-6">
		<div class="flex flex-wrap items-start justify-between gap-4">
			<div class="min-w-0">
				<p class="text-grafite text-lg font-semibold tracking-tight">
					<span class="font-mono">{oferta.discipline_code}</span>
					{oferta.discipline_name}
				</p>
				<p class="text-cinza mt-1 text-sm">
					{oferta.seats_available} de {oferta.seats} vagas livres. Da posição {corte + 1} em diante, a
					vaga depende de desistência.
				</p>
			</div>
			<button class="botao-discreto" type="button" onclick={fechar}>Voltar às disciplinas</button>
		</div>

		{#if carregandoCandidatos}
			<p class="etiqueta mt-6">Carregando…</p>
		{:else if candidatos.length === 0}
			<div class="border-borda bg-papel mt-6 border border-dashed p-10 text-center">
				<p class="text-grafite text-[0.9375rem]">Nenhum inscrito nesta disciplina.</p>
			</div>
		{:else}
			<!-- Nome, data de inscrição e posição, e nada mais: o docente não tem
			`download_requestdocument` (academic.0011) e classifica por mérito, não
			por pendência administrativa. Link de anexo aqui só levaria a 403. -->
			<ol class="mt-6 space-y-px">
				{#each candidatos as candidato, indice (candidato.item_id)}
					<li
						class="bg-papel regua-tinta flex flex-wrap items-center justify-between gap-4 px-5 py-4"
					>
						<div class="flex min-w-0 items-center gap-4">
							<span class="text-cinza w-6 shrink-0 text-right font-mono text-sm">
								{indice + 1}
							</span>
							<div class="min-w-0">
								<p class="text-grafite text-[0.9375rem] font-medium">{candidato.person_name}</p>
								<p class="text-cinza mt-0.5 text-sm">
									Inscrito em {formatarPrazo(candidato.submitted_at)}
								</p>
							</div>
						</div>
						<div class="flex items-center gap-2">
							<button
								class="botao-discreto"
								type="button"
								disabled={indice === 0 || salvando}
								aria-label="Subir {candidato.person_name}"
								onclick={() => mover(indice, indice - 1)}
							>
								↑
							</button>
							<button
								class="botao-discreto"
								type="button"
								disabled={indice === candidatos.length - 1 || salvando}
								aria-label="Descer {candidato.person_name}"
								onclick={() => mover(indice, indice + 1)}
							>
								↓
							</button>
						</div>
					</li>
					{#if indice + 1 === corte && indice + 1 < candidatos.length}
						<li class="border-tinta text-cinza border-t-2 px-5 py-2 text-sm" aria-hidden="true">
							Limite de vagas
						</li>
					{/if}
				{/each}
			</ol>

			{#if corte === 0}
				<p class="text-cinza mt-3 text-sm">
					Não há vaga livre nesta disciplina: a ordem vale como fila de espera.
				</p>
			{/if}

			<button class="botao mt-6" type="button" disabled={salvando} onclick={salvar}>
				{salvando ? 'Salvando…' : 'Salvar classificação'}
			</button>
		{/if}
	</section>
{/if}
