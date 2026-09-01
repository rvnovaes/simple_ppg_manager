<script lang="ts">
	import { api, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';
	import {
		EXPLICACAO_DA_SITUACAO_DA_ATA,
		ROTULO_DA_SITUACAO_DA_ATA,
		SITUACOES_DA_ATA,
		formatarMomento,
		type SituacaoDaAta
	} from '$lib/selecao';
	import { sessao } from '$lib/sessao.svelte';

	type Ata = components['schemas']['RecordSummaryOut'];
	type Assinatura = components['schemas']['RecordSignatureOut'];
	type Edital = components['schemas']['SelectionProcessOut'];
	type Etapa = components['schemas']['SelectionStageOut'];

	let editais = $state<Edital[]>([]);
	let etapas = $state<Etapa[]>([]);
	let atas = $state<Ata[]>([]);

	let carregando = $state(true);
	let reenviando = $state<number | null>(null);
	let erro = $state('');
	let aviso = $state('');

	// Reenviar o link do externo é o único poder da secretaria sobre a
	// assinatura (`change_recordsignature`, migration 0007). Coordenação e
	// Comissão veem a fila e não reenviam — a checagem que vale é a do
	// backend; esta existe para a tela não oferecer o que dá 403.
	const podeReenviar = $derived(sessao.pode('selection.change_recordsignature'));

	// --- filtros -----------------------------------------------------------

	// O edital é obrigatório na rota (`process_id`), e não por acaso: "as
	// atas do programa" misturaria anos e não responderia a pergunta de
	// ninguém. Enquanto nenhum for escolhido, a tela não consulta.
	let filtroEdital = $state<number | ''>('');
	let filtroEtapa = $state<number | ''>('');
	let filtroSituacao = $state<SituacaoDaAta | ''>('');

	/**
	 * As atas agrupadas por chave (etapa × nível × alvo).
	 *
	 * A listagem devolve **todas as versões** — a retificação guarda a
	 * anterior como `superseded` —, e mostrá-las como linhas irmãs faria
	 * parecer que houve duas bancas. Agrupar é o que deixa a versão vigente
	 * em cima e o histórico recolhido embaixo dela, que é como a secretaria
	 * lê: "esta ata, e o que houve antes".
	 *
	 * O servidor já ordena por etapa, nível, alvo e versão decrescente, então
	 * a primeira de cada grupo é a vigente e a ordem dos grupos é a dele.
	 */
	const grupos = $derived.by<{ chave: string; versoes: Ata[] }[]>(() => {
		const emOrdem: { chave: string; versoes: Ata[] }[] = [];
		const porChave: Record<string, Ata[]> = {};
		for (const ata of atas) {
			const chave = `${ata.stage_id}|${ata.level}|${ata.project_id ?? ''}|${ata.research_line_id ?? ''}`;
			if (porChave[chave] === undefined) {
				porChave[chave] = [ata];
				emOrdem.push({ chave, versoes: porChave[chave] });
			} else {
				porChave[chave].push(ata);
			}
		}
		return emOrdem;
	});

	const pendentes = $derived(
		atas
			.filter((a) => a.status === 'awaiting_signatures')
			.reduce((t, a) => t + a.pending_signatures, 0)
	);

	// --- carregamento ------------------------------------------------------

	async function carregarEditais() {
		const { data, error } = await api.GET('/selection/processes/');
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar os editais do programa.');
			return;
		}
		editais = data?.items ?? [];
	}

	async function carregarEtapas(processId: number) {
		const { data, error } = await api.GET('/selection/processes/{process_id}/stages/', {
			params: { path: { process_id: processId } }
		});
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar as etapas do edital.');
			return;
		}
		etapas = data ?? [];
	}

	/**
	 * Os filtros são lidos aqui, e nunca dentro do `$effect` de montagem:
	 * lê-los lá os tornaria dependência do efeito, e cada troca dispararia
	 * dois carregamentos (mesma armadilha das telas de bancas e inscrições).
	 */
	async function carregarAtas() {
		if (filtroEdital === '') {
			atas = [];
			return;
		}
		const { data, error } = await api.GET('/selection/records/', {
			params: {
				query: {
					process_id: filtroEdital,
					...(filtroEtapa === '' ? {} : { stage_id: filtroEtapa }),
					...(filtroSituacao === '' ? {} : { status: filtroSituacao })
				}
			}
		});
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar as atas deste edital.');
			return;
		}
		atas = data?.items ?? [];
	}

	async function refiltrar() {
		erro = '';
		aviso = '';
		carregando = true;
		await carregarAtas();
		carregando = false;
	}

	/** Trocar de edital invalida a etapa escolhida: ela é filha do edital
	 * anterior, e como filtro não acharia nada. */
	async function trocarEdital() {
		filtroEtapa = '';
		etapas = [];
		erro = '';
		aviso = '';
		carregando = true;
		if (filtroEdital !== '') await carregarEtapas(filtroEdital);
		await carregarAtas();
		carregando = false;
	}

	// --- reenvio do link do examinador externo ------------------------------

	async function reenviar(ata: Ata, assinatura: Assinatura) {
		if (reenviando !== null) return;
		erro = '';
		aviso = '';
		reenviando = assinatura.id;
		const { data, error } = await api.POST(
			'/selection/records/{record_id}/signatures/{signature_id}/resend-token',
			{ params: { path: { record_id: ata.id, signature_id: assinatura.id } } }
		);
		reenviando = null;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível reenviar o link de assinatura.');
			return;
		}
		// A linha é trocada pelo que voltou, e a lista não é recarregada: o
		// reenvio muda uma assinatura só, e recarregar perderia a posição da
		// secretaria numa fila que pode ter dezenas de atas.
		atas = atas.map((a) =>
			a.id === ata.id
				? { ...a, signatures: a.signatures.map((s) => (s.id === data.id ? data : s)) }
				: a
		);
		aviso = `Link reenviado para ${data.signer_name}. O link anterior deixou de valer.`;
	}

	function explicacao(situacao: string): string {
		return EXPLICACAO_DA_SITUACAO_DA_ATA[situacao as SituacaoDaAta] ?? '';
	}

	$effect(() => {
		carregando = true;
		carregarEditais().then(() => {
			carregando = false;
		});
	});
