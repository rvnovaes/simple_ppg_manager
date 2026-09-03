<script lang="ts">
	import { api, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';
	import Icone from '$lib/Icone.svelte';
	import {
		CRONOGRAMA,
		NIVEIS,
		SECOES,
		UNIDADES,
		formatarData,
		type CampoDeData,
		type Nivel,
		type Secao,
		type Unidade
	} from '$lib/bolsas';
	import { sessao } from '$lib/sessao.svelte';

	type Edicao = components['schemas']['ScholarshipEditionOut'];
	type Item = components['schemas']['BaremeItemOut'];
	type Membro = components['schemas']['CommitteeMemberOut'];
	type Docente = components['schemas']['TeacherOut'];

	let edicoes = $state<Edicao[]>([]);
	let itens = $state<Item[]>([]);
	let membros = $state<Membro[]>([]);
	let docentes = $state<Docente[]>([]);

	let carregando = $state(true);
	let erro = $state('');
	let aviso = $state('');
	let salvando = $state(false);

	let edicaoId = $state<number | null>(null);
	const edicao = $derived(edicoes.find((e) => e.id === edicaoId) ?? null);

	// O barema só aceita escrita com a edição em rascunho (409
	// `edition_not_draft` no backend). Quem responde é o servidor, resolvido
	// em `bareme_editable` — a tela não remonta a máquina de estados, só
	// deixa de oferecer o botão que levaria ao erro.
	const baremaEditavel = $derived(edicao?.bareme_editable ?? false);

	// Coordenação só acompanha: sem a permissão de escrita o formulário nem
	// existe na tela.
	const podeCriarEdicao = $derived(sessao.pode('scholarships.add_scholarshipedition'));
	const podeEditarEdicao = $derived(sessao.pode('scholarships.change_scholarshipedition'));
	const podeEditarBarema = $derived(sessao.pode('scholarships.add_baremeitem'));
	const podeEditarComissao = $derived(sessao.pode('scholarships.add_committeemember'));
	// A lista de professores é de outro app: quem não tem `view_teacher` vê a
	// comissão do ano, mas não o formulário que a compõe.
	const podeVerDocentes = $derived(sessao.pode('academic.view_teacher'));

	// --- carregamento ------------------------------------------------------

	async function carregarEdicoes(selecionar?: number) {
		const { data, error } = await api.GET('/scholarships/editions/');
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar as edições do programa.');
			return;
		}
		edicoes = data?.items ?? [];
		edicaoId = selecionar ?? edicoes[0]?.id ?? null;
	}

	async function carregarEdicao(alvo: number) {
		const [barema, comissao] = await Promise.all([
			api.GET('/scholarships/editions/{edition_id}/bareme/', {
				params: { path: { edition_id: alvo } }
			}),
			api.GET('/scholarships/editions/{edition_id}/committee/', {
				params: { path: { edition_id: alvo } }
			})
		]);
		const falha = barema.error ?? comissao.error;
		if (falha) {
			erro = mensagemDeErro(falha, 'Não foi possível carregar o barema e a comissão da edição.');
			return;
		}
		itens = barema.data ?? [];
		membros = comissao.data ?? [];
	}

	async function carregarDocentes() {
		if (!podeVerDocentes) return;
		const { data, error } = await api.GET('/academic/teachers/', {
			// A comissão é da portaria do ano inteiro: paginar aqui obrigaria a
			// secretaria a procurar o professor em páginas.
			params: { query: { limit: 500 } }
		});
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar os professores do programa.');
			return;
		}
		docentes = data?.items ?? [];
	}

	async function carregar() {
		carregando = true;
		erro = '';
		await Promise.all([carregarEdicoes(), carregarDocentes()]);
		if (edicaoId !== null) await carregarEdicao(edicaoId);
		carregando = false;
	}

	async function trocarDeEdicao(alvo: number) {
		edicaoId = alvo;
		itens = [];
		membros = [];
		erro = '';
		aviso = '';
		formDaEdicao = false;
		formDoItem = false;
		formDaClonagem = false;
		formDoMembro = false;
		await carregarEdicao(alvo);
	}

	/** Reflete no estado local a edição que a API devolveu. */
	function substituirEdicao(salva: Edicao) {
		const conhecida = edicoes.some((e) => e.id === salva.id);
		edicoes = conhecida ? edicoes.map((e) => (e.id === salva.id ? salva : e)) : [salva, ...edicoes];
		edicaoId = salva.id;
	}

	// --- formulário da edição e do cronograma ------------------------------

	let formDaEdicao = $state(false);
	let editandoEdicao = $state<Edicao | null>(null);
	let ano = $state(new Date().getFullYear() + 1);
	let titulo = $state('');
	// As cinco datas num registro só: o formulário percorre `CRONOGRAMA` em
	// vez de repetir cinco pares de `let`/`<input>` iguais.
	let datas = $state<Record<CampoDeData, string>>({
		submission_starts_on: '',
		submission_ends_on: '',
		preliminary_result_on: '',
		appeal_ends_on: '',
		final_result_on: ''
	});

	function limparDatas() {
		datas = {
			submission_starts_on: '',
			submission_ends_on: '',
			preliminary_result_on: '',
			appeal_ends_on: '',
			final_result_on: ''
		};
	}

	function abrirNovaEdicao() {
		editandoEdicao = null;
		ano = new Date().getFullYear() + 1;
		titulo = '';
		limparDatas();
		erro = '';
		aviso = '';
		formDaEdicao = true;
	}

	function editarEdicao(alvo: Edicao) {
		editandoEdicao = alvo;
		ano = alvo.year;
		titulo = alvo.title;
		datas = {
			submission_starts_on: alvo.submission_starts_on ?? '',
			submission_ends_on: alvo.submission_ends_on ?? '',
			preliminary_result_on: alvo.preliminary_result_on ?? '',
			appeal_ends_on: alvo.appeal_ends_on ?? '',
			final_result_on: alvo.final_result_on ?? ''
		};
		erro = '';
		aviso = '';
		formDaEdicao = true;
	}

	/**
	 * As cinco datas fora de ordem.
	 *
	 * Validação de UX apenas, e frouxa de propósito: data em branco não é
	 * erro (o cronograma é fechado aos poucos) e o backend não cobra a ordem
	 * — cronograma é informação publicada, não gatilho. Quem publica errado
	 * corrige pelo mesmo formulário, em qualquer estado.
	 */
	const cronogramaForaDeOrdem = $derived.by<string>(() => {
		const preenchidas = CRONOGRAMA.map(({ campo }) => datas[campo]).filter((d) => d !== '');
		const ordenadas = [...preenchidas].sort();
		return preenchidas.every((d, i) => d === ordenadas[i])
			? ''
			: 'As datas do cronograma estão fora da ordem do edital.';
	});

	async function salvarEdicao(event: SubmitEvent) {
		event.preventDefault();
		erro = '';
		aviso = '';
		salvando = true;
		// `null` explícito, e não campo ausente: é assim que a secretaria
		// apaga uma data já divulgada (o PATCH usa `exclude_unset`, sem
		// `exclude_none`).
		const corpo = {
			year: ano,
			title: titulo,
			submission_starts_on: datas.submission_starts_on || null,
			submission_ends_on: datas.submission_ends_on || null,
			preliminary_result_on: datas.preliminary_result_on || null,
			appeal_ends_on: datas.appeal_ends_on || null,
			final_result_on: datas.final_result_on || null
		};
		const alvo = editandoEdicao;
		const resposta = alvo
			? await api.PATCH('/scholarships/editions/{edition_id}/', {
					params: { path: { edition_id: alvo.id } },
					body: corpo
				})
			: await api.POST('/scholarships/editions/', { body: corpo });
		salvando = false;
		// A falha sai para uma const ANTES do `if`: dentro dele o objeto
		// inteiro é estreitado e `resposta.error` viraria `never`.
		const falha = resposta.error;
		if (falha || !resposta.data) {
			erro = mensagemDeErro(falha, 'Não foi possível salvar a edição.');
			return;
		}
		substituirEdicao(resposta.data);
		formDaEdicao = false;
		editandoEdicao = null;
		aviso = alvo ? 'Edição corrigida.' : 'Edição aberta em rascunho.';
		await carregarEdicao(resposta.data.id);
	}

	// --- as cinco transições -----------------------------------------------

	/**
	 * O próximo ato da edição, um por estado.
	 *
	 * Uma entrada por transição, com a permissão que cada uma exige:
	 * publicar é `publish_scholarshipedition` e não `change_`, porque
	 * publicar congela o ano e quem monta o edital não é necessariamente
	 * quem assina a lista. A recusa que vale continua sendo a do backend
	 * (409 com `code`); isto aqui só evita o clique que já se sabe perdido.
	 */
	type Transicao = {
		rotulo: string;
		permissao: string;
		consequencia: string;
	};

	const TRANSICOES: Partial<Record<Edicao['status'], Transicao>> = {
		draft: {
			rotulo: 'Abrir inscrições',
			permissao: 'scholarships.change_scholarshipedition',
			consequencia:
				'O barema fica congelado a partir de agora — nenhum item entra, sai ou muda de pontuação — e os discentes passam a se inscrever.'
		},
		submissions_open: {
			rotulo: 'Encerrar inscrições',
			permissao: 'scholarships.change_scholarshipedition',
			consequencia:
				'Ninguém mais se inscreve nem altera lançamento, e a fila vai para a Comissão de Bolsas analisar.'
		},
		under_review: {
			rotulo: 'Publicar resultado preliminar',
			permissao: 'scholarships.publish_scholarshipedition',
			consequencia:
				'A classificação dos dois níveis é calculada e congelada como lista publicada, com o sorteio dos empates. O candidato passa a ver a própria colocação.'
		},
		preliminary_result: {
			rotulo: 'Abrir recursos',
			permissao: 'scholarships.change_scholarshipedition',
			consequencia:
				'O candidato passa a interpor recurso e a comissão a julgá-lo. A lista preliminar continua publicada.'
		},
		appeals_under_review: {
			rotulo: 'Publicar resultado final',
			permissao: 'scholarships.publish_scholarshipedition',
			consequencia:
				'A lista é recalculada com o que os recursos mudaram, na mesma semente de sorteio, e publicada como resultado final. É o último ato da edição.'
		}
	};

	const transicao = $derived(edicao === null ? undefined : TRANSICOES[edicao.status]);
	const podeTransicionar = $derived(transicao !== undefined && sessao.pode(transicao.permissao));

	let confirmandoTransicao = $state(false);

	async function transicionar() {
		const alvo = edicao;
		if (alvo === null) return;
		erro = '';
		aviso = '';
		salvando = true;
		// Uma rota nomeada por ato, e não um PATCH de `status`: o `switch`
		// existe porque o cliente tipado exige o caminho literal.
		const resposta = await (async () => {
			switch (alvo.status) {
				case 'draft':
					return api.POST('/scholarships/editions/{edition_id}/open-submissions', {
						params: { path: { edition_id: alvo.id } }
					});
				case 'submissions_open':
					return api.POST('/scholarships/editions/{edition_id}/start-review', {
						params: { path: { edition_id: alvo.id } }
					});
				case 'under_review':
					return api.POST('/scholarships/editions/{edition_id}/publish-preliminary', {
						params: { path: { edition_id: alvo.id } }
					});
				case 'preliminary_result':
					return api.POST('/scholarships/editions/{edition_id}/open-appeals', {
						params: { path: { edition_id: alvo.id } }
					});
				case 'appeals_under_review':
					return api.POST('/scholarships/editions/{edition_id}/publish-final', {
						params: { path: { edition_id: alvo.id } }
					});
				default:
					return null;
			}
		})();
		salvando = false;
		confirmandoTransicao = false;
		if (resposta === null) return;
		const falha = resposta.error;
		if (falha || !resposta.data) {
			erro = mensagemDeErro(falha, 'Não foi possível mover a edição.');
			return;
		}
		substituirEdicao(resposta.data);
		aviso = `Edição agora em "${resposta.data.status_label}".`;
	}

	// --- barema --------------------------------------------------------------

	let nivel = $state<Nivel>('masters');
	const itensDoNivel = $derived(itens.filter((i) => i.level === nivel));

	/** O barema do nível agrupado por seção, na ordem dos incisos. */
	const secoesDoNivel = $derived(
		SECOES.map(({ valor, rotulo }) => ({
			valor,
			rotulo,
			linhas: itensDoNivel.filter((i) => i.section === valor)
		})).filter((s) => s.linhas.length > 0)
	);

	let formDoItem = $state(false);
	let editandoItem = $state<Item | null>(null);
	let secaoDoItem = $state<Secao>('formation');
	let codigoDoItem = $state('');
	let textoDoItem = $state('');
	let unidadeDoItem = $state<Unidade>('unit');
	let pontosDoItem = $state('0');
	let tetoDoItem = $state('0');

	function abrirNovoItem() {
		editandoItem = null;
		secaoDoItem = 'formation';
		codigoDoItem = '';
		textoDoItem = '';
		unidadeDoItem = 'unit';
		pontosDoItem = '0';
		tetoDoItem = '0';
		erro = '';
		formDoItem = true;
	}

	function editarItem(alvo: Item) {
		editandoItem = alvo;
		secaoDoItem = alvo.section;
		codigoDoItem = alvo.code;
		textoDoItem = alvo.text;
		unidadeDoItem = alvo.unit;
		pontosDoItem = alvo.points_per_unit;
		tetoDoItem = alvo.cap;
		erro = '';
		formDoItem = true;
	}

	async function salvarItem(event: SubmitEvent) {
		event.preventDefault();
		if (edicaoId === null) return;
		erro = '';
		aviso = '';
		salvando = true;
		const corpo = {
			// O nível é o da aba, e não um campo do formulário: mestrado e
			// doutorado são baremas independentes, e um `<select>` a mais aqui
			// só criaria a chance de gravar item de doutorado no mestrado.
			level: nivel,
			section: secaoDoItem,
			code: codigoDoItem,
			text: textoDoItem,
			unit: unidadeDoItem,
			points_per_unit: pontosDoItem,
			cap: tetoDoItem
		};
		const alvo = editandoItem;
		const resposta = alvo
			? await api.PATCH('/scholarships/editions/{edition_id}/bareme/{item_id}/', {
					params: { path: { edition_id: edicaoId, item_id: alvo.id } },
					body: corpo
				})
			: await api.POST('/scholarships/editions/{edition_id}/bareme/', {
					params: { path: { edition_id: edicaoId } },
					body: corpo
				});
		salvando = false;
		const falha = resposta.error;
		if (falha || !resposta.data) {
			erro = mensagemDeErro(falha, 'Não foi possível salvar o item do barema.');
			return;
		}
		const salvo = resposta.data;
		itens = alvo ? itens.map((i) => (i.id === salvo.id ? salvo : i)) : [...itens, salvo];
		formDoItem = false;
		editandoItem = null;
	}

	let removendoItem = $state<number | null>(null);

	async function removerItem(alvo: Item) {
		if (edicaoId === null) return;
		erro = '';
		aviso = '';
		salvando = true;
		const { error } = await api.DELETE('/scholarships/editions/{edition_id}/bareme/{item_id}/', {
			params: { path: { edition_id: edicaoId, item_id: alvo.id } }
		});
		salvando = false;
		removendoItem = null;
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível remover o item do barema.');
			return;
		}
		itens = itens.filter((i) => i.id !== alvo.id);
	}

	// --- clonar o barema de outra edição -------------------------------------

	let formDaClonagem = $state(false);
	let origemDaClonagem = $state<number | null>(null);

	// Qualquer outra edição do mesmo programa serve de origem — tipicamente a
	// do ano anterior, que é o caso que economiza a digitação inteira.
	const origensPossiveis = $derived(edicoes.filter((e) => e.id !== edicaoId));

	function abrirClonagem() {
		origemDaClonagem = origensPossiveis[0]?.id ?? null;
		erro = '';
		aviso = '';
		formDaClonagem = true;
	}

	async function clonarBarema(event: SubmitEvent) {
		event.preventDefault();
		if (edicaoId === null || origemDaClonagem === null) return;
		erro = '';
		aviso = '';
		salvando = true;
		const { data, error } = await api.POST('/scholarships/editions/{edition_id}/bareme/clone', {
			params: { path: { edition_id: edicaoId } },
			body: { source_edition_id: origemDaClonagem }
		});
		salvando = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível clonar o barema.');
			return;
		}
		// A resposta traz o barema completo do destino: a lista se refaz sem
		// uma segunda chamada, e `created` é o número que a secretaria confere
		// contra o edital do ano anterior.
		itens = data.items;
		formDaClonagem = false;
		aviso = `${data.created} item(ns) copiado(s) do barema da edição escolhida.`;
	}

	// --- comissão -------------------------------------------------------------

	let formDoMembro = $state(false);
	let docenteDoMembro = $state<number | null>(null);
	let designadoEm = $state('');
	let portaria = $state('');

	const docentesDisponiveis = $derived(
		docentes.filter((d) => !membros.some((m) => m.teacher_id === d.id))
	);

	function abrirNovoMembro() {
		docenteDoMembro = docentesDisponiveis[0]?.id ?? null;
		designadoEm = '';
		portaria = '';
		erro = '';
		aviso = '';
		formDoMembro = true;
	}

	async function salvarMembro(event: SubmitEvent) {
		event.preventDefault();
		if (edicaoId === null || docenteDoMembro === null) return;
		erro = '';
		aviso = '';
		salvando = true;
		const { data, error } = await api.POST('/scholarships/editions/{edition_id}/committee/', {
			params: { path: { edition_id: edicaoId } },
			body: {
				teacher_id: docenteDoMembro,
				appointed_on: designadoEm === '' ? null : designadoEm,
				ordinance: portaria
			}
		});
		salvando = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível designar o membro da comissão.');
			return;
		}
		membros = [...membros, data];
		formDoMembro = false;
	}

	let removendoMembro = $state<number | null>(null);

	async function removerMembro(alvo: Membro) {
		if (edicaoId === null) return;
		erro = '';
		aviso = '';
		salvando = true;
		const { error } = await api.DELETE(
			'/scholarships/editions/{edition_id}/committee/{member_id}/',
			{ params: { path: { edition_id: edicaoId, member_id: alvo.id } } }
		);
		salvando = false;
		removendoMembro = null;
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível retirar o membro da comissão.');
			return;
		}
		membros = membros.filter((m) => m.id !== alvo.id);
	}

	$effect(() => {
		carregar();
	});
