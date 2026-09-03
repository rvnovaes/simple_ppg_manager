<script lang="ts">
	import { resolve } from '$app/paths';
	import { api, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';
	import { EXPLICACAO_DA_SITUACAO, formatarMomento } from '$lib/selecao';

	type Situacao = components['schemas']['ApplicationStatusOut'];

	/*
	 * Consulta pública da inscrição pelo protocolo.
	 *
	 * O protocolo é o segredo que substitui a senha, e por isso a resposta
	 * do servidor não traz nome, CPF nem documento — quem digitou o número
	 * pode não ser o candidato. Protocolo inexistente volta 404 genérico: a
	 * tela repete a mensagem do backend em vez de inventar uma, para não
	 * dizer se o número nunca existiu ou é de outro edital.
	 */

	let protocolo = $state('');
	let consultando = $state(false);
	let erro = $state('');
	let situacao = $state<Situacao | null>(null);

	async function consultar(evento: SubmitEvent) {
		evento.preventDefault();
		erro = '';
		situacao = null;
		consultando = true;
		const resultado = await api.GET('/selection/public/applications/{protocol}', {
			params: { path: { protocol: protocolo.trim() } }
		});
		// O status se lê ANTES de desestruturar: no ramo de erro o TypeScript
		// estreita `resultado` para `never` (esta operação não declara corpo
		// de erro no OpenAPI) e `resultado.response` deixaria de existir.
		const status = resultado.response.status;
		const { data, error } = resultado;
		consultando = false;
		if (error || !data) {
			// O 404 desta rota é o genérico do Ninja ("No Application matches
			// the given query"), em inglês e de propósito: ele não diz se o
			// protocolo nunca existiu ou é de outro edital. Quem escreve a
			// frase para o candidato é a tela.
			erro =
				status === 404
					? 'Não encontramos inscrição com esse protocolo. Confira o número do comprovante.'
					: mensagemDeErro(error, 'Não foi possível consultar o protocolo.');
			return;
		}
		situacao = data;
	}
</script>

<svelte:head>
	<title>Consultar protocolo · PPGM</title>
</svelte:head>

<h1 class="text-grafite text-2xl font-semibold tracking-tight">Situação da inscrição</h1>
<p class="text-cinza mt-2 text-sm">
	Digite o protocolo que você recebeu ao se inscrever. A consulta mostra apenas em que pé está a
	inscrição, sem dados pessoais.
</p>

<form class="border-borda bg-papel mt-8 border p-6" onsubmit={consultar}>
	<label class="etiqueta mb-2 block" for="consulta-protocolo">Protocolo</label>
	<div class="flex flex-wrap items-center gap-3">
		<input
			id="consulta-protocolo"
			class="campo font-mono sm:max-w-xs"
			bind:value={protocolo}
			placeholder="PS2026R-XXXXXX"
			required
		/>
		<button class="botao" type="submit" disabled={consultando || protocolo.trim() === ''}>
			{consultando ? 'Consultando…' : 'Consultar'}
		</button>
	</div>
</form>

{#if erro}
	<p class="aviso-erro mt-6" role="alert">{erro}</p>
{/if}

{#if situacao}
	<section class="border-borda bg-papel mt-6 border p-6" role="status">
		<p class="etiqueta">{situacao.process_title}</p>
		<p class="text-tinta mt-2 font-mono text-lg tracking-tight">{situacao.protocol}</p>
		<p class="text-grafite mt-5 text-xl font-semibold tracking-tight">{situacao.status_label}</p>
		<p class="text-cinza mt-2 text-[0.9375rem]">{EXPLICACAO_DA_SITUACAO[situacao.status]}</p>
		<p class="text-cinza mt-4 text-sm">
			Inscrição enviada em {formatarMomento(situacao.submitted_at)}.
		</p>
	</section>
{/if}

<p class="text-cinza mt-8 text-sm">
	Ainda não se inscreveu?
	<a class="text-tinta underline" href={resolve('/selecao/inscricao')}>Ver os editais abertos</a>
</p>
