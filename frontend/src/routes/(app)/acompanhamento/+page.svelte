<script lang="ts">
	import { api, comoFormData, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';
	import {
		ORDEM_DO_EDITAL,
		ROTULO_DA_SITUACAO,
		ROTULO_DO_DOCUMENTO,
		ROTULO_DO_PAGAMENTO,
		formatarPrazo,
		formatarTamanho,
		type TipoDeDocumento
	} from '$lib/isolada';

	type Requerimento = components['schemas']['IsolatedRequestOut'];
	type Documento = components['schemas']['RequestDocumentOut'];

	let requerimentos = $state<Requerimento[]>([]);
	let documentos = $state<Documento[]>([]);
	let carregando = $state(true);
	let erro = $state('');
	let enviando = $state(false);

	// Recurso: texto obrigatório e anexo opcional (quem contesta a nota do
	// docente não tem o que juntar). O par tipo+arquivo viaja inteiro ou não
	// viaja — o backend recusa metade com `incomplete_document`.
	let textoDoRecurso = $state('');
	let tipoDoAnexo = $state<TipoDeDocumento | ''>('');
	let arquivoDoRecurso = $state<File | null>(null);

	// O rascunho é assunto da tela de inscrição; aqui só o que já foi
	// enviado. Um requerimento por ciclo, e o mais recente é o do edital
	// corrente.
	const requerimento = $derived(
		requerimentos
			.filter((r) => r.status !== 'draft')
			.sort((a, b) => b.created_at.localeCompare(a.created_at))[0] ?? null
	);

	const situacao = $derived(
		requerimento === null ? '' : (ROTULO_DA_SITUACAO[requerimento.status] ?? requerimento.status)
	);

	const comprovante = $derived(documentos.find((d) => d.kind === 'payment_receipt') ?? null);

	/**
	 * Por que a taxa não pode ser paga agora — ou string vazia, quando pode.
	 *
	 * As razões são as mesmas que `register_payment()` cobraria no backend;
	 * dizê-las antes evita o 4xx depois do clique. O isento sai daqui pela
	 * porta da frente: para ele não existe controle de envio nenhum.
	 */
	const impedimentoDoPagamento = $derived.by(() => {
		if (requerimento === null) return 'Sem requerimento.';
		if (requerimento.status === 'enrolled') {
			return 'A matrícula já foi efetivada: não há mais o que enviar.';
		}
		if (requerimento.status !== 'deferred') {
			return 'O comprovante da GRU só é aceito depois do deferimento.';
		}
		if (!requerimento.payment_open) {
			return `O prazo de pagamento encerrou em ${formatarPrazo(requerimento.payment_closes_at)}.`;
		}
		return '';
	});

	/** Idem para o recurso: estado, janela e recurso já interposto. */
	const impedimentoDoRecurso = $derived.by(() => {
		if (requerimento === null) return 'Sem requerimento.';
		if (requerimento.status !== 'rejected') return 'Só requerimento indeferido tem recurso.';
		if (requerimento.appealed_at !== null) return 'ja-recorreu';
		if (!requerimento.appeal_open) {
			return `A janela de recurso vai de ${formatarPrazo(requerimento.appeal_opens_at)} a ${formatarPrazo(requerimento.appeal_closes_at)} e não está aberta agora.`;
		}
		return '';
	});

	async function carregarDocumentos(requerimentoId: number) {
		const { data, error } = await api.GET('/academic/isolated/requests/{request_id}/documents', {
			params: { path: { request_id: requerimentoId } }
		});
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar seus anexos.');
			return;
		}
		documentos = data ?? [];
	}

	async function carregar() {
		carregando = true;
		erro = '';
		const resposta = await api.GET('/academic/isolated/requests/');
		// A falha sai do objeto ANTES do `if`: a rota não declara resposta de
		// erro no OpenAPI e dentro do bloco o objeto inteiro vira `never`.
		const falha = resposta.error;
		if (falha) {
			erro = mensagemDeErro(falha, 'Não foi possível carregar sua inscrição.');
			carregando = false;
			return;
		}
		requerimentos = resposta.data?.items ?? [];
		const meu = requerimentos
			.filter((r) => r.status !== 'draft')
			.sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
		if (meu) await carregarDocumentos(meu.id);
		carregando = false;
	}

	/** Recarrega o requerimento: situação e pagamento mudam no servidor. */
	function substituir(atualizado: Requerimento) {
		requerimentos = requerimentos.map((r) => (r.id === atualizado.id ? atualizado : r));
	}

	async function enviarComprovante(event: Event) {
		const campo = event.currentTarget as HTMLInputElement;
		const arquivo = campo.files?.[0];
		if (requerimento === null || !arquivo) return;
		erro = '';
		enviando = true;
		const { data, error } = await api.POST(
			'/academic/isolated/requests/{request_id}/payment-receipt',
			{
				params: { path: { request_id: requerimento.id } },
				// O tipo gerado declara `file: string` (binary no OpenAPI); o cast
				// é o preço de mandar o File de verdade pelo FormData.
				body: { file: arquivo as unknown as string },
				bodySerializer: comoFormData
			}
		);
		enviando = false;
		// Limpa sempre: com o nome do arquivo preso no campo, reenviar o mesmo
		// arquivo depois de corrigir algo não dispara o `change`.
		campo.value = '';
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível enviar o comprovante.');
			return;
		}
		substituir(data);
		await carregarDocumentos(data.id);
	}

	async function enviarRecurso() {
		if (requerimento === null || impedimentoDoRecurso !== '') return;
		if (textoDoRecurso.trim() === '') {
			erro = 'Escreva a razão do recurso.';
			return;
		}
		if ((tipoDoAnexo === '') !== (arquivoDoRecurso === null)) {
			erro = 'O anexo do recurso precisa do tipo e do arquivo juntos.';
			return;
		}
		erro = '';
		enviando = true;
		const { data, error } = await api.POST('/academic/isolated/requests/{request_id}/appeal', {
			params: { path: { request_id: requerimento.id } },
			body: {
				note: textoDoRecurso,
				kind: tipoDoAnexo === '' ? null : tipoDoAnexo,
				file: arquivoDoRecurso === null ? null : (arquivoDoRecurso as unknown as string)
			},
			bodySerializer: comoFormData
		});
		enviando = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível registrar seu recurso.');
			return;
		}
		substituir(data);
		textoDoRecurso = '';
		tipoDoAnexo = '';
		arquivoDoRecurso = null;
		await carregarDocumentos(data.id);
	}

	function escolherArquivoDoRecurso(event: Event) {
		arquivoDoRecurso = (event.currentTarget as HTMLInputElement).files?.[0] ?? null;
	}

	$effect(() => {
		carregar();
	});
