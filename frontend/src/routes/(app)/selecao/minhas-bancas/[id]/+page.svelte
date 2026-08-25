<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { api, codigoDeErro, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';
	import {
		EXPLICACAO_DA_SITUACAO_DA_ATA,
		PAPEIS_DA_BANCA,
		ehAContaLogada,
		formatarMomento,
		formatarNota,
		rotuloDoExaminador,
		type SituacaoDaAta
	} from '$lib/selecao';
	import { sessao } from '$lib/sessao.svelte';

	type MinhaBanca = components['schemas']['MyBoardOut'];
	type Etapa = components['schemas']['BoardStageOut'];
	type Nota = components['schemas']['StageScoreOut'];
	type Ata = components['schemas']['ExaminationRecordOut'];
	type NotaEnviada = components['schemas']['StageScoreIn'];

	const id = $derived(Number(page.params.id));

	let banca = $state<MinhaBanca | null>(null);
	let etapaId = $state<number | ''>('');
	let planilha = $state<Nota[]>([]);
	/**
	 * O que o usuário digitou, por inscrição — vazio enquanto ele não mexe.
	 *
	 * A nota é **texto** de ponta a ponta: a API a devolve como string (é
	 * `Decimal` no banco) e a aceita como string, então convertê-la para
	 * `number` no meio do caminho só perderia a casa decimal exata.
	 */
	let rascunho = $state<Record<number, { score: string; absent: boolean }>>({});
	let ata = $state<Ata | null>(null);
	/** A etapa foi consultada e a ata ainda não existe (404 do `record`). */
	let semAta = $state(false);

	let carregando = $state(true);
	let carregandoEtapa = $state(false);
	let salvando = $state(false);
	let mexendoNaAta = $state(false);
	let erro = $state('');
	let aviso = $state('');
	/** Confirmação em dois passos de congelar e reabrir — ver `(app)/selecao/editais`. */
	let confirmando = $state<'freeze' | 'reopen' | ''>('');
	let impedidoId = $state<number | ''>('');

	const pessoas = $derived(sessao.usuario?.people ?? []);
	const etapa = $derived<Etapa | null>(banca?.stages.find((e) => e.id === etapaId) ?? null);

	// --- quem sou eu nesta banca -------------------------------------------

	// Dica de tela, e não autorização (ver `ehAContaLogada`): quando o nome
	// não casa com nenhum dos quatro lugares, `papelDesconhecido` fica
	// verdadeiro e a tela oferece TODAS as ações — quem recusa é o backend,
	// com `not_the_board_president`/`not_a_titular_member`/`not_the_signer`.
	const meuPapel = $derived.by(() => {
		const daBanca = banca;
		if (daBanca === null) return null;
		return PAPEIS_DA_BANCA.find((p) => ehAContaLogada(daBanca[p.campo].full_name, pessoas)) ?? null;
	});
	const papelDesconhecido = $derived(banca !== null && meuPapel === null);
	const souPresidente = $derived(meuPapel?.campo === 'president' || papelDesconhecido);
	const souTitular = $derived(meuPapel?.campo !== 'alternate' || papelDesconhecido);

	/** A minha linha na lista de signatários da ata congelada, se houver. */
	const minhaAssinatura = $derived(
		ata?.signatures.find((a) => ehAContaLogada(a.signer_name, pessoas)) ?? null
	);

	// --- carregamento ------------------------------------------------------

	/**
	 * A banca sai de `boards/mine`, e não de `boards/{id}`.
	 *
	 * Duas razões, e as duas importam: é `mine` que embute as etapas (o
	 * Docente não tem `view_selectionstage`), e é ela que já responde
	 * "esta banca é sua" sem a tela precisar interpretar um 403.
	 */
	async function carregarBanca(boardId: number) {
		const { data, error } = await api.GET('/selection/boards/mine');
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar as suas bancas.');
			return;
		}
		banca = (data ?? []).find((b) => b.id === boardId) ?? null;
		if (banca === null) {
			erro = 'Esta banca não existe ou você não a compõe.';
			return;
		}
		etapaId = banca.stages[0]?.id ?? '';
	}

	async function carregarEtapa() {
		if (banca === null || etapaId === '') {
			planilha = [];
			ata = null;
			semAta = false;
			return;
		}
		carregandoEtapa = true;
		const caminho = { board_id: banca.id, stage_id: etapaId };
		const [
			{ data: dadosDasNotas, error: erroDasNotas },
			{ data: dadosDaAta, error: erroDaAta, response: respostaDaAta }
		] = await Promise.all([
			api.GET('/selection/boards/{board_id}/stages/{stage_id}/scores', {
				params: { path: caminho }
			}),
			api.GET('/selection/boards/{board_id}/stages/{stage_id}/record', {
				params: { path: caminho }
			})
		]);
		carregandoEtapa = false;

		if (dadosDasNotas === undefined) {
			erro = mensagemDeErro(erroDasNotas, 'Não foi possível carregar as notas da etapa.');
			planilha = [];
		} else {
			planilha = dadosDasNotas;
			rascunho = {};
		}

		// 404 aqui não é falha: é como a API diz "esta etapa ainda não tem
		// ata" (ver `_ata_corrente` no router). Qualquer outro status é erro.
		if (respostaDaAta.status === 404) {
			ata = null;
			semAta = true;
		} else if (dadosDaAta === undefined) {
			erro = mensagemDeErro(erroDaAta, 'Não foi possível carregar a ata da etapa.');
			ata = null;
			semAta = false;
		} else {
			ata = dadosDaAta;
			semAta = false;
		}
		impedidoId = ata?.replaced_member_id ?? '';
	}

	async function trocarEtapa() {
		erro = '';
		aviso = '';
		confirmando = '';
		await carregarEtapa();
	}

	$effect(() => {
		const boardId = id;
		carregando = true;
		carregarBanca(boardId)
			.then(() => carregarEtapa())
			.then(() => {
				carregando = false;
			});
	});

	// --- lançamento de notas -----------------------------------------------

	function valor(linha: Nota): { score: string; absent: boolean } {
		return rascunho[linha.application_id] ?? { score: linha.score ?? '', absent: linha.absent };
	}

	function editar(linha: Nota, mudanca: Partial<{ score: string; absent: boolean }>) {
		const atual = valor(linha);
		const novo = { ...atual, ...mudanca };
		// Ausente e nota são exclusivos no model (check `absent XOR score`):
		// marcar a caixa apaga o que estava digitado, em vez de mandar os
		// dois e colher `absent_xor_score` do servidor.
		if (novo.absent) novo.score = '';
		rascunho = { ...rascunho, [linha.application_id]: novo };
	}

	function mudou(linha: Nota): boolean {
		const atual = valor(linha);
		return atual.score !== (linha.score ?? '') || atual.absent !== linha.absent;
	}

	const alteradas = $derived(planilha.filter(mudou));

	async function salvarNotas() {
		if (banca === null || etapaId === '' || salvando || alteradas.length === 0) return;
		// Validação de UX; a que vale é o check do model. Sem nota e sem
		// ausência não há o que gravar — a API não apaga nota lançada.
		const vazias = alteradas.filter((l) => {
			const v = valor(l);
			return !v.absent && v.score.trim() === '';
		});
		if (vazias.length > 0) {
			erro = `Informe a nota ou marque a ausência de: ${vazias.map((l) => l.full_name).join(', ')}.`;
			return;
		}
		erro = '';
		aviso = '';
		salvando = true;
		const corpo: NotaEnviada[] = alteradas.map((linha) => {
			const v = valor(linha);
			return {
				application_id: linha.application_id,
				score: v.absent ? null : v.score.trim(),
				absent: v.absent
			};
		});
		const { data, error } = await api.PUT('/selection/boards/{board_id}/stages/{stage_id}/scores', {
			params: { path: { board_id: banca.id, stage_id: etapaId } },
			body: corpo
		});
		salvando = false;
		if (error || !data) {
			erro =
				codigoDeErro(error) === 'record_frozen'
					? mensagemDeErro(
							error,
							'A ata desta etapa já foi congelada: as notas viraram só leitura.'
						)
					: mensagemDeErro(error, 'Não foi possível gravar as notas.');
			return;
		}
		planilha = data;
		rascunho = {};
		aviso = `${corpo.length} nota(s) gravada(s).`;
	}

	// --- ciclo da ata ------------------------------------------------------

	function aplicar(atualizada: Ata | undefined, mensagem: string) {
		if (!atualizada) return;
		ata = atualizada;
		semAta = false;
		impedidoId = atualizada.replaced_member_id ?? '';
		aviso = mensagem;
	}

	async function gerarAta() {
		if (banca === null || etapaId === '' || mexendoNaAta) return;
		erro = '';
		aviso = '';
		mexendoNaAta = true;
		const { data, error } = await api.POST(
			'/selection/boards/{board_id}/stages/{stage_id}/record',
			{ params: { path: { board_id: banca.id, stage_id: etapaId } } }
		);
		mexendoNaAta = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível gerar a ata desta etapa.');
			return;
		}
		aplicar(data, 'Ata aberta em rascunho com as notas já lançadas.');
	}

	async function atualizarAta() {
		if (banca === null || etapaId === '' || mexendoNaAta) return;
		erro = '';
		aviso = '';
		mexendoNaAta = true;
		const { data, error } = await api.POST(
			'/selection/boards/{board_id}/stages/{stage_id}/record/refresh',
			{ params: { path: { board_id: banca.id, stage_id: etapaId } } }
		);
		mexendoNaAta = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível atualizar a ata.');
			return;
		}
		aplicar(data, 'Ata regerada com as notas de agora.');
	}

	async function congelarAta() {
		if (banca === null || etapaId === '' || mexendoNaAta) return;
		erro = '';
		aviso = '';
		confirmando = '';
		mexendoNaAta = true;
		const { data, error } = await api.POST(
			'/selection/boards/{board_id}/stages/{stage_id}/record/freeze',
			{
				params: { path: { board_id: banca.id, stage_id: etapaId } },
				body: { replaced_member_id: impedidoId === '' ? null : impedidoId }
			}
		);
		mexendoNaAta = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível congelar a ata.');
			return;
		}
		aplicar(data, 'Ata congelada. Os examinadores externos receberam o link por e-mail.');
	}

	async function reabrirAta() {
		if (banca === null || etapaId === '' || mexendoNaAta) return;
		erro = '';
		aviso = '';
		confirmando = '';
		mexendoNaAta = true;
		const { data, error } = await api.POST(
			'/selection/boards/{board_id}/stages/{stage_id}/record/reopen',
			{ params: { path: { board_id: banca.id, stage_id: etapaId } } }
		);
		mexendoNaAta = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível reabrir a ata.');
			return;
		}
		aplicar(data, 'Ata reaberta: as notas voltaram a ser editáveis.');
		await carregarEtapa();
	}

	async function assinarAta() {
		if (banca === null || etapaId === '' || ata === null || mexendoNaAta) return;
		erro = '';
		aviso = '';
		mexendoNaAta = true;
		// Manda o hash que ESTA tela mostrou: se o presidente reabriu e
		// recongelou entre a leitura e o clique, o servidor devolve
		// `record_changed` em vez de colher assinatura sobre texto velho.
		const { data, error } = await api.POST(
			'/selection/boards/{board_id}/stages/{stage_id}/record/sign',
			{
				params: { path: { board_id: banca.id, stage_id: etapaId } },
				body: { content_hash: ata.content_hash }
			}
		);
		mexendoNaAta = false;
		if (error || !data) {
			erro =
				codigoDeErro(error) === 'record_changed'
					? mensagemDeErro(
							error,
							'A ata mudou depois que esta tela a leu. Recarregue antes de assinar.'
						)
					: mensagemDeErro(error, 'Não foi possível assinar a ata.');
			return;
		}
		aplicar(
			data,
			data.status === 'signed'
				? 'Ata assinada por todos: os desfechos da etapa foram aplicados.'
				: 'Assinatura registrada.'
		);
		// A última assinatura fecha a etapa e muda os desfechos das
		// inscrições; a planilha ao lado precisa refletir isso.
		if (data.status === 'signed') await carregarEtapa();
	}

	// --- resumo da etapa fechada -------------------------------------------

	const promovidos = $derived(ata?.content.filter((l) => l.passed) ?? []);
	const eliminados = $derived(ata?.content.filter((l) => !l.passed) ?? []);

	function explicacao(situacao: SituacaoDaAta): string {
		return EXPLICACAO_DA_SITUACAO_DA_ATA[situacao];
	}
