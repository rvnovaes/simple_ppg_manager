<script lang="ts">
	import { api, codigoDeErro, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';
	import { NIVEIS, formatarData, formatarDinheiro, formatarNota, type Nivel } from '$lib/bolsas';

	type Edicao = components['schemas']['ScholarshipEditionOut'];
	type Faixa = components['schemas']['BandOut'];

	let edicoes = $state<Edicao[]>([]);
	let edicaoId = $state<number | null>(null);
	const edicao = $derived(edicoes.find((e) => e.id === edicaoId) ?? null);

	let nivel = $state<Nivel>('masters');
	let faixas = $state<Faixa[]>([]);

	let carregando = $state(true);
	let buscando = $state(false);
	let erro = $state('');
	/** 403 `result_not_published` não é falha: é o candidato chegando cedo. */
	let aindaNaoPublicado = $state(false);

	/**
	 * Qual dos dois documentos esta edição publica hoje.
	 *
	 * Mesma leitura de `pdf.tipo_do_resultado`: o carimbo do final manda, e
	 * antes de qualquer publicação a lista é a prévia de quem opera o
	 * edital — quem decide se ela pode ser vista continua sendo o servidor
	 * (403 `result_not_published`), a tela só a rotula corretamente.
	 */
	const rotuloDoDocumento = $derived.by(() => {
		if (edicao === null) return '';
		if (edicao.published_final_at !== null) return 'Resultado final';
		if (edicao.results_visible_to_student) return 'Resultado preliminar';
		return 'Prévia — ainda não publicada';
	});

	/** O carimbo da publicação, com hora — é o instante que congelou a lista.
	 * Mesmo molde do "Inscrito em" da tela de inscrição: `Date` sobre o ISO
	 * com fuso que o servidor manda, sem `T00:00:00` (esse truque é só para
	 * data pura, em `formatarData`). */
	function formatarCarimbo(iso: string | null): string {
		if (iso === null) return '—';
		return new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
	}

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
	 * O nível do próprio candidato, quando ele existe.
	 *
	 * O resultado sai em dois documentos independentes (mestrado e
	 * doutorado) e o candidato só tem assunto com o seu: abrir a tela já no
	 * nível certo poupa o clique errado. 404 é o caso normal de quem não se
	 * inscreveu — Secretaria, Coordenação e Comissão caem aqui sempre, e
	 * ficam no mestrado, que é o padrão.
	 */
	async function nivelDaMinhaInscricao(alvo: number) {
		const resposta = await api.GET('/scholarships/editions/{edition_id}/my-application', {
			params: { path: { edition_id: alvo } }
		});
		if (resposta.error || !resposta.data) return;
		nivel = resposta.data.level;
	}

	async function carregarResultado() {
		if (edicaoId === null) return;
		buscando = true;
		erro = '';
		aindaNaoPublicado = false;
		const { data, error } = await api.GET('/scholarships/editions/{edition_id}/result', {
			params: { path: { edition_id: edicaoId }, query: { level: nivel } }
		});
		buscando = false;
		if (error) {
			faixas = [];
			// O `code` é que decide, não o texto: "ainda não publicado" é uma
			// tela de espera, e não um erro que o candidato deva reportar.
			if (codigoDeErro(error) === 'result_not_published') {
				aindaNaoPublicado = true;
				return;
			}
			erro = mensagemDeErro(error, 'Não foi possível carregar o resultado desta edição.');
			return;
		}
		faixas = data ?? [];
	}

	async function carregar() {
		carregando = true;
		erro = '';
		await carregarEdicoes();
		if (edicaoId !== null) {
			await nivelDaMinhaInscricao(edicaoId);
			await carregarResultado();
		}
		carregando = false;
	}

	async function trocarDeEdicao(alvo: number) {
		edicaoId = alvo;
		faixas = [];
		await carregarResultado();
	}

	async function trocarDeNivel(alvo: Nivel) {
		nivel = alvo;
		faixas = [];
		await carregarResultado();
	}

	$effect(() => {
		carregar();
	});
</script>

<svelte:head>
	<title>Resultado da bolsa · PPGM</title>
</svelte:head>

<header>
	<p class="etiqueta">Bolsas</p>
	<h1 class="text-grafite mt-1 text-2xl font-semibold tracking-tight">Resultado</h1>
	<p class="text-cinza mt-1 text-sm">
		As dez faixas de prioridade do edital, na ordem em que ele as classifica. A lista sai por nível
		— mestrado e doutorado correm independentes — e é a mesma que o PDF publica.
	</p>
</header>

{#if erro}
	<p class="aviso-erro mt-6" role="alert">{erro}</p>
{/if}

{#if carregando}
	<p class="etiqueta mt-6">Carregando…</p>
{:else if edicoes.length === 0}
	<div class="border-borda bg-papel mt-6 border border-dashed p-10 text-center">
		<p class="text-grafite text-[0.9375rem]">Nenhum edital de bolsas neste programa.</p>
	</div>
{:else}
	<div class="mt-8 grid gap-4 sm:grid-cols-2">
		<div>
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
		<div>
			<label class="etiqueta mb-2 block" for="nivel-selecao">Nível</label>
			<select
				id="nivel-selecao"
				class="campo"
				value={nivel}
				onchange={(e) => trocarDeNivel(e.currentTarget.value as Nivel)}
			>
				{#each NIVEIS as opcao (opcao.valor)}
					<option value={opcao.valor}>{opcao.rotulo}</option>
				{/each}
			</select>
		</div>
	</div>

	{#if edicao}
		<section class="border-borda bg-papel mt-6 border p-5">
			<div class="flex flex-wrap items-center justify-between gap-4">
				<div>
					<p class="etiqueta">{rotuloDoDocumento}</p>
					<h2 class="text-grafite mt-1 text-lg font-semibold tracking-tight">
						{edicao.title} · {NIVEIS.find((n) => n.valor === nivel)?.rotulo}
					</h2>
				</div>
				{#if !aindaNaoPublicado}
					<!-- Endereço da API, e não rota da SPA: o PDF é montado pelo Django
					e a visibilidade é conferida lá (`_garantir_resultado_visivel`, a
					mesma função do JSON), então `resolve()` não se aplica. Continua
					relativo — origem única (ADR-004). -->
					<!-- eslint-disable svelte/no-navigation-without-resolve -->
					<a
						class="botao-discreto shrink-0"
						href="/api/v1/scholarships/editions/{edicao.id}/result.pdf?level={nivel}"
					>
						Baixar PDF
					</a>
					<!-- eslint-enable svelte/no-navigation-without-resolve -->
				{/if}
			</div>
			<dl class="text-grafite mt-4 grid gap-3 text-sm sm:grid-cols-3">
				<div>
					<dt class="etiqueta">Preliminar publicado em</dt>
					<dd>{formatarCarimbo(edicao.published_preliminary_at)}</dd>
				</div>
				<div>
					<dt class="etiqueta">Final publicado em</dt>
					<dd>{formatarCarimbo(edicao.published_final_at)}</dd>
				</div>
				<div>
					<dt class="etiqueta">Recursos encerram em</dt>
					<dd>{formatarData(edicao.appeal_ends_on)}</dd>
				</div>
			</dl>
		</section>
	{/if}

	{#if aindaNaoPublicado}
		<div class="border-borda bg-papel mt-6 border border-dashed p-10 text-center">
			<p class="text-grafite text-[0.9375rem]">O resultado desta edição ainda não foi publicado.</p>
			<p class="text-cinza mt-1 text-sm">
				A lista aparece aqui quando a secretaria publicar o resultado preliminar, na data do
				cronograma do edital.
			</p>
		</div>
	{:else if buscando}
		<p class="etiqueta mt-6">Carregando o resultado…</p>
	{:else}
		<!-- As dez faixas vêm SEMPRE, na ordem canônica e inclusive vazias: a
		lista é a ordem de prioridade do edital, e uma faixa que sumisse da
		tela seria uma prioridade a menos no documento. Título, ordem e regra
		de ordenação vêm prontos do servidor, da mesma constante que ordenou. -->
		{#each faixas as faixa (faixa.band)}
			<section class="border-borda bg-papel mt-6 border p-5">
				<p class="etiqueta">{faixa.priority_label}</p>
				<h3 class="text-grafite mt-1 text-base font-semibold tracking-tight">{faixa.title}</h3>
				<p class="text-cinza mt-1 text-sm">Critério de ordenação: {faixa.ordering_rule}</p>

				{#if faixa.rows.length === 0}
					<p class="text-cinza mt-4 text-sm">Nenhum candidato nesta faixa.</p>
				{:else}
					<table class="mt-4 w-full text-sm">
						<thead>
							<tr class="border-borda border-b text-left">
								<th class="etiqueta py-2">Ordem</th>
								<th class="etiqueta py-2">Candidato(a)</th>
								<th class="etiqueta py-2 text-right">Nota</th>
								{#if faixa.shows_income}
									<th class="etiqueta py-2 text-right">Remuneração</th>
								{/if}
							</tr>
						</thead>
						<tbody>
							{#each faixa.rows as linha (linha.application_id)}
								<tr class="border-borda text-grafite border-b">
									<td class="py-2">{linha.position}</td>
									<td class="py-2">
										{linha.name}
										{#if linha.draw_order !== null}
											<span class="text-cinza block text-sm">
												Desempate por sorteio · ordem {linha.draw_order}
											</span>
										{/if}
									</td>
									<td class="py-2 text-right">{formatarNota(linha.score)}</td>
									{#if faixa.shows_income}
										<td class="py-2 text-right">{formatarDinheiro(linha.income)}</td>
									{/if}
								</tr>
							{/each}
						</tbody>
					</table>
					{#if faixa.rows.some((l) => l.draw_order !== null)}
						<p class="text-cinza mt-2 text-sm">
							Nesta faixa houve empate resolvido por sorteio, na forma do item 3.3 do edital.
						</p>
					{/if}
				{/if}
			</section>
		{/each}
	{/if}
{/if}
