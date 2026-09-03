<script lang="ts">
	import { resolve } from '$app/paths';
	import { api, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';
	import { CRONOGRAMA, formatarData } from '$lib/bolsas';

	type Edicao = components['schemas']['ScholarshipEditionOut'];
	type Inscricao = components['schemas']['ScholarshipApplicationOut'];

	let edicoes = $state<Edicao[]>([]);
	let edicaoId = $state<number | null>(null);
	const edicao = $derived(edicoes.find((e) => e.id === edicaoId) ?? null);

	let inscricao = $state<Inscricao | null>(null);
	/** O recurso viaja dentro da inscrição (`ScholarshipApplicationOut.appeal`):
	 * não há segunda chamada para saber se já foi interposto ou julgado. */
	const recurso = $derived(inscricao?.appeal ?? null);

	let texto = $state('');
	let carregando = $state(true);
	let salvando = $state(false);
	let erro = $state('');
	let aviso = $state('');

	/**
	 * O botão de recorrer é o bool do servidor, nunca uma cópia da máquina
	 * de estados: `can_appeal` já reúne as duas condições do domínio (a
	 * fase aberta por `open_appeals()` — publicar o preliminar não basta —
	 * e o recurso ainda não interposto, que é um por inscrição).
	 */
	const podeRecorrer = $derived(inscricao?.can_appeal ?? false);

	// --- carregamento --------------------------------------------------------

	async function carregarEdicoes() {
		const { data, error } = await api.GET('/scholarships/editions/');
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar as edições do edital de bolsas.');
			return;
		}
		edicoes = data?.items ?? [];
		edicaoId = edicoes[0]?.id ?? null;
	}

	/**
	 * A inscrição do próprio candidato — ou nenhuma.
	 *
	 * 404 aqui é o caso normal de quem não se inscreveu naquela edição, e
	 * é ele que faz a tela dizer isso em vez de mostrar um erro. O código
	 * HTTP sai para uma const ANTES do `if`: dentro dele o objeto inteiro é
	 * estreitado e `resposta.response` viraria `never`.
	 */
	async function carregarInscricao(alvo: number) {
		const resposta = await api.GET('/scholarships/editions/{edition_id}/my-application', {
			params: { path: { edition_id: alvo } }
		});
		const codigo = resposta.response.status;
		const falha = resposta.error;
		if (falha || !resposta.data) {
			inscricao = null;
			if (codigo !== 404) {
				erro = mensagemDeErro(falha, 'Não foi possível carregar a sua inscrição.');
			}
			return;
		}
		inscricao = resposta.data;
	}

	async function carregar() {
		carregando = true;
		erro = '';
		await carregarEdicoes();
		if (edicaoId !== null) await carregarInscricao(edicaoId);
		carregando = false;
	}

	async function trocarDeEdicao(alvo: number) {
		edicaoId = alvo;
		inscricao = null;
		texto = '';
		erro = '';
		aviso = '';
		await carregarInscricao(alvo);
	}

	// --- interposição ---------------------------------------------------------

	/**
	 * Interpõe o recurso — **texto e só**.
	 *
	 * Não há anexo aqui, e a ausência é do edital: o item 1.3 veta a
	 * postagem de documento fora do prazo de inscrição, e o recurso ataca a
	 * pontuação com argumento sobre o que já foi entregue.
	 */
	async function interpor(event: SubmitEvent) {
		event.preventDefault();
		const alvo = inscricao;
		if (alvo === null || texto.trim() === '') return;
		erro = '';
		aviso = '';
		salvando = true;
		const { error } = await api.POST('/scholarships/applications/{application_id}/appeal', {
			params: { path: { application_id: alvo.id } },
			body: { text: texto }
		});
		salvando = false;
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível interpor o recurso.');
			return;
		}
		texto = '';
		aviso = 'Recurso interposto. A Comissão de Bolsas julga e a fundamentação aparece aqui.';
		// Recarrega a inscrição inteira: `appeal` e `can_appeal` são
		// derivados no servidor, e é deles que sai o que a tela desenha.
		if (edicaoId !== null) await carregarInscricao(edicaoId);
	}

	$effect(() => {
		carregar();
	});
</script>

<svelte:head>
	<title>Recurso da bolsa · PPGM</title>
</svelte:head>

<header>
	<p class="etiqueta">Bolsas</p>
	<h1 class="text-grafite mt-1 text-2xl font-semibold tracking-tight">Recurso</h1>
	<p class="text-cinza mt-1 text-sm">
		O recurso ataca a pontuação do resultado preliminar, é um por inscrição e vai só com as suas
		razões — o edital (item 1.3) não admite documento novo fora do prazo de inscrição.
	</p>
</header>

