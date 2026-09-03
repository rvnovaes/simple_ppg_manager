<script lang="ts">
	import { resolve } from '$app/paths';
	import Icone from '$lib/Icone.svelte';
	import { api, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';
	import { sessao } from '$lib/sessao.svelte';

	type Professor = components['schemas']['TeacherOut'];
	type Pessoa = components['schemas']['PersonOut'];
	type Linha = components['schemas']['ResearchLineOut'];
	type Projeto = components['schemas']['CollectiveProjectOut'];

	// As três primeiras são categorias CAPES e entram no relatório do
	// programa. `external` não é: existe só para o professor de outra
	// instituição compor banca do processo seletivo — e por isso a
	// instituição de origem é obrigatória nela (`Teacher.clean`).
	const CATEGORIAS = [
		{ valor: 'permanent', rotulo: 'Permanente' },
		{ valor: 'collaborator', rotulo: 'Colaborador' },
		{ valor: 'visiting', rotulo: 'Visitante' },
		{ valor: 'external', rotulo: 'Externo (banca)' }
	] as const;

	const TITULACOES = [
		{ valor: 'doctorate', rotulo: 'Doutor' },
		{ valor: 'postdoctorate', rotulo: 'Pós-doutor' },
		{ valor: 'habilitation', rotulo: 'Livre-docente' }
	] as const;

	type Categoria = (typeof CATEGORIAS)[number]['valor'];
	type Titulacao = (typeof TITULACOES)[number]['valor'];

	function rotuloDeCategoria(valor: string): string {
		return CATEGORIAS.find((c) => c.valor === valor)?.rotulo ?? valor;
	}

	function rotuloDeTitulacao(valor: string): string {
		return TITULACOES.find((t) => t.valor === valor)?.rotulo ?? valor;
	}

	let professores = $state<Professor[]>([]);
	let linhas = $state<Linha[]>([]);
	let projetos = $state<Projeto[]>([]);
	let carregando = $state(true);
	let erro = $state('');
	let aviso = $state('');
	let descredenciando = $state<number | null>(null);

	// Filtro da lista. O backend também aceita `category`, mas filtrar em
	// memória evita uma ida ao servidor a cada clique.
	let filtroCategoria = $state<Categoria | ''>('');

	// Coordenação só lê: sem a permissão de escrita o formulário nem existe
	// na tela (a checagem que vale continua sendo a do backend).
	const podeCriar = $derived(sessao.pode('academic.add_teacher'));
	const podeEditar = $derived(sessao.pode('academic.change_teacher'));
	const podeDefinirSenha = $derived(sessao.pode('accounts.change_user'));

	const visiveis = $derived(
		filtroCategoria === '' ? professores : professores.filter((p) => p.category === filtroCategoria)
	);

	// Projeto pertence a uma linha: mostrar a linha ao lado do nome evita
	// dois projetos homônimos indistinguíveis na seleção múltipla.
	const nomeDaLinha = $derived.by(() => {
		const nomes: Record<number, string> = {};
		for (const linha of linhas) nomes[linha.id] = linha.name;
		return nomes;
	});

	function porNomeDaPessoa(a: Professor, b: Professor): number {
		return a.person.full_name.localeCompare(b.person.full_name, 'pt-BR');
	}

	async function carregar() {
		carregando = true;
		erro = '';
		const [respProfessores, respLinhas, respProjetos] = await Promise.all([
			api.GET('/academic/teachers/'),
			api.GET('/programs/research-lines/'),
			api.GET('/programs/collective-projects/')
		]);
		const falha = respProfessores.error ?? respLinhas.error ?? respProjetos.error;
		if (falha) {
			erro = mensagemDeErro(falha, 'Não foi possível carregar os professores.');
		} else {
			professores = respProfessores.data?.items ?? [];
			linhas = respLinhas.data?.items ?? [];
			projetos = respProjetos.data?.items ?? [];
		}
		carregando = false;
	}

	// ------------------------------------------------------------ formulário

	let formAberto = $state(false);
	let emEdicao = $state<Professor | null>(null);
	let salvando = $state(false);

	let nome = $state('');
	let email = $state('');
	let telefone = $state('');
	// Preenchido quando a busca por e-mail achou alguém: daí em diante o POST
	// reaproveita a pessoa em vez de criar outra.
	let pessoaEncontrada = $state<Pessoa | null>(null);
	let buscandoPessoa = $state(false);
	let emailConsultado = $state('');

	let categoria = $state<Categoria>('permanent');
	let titulacao = $state<Titulacao>('doctorate');
	let credenciadoDesde = $state('');
	let credenciadoAte = $state('');
	let lattes = $state('');
	let instituicao = $state('');
	const externo = $derived(categoria === 'external');
	let linhasSelecionadas = $state<number[]>([]);
	let projetosSelecionados = $state<number[]>([]);

	function limparPessoa() {
		pessoaEncontrada = null;
		emailConsultado = '';
	}

	function abrirNovo() {
		emEdicao = null;
		nome = '';
		email = '';
		telefone = '';
		limparPessoa();
		categoria = 'permanent';
		titulacao = 'doctorate';
		credenciadoDesde = '';
		credenciadoAte = '';
		lattes = '';
		instituicao = '';
		linhasSelecionadas = [];
		projetosSelecionados = [];
		formAberto = true;
	}

	async function descredenciar(professor: Professor) {
		erro = '';
		descredenciando = professor.id;
		// Sem corpo: a data padrão é hoje, e o backend a resolve. Data
		// retroativa é caso da edição, não do botão da lista.
		const { data, error } = await api.POST('/academic/teachers/{teacher_id}/deaccredit', {
			params: { path: { teacher_id: professor.id } },
			body: {}
		});
		descredenciando = null;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível descredenciar o professor.');
			return;
		}
		professores = professores.map((p) => (p.id === data.id ? data : p));
	}

	function editar(professor: Professor) {
		emEdicao = professor;
		nome = professor.person.full_name;
		email = professor.person.primary_email;
		telefone = professor.person.phone_number;
		limparPessoa();
		categoria = professor.category as Categoria;
		titulacao = professor.academic_degree as Titulacao;
		credenciadoDesde = professor.accredited_since;
		credenciadoAte = professor.accredited_until ?? '';
		lattes = professor.lattes_url;
		instituicao = professor.home_institution;
		linhasSelecionadas = [...professor.research_line_ids];
		projetosSelecionados = [...professor.project_ids];
		formAberto = true;
	}

	function fechar() {
		formAberto = false;
		emEdicao = null;
		limparPessoa();
	}

	/**
	 * Procura a pessoa pelo e-mail ANTES de criar.
	 *
	 * Sem isto, cadastrar quem já existe no programa esbarra na
	 * UniqueConstraint (program, primary_email) e o erro chega como falha
	 * técnica, quando o certo é oferecer o registro que já está lá.
	 */
	async function procurarPessoa() {
		if (!email) return;
		erro = '';
		aviso = '';
		buscandoPessoa = true;
		const { data, error } = await api.GET('/people/', { params: { query: { email } } });
		buscandoPessoa = false;
		emailConsultado = email;
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível consultar as pessoas.');
			return;
		}
		const achada = data?.items?.[0] ?? null;
		pessoaEncontrada = achada;
		if (achada) {
			nome = achada.full_name;
			telefone = achada.phone_number;
		}
	}

	function descartarPessoaEncontrada() {
		pessoaEncontrada = null;
	}

	function alternar(lista: number[], id: number): number[] {
		return lista.includes(id) ? lista.filter((item) => item !== id) : [...lista, id];
	}

	async function salvar(event: SubmitEvent) {
		event.preventDefault();
		erro = '';
		aviso = '';
		salvando = true;
		const vinculo = {
			category: categoria,
			academic_degree: titulacao,
			accredited_since: credenciadoDesde,
			accredited_until: credenciadoAte || null,
			lattes_url: lattes,
			home_institution: instituicao,
			research_line_ids: linhasSelecionadas,
			project_ids: projetosSelecionados
		};
		const alvo = emEdicao;
		const { data, error } = alvo
			? await api.PATCH('/academic/teachers/{teacher_id}/', {
					params: { path: { teacher_id: alvo.id } },
					body: vinculo
				})
			: await api.POST('/academic/teachers/', {
					body: pessoaEncontrada
						? // O telefone da pessoa que já existe não muda por aqui; quem
							// edita cadastro de pessoa é a tela de Pessoas.
							{ ...vinculo, person_id: pessoaEncontrada.id, phone_number: '' }
						: { ...vinculo, full_name: nome, primary_email: email, phone_number: telefone }
				});
		salvando = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível salvar o professor.');
			return;
		}
		professores = alvo
			? professores.map((p) => (p.id === data.id ? data : p))
			: [...professores, data].sort(porNomeDaPessoa);
		fechar();
	}

	// --------------------------------------------------------- senha inicial

	let definindoSenhaDe = $state<number | null>(null);
	let senha = $state('');
	let enviandoSenha = $state(false);

	function abrirSenha(professor: Professor) {
		definindoSenhaDe = professor.id;
		senha = '';
	}

	async function definirSenha(event: SubmitEvent, professor: Professor) {
		event.preventDefault();
		const userId = professor.person.user_id;
		if (userId === null) return;
		erro = '';
		aviso = '';
		enviandoSenha = true;
		const { data, error } = await api.POST('/accounts/users/{user_id}/set-initial-password', {
			params: { path: { user_id: userId } },
			body: { password: senha }
		});
		enviandoSenha = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível definir a senha inicial.');
			return;
		}
		aviso = `Senha inicial definida para ${professor.person.full_name}.`;
		// A ação some da tela: o backend recusa a segunda tentativa, e a
		// Secretaria não assume conta de quem já entrou no sistema.
		professores = professores.map((p) =>
			p.id === professor.id ? { ...p, person: { ...p.person, needs_initial_password: false } } : p
		);
		definindoSenhaDe = null;
		senha = '';
	}

	$effect(() => {
		carregar();
	});
