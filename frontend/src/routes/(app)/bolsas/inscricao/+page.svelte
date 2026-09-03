<script lang="ts">
	import { api, comoFormData, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';
	import Icone from '$lib/Icone.svelte';
	import {
		ACEITA_COMPROVANTE,
		ACEITA_DOCUMENTO,
		CRONOGRAMA,
		QUESTIONARIO,
		SECOES,
		formatarData,
		formatarNota,
		rotuloDoItem,
		type CampoDoQuestionario,
		type TipoDeComprovante
	} from '$lib/bolsas';
	import { sessao } from '$lib/sessao.svelte';

	type Edicao = components['schemas']['ScholarshipEditionOut'];
	type Inscricao = components['schemas']['ScholarshipApplicationOut'];
	type Item = components['schemas']['BaremeItemOut'];
	type Lancamento = components['schemas']['BaremeEntryOut'];

	let edicoes = $state<Edicao[]>([]);
	let edicaoId = $state<number | null>(null);
	const edicao = $derived(edicoes.find((e) => e.id === edicaoId) ?? null);

	let inscricao = $state<Inscricao | null>(null);
	let itens = $state<Item[]>([]);
	let lancamentos = $state<Lancamento[]>([]);

	let carregando = $state(true);
	let erro = $state('');
	let aviso = $state('');
	let salvando = $state(false);

	// Quem pode o quê sai do papel, não do estado da tela. O Discente é o
	// único com `add_scholarshipapplication` (scholarships.0008_papeis_da_bolsa),
	// e é por essa permissão que o item de menu aparece.
	const podeInscrever = $derived(sessao.pode('scholarships.add_scholarshipapplication'));
	const podeEditar = $derived(sessao.pode('scholarships.change_scholarshipapplication'));
	const podeLancar = $derived(sessao.pode('scholarships.add_baremeentry'));
	const podeEditarLancamento = $derived(sessao.pode('scholarships.change_baremeentry'));

	/**
	 * A janela de inscrição, sempre pela palavra do servidor.
	 *
	 * `submission_open` vem resolvido tanto na edição quanto na inscrição —
	 * é o mesmo método do model. A tela não compara `status === '...'` nem
	 * olha data de cronograma: o cronograma é informação publicada, não
	 * gatilho, e quem abre e fecha é a secretaria, botão a botão.
	 */
	const janelaAberta = $derived(inscricao?.submission_open ?? edicao?.submission_open ?? false);

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
	 * A inscrição do próprio candidato naquela edição — ou nenhuma.
	 *
	 * 404 aqui não é falha: é a resposta de quem ainda não se inscreveu, e
	 * é ela que faz a tela oferecer o questionário em branco. Por isso o
	 * `response.status` é consultado antes de virar mensagem de erro.
	 */
	async function carregarInscricao(alvo: number) {
		const resposta = await api.GET('/scholarships/editions/{edition_id}/my-application', {
			params: { path: { edition_id: alvo } }
		});
		// O código HTTP sai para uma const ANTES do `if`: dentro dele o
		// objeto inteiro é estreitado e `resposta.response` viraria `never`.
		const codigo = resposta.response.status;
		const falha = resposta.error;
		if (falha || !resposta.data) {
			inscricao = null;
			lancamentos = [];
			if (codigo !== 404) {
				erro = mensagemDeErro(falha, 'Não foi possível carregar a sua inscrição.');
			}
			limparQuestionario();
			return;
		}
		const data = resposta.data;
		aplicarNaTela(data);
		await carregarLancamentos(data.id);
	}

	async function carregarBarema(alvo: number) {
		const { data, error } = await api.GET('/scholarships/editions/{edition_id}/bareme/', {
			params: { path: { edition_id: alvo } }
		});
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar o barema desta edição.');
			return;
		}
		itens = data ?? [];
	}

	async function carregarLancamentos(alvo: number) {
		const { data, error } = await api.GET('/scholarships/applications/{application_id}/entries/', {
			params: { path: { application_id: alvo } }
		});
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar os seus lançamentos.');
			return;
		}
		lancamentos = data ?? [];
	}

	async function carregar() {
		carregando = true;
		erro = '';
		await carregarEdicoes();
		if (edicaoId !== null) {
			await Promise.all([carregarBarema(edicaoId), carregarInscricao(edicaoId)]);
		}
		carregando = false;
	}

	async function trocarDeEdicao(alvo: number) {
		edicaoId = alvo;
		inscricao = null;
		itens = [];
		lancamentos = [];
		erro = '';
		aviso = '';
		fecharFormularioDoLancamento();
		await Promise.all([carregarBarema(alvo), carregarInscricao(alvo)]);
	}

	// --- questionário ---------------------------------------------------------

	let respostas = $state<Record<CampoDoQuestionario, boolean>>(questionarioEmBranco());
	let rendimento = $state('');
	let horas = $state('');

	function questionarioEmBranco(): Record<CampoDoQuestionario, boolean> {
		return {
			has_paid_activity: false,
			affirmative_action: false,
			socioeconomic_vulnerability: false,
			cadastro_unico: false,
			substitute_teacher: false,
			basic_education_or_collective_health: false,
			public_service: false,
			private_service: false,
			other_non_public_scholarship: false
		};
	}

	function limparQuestionario() {
		respostas = questionarioEmBranco();
		rendimento = '';
		horas = '';
	}

	/** Reflete na tela a inscrição que o servidor devolveu. */
	function aplicarNaTela(salva: Inscricao) {
		inscricao = salva;
		respostas = Object.fromEntries(
			QUESTIONARIO.map(({ campo }) => [campo, salva[campo]])
		) as Record<CampoDoQuestionario, boolean>;
		rendimento = salva.monthly_income === null ? '' : String(salva.monthly_income);
		horas = salva.weekly_hours === null ? '' : String(salva.weekly_hours);
	}

	/**
	 * Rendimento e carga horária só existem para quem exerce atividade
	 * remunerada — e por isso aparecem ao marcar a chave, e não antes.
	 *
	 * A validação que vale continua sendo a do `clean()` no backend
	 * (`income_required`): isto aqui é UX, para o candidato não procurar um
	 * campo que não é dele nem esquecer o que é.
	 */
	const exigeRendimento = $derived(respostas.has_paid_activity);

	const faltaRendimento = $derived(exigeRendimento && (rendimento === '' || horas === ''));

	function corpoDoQuestionario() {
		return {
			...respostas,
			// String vazia não é zero: em branco o campo vai `null`, e é o
			// backend que decide se a ausência é aceitável.
			monthly_income: exigeRendimento && rendimento !== '' ? rendimento : null,
			weekly_hours: exigeRendimento && horas !== '' ? Number(horas) : null
		};
	}

	async function salvarQuestionario(event: SubmitEvent) {
		event.preventDefault();
		if (edicaoId === null) return;
		erro = '';
		aviso = '';
		salvando = true;
		const alvo = inscricao;
		const resposta = alvo
			? await api.PATCH('/scholarships/applications/{application_id}/', {
					params: { path: { application_id: alvo.id } },
					body: corpoDoQuestionario()
				})
			: await api.POST('/scholarships/applications/', {
					body: { edition_id: edicaoId, ...corpoDoQuestionario() }
				});
		salvando = false;
		// A falha sai para uma const ANTES do `if`: dentro dele o objeto
		// inteiro é estreitado e `resposta.error` viraria `never`.
		const falha = resposta.error;
		if (falha || !resposta.data) {
			erro = mensagemDeErro(falha, 'Não foi possível salvar a sua inscrição.');
			return;
		}
		aplicarNaTela(resposta.data);
		aviso = alvo ? 'Questionário retificado.' : 'Inscrição registrada.';
		if (!alvo) await carregarLancamentos(resposta.data.id);
	}

	let confirmandoExclusao = $state(false);

	async function excluirInscricao() {
		const alvo = inscricao;
		if (alvo === null) return;
		erro = '';
		aviso = '';
		salvando = true;
		const { error } = await api.DELETE('/scholarships/applications/{application_id}/', {
			params: { path: { application_id: alvo.id } }
		});
		salvando = false;
		confirmandoExclusao = false;
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível excluir a sua inscrição.');
			return;
		}
		inscricao = null;
		lancamentos = [];
		limparQuestionario();
		aviso = 'Inscrição excluída. Enquanto a janela estiver aberta você pode se inscrever de novo.';
	}

	// --- comprovantes do questionário ----------------------------------------

	/** O comprovante já enviado daquele tipo, se houver. */
	function documentoDe(tipo: TipoDeComprovante) {
		return inscricao?.documents.find((d) => d.kind === tipo) ?? null;
	}

	let enviandoDocumento = $state<TipoDeComprovante | ''>('');

	async function anexar(tipo: TipoDeComprovante, event: Event) {
		const campo = event.currentTarget as HTMLInputElement;
		const arquivo = campo.files?.[0];
		if (inscricao === null || !arquivo) return;
		erro = '';
		aviso = '';
		enviandoDocumento = tipo;
		const { error } = await api.POST('/scholarships/applications/{application_id}/documents', {
			params: { path: { application_id: inscricao.id } },
			// O tipo gerado declara `file: string` (é `format: binary` no
			// OpenAPI); o cast é o preço de mandar o File de verdade.
			body: { kind: tipo, file: arquivo as unknown as string },
			bodySerializer: comoFormData
		});
		enviandoDocumento = '';
		// Sempre limpa o campo: sucesso ou falha, deixar o nome do arquivo ali
		// impede reenviar o mesmo arquivo depois de corrigir algo.
		campo.value = '';
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível anexar o comprovante.');
			return;
		}
		// Recarrega a inscrição inteira: `documents` e `pending_docs` são
		// calculados no servidor, e é deles que sai o "Sim — não enviado".
		if (edicaoId !== null) await carregarInscricao(edicaoId);
	}

	// --- lançamentos do barema -------------------------------------------------

	const itensDoNivel = $derived(
		inscricao === null ? [] : itens.filter((i) => i.level === inscricao?.level)
	);

	/**
	 * O barema do nível agrupado por seção, na ordem dos incisos (I..VI).
	 *
	 * Os itens sem lançamento nenhum continuam na lista: é sob o texto
	 * normativo do item que o candidato lança, e esconder o item vazio
	 * esconderia justamente o que ele ainda pode pontuar.
	 */
	const secoesDoBarema = $derived(
		SECOES.map(({ valor, rotulo }) => ({
			valor,
			rotulo,
			linhas: itensDoNivel
				.filter((i) => i.section === valor)
				.map((item) => ({ item, lancamentos: lancamentos.filter((l) => l.item_id === item.id) }))
		})).filter((s) => s.linhas.length > 0)
	);

	let itemDoFormulario = $state<number | null>(null);
	let editandoLancamento = $state<Lancamento | null>(null);
	let descricao = $state('');
	let quantidade = $state('1');
	let comprovante = $state<File | null>(null);

	function fecharFormularioDoLancamento() {
		itemDoFormulario = null;
		editandoLancamento = null;
		descricao = '';
		quantidade = '1';
		comprovante = null;
	}

	function abrirLancamento(item: Item) {
		fecharFormularioDoLancamento();
		itemDoFormulario = item.id;
		erro = '';
		aviso = '';
	}

	function editarLancamento(alvo: Lancamento) {
		fecharFormularioDoLancamento();
		itemDoFormulario = alvo.item_id;
		editandoLancamento = alvo;
		descricao = alvo.description;
		quantidade = String(alvo.quantity);
		erro = '';
		aviso = '';
	}

	function escolherComprovante(event: Event) {
		comprovante = (event.currentTarget as HTMLInputElement).files?.[0] ?? null;
	}

	/**
	 * Cria ou retifica o lançamento.
	 *
	 * Criar é **multipart**, com o comprovante no mesmo POST: sem
	 * comprovante o lançamento não existe. Retificar é **JSON**, porque o
	 * Django não parseia `multipart/form-data` em `PATCH` — trocar o
	 * arquivo tem rota própria (`POST .../proof`), e é ela que o botão
	 * "Trocar comprovante" chama.
	 */
	async function salvarLancamento(event: SubmitEvent) {
		event.preventDefault();
		const alvo = inscricao;
		if (alvo === null || itemDoFormulario === null) return;
		erro = '';
		aviso = '';
		const emEdicao = editandoLancamento;
		if (emEdicao === null && comprovante === null) {
			erro = 'O lançamento só existe com o comprovante: anexe o PDF antes de salvar.';
			return;
		}
		salvando = true;
		const resposta = emEdicao
			? await api.PATCH('/scholarships/applications/{application_id}/entries/{entry_id}/', {
					params: { path: { application_id: alvo.id, entry_id: emEdicao.id } },
					body: { item_id: itemDoFormulario, description: descricao, quantity: quantidade }
				})
			: await api.POST('/scholarships/applications/{application_id}/entries/', {
					params: { path: { application_id: alvo.id } },
					body: {
						item_id: itemDoFormulario,
						description: descricao,
						quantity: quantidade,
						proof: comprovante as unknown as string
					},
					bodySerializer: comoFormData
				});
		salvando = false;
		const falha = resposta.error;
		if (falha || !resposta.data) {
			erro = mensagemDeErro(falha, 'Não foi possível salvar o lançamento.');
			return;
		}
		const salvo = resposta.data;
		lancamentos = emEdicao
			? lancamentos.map((l) => (l.id === salvo.id ? salvo : l))
			: [...lancamentos, salvo];
		fecharFormularioDoLancamento();
	}

	let trocandoComprovante = $state<number | null>(null);

	async function trocarComprovante(alvo: Lancamento, event: Event) {
		const campo = event.currentTarget as HTMLInputElement;
		const arquivo = campo.files?.[0];
		if (inscricao === null || !arquivo) return;
		erro = '';
		aviso = '';
		salvando = true;
		const { data, error } = await api.POST(
			'/scholarships/applications/{application_id}/entries/{entry_id}/proof',
			{
				params: { path: { application_id: inscricao.id, entry_id: alvo.id } },
				body: { proof: arquivo as unknown as string },
				bodySerializer: comoFormData
			}
		);
		salvando = false;
		campo.value = '';
		trocandoComprovante = null;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível trocar o comprovante.');
			return;
		}
		lancamentos = lancamentos.map((l) => (l.id === data.id ? data : l));
	}

	let removendoLancamento = $state<number | null>(null);

	async function removerLancamento(alvo: Lancamento) {
		if (inscricao === null) return;
		erro = '';
		aviso = '';
		salvando = true;
		const { error } = await api.DELETE(
			'/scholarships/applications/{application_id}/entries/{entry_id}/',
			{ params: { path: { application_id: inscricao.id, entry_id: alvo.id } } }
		);
		salvando = false;
		removendoLancamento = null;
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível excluir o lançamento.');
			return;
		}
		lancamentos = lancamentos.filter((l) => l.id !== alvo.id);
	}

	$effect(() => {
		carregar();
	});