{#if erro}
	<p class="aviso-erro mt-6" role="alert">{erro}</p>
{/if}
{#if aviso}
	<p class="border-borda bg-papel text-grafite mt-6 border px-4 py-3 text-sm" role="status">
		{aviso}
	</p>
{/if}

{#if carregando}
	<p class="etiqueta mt-6">Carregando…</p>
{:else if edicoes.length === 0}
	<div class="border-borda bg-papel mt-6 border border-dashed p-10 text-center">
		<p class="text-grafite text-[0.9375rem]">Nenhum edital de bolsas neste programa.</p>
	</div>
{:else}
	<div class="mt-8">
		<label class="etiqueta mb-2 block" for="edicao-selecao">Edição</label>
		<select
			id="edicao-selecao"
			class="campo"
			value={edicaoId}
			onchange={(e) => trocarDeEdicao(Number(e.currentTarget.value))}
		>
			{#each edicoes as opcao (opcao.id)}
				<option value={opcao.id}>
					{opcao.year} · {opcao.title} ({opcao.status_label})
				</option>
			{/each}
		</select>
	</div>

	{#if edicao}
		<section class="border-borda bg-papel mt-6 border p-5">
			<div class="flex flex-wrap items-center justify-between gap-4">
				<p class="etiqueta">Edição {edicao.year}</p>
				<span class="etiqueta">{edicao.status_label}</span>
			</div>
			<h2 class="text-grafite mt-2 text-lg font-semibold tracking-tight">{edicao.title}</h2>
			<dl class="text-grafite mt-4 grid gap-3 text-sm sm:grid-cols-3">
				{#each CRONOGRAMA as { campo, rotulo } (campo)}
					<div>
						<dt class="etiqueta">{rotulo}</dt>
						<dd>{formatarData(edicao[campo])}</dd>
					</div>
				{/each}
			</dl>
			{#if edicao.results_visible_to_student}
				<p class="mt-4 text-sm">
					<a class="underline" href={resolve('/bolsas/resultado')}>
						Ver o resultado publicado desta edição
					</a>
				</p>
			{/if}
		</section>
	{/if}

	{#if inscricao === null}
		<div class="border-borda bg-papel mt-6 border border-dashed p-10 text-center">
			<p class="text-grafite text-[0.9375rem]">
				Você não tem inscrição nesta edição do edital de bolsas.
			</p>
			<p class="text-cinza mt-1 text-sm">Só quem se inscreveu pode recorrer do resultado.</p>
		</div>
	{:else if recurso}
		<!-- Recurso já interposto: a tela vira acompanhamento. -->
		<section class="border-borda bg-papel mt-6 border p-5">
			<p class="etiqueta">Recurso interposto</p>
			<p class="text-cinza mt-1 text-sm">
				Em {new Date(recurso.submitted_at).toLocaleString('pt-BR', {
					dateStyle: 'short',
					timeStyle: 'short'
				})}
			</p>
			<p class="text-grafite mt-4 text-sm whitespace-pre-line">{recurso.text}</p>
		</section>

		<section class="border-borda bg-papel mt-6 border p-5">
			<p class="etiqueta">Julgamento</p>
			{#if recurso.judged}
				<h3 class="text-grafite mt-1 text-base font-semibold tracking-tight">
					{recurso.outcome_label}
				</h3>
				<p class="text-cinza mt-1 text-sm">
					Julgado em {recurso.decided_at
						? new Date(recurso.decided_at).toLocaleString('pt-BR', {
								dateStyle: 'short',
								timeStyle: 'short'
							})
						: '—'}
				</p>
				<!-- A fundamentação é obrigatória no julgamento
				(`appeal_reasoning_required` no model): é ela que o candidato lê
				para entender o que a comissão decidiu. -->
				<p class="text-grafite mt-4 text-sm whitespace-pre-line">{recurso.reasoning}</p>
			{:else}
				<p class="text-grafite mt-1 text-sm">
					Aguardando o julgamento da Comissão de Bolsas. O resultado e a fundamentação aparecem
					aqui.
				</p>
			{/if}
		</section>
	{:else if podeRecorrer}
		<form class="border-borda bg-papel mt-6 border p-5" onsubmit={interpor}>
			<p class="etiqueta">Interpor recurso</p>
			<p class="text-cinza mt-1 text-sm">
				Escreva as suas razões contra a pontuação publicada. O recurso é um por inscrição: depois de
				enviado não pode ser reescrito.
			</p>
			<label class="etiqueta mt-4 mb-2 block" for="texto-do-recurso">Razões do recurso</label>
			<textarea id="texto-do-recurso" class="campo" rows="10" bind:value={texto}></textarea>
			<div class="mt-4 flex items-center gap-4">
				<button class="botao" type="submit" disabled={salvando || texto.trim() === ''}>
					{salvando ? 'Enviando…' : 'Interpor recurso'}
				</button>
			</div>
		</form>
	{:else}
		<div class="border-borda bg-papel mt-6 border border-dashed p-10 text-center">
			<p class="text-grafite text-[0.9375rem]">A fase de recursos desta edição não está aberta.</p>
			<p class="text-cinza mt-1 text-sm">
				Publicar o resultado preliminar não abre o prazo: quem o abre é a secretaria, na data do
				cronograma. Enquanto isso o formulário fica fechado.
			</p>
		</div>
	{/if}
{/if}
