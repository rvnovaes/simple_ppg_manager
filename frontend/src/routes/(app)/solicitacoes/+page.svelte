<script lang="ts">
	import { api, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';
	import {
		ORDEM_DAS_SITUACOES,
		ROTULO_DA_CATEGORIA,
		ROTULO_DA_SITUACAO,
		ROTULO_DA_TITULACAO,
		ROTULO_DO_PERFIL,
		type CategoriaDocente,
		type Perfil,
		type SituacaoDoCadastro,
		type Titulacao
	} from '$lib/acesso';

	type Solicitacao = components['schemas']['AccessRequestOut'];
	type Professor = components['schemas']['TeacherOut'];
	type Projeto = components['schemas']['CollectiveProjectOut'];
	type Nivel = components['schemas']['Level'];

	// Espelho do que a tela de alunos oferece: o vínculo que nasce daqui é
	// sempre regular, e regular só existe em mestrado e doutorado.
	const NIVEIS: { valor: Nivel; rotulo: string }[] = [
		{ valor: 'masters', rotulo: 'Mestrado' },
		{ valor: 'doctorate', rotulo: 'Doutorado' }
	];

	let solicitacoes = $state<Solicitacao[]>([]);
	let professores = $state<Professor[]>([]);
	let projetos = $state<Projeto[]>([]);

	let carregando = $state(true);
	let decidindo = $state(false);
	let erro = $state('');
	let aviso = $state('');

	// Filtro do servidor, e não da tela: a fila é paginada, e filtrar depois
	// de paginar mostraria "3 de 40" de uma página só. O default `pending` é
	// o do próprio endpoint — a fila existe para o que falta decidir.
	let filtroDeSituacao = $state<SituacaoDoCadastro>('pending');

	// Uma solicitação aberta por vez: a decisão é sobre uma pessoa só, e o
	// painel carrega os campos que a secretaria preenche na hora.
	let abertoId = $state<number | null>(null);

	// Campos da confirmação. Ficam fora do painel para zerar a cada abertura:
	// a data de credenciamento de um docente não pode vazar para o próximo.
	let credenciadoDesde = $state('');
	let nivel = $state<Nivel>('masters');
	let projetoId = $state<number | ''>('');
	let orientadorId = $state<number | ''>('');
	let ingresso = $state('');
	let motivo = $state('');

	const aberto = $derived(solicitacoes.find((s) => s.id === abertoId) ?? null);

	const nomeDoOrientador = $derived.by(() => {
		const nomes: Record<number, string> = {};
		for (const professor of professores) nomes[professor.id] = professor.person.full_name;
		return nomes;
	});

	function formatarData(iso: string | null): string {
		return iso === null ? '—' : new Date(iso).toLocaleDateString('pt-BR');
	}

	function rotuloDoPerfil(valor: string): string {
		return ROTULO_DO_PERFIL[valor as Perfil] ?? valor;
	}

	function rotuloDaSituacao(valor: string): string {
		return ROTULO_DA_SITUACAO[valor as SituacaoDoCadastro] ?? valor;
	}

	async function carregar(situacao: SituacaoDoCadastro) {
		carregando = true;
		erro = '';
		const resposta = await api.GET('/access/requests/', {
			params: { query: { status: situacao } }
		});
		// A falha sai do objeto ANTES do `if`: a rota não declara resposta de
		// erro no OpenAPI e dentro do bloco o objeto inteiro vira `never`.
		const falha = resposta.error;
		carregando = false;
		if (falha) {
			erro = mensagemDeErro(falha, 'Não foi possível carregar as solicitações de acesso.');
			return;
		}
		solicitacoes = (resposta.data?.items ?? [])
			.slice()
			.sort((a, b) => a.person_name.localeCompare(b.person_name, 'pt-BR'));
	}

	/**
	 * Professores e projetos do programa, para os selects do discente.
	 *
	 * Só na primeira vez que um discente é aberto: a fila costuma ser de
	 * docentes, e duas listas inteiras a cada abertura seriam duas consultas
	 * que ninguém leu.
	 */
	async function carregarVinculos() {
		if (professores.length > 0 || projetos.length > 0) return;
		const [respProfessores, respProjetos] = await Promise.all([
			api.GET('/academic/teachers/'),
			api.GET('/programs/collective-projects/')
		]);
		const falha = respProfessores.error ?? respProjetos.error;
		if (falha) {
			erro = mensagemDeErro(falha, 'Não foi possível carregar orientadores e projetos.');
			return;
		}
		professores = respProfessores.data?.items ?? [];
		projetos = (respProjetos.data?.items ?? []).filter((p) => p.is_active);
	}

	async function abrir(solicitacao: Solicitacao) {
		if (abertoId === solicitacao.id) {
			abertoId = null;
			return;
		}
		abertoId = solicitacao.id;
		erro = '';
		aviso = '';
		credenciadoDesde = '';
		nivel = 'masters';
		projetoId = '';
		orientadorId = '';
		ingresso = '';
		motivo = '';
		if (solicitacao.profile === 'student') await carregarVinculos();
	}

	/**
	 * Tira a solicitação decidida da lista quando ela deixa de casar com o
	 * filtro — que é o caso normal, porque o filtro parte de "pendente".
	 * Deixá-la na tela com a situação nova daria a impressão de que a fila
	 * do servidor ainda a contém.
	 */
	function retirar(decidida: Solicitacao) {
		abertoId = null;
		solicitacoes =
			decidida.status === filtroDeSituacao
				? solicitacoes.map((s) => (s.id === decidida.id ? decidida : s))
				: solicitacoes.filter((s) => s.id !== decidida.id);
	}

	async function confirmar() {
		if (aberto === null || decidindo) return;
		erro = '';
		aviso = '';
		decidindo = true;
		// Campo em branco vira `null`: o que cada perfil exige é cobrado pelo
		// domínio (`accredited_since_required`, `incomplete_regular`), com
		// mensagem e `code` estáveis — repetir a regra aqui criaria uma
		// segunda verdade sobre o mesmo invariante.
		const { data, error } = await api.POST('/access/requests/{request_id}/approve', {
			params: { path: { request_id: aberto.id } },
			body:
				aberto.profile === 'student'
					? {
							level: nivel,
							project_id: projetoId === '' ? null : projetoId,
							advisor_id: orientadorId === '' ? null : orientadorId,
							admission_date: ingresso === '' ? null : ingresso
						}
					: { accredited_since: credenciadoDesde === '' ? null : credenciadoDesde }
		});
		decidindo = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível confirmar o cadastro.');
			return;
		}
		aviso = `Cadastro de ${data.person_name} confirmado — a pessoa já enxerga o sistema como ${rotuloDoPerfil(data.profile).toLowerCase()}.`;
		retirar(data);
	}

	async function recusar() {
		if (aberto === null || decidindo) return;
		if (motivo.trim() === '') {
			erro = 'Escreva o motivo: é o texto que a pessoa lê na tela de espera dela.';
			return;
		}
		erro = '';
		aviso = '';
		decidindo = true;
		const { data, error } = await api.POST('/access/requests/{request_id}/reject', {
			params: { path: { request_id: aberto.id } },
			body: { note: motivo.trim() }
		});
		decidindo = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível recusar o cadastro.');
			return;
		}
		aviso = `Cadastro de ${data.person_name} não confirmado. A pessoa não consegue se cadastrar de novo neste programa: para reabrir o acesso, reative-a em Pessoas.`;
		retirar(data);
	}

	// Relê a fila sempre que o filtro muda: a leitura abaixo é o que registra
	// a dependência do efeito.
	$effect(() => {
		carregar(filtroDeSituacao);
	});