</script>

<svelte:head>
	<title>{banca ? `${banca.level_label} · ${banca.target_label}` : 'Banca'} · PPGD Manager</title>
</svelte:head>

<a class="etiqueta hover:text-tinta" href={resolve('/(app)/selecao/minhas-bancas')}>
	← Minhas bancas
</a>

{#if erro}
	<p class="aviso-erro mt-6" role="alert">{erro}</p>
{/if}

{#if aviso}
	<p class="etiqueta mt-6" role="status">{aviso}</p>
{/if}

{#if carregando}
	<p class="etiqueta mt-6">Carregando…</p>
{:else if banca !== null}
	<header class="mt-4">
		<p class="etiqueta">{banca.process_title}</p>
		<h1 class="text-grafite mt-1 text-2xl font-semibold tracking-tight">
			{banca.level_label} · {banca.target_label || '—'}
		</h1>
		{#if meuPapel}
			<p class="text-cinza mt-2 text-sm">Você compõe esta banca como {meuPapel.rotulo}.</p>
		{/if}
	</header>

	<dl class="bg-papel mt-4 grid gap-x-6 gap-y-1 px-5 py-4 sm:grid-cols-2 lg:grid-cols-4">
		{#each PAPEIS_DA_BANCA as papel (papel.campo)}
			<div>
				<dt class="etiqueta">{papel.rotulo}</dt>
				<dd class="text-grafite text-[0.8125rem]">{rotuloDoExaminador(banca[papel.campo])}</dd>
			</div>
		{/each}
	</dl>

	{#if banca.stages.length === 0}
		<div class="border-borda bg-papel mt-6 border border-dashed p-10 text-center">
			<p class="text-grafite text-[0.9375rem]">Este edital ainda não tem etapas.</p>
			<p class="text-cinza mt-1 text-sm">Quem as cria é a secretaria, na tela de editais.</p>
		</div>
	{:else}
		<div class="mt-6 flex flex-wrap items-end gap-3">
			<div>
				<label class="etiqueta mb-1 block" for="etapa">Etapa</label>
				<select id="etapa" class="campo w-80" bind:value={etapaId} onchange={trocarEtapa}>
					{#each banca.stages as opcao (opcao.id)}
						<option value={opcao.id}>{opcao.order}. {opcao.name}</option>
					{/each}
				</select>
			</div>
			{#if etapa !== null}
				<p class="text-cinza pb-2 text-sm">
					Sessão: {formatarMomento(etapa.session_at)}{#if etapa.location}
						· {etapa.location}{/if}
				</p>
			{/if}
		</div>

		{#if carregandoEtapa}
			<p class="etiqueta mt-6">Carregando a etapa…</p>
		{:else}
			<!-- Notas ------------------------------------------------------ -->
			<section class="mt-8">
				<h2 class="text-grafite text-lg font-semibold tracking-tight">Notas da etapa</h2>
				<p class="text-cinza mt-1 text-sm">
					A planilha nasce das inscrições vivas do recorte desta banca — quem ainda não foi avaliado
					aparece sem nota.
				</p>

				{#if planilha.length === 0}
					<div class="border-borda bg-papel mt-4 border border-dashed p-10 text-center">
						<p class="text-grafite text-[0.9375rem]">Nenhuma inscrição viva neste recorte.</p>
					</div>
				{:else}
					{@const congelada = ata !== null && ata.status !== 'draft'}
					<div class="bg-papel mt-4 overflow-x-auto">
						<table class="w-full text-sm">
							<thead>
								<tr class="border-borda border-b">
									<th class="etiqueta px-4 py-2 text-left">Candidato</th>
									<th class="etiqueta px-4 py-2 text-left">Categoria</th>
									<th class="etiqueta px-4 py-2 text-left">Nota</th>
									<th class="etiqueta px-4 py-2 text-left">Ausente</th>
									<th class="etiqueta px-4 py-2 text-left">Lançada por</th>
								</tr>
							</thead>
							<tbody>
								{#each planilha as linha (linha.application_id)}
									{@const v = valor(linha)}
									<tr class="border-borda border-b last:border-0">
										<td class="px-4 py-2">
											<span class="text-grafite">{linha.full_name}</span>
											<span class="text-cinza ml-2 font-mono text-xs">{linha.protocol}</span>
										</td>
										<td class="text-cinza px-4 py-2">{linha.quota_category_label}</td>
										<td class="px-4 py-2">
											<input
												class="campo w-24"
												inputmode="decimal"
												aria-label="Nota de {linha.full_name}"
												value={v.score}
												disabled={congelada || v.absent || salvando}
												oninput={(e) => editar(linha, { score: e.currentTarget.value })}
											/>
											{#if linha.scored && !linha.absent}
												<span class="text-cinza ml-2 text-xs">
													{linha.passed ? 'aprovado' : 'abaixo do corte'}
												</span>
											{/if}
										</td>
										<td class="px-4 py-2">
											<input
												type="checkbox"
												aria-label="Ausente: {linha.full_name}"
												checked={v.absent}
												disabled={congelada || salvando}
												onchange={(e) => editar(linha, { absent: e.currentTarget.checked })}
											/>
										</td>
										<td class="text-cinza px-4 py-2">
											{linha.entered_by || '—'}
											{#if linha.entered_at}
												<span class="block text-xs">{formatarMomento(linha.entered_at)}</span>
											{/if}
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>

					{#if congelada}
						<p class="text-cinza mt-3 text-sm">
							A ata desta etapa está {ata === null ? '' : ata.status_label.toLowerCase()}: as notas
							são só leitura (o hash que os examinadores assinam cobre esta fotografia).
						</p>
					{:else}
						<div class="mt-4 flex flex-wrap items-center gap-3">
							<button
								class="botao"
								type="button"
								disabled={salvando || alteradas.length === 0}
								onclick={salvarNotas}
							>
								{salvando ? 'Gravando…' : 'Salvar notas'}
							</button>
							<span class="text-cinza text-sm">
								{alteradas.length === 0
									? 'Nada alterado.'
									: `${alteradas.length} linha(s) alterada(s).`}
							</span>
						</div>
					{/if}
				{/if}
			</section>

			<!-- Ata --------------------------------------------------------- -->
			<section class="mt-10">
				<h2 class="text-grafite text-lg font-semibold tracking-tight">Ata da etapa</h2>

				{#if semAta}
					<div class="border-borda bg-papel mt-4 border border-dashed p-10 text-center">
						<p class="text-grafite text-[0.9375rem]">Esta etapa ainda não tem ata.</p>
						<p class="text-cinza mt-1 text-sm">
							Gerar abre o rascunho com as notas já lançadas; ele pode ser atualizado quantas vezes
							for preciso antes de congelar.
						</p>
						{#if souTitular}
							<button class="botao mt-4" type="button" disabled={mexendoNaAta} onclick={gerarAta}>
								{mexendoNaAta ? 'Gerando…' : 'Gerar ata'}
							</button>
						{:else}
							<p class="text-cinza mt-4 text-sm">
								Quem monta a ata são os três titulares da banca.
							</p>
						{/if}
					</div>
				{:else if ata !== null}
					<div class="bg-papel regua-tinta mt-4 px-5 py-4">
						<div class="flex flex-wrap items-center justify-between gap-4">
							<div>
								<p class="text-grafite text-[0.9375rem] font-medium">
									{ata.stage_name} · versão {ata.version}
								</p>
								<p class="text-cinza mt-0.5 text-sm">{explicacao(ata.status)}</p>
							</div>
							<span class="etiqueta">{ata.status_label}</span>
						</div>

						<dl class="mt-4 grid gap-x-6 gap-y-1 sm:grid-cols-2 lg:grid-cols-4">
							<div>
								<dt class="etiqueta">Congelada em</dt>
								<dd class="text-grafite text-[0.8125rem]">{formatarMomento(ata.frozen_at)}</dd>
							</div>
							<div>
								<dt class="etiqueta">Assinada em</dt>
								<dd class="text-grafite text-[0.8125rem]">{formatarMomento(ata.signed_at)}</dd>
							</div>
							<div>
								<dt class="etiqueta">Titular impedido</dt>
								<dd class="text-grafite text-[0.8125rem]">{ata.replaced_member_name || '—'}</dd>
							</div>
							<div>
								<dt class="etiqueta">Conferência do texto</dt>
								<dd class="text-grafite text-[0.8125rem]">
									{#if ata.content_hash === ''}
										—
									{:else}
										<span class="font-mono">{ata.content_hash.slice(0, 12)}</span>
										· {ata.hash_ok ? 'confere' : 'NÃO confere'}
									{/if}
								</dd>
							</div>
						</dl>

						{#if ata.content.length === 0}
							<p class="text-cinza mt-4 text-sm">A ata ainda não tem linhas.</p>
						{:else}
							<div class="mt-4 overflow-x-auto">
								<table class="w-full text-sm">
									<thead>
										<tr class="border-borda border-b">
											<th class="etiqueta px-4 py-2 text-left">Candidato</th>
											<th class="etiqueta px-4 py-2 text-left">Protocolo</th>
											<th class="etiqueta px-4 py-2 text-left">Categoria</th>
											<th class="etiqueta px-4 py-2 text-left">Nota</th>
											<th class="etiqueta px-4 py-2 text-left">Desfecho</th>
										</tr>
									</thead>
									<tbody>
										{#each ata.content as linha (linha.application_id)}
											<tr class="border-borda border-b last:border-0">
												<td class="text-grafite px-4 py-2">{linha.full_name}</td>
												<td class="text-cinza px-4 py-2 font-mono text-xs">{linha.protocol}</td>
												<td class="text-cinza px-4 py-2">{linha.quota_category}</td>
												<td class="text-grafite px-4 py-2">
													{formatarNota(linha.score, linha.absent)}
												</td>
												<td class="px-4 py-2" class:text-carimbo={!linha.passed}>
													{linha.passed ? 'Promovido' : 'Eliminado'}
												</td>
											</tr>
										{/each}
									</tbody>
								</table>
							</div>
						{/if}

						{#if ata.status === 'signed'}
							<p class="text-cinza mt-4 text-sm">
								Etapa fechada: {promovidos.length} promovido(s) e {eliminados.length} eliminado(s).
								{#if ata.has_pdf}
									O PDF da ata foi gravado e fica disponível na tela de
									<a class="text-tinta underline" href={resolve('/(app)/selecao/atas')}>atas</a>.
								{/if}
							</p>
						{/if}

						<!-- Ações do rascunho -->
						{#if ata.status === 'draft'}
							<div class="border-borda mt-6 border-t pt-4">
								<div class="flex flex-wrap items-center gap-3">
									{#if souTitular}
										<button
											class="botao-discreto"
											type="button"
											disabled={mexendoNaAta}
											onclick={atualizarAta}
										>
											Atualizar com as notas de agora
										</button>
									{/if}
									{#if souPresidente}
										<div>
											<label class="etiqueta mb-1 block" for="impedido">
												Titular impedido (o suplente assina no lugar)
											</label>
											<select id="impedido" class="campo w-72" bind:value={impedidoId}>
												<option value="">Nenhum</option>
												{#each PAPEIS_DA_BANCA.filter((p) => p.campo !== 'alternate') as papel (papel.campo)}
													<option value={banca[papel.campo].id}>
														{papel.rotulo} · {banca[papel.campo].full_name}
													</option>
												{/each}
											</select>
										</div>
										{#if confirmando === 'freeze'}
											<button
												class="botao"
												type="button"
												disabled={mexendoNaAta}
												onclick={congelarAta}
											>
												{mexendoNaAta ? 'Congelando…' : 'Confirmar o congelamento'}
											</button>
											<button
												class="botao-discreto"
												type="button"
												onclick={() => (confirmando = '')}
											>
												Cancelar
											</button>
										{:else}
											<button
												class="botao"
												type="button"
												disabled={mexendoNaAta}
												onclick={() => (confirmando = 'freeze')}
											>
												Congelar para assinatura
											</button>
										{/if}
									{/if}
								</div>
								{#if souPresidente}
									<p class="text-cinza mt-2 text-sm">
										Congelar é o ponto sem volta editorial da etapa: as notas viram só leitura e
										cada examinador passa a assinar exatamente este texto.
									</p>
								{:else}
									<p class="text-cinza mt-2 text-sm">Quem congela a ata é o presidente da banca.</p>
								{/if}
							</div>
						{/if}

						<!-- Assinaturas -->
						{#if ata.status !== 'draft'}
							<div class="border-borda mt-6 border-t pt-4">
								<h3 class="etiqueta">
									Assinaturas · {ata.pending_signatures} pendente(s)
								</h3>
								<ul class="mt-2 space-y-px">
									{#each ata.signatures as assinatura (assinatura.id)}
										<li
											class="border-borda flex flex-wrap items-center justify-between gap-4 border-b py-2 last:border-0"
										>
											<div class="min-w-0">
												<p class="text-grafite text-[0.9375rem]">
													{assinatura.signer_name}
													{#if assinatura.signer_institution}
														<span class="text-cinza">· {assinatura.signer_institution}</span>
													{/if}
												</p>
												<p class="text-cinza mt-0.5 text-sm">
													{assinatura.method_label}
													{#if assinatura.signed}
														· assinada em {formatarMomento(assinatura.signed_at)}
														{#if assinatura.signed_hash_prefix}
															· <span class="font-mono text-xs"
																>{assinatura.signed_hash_prefix}</span
															>
														{/if}
													{:else if assinatura.method === 'token'}
														· link enviado em {formatarMomento(assinatura.token_sent_at)} · vence em {formatarMomento(
															assinatura.token_expires_at
														)}
													{/if}
												</p>
											</div>
											<span class="etiqueta">
												{assinatura.signed ? 'Assinada' : 'Pendente'}
											</span>
										</li>
									{/each}
								</ul>

								{#if ata.status === 'awaiting_signatures'}
									<div class="mt-4 flex flex-wrap items-center gap-3">
										{#if minhaAssinatura !== null && minhaAssinatura.signed}
											<p class="text-cinza text-sm">
												Você assinou esta ata em {formatarMomento(minhaAssinatura.signed_at)}.
											</p>
										{:else if minhaAssinatura !== null || papelDesconhecido}
											<button
												class="botao"
												type="button"
												disabled={mexendoNaAta}
												onclick={assinarAta}
											>
												{mexendoNaAta ? 'Assinando…' : 'Assinar a ata'}
											</button>
										{:else}
											<p class="text-cinza text-sm">
												Você não está na lista de signatários desta ata.
											</p>
										{/if}

										{#if souPresidente}
											{#if confirmando === 'reopen'}
												<button
													class="botao-discreto"
													type="button"
													disabled={mexendoNaAta}
													onclick={reabrirAta}
												>
													Confirmar a reabertura
												</button>
												<button
													class="botao-discreto"
													type="button"
													onclick={() => (confirmando = '')}
												>
													Cancelar
												</button>
											{:else}
												<button
													class="botao-discreto"
													type="button"
													disabled={mexendoNaAta}
													onclick={() => (confirmando = 'reopen')}
												>
													Reabrir a ata
												</button>
											{/if}
										{/if}
									</div>
									{#if souPresidente}
										<p class="text-cinza mt-2 text-sm">
											Reabrir apaga as assinaturas ainda pendentes e devolve as notas à edição;
											depois da primeira assinatura dada, o caminho é retificar.
										</p>
									{/if}
								{/if}
							</div>
						{/if}
					</div>
				{/if}
			</section>
		{/if}
	{/if}
{/if}