</script>

<svelte:head>
	<title>Atas · PPGD Manager</title>
</svelte:head>

<header>
	<p class="etiqueta">Processo seletivo</p>
	<h1 class="text-grafite mt-1 text-2xl font-semibold tracking-tight">Atas</h1>
	<p class="text-cinza mt-2 text-sm">
		As atas de cada etapa do edital, com quem já assinou e quem falta. Quem lança nota e assina é a
		banca; aqui a secretaria acompanha, reenvia o link do examinador externo e baixa o PDF.
	</p>
</header>

<div class="mt-6 flex flex-wrap items-end gap-3">
	<div>
		<label class="etiqueta mb-1 block" for="filtro-edital">Edital</label>
		<select id="filtro-edital" class="campo w-72" bind:value={filtroEdital} onchange={trocarEdital}>
			<option value="">Escolha um edital</option>
			{#each editais as opcao (opcao.id)}
				<option value={opcao.id}>{opcao.title}</option>
			{/each}
		</select>
	</div>
	<div>
		<label class="etiqueta mb-1 block" for="filtro-etapa">Etapa</label>
		<select
			id="filtro-etapa"
			class="campo w-56"
			bind:value={filtroEtapa}
			onchange={refiltrar}
			disabled={filtroEdital === ''}
		>
			<option value="">Todas</option>
			{#each etapas as opcao (opcao.id)}
				<option value={opcao.id}>{opcao.order}. {opcao.name}</option>
			{/each}
		</select>
	</div>
	<div>
		<label class="etiqueta mb-1 block" for="filtro-situacao">Situação</label>
		<select
			id="filtro-situacao"
			class="campo w-56"
			bind:value={filtroSituacao}
			onchange={refiltrar}
			disabled={filtroEdital === ''}
		>
			<option value="">Todas</option>
			{#each SITUACOES_DA_ATA as opcao (opcao)}
				<option value={opcao}>{ROTULO_DA_SITUACAO_DA_ATA[opcao]}</option>
			{/each}
		</select>
	</div>
</div>

{#if erro}
	<p class="aviso-erro mt-6" role="alert">{erro}</p>
{/if}

{#if aviso}
	<p class="etiqueta mt-6" role="status">{aviso}</p>
{/if}

{#if carregando}
	<p class="etiqueta mt-6">Carregando…</p>
{:else if filtroEdital === ''}
	<div class="border-borda bg-papel mt-6 border border-dashed p-10 text-center">
		<p class="text-grafite text-[0.9375rem]">Escolha um edital para ver as atas.</p>
		<p class="text-cinza mt-1 text-sm">
			Cada edital tem uma ata por etapa, nível e alvo — e é sempre de um edital que se fala.
		</p>
	</div>
{:else if atas.length === 0}
	<div class="border-borda bg-papel mt-6 border border-dashed p-10 text-center">
		<p class="text-grafite text-[0.9375rem]">Nenhuma ata com estes filtros.</p>
		<p class="text-cinza mt-1 text-sm">
			A ata nasce quando a banca a monta, com as notas já lançadas na etapa.
		</p>
	</div>
{:else}
	{#if pendentes > 0}
		<p class="text-cinza mt-6 text-sm">
			{pendentes} assinatura(s) pendente(s) neste edital.
		</p>
	{/if}

	<ul class="mt-6 space-y-px">
		{#each grupos as grupo (grupo.chave)}
			{@const ata = grupo.versoes[0]}
			{@const anteriores = grupo.versoes.slice(1)}
			<li
				class="bg-papel regua-tinta px-5 py-4"
				style:border-left-color={ata.status === 'signed'
					? 'var(--color-tinta)'
					: 'var(--color-carimbo)'}
			>
				<div class="flex flex-wrap items-center justify-between gap-4">
					<div class="min-w-0">
						<p class="text-grafite text-[0.9375rem] font-medium">
							{ata.stage_name} · {ata.level_label} · {ata.target_label || '—'}
						</p>
						<p class="text-cinza mt-0.5 text-sm">
							Versão {ata.version} · congelada em {formatarMomento(ata.frozen_at)} · assinada em {formatarMomento(
								ata.signed_at
							)}
						</p>
					</div>
					<div class="flex items-center gap-4">
						<span class="etiqueta">{ata.status_label}</span>
						{#if ata.has_pdf}
							<!-- Endereço da API, e não rota da SPA: o PDF sai pelo Django
							(o MEDIA não é servido direto) e a leitura é auditada, então
							`resolve()` não se aplica. Continua relativo — origem única
							(ADR-004). -->
							<!-- eslint-disable svelte/no-navigation-without-resolve -->
							<a class="botao-discreto shrink-0" href="/api/v1/selection/records/{ata.id}/pdf">
								Baixar PDF
							</a>
							<!-- eslint-enable svelte/no-navigation-without-resolve -->
						{/if}
					</div>
				</div>
				<p class="text-cinza mt-1 text-sm">{explicacao(ata.status)}</p>

				{#if ata.status !== 'draft' && !ata.hash_ok}
					<p class="aviso-erro mt-3" role="alert">
						O conteúdo gravado não bate mais com o hash assinado. Não use este PDF sem falar com
						quem preside a banca.
					</p>
				{/if}

				{#if ata.replaced_member_name}
					<p class="text-cinza mt-1 text-sm">
						Titular impedido: {ata.replaced_member_name} — o suplente assina no lugar.
					</p>
				{/if}

				{#if ata.signatures.length > 0}
					<div class="border-borda mt-4 border-t pt-3">
						<h2 class="etiqueta">Assinaturas · {ata.pending_signatures} pendente(s)</h2>
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
													· <span class="font-mono text-xs">{assinatura.signed_hash_prefix}</span>
												{/if}
											{:else if assinatura.method === 'token'}
												· link enviado em {formatarMomento(assinatura.token_sent_at)} · vence em {formatarMomento(
													assinatura.token_expires_at
												)}
											{/if}
										</p>
									</div>
									<div class="flex shrink-0 items-center gap-3">
										<span class="etiqueta">{assinatura.signed ? 'Assinada' : 'Pendente'}</span>
										{#if podeReenviar && !assinatura.signed && assinatura.method === 'token' && ata.status === 'awaiting_signatures'}
											<button
												class="botao-discreto"
												type="button"
												disabled={reenviando !== null}
												onclick={() => reenviar(ata, assinatura)}
											>
												{reenviando === assinatura.id ? 'Reenviando…' : 'Reenviar link'}
											</button>
										{/if}
									</div>
								</li>
							{/each}
						</ul>
					</div>
				{/if}

				{#if anteriores.length > 0}
					<div class="border-borda mt-4 border-t pt-3">
						<h2 class="etiqueta">Versões anteriores</h2>
						<ul class="mt-2 space-y-px">
							{#each anteriores as antiga (antiga.id)}
								<li
									class="border-borda flex flex-wrap items-center justify-between gap-4 border-b py-2 last:border-0"
								>
									<p class="text-cinza text-sm">
										Versão {antiga.version} · {antiga.status_label} · assinada em {formatarMomento(
											antiga.signed_at
										)}
									</p>
									{#if antiga.has_pdf}
										<!-- eslint-disable svelte/no-navigation-without-resolve -->
										<a
											class="botao-discreto shrink-0"
											href="/api/v1/selection/records/{antiga.id}/pdf"
										>
											Baixar PDF
										</a>
										<!-- eslint-enable svelte/no-navigation-without-resolve -->
									{/if}
								</li>
							{/each}
						</ul>
					</div>
				{/if}
			</li>
		{/each}
	</ul>
{/if}