</script>

<svelte:head>
	<title>Solicitações de acesso · PPGD Manager</title>
</svelte:head>

<header>
	<p class="etiqueta">Pessoas</p>
	<h1 class="text-grafite mt-1 text-2xl font-semibold tracking-tight">Solicitações de acesso</h1>
	<p class="text-cinza mt-2 text-sm">
		Quem se cadastrou sozinho neste programa e ainda depende de você. Confirme conferindo o que a
		pessoa declarou — é a confirmação que cria a ficha de docente ou de discente e abre o sistema
		para ela.
	</p>
</header>

<div class="mt-6 flex flex-wrap items-end gap-3">
	<div>
		<label class="etiqueta mb-1 block" for="filtro-situacao">Situação</label>
		<select id="filtro-situacao" class="campo" bind:value={filtroDeSituacao}>
			{#each ORDEM_DAS_SITUACOES as situacao (situacao)}
				<option value={situacao}>{ROTULO_DA_SITUACAO[situacao]}</option>
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
{:else if solicitacoes.length === 0}
	<div class="border-borda bg-papel mt-6 border border-dashed p-10 text-center">
		<p class="text-grafite text-[0.9375rem]">
			{filtroDeSituacao === 'pending'
				? 'Nenhuma solicitação aguardando confirmação.'
				: 'Nenhuma solicitação nesta situação.'}
		</p>
	</div>
{:else}
	<ul class="mt-6 space-y-px">
		{#each solicitacoes as solicitacao (solicitacao.id)}
			<li
				class="bg-papel regua-tinta px-5 py-4"
				style:border-left-color={solicitacao.status === 'rejected'
					? 'var(--color-carimbo)'
					: 'var(--color-tinta)'}
			>
				<div class="flex flex-wrap items-center justify-between gap-4">
					<p class="text-grafite text-[0.9375rem] font-medium">{solicitacao.person_name}</p>
					<div class="flex items-center gap-4">
						<span class="etiqueta">
							{rotuloDoPerfil(solicitacao.profile)} · {rotuloDaSituacao(solicitacao.status)}
						</span>
						<button class="botao-discreto" type="button" onclick={() => abrir(solicitacao)}>
							{abertoId === solicitacao.id ? 'Fechar' : 'Analisar'}
						</button>
					</div>
				</div>
				<p class="text-cinza mt-1 text-sm">
					{solicitacao.person_email}
					{#if solicitacao.person_phone_number}· {solicitacao.person_phone_number}{/if}
					· cadastro em {formatarData(solicitacao.created_at)}
				</p>
				{#if solicitacao.decision_note}
					<p class="text-cinza mt-2 text-sm">Decisão: {solicitacao.decision_note}</p>
				{/if}

				{#if abertoId === solicitacao.id}
					<div class="border-borda mt-4 border-t pt-4">
						<h2 class="etiqueta">O que a pessoa declarou</h2>
						<dl class="mt-2 grid gap-3 sm:grid-cols-2">
							<div>
								<dt class="etiqueta">Perfil</dt>
								<dd class="text-grafite mt-0.5 text-[0.9375rem]">
									{rotuloDoPerfil(solicitacao.profile)}
								</dd>
							</div>
							{#if solicitacao.teacher_category}
								<div>
									<dt class="etiqueta">Categoria</dt>
									<dd class="text-grafite mt-0.5 text-[0.9375rem]">
										{ROTULO_DA_CATEGORIA[solicitacao.teacher_category as CategoriaDocente] ??
											solicitacao.teacher_category}
									</dd>
								</div>
							{/if}
							{#if solicitacao.academic_degree}
								<div>
									<dt class="etiqueta">Titulação</dt>
									<dd class="text-grafite mt-0.5 text-[0.9375rem]">
										{ROTULO_DA_TITULACAO[solicitacao.academic_degree as Titulacao] ??
											solicitacao.academic_degree}
									</dd>
								</div>
							{/if}
							{#if solicitacao.home_institution}
								<div>
									<dt class="etiqueta">Instituição de origem</dt>
									<dd class="text-grafite mt-0.5 text-[0.9375rem]">
										{solicitacao.home_institution}
									</dd>
								</div>
							{/if}
							{#if solicitacao.lattes_url}
								<div>
									<dt class="etiqueta">Currículo Lattes</dt>
									<dd class="text-grafite mt-0.5 truncate text-[0.9375rem]">
										<!-- Endereço externo (lattes.cnpq.br), e não rota da SPA:
										`resolve()` não se aplica a link que sai do sistema. -->
										<!-- eslint-disable svelte/no-navigation-without-resolve -->
										<a
											class="underline"
											href={solicitacao.lattes_url}
											target="_blank"
											rel="noopener"
										>
											{solicitacao.lattes_url}
										</a>
										<!-- eslint-enable svelte/no-navigation-without-resolve -->
									</dd>
								</div>
							{/if}
						</dl>

						{#if solicitacao.status === 'pending'}
							<h2 class="etiqueta mt-6">Confirmar o cadastro</h2>
							{#if solicitacao.profile === 'student'}
								<p class="text-cinza mt-2 text-sm">
									O vínculo nasce regular e ativo; o prazo regimental sai do nível e da data de
									ingresso. O orientador pode entrar depois.
								</p>
								<div class="mt-2 grid gap-3 sm:grid-cols-2">
									<label class="block">
										<span class="etiqueta">Nível</span>
										<select class="campo mt-1 w-full" bind:value={nivel} disabled={decidindo}>
											{#each NIVEIS as item (item.valor)}
												<option value={item.valor}>{item.rotulo}</option>
											{/each}
										</select>
									</label>
									<label class="block">
										<span class="etiqueta">Data de ingresso</span>
										<input
											class="campo mt-1 w-full"
											type="date"
											bind:value={ingresso}
											disabled={decidindo}
										/>
									</label>
									<label class="block">
										<span class="etiqueta">Projeto coletivo</span>
										<select class="campo mt-1 w-full" bind:value={projetoId} disabled={decidindo}>
											<option value="">Selecione…</option>
											{#each projetos as projeto (projeto.id)}
												<option value={projeto.id}>{projeto.name}</option>
											{/each}
										</select>
									</label>
									<label class="block">
										<span class="etiqueta">Orientador (opcional)</span>
										<select
											class="campo mt-1 w-full"
											bind:value={orientadorId}
											disabled={decidindo}
										>
											<option value="">Sem orientador por enquanto</option>
											{#each professores as professor (professor.id)}
												<option value={professor.id}>{nomeDoOrientador[professor.id]}</option>
											{/each}
										</select>
									</label>
								</div>
							{:else}
								<p class="text-cinza mt-2 text-sm">
									A data do credenciamento é decisão de quem confirma. A categoria e a titulação
									declaradas acima entram na ficha; linha de pesquisa e projeto são edição
									posterior, em Professores.
								</p>
								<label class="mt-2 block sm:w-1/2">
									<span class="etiqueta">Credenciado desde</span>
									<input
										class="campo mt-1 w-full"
										type="date"
										bind:value={credenciadoDesde}
										disabled={decidindo}
									/>
								</label>
							{/if}

							<h2 class="etiqueta mt-6">Não confirmar</h2>
							<label class="mt-2 block">
								<span class="etiqueta">Motivo</span>
								<input class="campo mt-1 w-full" bind:value={motivo} disabled={decidindo} />
							</label>
							<p class="text-cinza mt-2 text-sm">
								Quem não é confirmado tem a pessoa arquivada e <strong
									>não consegue se cadastrar de novo neste programa</strong
								>: a saída é reativá-la em Pessoas. O motivo é o texto que ela lê na tela de espera
								— recusar sem explicar é porta fechada sem aviso.
							</p>

							<div class="mt-4 flex flex-wrap gap-3">
								<button class="botao" type="button" disabled={decidindo} onclick={confirmar}>
									{decidindo ? 'Registrando…' : 'Confirmar'}
								</button>
								<button class="botao-discreto" type="button" disabled={decidindo} onclick={recusar}>
									Recusar
								</button>
							</div>
						{:else}
							<p class="text-cinza mt-6 text-sm">
								{rotuloDaSituacao(solicitacao.status)} em {formatarData(solicitacao.decided_at)}.
							</p>
						{/if}
					</div>
				{/if}
			</li>
		{/each}
	</ul>
{/if}