</script>

<svelte:head>
	<title>Edital de bolsas · PPGM</title>
</svelte:head>

<header class="flex flex-wrap items-end justify-between gap-4">
	<div>
		<p class="etiqueta">Bolsas</p>
		<h1 class="text-grafite mt-1 text-2xl font-semibold tracking-tight">Edital</h1>
	</div>
	{#if podeCriarEdicao}
		<button class="botao-discreto" type="button" onclick={abrirNovaEdicao}>Nova edição</button>
	{/if}
</header>

{#if erro}
	<p class="aviso-erro mt-6" role="alert">{erro}</p>
{/if}
{#if aviso}
	<p class="border-borda bg-papel text-grafite mt-6 border px-4 py-3 text-sm" role="status">
		{aviso}
	</p>
{/if}

{#if formDaEdicao}
	<form class="border-borda bg-papel mt-6 border p-5" onsubmit={salvarEdicao}>
		<p class="etiqueta">{editandoEdicao ? 'Corrigir edição' : 'Nova edição'}</p>
		<div class="mt-4 grid gap-4 sm:grid-cols-2">
			<div>
				<label class="etiqueta mb-2 block" for="edicao-ano">Ano</label>
				<input id="edicao-ano" class="campo" type="number" min="2000" bind:value={ano} required />
			</div>
			<div>
				<label class="etiqueta mb-2 block" for="edicao-titulo">Título</label>
				<input id="edicao-titulo" class="campo" type="text" bind:value={titulo} required />
			</div>
			{#each CRONOGRAMA as { campo, rotulo } (campo)}
				<div>
					<label class="etiqueta mb-2 block" for={`edicao-${campo}`}>{rotulo}</label>
					<input id={`edicao-${campo}`} class="campo" type="date" bind:value={datas[campo]} />
				</div>
			{/each}
		</div>
		<p class="text-cinza mt-4 text-sm">
			O cronograma é informação publicada, não gatilho: nada abre ou fecha sozinho na data. Quem
			move a edição é a secretaria, pelo botão do próximo ato — e por isso data em branco não impede
			nada.
		</p>
		{#if cronogramaForaDeOrdem !== ''}
			<p class="text-cinza mt-2 text-sm">{cronogramaForaDeOrdem}</p>
		{/if}
		<div class="mt-4 flex items-center gap-2">
			<button class="botao" type="submit" disabled={salvando}>
				{salvando ? 'Salvando…' : 'Salvar edição'}
			</button>
			<button class="botao-discreto" type="button" onclick={() => (formDaEdicao = false)}>
				Cancelar
			</button>
		</div>
	</form>
{/if}

{#if carregando}
	<p class="etiqueta mt-6">Carregando…</p>
{:else if edicoes.length === 0}
	<div class="border-borda bg-papel mt-6 border border-dashed p-10 text-center">
		<p class="text-grafite text-[0.9375rem]">
			Nenhuma edição do edital de bolsas cadastrada ainda.
		</p>
		<p class="text-cinza mt-1 text-sm">
			{podeCriarEdicao
				? 'A edição reúne o cronograma, o barema dos dois níveis e a comissão do ano. Sem ela ninguém se inscreve.'
				: 'A secretaria ainda não abriu a edição deste ano.'}
		</p>
	</div>
{:else}
	<div class="mt-8 grid gap-4 sm:grid-cols-[1fr_auto]">
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
		{#if edicao}
			<div class="flex flex-wrap items-end gap-2">
				{#if podeEditarEdicao}
					<button class="botao-discreto" type="button" onclick={() => editarEdicao(edicao)}>
						Corrigir edição
					</button>
				{/if}
				{#if transicao && podeTransicionar}
					<button
						class="botao-discreto"
						type="button"
						onclick={() => (confirmandoTransicao = true)}
					>
						{transicao.rotulo}
					</button>
				{/if}
			</div>
		{/if}
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
				<div>
					<dt class="etiqueta">Publicação</dt>
					<dd>
						{edicao.published_preliminary_at
							? `preliminar em ${new Date(edicao.published_preliminary_at).toLocaleDateString('pt-BR')}`
							: 'preliminar não publicado'}{edicao.published_final_at
							? ` · final em ${new Date(edicao.published_final_at).toLocaleDateString('pt-BR')}`
							: ''}
					</dd>
				</div>
				<div>
					<dt class="etiqueta">PDF do edital</dt>
					<dd>
						{#if edicao.notice_url}
							<!-- O PDF é URL de MEDIA servida pelo Nginx, e não rota da SPA:
							`resolve()` não se aplica. Continua relativa — origem única
							(ADR-004). -->
							<!-- eslint-disable svelte/no-navigation-without-resolve -->
							<a class="underline" href={edicao.notice_url} target="_blank" rel="noopener">
								<Icone nome="documento" tamanho={14} rotulo="Abrir PDF" />
								{edicao.notice_filename}
							</a>
							<!-- eslint-enable svelte/no-navigation-without-resolve -->
						{:else}
							<span class="text-cinza">Nenhum arquivo anexado.</span>
						{/if}
					</dd>
				</div>
			</dl>
			{#if !baremaEditavel}
				<p class="text-cinza mt-4 text-sm">
					O barema desta edição está congelado desde a abertura das inscrições: ele é a régua com
					que os lançamentos já foram pontuados.
				</p>
			{/if}
		</section>

		{#if confirmandoTransicao && transicao}
			<section class="border-borda bg-papel mt-4 border p-5" role="alertdialog">
				<p class="etiqueta">{transicao.rotulo} · {edicao.title}</p>
				<p class="text-grafite mt-3 text-sm">
					{transicao.consequencia} A edição só anda para frente: não há volta ao estado anterior.
				</p>
				<div class="mt-4 flex items-center gap-2">
					<button class="botao" type="button" disabled={salvando} onclick={transicionar}>
						{salvando ? 'Aplicando…' : `${transicao.rotulo} mesmo assim`}
					</button>
					<button
						class="botao-discreto"
						type="button"
						onclick={() => (confirmandoTransicao = false)}
					>
						Cancelar
					</button>
				</div>
			</section>
		{/if}

		<!-- Barema ------------------------------------------------------------ -->
		<section class="border-borda bg-papel mt-6 border p-5">
			<div class="flex flex-wrap items-center justify-between gap-4">
				<div>
					<p class="etiqueta">Barema</p>
					<p class="text-cinza mt-1 text-sm">
						Mestrado e doutorado são listas independentes, cada uma com os seus seis incisos.
					</p>
				</div>
				<div class="flex flex-wrap items-center gap-2">
					{#each NIVEIS as opcao (opcao.valor)}
						<button
							class={nivel === opcao.valor ? 'botao' : 'botao-discreto'}
							type="button"
							aria-pressed={nivel === opcao.valor}
							onclick={() => {
								nivel = opcao.valor;
								formDoItem = false;
							}}
						>
							{opcao.rotulo}
						</button>
					{/each}
				</div>
			</div>

			{#if podeEditarBarema && baremaEditavel}
				<div class="mt-4 flex flex-wrap items-center gap-2">
					<button class="botao-discreto" type="button" onclick={abrirNovoItem}>Novo item</button>
					{#if origensPossiveis.length > 0}
						<button class="botao-discreto" type="button" onclick={abrirClonagem}>
							Clonar de outra edição
						</button>
					{/if}
				</div>
			{/if}

			{#if formDaClonagem}
				<form class="border-borda mt-4 border border-dashed p-4" onsubmit={clonarBarema}>
					<p class="etiqueta">Clonar barema</p>
					<p class="text-cinza mt-1 text-sm">
						Copia os itens dos dois níveis da edição escolhida para esta. Item de código repetido é
						recusado pelo servidor — a clonagem é para barema em branco.
					</p>
					<div class="mt-3">
						<label class="etiqueta mb-2 block" for="clone-origem">Copiar da edição</label>
						<select
							id="clone-origem"
							class="campo"
							value={origemDaClonagem}
							onchange={(e) => (origemDaClonagem = Number(e.currentTarget.value))}
						>
							{#each origensPossiveis as opcao (opcao.id)}
								<option value={opcao.id}>{opcao.year} · {opcao.title}</option>
							{/each}
						</select>
					</div>
					<div class="mt-4 flex items-center gap-2">
						<button class="botao" type="submit" disabled={salvando}>
							{salvando ? 'Copiando…' : 'Copiar barema'}
						</button>
						<button class="botao-discreto" type="button" onclick={() => (formDaClonagem = false)}>
							Cancelar
						</button>
					</div>
				</form>
			{/if}

			{#if formDoItem}
				<form class="border-borda mt-4 border border-dashed p-4" onsubmit={salvarItem}>
					<p class="etiqueta">
						{editandoItem ? 'Corrigir item' : 'Novo item'} · {NIVEIS.find((n) => n.valor === nivel)
							?.rotulo}
					</p>
					<div class="mt-3 grid gap-4 sm:grid-cols-2">
						<div>
							<label class="etiqueta mb-2 block" for="item-secao">Seção</label>
							<select id="item-secao" class="campo" bind:value={secaoDoItem} required>
								{#each SECOES as opcao (opcao.valor)}
									<option value={opcao.valor}>{opcao.rotulo}</option>
								{/each}
							</select>
						</div>
						<div>
							<label class="etiqueta mb-2 block" for="item-codigo">Código no edital</label>
							<input
								id="item-codigo"
								class="campo"
								type="text"
								bind:value={codigoDoItem}
								required
							/>
						</div>
						<div class="sm:col-span-2">
							<label class="etiqueta mb-2 block" for="item-texto">Descrição</label>
							<input id="item-texto" class="campo" type="text" bind:value={textoDoItem} required />
						</div>
						<div>
							<label class="etiqueta mb-2 block" for="item-unidade">Unidade</label>
							<select id="item-unidade" class="campo" bind:value={unidadeDoItem} required>
								{#each UNIDADES as opcao (opcao.valor)}
									<option value={opcao.valor}>{opcao.rotulo}</option>
								{/each}
							</select>
						</div>
						<div class="grid grid-cols-2 gap-4">
							<div>
								<label class="etiqueta mb-2 block" for="item-pontos">Pontos por unidade</label>
								<input
									id="item-pontos"
									class="campo"
									type="number"
									step="0.01"
									min="0"
									bind:value={pontosDoItem}
									required
								/>
							</div>
							<div>
								<label class="etiqueta mb-2 block" for="item-teto">Teto do item</label>
								<input
									id="item-teto"
									class="campo"
									type="number"
									step="0.01"
									min="0"
									bind:value={tetoDoItem}
									required
								/>
							</div>
						</div>
					</div>
					<p class="text-cinza mt-3 text-sm">
						O teto vale sobre a soma dos lançamentos do item, e não sobre cada lançamento.
					</p>
					<div class="mt-4 flex items-center gap-2">
						<button class="botao" type="submit" disabled={salvando}>
							{salvando ? 'Salvando…' : 'Salvar item'}
						</button>
						<button class="botao-discreto" type="button" onclick={() => (formDoItem = false)}>
							Cancelar
						</button>
					</div>
				</form>
			{/if}

			{#if itensDoNivel.length === 0}
				<p class="text-cinza mt-4 text-sm">
					Nenhum item no barema deste nível ainda.
					{#if podeEditarBarema && baremaEditavel && origensPossiveis.length > 0}
						Clonar a edição anterior costuma ser o caminho mais curto.
					{/if}
				</p>
			{:else}
				{#each secoesDoNivel as secao (secao.valor)}
					<h3 class="text-grafite mt-6 text-[0.9375rem] font-semibold">{secao.rotulo}</h3>
					<table class="mt-2 w-full text-sm">
						<thead>
							<tr class="border-borda border-b text-left">
								<th class="etiqueta py-2">Código</th>
								<th class="etiqueta py-2">Descrição</th>
								<th class="etiqueta py-2">Unidade</th>
								<th class="etiqueta py-2 text-right">Pontos</th>
								<th class="etiqueta py-2 text-right">Teto</th>
								<th class="etiqueta py-2"><span class="sr-only">Ações</span></th>
							</tr>
						</thead>
						<tbody>
							{#each secao.linhas as item (item.id)}
								<tr class="border-borda text-grafite border-b">
									<td class="py-2 align-top">{item.code}</td>
									<td class="py-2 align-top">{item.text}</td>
									<td class="py-2 align-top">{item.unit_label}</td>
									<td class="py-2 text-right align-top">{item.points_per_unit}</td>
									<td class="py-2 text-right align-top">{item.cap}</td>
									<td class="py-2 text-right align-top">
										{#if podeEditarBarema && baremaEditavel}
											{#if removendoItem === item.id}
												<span class="flex flex-wrap justify-end gap-2">
													<button
														class="botao-discreto"
														type="button"
														disabled={salvando}
														onclick={() => removerItem(item)}
													>
														Remover mesmo assim
													</button>
													<button
														class="botao-discreto"
														type="button"
														onclick={() => (removendoItem = null)}
													>
														Cancelar
													</button>
												</span>
											{:else}
												<span class="flex flex-wrap justify-end gap-2">
													<button
														class="botao-discreto"
														type="button"
														onclick={() => editarItem(item)}
													>
														Corrigir
													</button>
													<button
														class="botao-discreto"
														type="button"
														onclick={() => (removendoItem = item.id)}
													>
														Remover
													</button>
												</span>
											{/if}
										{/if}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				{/each}
			{/if}
		</section>

		<!-- Comissão ---------------------------------------------------------- -->
		<section class="border-borda bg-papel mt-6 border p-5">
			<div class="flex flex-wrap items-center justify-between gap-4">
				<div>
					<p class="etiqueta">Comissão de Bolsas</p>
					<p class="text-cinza mt-1 text-sm">
						Registro de quem compôs a comissão do ano, com a portaria. Não é o que dá acesso: quem
						avalia é quem está no papel "Comissão de Bolsas".
					</p>
				</div>
				{#if podeEditarComissao && podeVerDocentes && docentesDisponiveis.length > 0}
					<button class="botao-discreto" type="button" onclick={abrirNovoMembro}>
						Designar membro
					</button>
				{/if}
			</div>

			{#if formDoMembro}
				<form class="border-borda mt-4 border border-dashed p-4" onsubmit={salvarMembro}>
					<p class="etiqueta">Designar membro</p>
					<div class="mt-3 grid gap-4 sm:grid-cols-3">
						<div>
							<label class="etiqueta mb-2 block" for="membro-docente">Professor</label>
							<select
								id="membro-docente"
								class="campo"
								value={docenteDoMembro}
								onchange={(e) => (docenteDoMembro = Number(e.currentTarget.value))}
							>
								{#each docentesDisponiveis as opcao (opcao.id)}
									<option value={opcao.id}>{opcao.person.full_name}</option>
								{/each}
							</select>
						</div>
						<div>
							<label class="etiqueta mb-2 block" for="membro-data">Designado em</label>
							<input id="membro-data" class="campo" type="date" bind:value={designadoEm} />
						</div>
						<div>
							<label class="etiqueta mb-2 block" for="membro-portaria">Portaria</label>
							<input id="membro-portaria" class="campo" type="text" bind:value={portaria} />
						</div>
					</div>
					<div class="mt-4 flex items-center gap-2">
						<button class="botao" type="submit" disabled={salvando}>
							{salvando ? 'Salvando…' : 'Designar'}
						</button>
						<button class="botao-discreto" type="button" onclick={() => (formDoMembro = false)}>
							Cancelar
						</button>
					</div>
				</form>
			{/if}

			{#if membros.length === 0}
				<p class="text-cinza mt-4 text-sm">Nenhum membro designado nesta edição.</p>
			{:else}
				<table class="mt-4 w-full text-sm">
					<thead>
						<tr class="border-borda border-b text-left">
							<th class="etiqueta py-2">Professor</th>
							<th class="etiqueta py-2">Designado em</th>
							<th class="etiqueta py-2">Portaria</th>
							<th class="etiqueta py-2"><span class="sr-only">Ações</span></th>
						</tr>
					</thead>
					<tbody>
						{#each membros as membro (membro.id)}
							<tr class="border-borda text-grafite border-b">
								<td class="py-2 align-top">{membro.teacher_name}</td>
								<td class="py-2 align-top">{formatarData(membro.appointed_on)}</td>
								<td class="py-2 align-top">{membro.ordinance || '—'}</td>
								<td class="py-2 text-right align-top">
									{#if podeEditarComissao}
										{#if removendoMembro === membro.id}
											<span class="flex flex-wrap justify-end gap-2">
												<button
													class="botao-discreto"
													type="button"
													disabled={salvando}
													onclick={() => removerMembro(membro)}
												>
													Retirar mesmo assim
												</button>
												<button
													class="botao-discreto"
													type="button"
													onclick={() => (removendoMembro = null)}
												>
													Cancelar
												</button>
											</span>
										{:else}
											<button
												class="botao-discreto"
												type="button"
												onclick={() => (removendoMembro = membro.id)}
											>
												Retirar
											</button>
										{/if}
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}
		</section>
	{/if}
{/if}
