<script lang="ts">
	import { page } from '$app/state';
	import { api, codigoDeErro, garantirCsrf, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';
	import { formatarMomento, formatarNota } from '$lib/selecao';

	type Assinatura = components['schemas']['PublicSignatureOut'];
	type Comprovante = components['schemas']['PublicSignatureReceiptOut'];

	/*
	 * A ata que o examinador externo abre pelo link do e-mail.
	 *
	 * Grupo `(publico)` porque aqui NÃO há sessão: o examinador é professor
	 * de outra instituição e não tem conta. O token do caminho é o que faz
	 * as vezes de credencial — ele vale uma vez, expira, e é por isso que a
	 * tela não guarda nada dele além do que a URL já traz.
	 *
	 * O endereço tem que casar com o que `apps/selection/emails.py` monta:
	 * `{SITE_URL}/selecao/assinatura/{token}`.
	 *
	 * Quatro estados: carregando, ata para conferir, link morto (404
	 * genérico do servidor — inexistente, expirado, já usado ou de ata
	 * reaberta, sem distinguir) e comprovante depois de assinar. Depois de
	 * assinar o link não abre mais, então o comprovante é a única
	 * confirmação que o examinador recebe: ele fica na tela.
	 */

	const token = $derived(page.params.token ?? '');

	let carregando = $state(true);
	let assinando = $state(false);
	/** Link que não abre. Mensagem própria: o 404 do servidor é genérico. */
	let linkMorto = $state('');
	let erro = $state('');
	let assinatura = $state<Assinatura | null>(null);
	let comprovante = $state<Comprovante | null>(null);

	async function carregar(chave: string) {
		carregando = true;
		linkMorto = '';
		erro = '';
		const resultado = await api.GET('/selection/public/signatures/{token}', {
			params: { path: { token: chave } }
		});
		// O status se lê ANTES de desestruturar: no ramo de erro o TypeScript
		// estreita `resultado` para `never` (a operação só declara o 200) e
		// `resultado.response` deixaria de existir.
		const status = resultado.response.status;
		const { data, error } = resultado;
		carregando = false;
		if (data === undefined) {
			if (status === 404) {
				linkMorto =
					'Este link não é mais válido. Ele vale uma vez só e tem prazo — se você ainda não assinou, peça à secretaria o reenvio do e-mail.';
			} else if (status === 429) {
				linkMorto = 'Muitas tentativas seguidas. Espere um minuto e recarregue a página.';
			} else {
				erro = mensagemDeErro(error, 'Não foi possível abrir a ata deste link.');
			}
			assinatura = null;
			return;
		}
		assinatura = data;
	}

	$effect(() => {
		const chave = token;
		if (chave === '') {
			carregando = false;
			linkMorto = 'Link incompleto: falta o código de assinatura.';
			return;
		}
		carregar(chave);
	});

	async function assinar() {
		const atual = assinatura;
		if (atual === null || assinando) return;
		erro = '';
		assinando = true;
		await garantirCsrf();
		// Manda o hash que ESTA tela mostrou: se a ata foi reaberta e
		// recongelada entre a conferência e o clique, o servidor recusa com
		// `record_changed` em vez de colher assinatura sobre texto não lido.
		const resultado = await api.POST('/selection/public/signatures/{token}/sign', {
			params: { path: { token } },
			body: { content_hash: atual.content_hash }
		});
		const status = resultado.response.status;
		const { data, error } = resultado;
		assinando = false;
		if (data === undefined) {
			// Na escrita o servidor é específico de propósito (quem já provou
			// ter um token legítimo precisa saber por que ele não serve mais);
			// só o 404 continua mudo.
			const codigo = codigoDeErro(error);
			if (codigo === 'record_changed') {
				erro =
					'A ata mudou depois que esta tela a abriu. Recarregue a página e confira o texto antes de assinar.';
			} else if (status === 404) {
				linkMorto = 'Este link não é mais válido. Peça à secretaria o reenvio do e-mail.';
				assinatura = null;
			} else {
				erro = mensagemDeErro(error, 'Não foi possível registrar a sua assinatura.');
			}
			return;
		}
		comprovante = data;
		assinatura = null;
	}
</script>

<svelte:head>
	<title>Assinatura da ata · PPGD Manager</title>
</svelte:head>

<h1 class="text-grafite text-2xl font-semibold tracking-tight">Assinatura da ata</h1>

{#if erro}
	<p class="aviso-erro mt-6" role="alert">{erro}</p>
{/if}

{#if carregando}
	<p class="etiqueta mt-6">Abrindo a ata…</p>
{:else if comprovante !== null}
	<section class="border-borda bg-papel regua-tinta mt-6 border p-6" role="status">
		<p class="etiqueta">Assinatura registrada</p>
		<p class="text-grafite mt-2 text-xl font-semibold tracking-tight">{comprovante.signer_name}</p>
		<p class="text-cinza mt-1 text-[0.9375rem]">
			Assinada em {formatarMomento(comprovante.signed_at)}.
		</p>
		<dl class="mt-5 grid gap-x-6 gap-y-3 sm:grid-cols-2">
			<div>
				<dt class="etiqueta">Texto assinado</dt>
				<dd class="text-grafite font-mono text-[0.8125rem]">
					{comprovante.signed_hash.slice(0, 12)}
				</dd>
			</div>
			<div>
				<dt class="etiqueta">Situação da ata</dt>
				<dd class="text-grafite text-[0.8125rem]">{comprovante.record_status_label}</dd>
			</div>
		</dl>
		<p class="text-cinza mt-5 text-sm">
			{#if comprovante.pending_signatures === 0}
				Era a última assinatura que faltava: a ata está fechada.
			{:else}
				Faltam {comprovante.pending_signatures} assinatura(s) para a ata ficar fechada.
			{/if}
		</p>
		<p class="text-cinza mt-4 text-sm">
			Este link não abre mais — ele vale uma vez só. Guarde ou imprima esta página se quiser
			registro da assinatura.
		</p>
	</section>
{:else if linkMorto}
	<section class="border-borda bg-papel mt-6 border border-dashed p-10 text-center" role="status">
		<p class="text-grafite text-[0.9375rem]">{linkMorto}</p>
	</section>
{:else if assinatura !== null}
	<p class="text-cinza mt-2 text-sm">
		Confira o texto abaixo antes de assinar. Sua assinatura vale sobre exatamente estas notas.
	</p>

	<section class="bg-papel regua-tinta mt-6 px-5 py-4">
		<p class="etiqueta">{assinatura.process_title}</p>
		<h2 class="text-grafite mt-1 text-lg font-semibold tracking-tight">
			{assinatura.stage_name} · {assinatura.level_label} · {assinatura.target_label || '—'}
		</h2>

		<dl class="mt-4 grid gap-x-6 gap-y-1 sm:grid-cols-2 lg:grid-cols-4">
			<div>
				<dt class="etiqueta">Examinador</dt>
				<dd class="text-grafite text-[0.8125rem]">
					{assinatura.signer_name}
					{#if assinatura.signer_institution}
						<span class="text-cinza block text-xs">{assinatura.signer_institution}</span>
					{/if}
				</dd>
			</div>
			<div>
				<dt class="etiqueta">Versão</dt>
				<dd class="text-grafite text-[0.8125rem]">
					{assinatura.version} · congelada em {formatarMomento(assinatura.frozen_at)}
				</dd>
			</div>
			<div>
				<dt class="etiqueta">Conferência do texto</dt>
				<dd class="text-grafite text-[0.8125rem]">
					<span class="font-mono">{assinatura.content_hash.slice(0, 12)}</span>
					· {assinatura.hash_ok ? 'confere' : 'NÃO confere'}
				</dd>
			</div>
			<div>
				<dt class="etiqueta">Link válido até</dt>
				<dd class="text-grafite text-[0.8125rem]">
					{formatarMomento(assinatura.token_expires_at)}
				</dd>
			</div>
		</dl>

		{#if assinatura.content.length === 0}
			<p class="text-cinza mt-4 text-sm">A ata não tem linhas.</p>
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
						{#each assinatura.content as linha (linha.application_id)}
							<tr class="border-borda border-b last:border-0">
								<td class="text-grafite px-4 py-2">{linha.full_name}</td>
								<td class="text-cinza px-4 py-2 font-mono text-xs">{linha.protocol}</td>
								<td class="text-cinza px-4 py-2">{linha.quota_category}</td>
								<td class="text-grafite px-4 py-2">{formatarNota(linha.score, linha.absent)}</td>
								<td class="px-4 py-2" class:text-carimbo={!linha.passed}>
									{linha.passed ? 'Promovido' : 'Eliminado'}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}

		{#if !assinatura.hash_ok}
			<p class="aviso-erro mt-4" role="alert">
				O texto desta ata não confere com o hash registrado no congelamento. Não assine: avise a
				secretaria.
			</p>
		{/if}
	</section>

	<div class="mt-6 flex flex-wrap items-center gap-3">
		<button class="botao" type="button" disabled={assinando} onclick={assinar}>
			{assinando ? 'Assinando…' : 'Assinar a ata'}
		</button>
		<span class="text-cinza text-sm">
			{#if assinatura.pending_signatures <= 1}
				A sua é a última assinatura que falta.
			{:else}
				Faltam {assinatura.pending_signatures} assinaturas, contando a sua.
			{/if}
		</span>
	</div>
{/if}