</script>

<svelte:head>
	<title>Inscrição na bolsa · PPGM</title>
</svelte:head>

<header>
	<p class="etiqueta">Bolsas</p>
	<h1 class="text-grafite mt-1 text-2xl font-semibold tracking-tight">Minha inscrição</h1>
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
		<p class="text-grafite text-[0.9375rem]">Nenhum edital de bolsas aberto neste programa.</p>
		<p class="text-cinza mt-1 text-sm">
			Quando a secretaria publicar a edição do ano, ela aparece aqui com o questionário e o barema.
		</p>
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
			{#if edicao.notice_url}
				<p class="mt-4 text-sm">
					<!-- O PDF do edital é URL de MEDIA servida pelo Nginx, e não rota da
					SPA: `resolve()` não se aplica. Continua relativa — origem única
					(ADR-004). -->
					<!-- eslint-disable svelte/no-navigation-without-resolve -->
					<a class="underline" href={edicao.notice_url} target="_blank" rel="noopener">
						<Icone nome="documento" tamanho={14} rotulo="Abrir PDF" />
						{edicao.notice_filename}
					</a>
					<!-- eslint-enable svelte/no-navigation-without-resolve -->
				</p>
			{/if}
			{#if !janelaAberta}
				<p class="text-cinza mt-4 text-sm">
					A janela de inscrição desta edição está fechada: o que está abaixo é somente leitura. Nem
					o questionário nem os lançamentos podem ser alterados — é este material que a Comissão de
					Bolsas analisa.
				</p>
			{/if}
			{#if inscricao}
				<dl class="text-grafite mt-4 grid gap-3 text-sm sm:grid-cols-3">
					<div>
						<dt class="etiqueta">Nível</dt>
						<dd>{inscricao.level_label}</dd>
					</div>
					<div>
						<dt class="etiqueta">Inscrito em</dt>
						<dd>
							{inscricao.submitted_at
								? new Date(inscricao.submitted_at).toLocaleDateString('pt-BR')
								: '—'}
						</dd>
					</div>
					<div>
						<dt class="etiqueta">Faixa de prioridade</dt>
						<!-- Derivada pelo servidor a partir do questionário: a tela lê,
						nunca recalcula. -->
						<dd>{inscricao.band ?? '—'}</dd>
					</div>
				</dl>
			{/if}
		</section>

		{#if inscricao === null && !janelaAberta}
			<div class="border-borda bg-papel mt-6 border border-dashed p-10 text-center">
				<p class="text-grafite text-[0.9375rem]">
					Você não se inscreveu nesta edição e a janela já está fechada.
				</p>
			</div>
		{:else}
			<!-- Questionário ------------------------------------------------------ -->
			<section class="border-borda bg-papel mt-6 border p-5">
				<p class="etiqueta">Questionário do edital</p>
				<p class="text-cinza mt-1 text-sm">
					Cada afirmação marcada exige o comprovante correspondente. É deste questionário que sai a
					faixa de prioridade em que você concorre — quem a deriva é o servidor.
				</p>

				<form class="mt-4" onsubmit={salvarQuestionario}>
					<fieldset disabled={!janelaAberta || !(inscricao ? podeEditar : podeInscrever)}>
						<ul class="mt-2 flex flex-col gap-4">
							{#each QUESTIONARIO as pergunta (pergunta.campo)}
								<li class="border-borda border-b pb-4 last:border-b-0">
									<label class="text-grafite flex items-start gap-3 text-sm">
										<input class="mt-1" type="checkbox" bind:checked={respostas[pergunta.campo]} />
										<span>
											{pergunta.rotulo}
											{#if pergunta.ajuda}
												<span class="text-cinza mt-1 block text-sm">{pergunta.ajuda}</span>
											{/if}
										</span>
									</label>

									{#if pergunta.campo === 'has_paid_activity' && exigeRendimento}
										<div class="mt-3 grid gap-4 sm:grid-cols-2">
											<div>
												<label class="etiqueta mb-2 block" for="questionario-rendimento">
													Rendimento mensal (R$)
												</label>
												<input
													id="questionario-rendimento"
													class="campo"
													type="number"
													step="0.01"
													min="0"
													bind:value={rendimento}
												/>
											</div>
											<div>
												<label class="etiqueta mb-2 block" for="questionario-horas">
													Carga horária semanal (horas)
												</label>
												<input
													id="questionario-horas"
													class="campo"
													type="number"
													step="1"
													min="0"
													bind:value={horas}
												/>
											</div>
										</div>
										{#if faltaRendimento}
											<p class="text-cinza mt-2 text-sm">
												Quem declara atividade remunerada informa os dois: é por eles que a
												classificação ordena as faixas 2.4-V e 2.4-VI/VII/VIII.
											</p>
										{/if}
									{/if}
								</li>
							{/each}
						</ul>
					</fieldset>

					{#if janelaAberta && (inscricao ? podeEditar : podeInscrever)}
						<div class="mt-4 flex flex-wrap items-center gap-2">
							<button class="botao" type="submit" disabled={salvando}>
								{salvando ? 'Salvando…' : inscricao ? 'Salvar questionário' : 'Inscrever-se'}
							</button>
							{#if inscricao && !confirmandoExclusao}
								<button
									class="botao-discreto"
									type="button"
									onclick={() => (confirmandoExclusao = true)}
								>
									Excluir inscrição
								</button>
							{/if}
						</div>
					{/if}
				</form>

				{#if confirmandoExclusao}
					<div class="border-borda mt-4 border border-dashed p-4" role="alertdialog">
						<p class="etiqueta">Excluir inscrição</p>
						<p class="text-grafite mt-2 text-sm">
							Some tudo: o questionário, os comprovantes anexados e todos os lançamentos do barema,
							com os PDFs. Enquanto a janela estiver aberta, dá para se inscrever de novo — do zero.
						</p>
						<div class="mt-4 flex items-center gap-2">
							<button class="botao" type="button" disabled={salvando} onclick={excluirInscricao}>
								{salvando ? 'Excluindo…' : 'Excluir mesmo assim'}
							</button>
							<button
								class="botao-discreto"
								type="button"
								onclick={() => (confirmandoExclusao = false)}
							>
								Cancelar
							</button>
						</div>
					</div>
				{/if}
			</section>

			{#if inscricao}
				<!-- Comprovantes do questionário ---------------------------------- -->
				<section class="border-borda bg-papel mt-6 border p-5">
					<p class="etiqueta">Comprovantes do questionário</p>
					<p class="text-cinza mt-1 text-sm">
						Um arquivo por afirmação marcada ({ACEITA_DOCUMENTO}, até 10 MB). Reenviar substitui o
						anterior — é assim que se corrige a página errada.
					</p>
					{#if inscricao.pending_docs.length > 0}
						<p class="text-grafite mt-3 text-sm">
							Falta enviar: {inscricao.pending_docs.map((d) => d.kind_label).join(', ')}.
						</p>
					{/if}

					<ul class="mt-4 flex flex-col gap-4">
						{#each QUESTIONARIO.filter((p) => p.documento && respostas[p.campo]) as pergunta (pergunta.campo)}
							{@const tipo = pergunta.documento as TipoDeComprovante}
							{@const enviado = documentoDe(tipo)}
							<li class="border-borda border-b pb-4 last:border-b-0">
								<p class="text-grafite text-sm">{pergunta.rotulo}</p>
								{#if enviado}
									<p class="mt-1 text-sm">
										<!-- Download pelo Django (rota auditada), e não pela URL do
										MEDIA: não é rota da SPA, então `resolve()` não se aplica. -->
										<!-- eslint-disable svelte/no-navigation-without-resolve -->
										<a
											class="underline"
											href={`/api/v1/scholarships/documents/${enviado.id}/download`}
										>
											<Icone nome="documento" tamanho={14} rotulo="Baixar" />
											{enviado.filename}
										</a>
										<!-- eslint-enable svelte/no-navigation-without-resolve -->
									</p>
								{:else}
									<p class="text-cinza mt-1 text-sm">Sim — não enviado.</p>
								{/if}
								{#if janelaAberta && podeEditar}
									<input
										class="campo mt-2"
										type="file"
										accept={ACEITA_DOCUMENTO}
										disabled={enviandoDocumento === tipo}
										onchange={(e) => anexar(tipo, e)}
										aria-label={`Anexar comprovante: ${pergunta.rotulo}`}
									/>
								{/if}
							</li>
						{/each}
					</ul>
					{#if QUESTIONARIO.filter((p) => p.documento && respostas[p.campo]).length === 0}
						<p class="text-cinza mt-4 text-sm">
							Nenhuma afirmação marcada exige comprovante até aqui.
						</p>
					{/if}
				</section>

				<!-- Lançamentos do barema ----------------------------------------- -->
				<section class="border-borda bg-papel mt-6 border p-5">
					<p class="etiqueta">Barema · {inscricao.level_label}</p>
					<p class="text-cinza mt-1 text-sm">
						Lance sob o item do edital que corresponde ao seu título, com o comprovante em PDF. A
						nota de cada lançamento é calculada pelo servidor, e o limite vale sobre a soma dos
						lançamentos do item — não sobre cada um.
					</p>

					{#if secoesDoBarema.length === 0}
						<p class="text-cinza mt-4 text-sm">
							O barema deste nível ainda não foi montado pela secretaria.
						</p>
					{/if}

					{#each secoesDoBarema as secao (secao.valor)}
						<h3 class="text-grafite mt-6 text-[0.9375rem] font-semibold">{secao.rotulo}</h3>
						{#each secao.linhas as linha (linha.item.id)}
							<article class="border-borda mt-3 border p-4">
								<p class="text-grafite text-sm font-semibold">{rotuloDoItem(linha.item)}</p>

								{#if linha.lancamentos.length === 0}
									<p class="text-cinza mt-2 text-sm">Nenhum lançamento neste item.</p>
								{:else}
									<table class="mt-2 w-full text-sm">
										<thead>
											<tr class="border-borda border-b text-left">
												<th class="etiqueta py-2">Descrição</th>
												<th class="etiqueta py-2 text-right">{linha.item.unit_label}</th>
												<th class="etiqueta py-2 text-right">Nota</th>
												<th class="etiqueta py-2">Comprovante</th>
												<th class="etiqueta py-2"><span class="sr-only">Ações</span></th>
											</tr>
										</thead>
										<tbody>
											{#each linha.lancamentos as lancamento (lancamento.id)}
												<tr class="border-borda text-grafite border-b">
													<td class="py-2 align-top">{lancamento.description}</td>
													<td class="py-2 text-right align-top">
														{formatarNota(lancamento.quantity)}
													</td>
													<td class="py-2 text-right align-top">
														{formatarNota(lancamento.candidate_score)}
													</td>
													<td class="py-2 align-top">
														<!-- eslint-disable svelte/no-navigation-without-resolve -->
														<a
															class="underline"
															href={`/api/v1/scholarships/entries/${lancamento.id}/proof/download`}
														>
															<Icone nome="documento" tamanho={14} rotulo="Baixar" />
															{lancamento.proof_filename}
														</a>
														<!-- eslint-enable svelte/no-navigation-without-resolve -->
													</td>
													<td class="py-2 text-right align-top">
														{#if janelaAberta && podeEditarLancamento}
															{#if removendoLancamento === lancamento.id}
																<span class="flex flex-wrap justify-end gap-2">
																	<button
																		class="botao-discreto"
																		type="button"
																		disabled={salvando}
																		onclick={() => removerLancamento(lancamento)}
																	>
																		Excluir mesmo assim
																	</button>
																	<button
																		class="botao-discreto"
																		type="button"
																		onclick={() => (removendoLancamento = null)}
																	>
																		Cancelar
																	</button>
																</span>
															{:else if trocandoComprovante === lancamento.id}
																<span class="flex flex-wrap justify-end gap-2">
																	<input
																		class="campo"
																		type="file"
																		accept={ACEITA_COMPROVANTE}
																		onchange={(e) => trocarComprovante(lancamento, e)}
																		aria-label="Novo comprovante do lançamento"
																	/>
																	<button
																		class="botao-discreto"
																		type="button"
																		onclick={() => (trocandoComprovante = null)}
																	>
																		Cancelar
																	</button>
																</span>
															{:else}
																<span class="flex flex-wrap justify-end gap-2">
																	<button
																		class="botao-discreto"
																		type="button"
																		onclick={() => editarLancamento(lancamento)}
																	>
																		Corrigir
																	</button>
																	<button
																		class="botao-discreto"
																		type="button"
																		onclick={() => (trocandoComprovante = lancamento.id)}
																	>
																		Trocar comprovante
																	</button>
																	<button
																		class="botao-discreto"
																		type="button"
																		onclick={() => (removendoLancamento = lancamento.id)}
																	>
																		Excluir
																	</button>
																</span>
															{/if}
														{/if}
													</td>
												</tr>
											{/each}
										</tbody>
									</table>
								{/if}

								{#if janelaAberta && podeLancar && itemDoFormulario !== linha.item.id}
									<button
										class="botao-discreto mt-3"
										type="button"
										onclick={() => abrirLancamento(linha.item)}
									>
										Lançar neste item
									</button>
								{/if}

								{#if itemDoFormulario === linha.item.id}
									<form
										class="border-borda mt-3 border border-dashed p-4"
										onsubmit={salvarLancamento}
									>
										<p class="etiqueta">
											{editandoLancamento ? 'Corrigir lançamento' : 'Novo lançamento'}
										</p>
										<div class="mt-3 grid gap-4 sm:grid-cols-2">
											<div class="sm:col-span-2">
												<label class="etiqueta mb-2 block" for="lancamento-descricao">
													Descrição
												</label>
												<input
													id="lancamento-descricao"
													class="campo"
													type="text"
													bind:value={descricao}
													required
												/>
											</div>
											<div>
												<label class="etiqueta mb-2 block" for="lancamento-quantidade">
													Quantidade ({linha.item.unit_label.toLocaleLowerCase('pt-BR')})
												</label>
												<input
													id="lancamento-quantidade"
													class="campo"
													type="number"
													step="0.01"
													min="0"
													bind:value={quantidade}
													required
												/>
											</div>
											{#if editandoLancamento === null}
												<div>
													<label class="etiqueta mb-2 block" for="lancamento-comprovante">
														Comprovante (PDF)
													</label>
													<input
														id="lancamento-comprovante"
														class="campo"
														type="file"
														accept={ACEITA_COMPROVANTE}
														onchange={escolherComprovante}
														required
													/>
												</div>
											{/if}
										</div>
										{#if editandoLancamento}
											<p class="text-cinza mt-3 text-sm">
												O comprovante não muda por aqui: use "Trocar comprovante", ao lado do
												lançamento.
											</p>
										{/if}
										<div class="mt-4 flex items-center gap-2">
											<button class="botao" type="submit" disabled={salvando}>
												{salvando ? 'Salvando…' : 'Salvar lançamento'}
											</button>
											<button
												class="botao-discreto"
												type="button"
												onclick={fecharFormularioDoLancamento}
											>
												Cancelar
											</button>
										</div>
									</form>
								{/if}
							</article>
						{/each}
					{/each}
				</section>
			{/if}
		{/if}
	{/if}
{/if}