</script>

<svelte:head>
	<title>Acompanhamento da inscrição · PPGD Manager</title>
</svelte:head>

<header>
	<p class="etiqueta">Disciplina isolada</p>
	<h1 class="text-grafite mt-1 text-2xl font-semibold tracking-tight">Acompanhamento</h1>
</header>

{#if erro}
	<p class="aviso-erro mt-6" role="alert">{erro}</p>
{/if}

{#if carregando}
	<p class="etiqueta mt-6">Carregando…</p>
{:else if requerimento === null}
	<div class="border-borda bg-papel mt-6 border border-dashed p-5">
		<p class="etiqueta">Nada para acompanhar</p>
		<p class="text-grafite mt-2 text-[0.9375rem]">
			Você ainda não enviou uma inscrição neste edital. Monte-a na tela de inscrição.
		</p>
	</div>
{:else}
	<section class="border-borda bg-papel mt-6 border p-5">
		<p class="etiqueta">Situação</p>
		<p class="text-grafite mt-1 text-lg font-semibold tracking-tight">{situacao}</p>
		{#if requerimento.status === 'submitted'}
			<p class="text-cinza mt-2 text-sm">
				Sua inscrição está em análise. O resultado sai por esta tela.
			</p>
		{:else if requerimento.status === 'deferred'}
			<p class="text-cinza mt-2 text-sm">
				Sua inscrição foi deferida. A matrícula é efetivada pela secretaria depois da taxa.
			</p>
		{:else if requerimento.status === 'enrolled'}
			<p class="text-cinza mt-2 text-sm">Sua matrícula na disciplina isolada está efetivada.</p>
		{:else if requerimento.status === 'cancelled'}
			<p class="text-cinza mt-2 text-sm">Esta inscrição foi cancelada.</p>
		{/if}
		{#if requerimento.decision_note}
			<p class="text-grafite mt-3 text-[0.9375rem]">{requerimento.decision_note}</p>
		{/if}
		<ul class="mt-4 space-y-1">
			{#each requerimento.items as item (item.id)}
				<li class="text-cinza text-sm">
					<span class="text-grafite font-mono">{item.discipline_code}</span>
					{item.discipline_name}
					{#if item.rank !== null}
						· classificação {item.rank}
					{/if}
				</li>
			{/each}
		</ul>
	</section>

	<section class="mt-8">
		<h2 class="etiqueta">Taxa de inscrição · {ROTULO_DO_PAGAMENTO[requerimento.payment_status]}</h2>
		{#if requerimento.payment_status === 'exempt'}
			<p class="text-grafite mt-2 text-[0.9375rem]">
				Servidor da UFMG é isento: não há taxa a pagar e não há comprovante a enviar.
			</p>
		{:else if requerimento.status !== 'deferred' && requerimento.status !== 'enrolled'}
			<!-- Antes do deferimento não existe GRU: mostrar o link ou o prazo
			aqui seria inventar um passo que o edital ainda não abriu. -->
			<p class="text-cinza mt-2 text-sm">{impedimentoDoPagamento}</p>
		{:else}
			{#if requerimento.gru_url}
				<p class="mt-2 text-[0.9375rem]">
					<!-- Link externo, e não rota da SPA: a guia é emitida pelo sistema
					de arrecadação da UFMG e a secretaria só cola o endereço dela aqui.
					`resolve()` não se aplica. -->
					<!-- eslint-disable svelte/no-navigation-without-resolve -->
					<a
						class="text-tinta underline"
						href={requerimento.gru_url}
						target="_blank"
						rel="noreferrer"
					>
						Abrir a GRU para pagamento
					</a>
					<!-- eslint-enable svelte/no-navigation-without-resolve -->
				</p>
			{:else}
				<p class="text-cinza mt-2 text-sm">
					A secretaria ainda não registrou o link da GRU. Procure-a se o prazo estiver perto de
					vencer.
				</p>
			{/if}
			<p class="text-cinza mt-1 text-sm">
				Prazo de pagamento: {formatarPrazo(requerimento.payment_closes_at)}.
			</p>
			{#if comprovante}
				<p class="text-grafite mt-3 text-[0.9375rem]">
					Comprovante enviado: {comprovante.filename} · {formatarTamanho(comprovante.size)}
				</p>
			{/if}
			{#if impedimentoDoPagamento}
				<p class="text-cinza mt-3 text-sm">{impedimentoDoPagamento}</p>
			{:else}
				<label class="etiqueta mt-3 inline-block cursor-pointer">
					<span class="botao-discreto inline-block">
						{#if enviando}
							Enviando…
						{:else}
							{comprovante ? 'Substituir comprovante' : 'Enviar comprovante'}
						{/if}
					</span>
					<input class="sr-only" type="file" disabled={enviando} onchange={enviarComprovante} />
				</label>
			{/if}
		{/if}
	</section>

	{#if requerimento.status === 'rejected' || requerimento.appealed_at !== null}
		<section class="mt-8">
			<h2 class="etiqueta">Recurso</h2>
			{#if requerimento.appealed_at !== null}
				<p class="text-cinza mt-2 text-sm">
					Recurso interposto em {formatarPrazo(requerimento.appealed_at)}. A secretaria decide de
					novo e o resultado aparece nesta tela.
				</p>
				<p class="text-grafite mt-2 text-[0.9375rem]">{requerimento.appeal_note}</p>
			{:else if impedimentoDoRecurso}
				<p class="text-cinza mt-2 text-sm">{impedimentoDoRecurso}</p>
			{:else}
				<p class="text-cinza mt-2 text-sm">
					A janela de recurso encerra em {formatarPrazo(requerimento.appeal_closes_at)}.
				</p>
				<label class="mt-3 block">
					<span class="etiqueta">Razão do recurso</span>
					<textarea
						class="campo mt-1 w-full"
						rows="4"
						bind:value={textoDoRecurso}
						disabled={enviando}></textarea>
				</label>
				<div class="mt-3 flex flex-wrap items-end gap-4">
					<label class="block">
						<span class="etiqueta">Anexo (opcional)</span>
						<select class="campo mt-1" bind:value={tipoDoAnexo} disabled={enviando}>
							<option value="">Sem anexo</option>
							{#each ORDEM_DO_EDITAL as tipo (tipo)}
								<option value={tipo}>{ROTULO_DO_DOCUMENTO[tipo]}</option>
							{/each}
						</select>
					</label>
					{#if tipoDoAnexo !== ''}
						<label class="etiqueta cursor-pointer">
							<span class="botao-discreto inline-block">
								{arquivoDoRecurso ? arquivoDoRecurso.name : 'Escolher arquivo'}
							</span>
							<input
								class="sr-only"
								type="file"
								disabled={enviando}
								onchange={escolherArquivoDoRecurso}
							/>
						</label>
					{/if}
				</div>
				<button class="botao mt-4" type="button" disabled={enviando} onclick={enviarRecurso}>
					{enviando ? 'Enviando…' : 'Interpor recurso'}
				</button>
			{/if}
		</section>
	{/if}

	<section class="mt-8">
		<h2 class="etiqueta">Documentos enviados</h2>
		{#if documentos.length === 0}
			<p class="text-cinza mt-2 text-sm">Nenhum documento anexado.</p>
		{:else}
			<ul class="mt-2 space-y-px">
				{#each documentos as documento (documento.id)}
					<li class="border-borda flex items-center justify-between gap-4 border-b px-1 py-3">
						<div class="min-w-0">
							<p class="text-grafite text-[0.9375rem]">
								{ROTULO_DO_DOCUMENTO[documento.kind] ?? documento.kind_label}
							</p>
							<p class="text-cinza mt-0.5 truncate text-sm">
								{documento.filename} · {formatarTamanho(documento.size)}
							</p>
						</div>
					</li>
				{/each}
			</ul>
		{/if}
	</section>
{/if}