</script>

<svelte:head>
	<title>Professores · PPGM</title>
</svelte:head>

<header class="flex flex-wrap items-end justify-between gap-4">
	<div>
		<p class="etiqueta">Cadastro</p>
		<h1 class="text-grafite mt-1 text-2xl font-semibold tracking-tight">Professores</h1>
	</div>
	<div class="flex items-center gap-4">
		<label class="etiqueta" for="filtro-categoria">Categoria</label>
		<select id="filtro-categoria" class="campo w-44" bind:value={filtroCategoria}>
			<option value="">Todas</option>
			{#each CATEGORIAS as opcao (opcao.valor)}
				<option value={opcao.valor}>{opcao.rotulo}</option>
			{/each}
		</select>
		{#if podeCriar}
			<button class="botao-discreto" type="button" onclick={abrirNovo}>Novo professor</button>
		{/if}
	</div>
</header>

{#if erro}
	<p class="aviso-erro mt-6" role="alert">{erro}</p>
{/if}
{#if aviso}
	<p class="etiqueta mt-6" role="status">{aviso}</p>
{/if}

{#if formAberto}
	<form class="border-borda bg-papel mt-8 border p-5" onsubmit={salvar}>
		<p class="etiqueta">{emEdicao ? 'Editar professor' : 'Novo professor'}</p>

		{#if !emEdicao}
			<div class="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-[2fr_1fr_auto]">
				<div>
					<label class="etiqueta mb-2 block" for="prof-email">E-mail</label>
					<input
						id="prof-email"
						type="email"
						class="campo font-mono"
						bind:value={email}
						onblur={procurarPessoa}
						required
					/>
				</div>
				<div>
					<label class="etiqueta mb-2 block" for="prof-telefone">Telefone</label>
					<input
						id="prof-telefone"
						class="campo font-mono"
						bind:value={telefone}
						disabled={pessoaEncontrada !== null}
					/>
				</div>
				<div class="flex items-end">
					<button class="botao-discreto" type="button" onclick={procurarPessoa} disabled={!email}>
						{buscandoPessoa ? 'Procurando…' : 'Procurar pessoa'}
					</button>
				</div>
			</div>

			{#if pessoaEncontrada}
				<div class="border-borda mt-4 border border-dashed p-4">
					<p class="text-grafite text-sm">
						Já existe <strong>{pessoaEncontrada.full_name}</strong> com este e-mail neste programa. O
						vínculo docente será criado para ela, sem duplicar o cadastro.
					</p>
					<button class="botao-discreto mt-3" type="button" onclick={descartarPessoaEncontrada}>
						Não é a mesma pessoa
					</button>
				</div>
			{:else if emailConsultado && emailConsultado === email}
				<p class="text-cinza mt-3 text-sm">
					Nenhuma pessoa com este e-mail: uma nova será cadastrada.
				</p>
			{/if}
		{/if}

		<div class="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
			<div class="lg:col-span-2">
				<label class="etiqueta mb-2 block" for="prof-nome">Nome completo</label>
				<input
					id="prof-nome"
					class="campo"
					bind:value={nome}
					disabled={emEdicao !== null || pessoaEncontrada !== null}
					required
				/>
			</div>
			<div>
				<label class="etiqueta mb-2 block" for="prof-categoria">Categoria</label>
				<select id="prof-categoria" class="campo" bind:value={categoria}>
					{#each CATEGORIAS as opcao (opcao.valor)}
						<option value={opcao.valor}>{opcao.rotulo}</option>
					{/each}
				</select>
			</div>
			<div>
				<label class="etiqueta mb-2 block" for="prof-titulacao">Titulação</label>
				<select id="prof-titulacao" class="campo" bind:value={titulacao}>
					{#each TITULACOES as opcao (opcao.valor)}
						<option value={opcao.valor}>{opcao.rotulo}</option>
					{/each}
				</select>
			</div>
			<div>
				<label class="etiqueta mb-2 block" for="prof-desde">Credenciado desde</label>
				<input
					id="prof-desde"
					type="date"
					class="campo font-mono"
					bind:value={credenciadoDesde}
					required
				/>
			</div>
			<div>
				<!-- Vazio = credenciamento vigente; preenchido = descredenciado. -->
				<label class="etiqueta mb-2 block" for="prof-ate">Credenciado até</label>
				<input id="prof-ate" type="date" class="campo font-mono" bind:value={credenciadoAte} />
			</div>
			<div class="lg:col-span-2">
				<label class="etiqueta mb-2 block" for="prof-lattes">Currículo Lattes</label>
				<input id="prof-lattes" type="url" class="campo font-mono" bind:value={lattes} />
			</div>
			<div>
				<label class="etiqueta mb-2 block" for="prof-instituicao">
					Instituição de origem{externo ? ' *' : ''}
				</label>
				<!-- Obrigatória no externo: a categoria só existe para dizer de
				onde o professor vem. A validação que vale é a do `clean()` do
				model (`external_requires_institution`); esta aqui só evita a
				viagem até o servidor. -->
				<input id="prof-instituicao" class="campo" bind:value={instituicao} required={externo} />
				{#if externo}
					<p class="text-cinza mt-1 text-[0.8125rem]">
						Obrigatória para o professor externo, que compõe banca do processo seletivo.
					</p>
				{/if}
			</div>
		</div>

		<div class="mt-6 grid gap-6 sm:grid-cols-2">
			<fieldset>
				<legend class="etiqueta mb-2">Linhas de pesquisa</legend>
				{#if linhas.length === 0}
					<p class="text-cinza text-sm">Nenhuma linha cadastrada ainda.</p>
				{:else}
					<div class="border-borda max-h-44 overflow-y-auto border p-3">
						{#each linhas as linha (linha.id)}
							<label class="text-grafite flex items-center gap-2 py-1 text-sm">
								<input
									type="checkbox"
									checked={linhasSelecionadas.includes(linha.id)}
									onchange={() => (linhasSelecionadas = alternar(linhasSelecionadas, linha.id))}
								/>
								{linha.name}
							</label>
						{/each}
					</div>
				{/if}
			</fieldset>

			<fieldset>
				<legend class="etiqueta mb-2">Projetos coletivos</legend>
				{#if projetos.length === 0}
					<p class="text-cinza text-sm">Nenhum projeto cadastrado ainda.</p>
				{:else}
					<div class="border-borda max-h-44 overflow-y-auto border p-3">
						{#each projetos as projeto (projeto.id)}
							<label class="text-grafite flex items-center gap-2 py-1 text-sm">
								<input
									type="checkbox"
									checked={projetosSelecionados.includes(projeto.id)}
									onchange={() =>
										(projetosSelecionados = alternar(projetosSelecionados, projeto.id))}
								/>
								{projeto.name}
								<span class="text-cinza">· {nomeDaLinha[projeto.research_line_id] ?? '—'}</span>
							</label>
						{/each}
					</div>
				{/if}
			</fieldset>
		</div>

		<div class="mt-6 flex gap-2">
			<button class="botao" type="submit" disabled={salvando}>
				{salvando ? 'Salvando…' : 'Salvar'}
			</button>
			<button class="botao-discreto" type="button" onclick={fechar}>Cancelar</button>
		</div>
	</form>
{/if}

<section class="mt-10">
	{#if carregando}
		<p class="etiqueta">Carregando…</p>
	{:else if visiveis.length === 0}
		<div class="border-borda bg-papel border border-dashed p-10 text-center">
			<p class="text-grafite text-[0.9375rem]">
				{professores.length === 0
					? 'Nenhum professor cadastrado ainda.'
					: 'Nenhum professor nesta categoria.'}
			</p>
			<p class="text-cinza mt-1 text-sm">
				{podeCriar
					? 'Use "Novo professor" para cadastrar.'
					: 'Peça à secretaria para fazer o cadastro.'}
			</p>
		</div>
	{:else}
		<ul class="space-y-px">
			{#each visiveis as professor (professor.id)}
				<li
					class="bg-papel regua-tinta px-5 py-4"
					class:opacity-55={professor.accredited_until !== null}
					style:border-left-color={professor.accredited_until === null
						? 'var(--color-tinta)'
						: 'var(--color-borda)'}
				>
					<div class="flex flex-wrap items-center justify-between gap-4">
						<div class="min-w-0">
							<p class="text-grafite truncate text-[0.9375rem] font-medium">
								{professor.person.full_name}
							</p>
							<p class="text-cinza mt-0.5 truncate font-mono text-[0.8125rem]">
								{professor.person.primary_email}
							</p>
							<p class="text-cinza mt-0.5 text-[0.8125rem]">
								{rotuloDeCategoria(professor.category)} · {rotuloDeTitulacao(
									professor.academic_degree
								)} · {professor.research_line_ids.length} linhas · {professor.project_ids.length} projetos
							</p>
						</div>
						<div class="flex shrink-0 items-center gap-4">
							<span class="etiqueta">
								{professor.accredited_until === null ? 'Credenciado' : 'Descredenciado'}
							</span>
							{#if podeDefinirSenha && professor.person.needs_initial_password}
								<button class="botao-discreto" type="button" onclick={() => abrirSenha(professor)}>
									Definir senha inicial
								</button>
							{/if}
							<div class="flex items-center gap-1">
								<a
									class="botao-icone"
									href={resolve('/(app)/professores/[id]', { id: String(professor.id) })}
									title="Detalhes de {professor.person.full_name}"
								>
									<Icone nome="olho" rotulo="Detalhes" />
								</a>
								{#if podeEditar}
									<button
										class="botao-icone"
										type="button"
										title="Editar {professor.person.full_name}"
										onclick={() => editar(professor)}
									>
										<Icone nome="lapis" rotulo="Editar" />
									</button>
									<!-- Descredenciar, e não apagar: o professor descredenciado
									continua sendo quem orientou os alunos dele. Já
									descredenciado, o botão fica desabilitado em vez de sumir —
									some daria a impressão de que a ação não existe. -->
									<button
										class="botao-icone botao-icone-perigo"
										type="button"
										disabled={professor.accredited_until !== null ||
											descredenciando === professor.id}
										title={professor.accredited_until !== null
											? 'Já descredenciado'
											: `Descredenciar ${professor.person.full_name}`}
										onclick={() => descredenciar(professor)}
									>
										<Icone nome="arquivo" rotulo="Descredenciar" />
									</button>
								{/if}
							</div>
						</div>
					</div>

					{#if definindoSenhaDe === professor.id}
						<form
							class="border-borda mt-4 flex flex-wrap items-end gap-3 border border-dashed p-4"
							onsubmit={(event) => definirSenha(event, professor)}
						>
							<div>
								<label class="etiqueta mb-2 block" for="senha-{professor.id}">
									Senha do primeiro acesso
								</label>
								<input
									id="senha-{professor.id}"
									type="password"
									class="campo font-mono"
									bind:value={senha}
									required
								/>
							</div>
							<button class="botao" type="submit" disabled={enviandoSenha}>
								{enviandoSenha ? 'Definindo…' : 'Definir'}
							</button>
							<button
								class="botao-discreto"
								type="button"
								onclick={() => (definindoSenhaDe = null)}
							>
								Cancelar
							</button>
						</form>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}
</section>
