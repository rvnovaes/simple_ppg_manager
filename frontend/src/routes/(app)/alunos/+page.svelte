<script lang="ts">
	import { resolve } from '$app/paths';
	import Icone from '$lib/Icone.svelte';
	import { api, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';
	import { sessao } from '$lib/sessao.svelte';

	type Aluno = components['schemas']['StudentOut'];
	type Pessoa = components['schemas']['PersonOut'];
	type Professor = components['schemas']['TeacherOut'];
	type Projeto = components['schemas']['CollectiveProjectOut'];
	type Periodo = components['schemas']['AcademicTermOut'];

	// Modalidade e situação são campos separados (ADR-007 dec. 1) e assim
	// aparecem na tela: nunca um rótulo combinado tipo "Regular trancado".
	const MODALIDADES = [
		{ valor: 'regular', rotulo: 'Regular' },
		{ valor: 'isolated', rotulo: 'Isolada' },
		{ valor: 'elective', rotulo: 'Eletiva' }
	] as const;

	const SITUACOES = [
		{ valor: 'active', rotulo: 'Ativo' },
		{ valor: 'leave', rotulo: 'Trancado' },
		{ valor: 'excluded', rotulo: 'Excluído' }
	] as const;

	const NIVEIS = [
		{ valor: 'masters', rotulo: 'Mestrado' },
		{ valor: 'doctorate', rotulo: 'Doutorado' }
	] as const;

	type Modalidade = (typeof MODALIDADES)[number]['valor'];
	type Situacao = (typeof SITUACOES)[number]['valor'];
	type Nivel = (typeof NIVEIS)[number]['valor'];

	// Espelha Student.PRAZO_EM_ANOS: 24 meses no mestrado, 48 no doutorado.
	const PRAZO_EM_ANOS: Record<Nivel, number> = { masters: 2, doctorate: 4 };

	function rotulo(
		opcoes: readonly { valor: string; rotulo: string }[],
		valor: string | null
	): string {
		if (valor === null) return '—';
		return opcoes.find((o) => o.valor === valor)?.rotulo ?? valor;
	}

	let alunos = $state<Aluno[]>([]);
	let professores = $state<Professor[]>([]);
	let projetos = $state<Projeto[]>([]);
	let periodos = $state<Periodo[]>([]);
	let carregando = $state(true);
	let erro = $state('');
	let aviso = $state('');
	let excluindo = $state<number | null>(null);

	// Filtros da lista. O backend também os aceita como query string, mas
	// filtrar em memória evita uma ida ao servidor a cada clique.
	let filtroModalidade = $state<Modalidade | ''>('');
	let filtroSituacao = $state<Situacao | ''>('');
	let filtroNivel = $state<Nivel | ''>('');
	let filtroPeriodo = $state<number | ''>('');

	// Coordenação só lê: sem a permissão de escrita o botão nem existe na
	// tela (a checagem que vale continua sendo a do backend).
	const podeCriar = $derived(sessao.pode('academic.add_student'));
	const podeEditar = $derived(sessao.pode('academic.change_student'));
	const podeDefinirSenha = $derived(sessao.pode('accounts.change_user'));

	const visiveis = $derived(
		alunos.filter(
			(a) =>
				(filtroModalidade === '' || a.modality === filtroModalidade) &&
				(filtroSituacao === '' || a.status === filtroSituacao) &&
				(filtroNivel === '' || a.level === filtroNivel) &&
				(filtroPeriodo === '' || a.term_id === filtroPeriodo)
		)
	);

	const nomeDoProjeto = $derived.by(() => {
		const nomes: Record<number, string> = {};
		for (const projeto of projetos) nomes[projeto.id] = projeto.name;
		return nomes;
	});

	const nomeDoOrientador = $derived.by(() => {
		const nomes: Record<number, string> = {};
		for (const professor of professores) nomes[professor.id] = professor.person.full_name;
		return nomes;
	});

	const rotuloDoPeriodo = $derived.by(() => {
		const rotulos: Record<number, string> = {};
		for (const periodo of periodos) rotulos[periodo.id] = periodo.label;
		return rotulos;
	});

	function porNomeDaPessoa(a: Aluno, b: Aluno): number {
		return a.person.full_name.localeCompare(b.person.full_name, 'pt-BR');
	}

	async function carregar() {
		carregando = true;
		erro = '';
		const [respAlunos, respProfessores, respProjetos, respPeriodos] = await Promise.all([
			api.GET('/academic/students/'),
			api.GET('/academic/teachers/'),
			api.GET('/programs/collective-projects/'),
			api.GET('/programs/terms/')
		]);
		const falha =
			respAlunos.error ?? respProfessores.error ?? respProjetos.error ?? respPeriodos.error;
		if (falha) {
			erro = mensagemDeErro(falha, 'Não foi possível carregar os alunos.');
		} else {
			alunos = respAlunos.data?.items ?? [];
			professores = respProfessores.data?.items ?? [];
			projetos = respProjetos.data?.items ?? [];
			periodos = respPeriodos.data?.items ?? [];
		}
		carregando = false;
	}

	// ------------------------------------------------------------ formulário

	let formAberto = $state(false);
	let emEdicao = $state<Aluno | null>(null);
	let salvando = $state(false);

	let nome = $state('');
	let email = $state('');
	let telefone = $state('');
	// Preenchido quando a busca por e-mail achou alguém: daí em diante o
	// POST reaproveita a pessoa em vez de criar outra. É o caminho normal
	// de quem volta a cursar isolada em outro semestre.
	let pessoaEncontrada = $state<Pessoa | null>(null);
	let buscandoPessoa = $state(false);
	let emailConsultado = $state('');

	let modalidade = $state<Modalidade>('regular');
	let situacao = $state<Situacao>('active');
	let matricula = $state('');
	let nivel = $state<Nivel>('masters');
	let projetoId = $state<number | null>(null);
	let orientadorId = $state<number | null>(null);
	let ingresso = $state('');
	let prazo = $state('');
	let defesa = $state('');
	let periodoId = $state<number | null>(null);
	// O prazo é default, não invariante: depois que alguém digita, a tela
	// para de recalcular (prorrogação é rotina do programa).
	let prazoEditado = $state(false);

	const ehRegular = $derived(modalidade === 'regular');
	// Trancamento só existe no vínculo regular (CheckConstraint
	// student_leave_only_when_regular).
	const situacoesPossiveis = $derived(
		ehRegular ? SITUACOES : SITUACOES.filter((s) => s.valor !== 'leave')
	);

	/** Mesma conta de `Student.default_deadline`: ingresso + 2 ou 4 anos. */
	function prazoCalculado(): string {
		if (!ingresso) return '';
		const [ano, mes, dia] = ingresso.split('-').map(Number);
		if (!ano || !mes || !dia) return '';
		const anoAlvo = ano + PRAZO_EM_ANOS[nivel];
		// 29/02 em ano seguinte não bissexto cai em 28/02, como `_somar_anos`.
		const bissexto = (anoAlvo % 4 === 0 && anoAlvo % 100 !== 0) || anoAlvo % 400 === 0;
		const diaAlvo = mes === 2 && dia === 29 && !bissexto ? 28 : dia;
		return `${anoAlvo}-${String(mes).padStart(2, '0')}-${String(diaAlvo).padStart(2, '0')}`;
	}

	function recalcularPrazo() {
		if (!ehRegular || prazoEditado) return;
		prazo = prazoCalculado();
	}

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
		modalidade = 'regular';
		situacao = 'active';
		matricula = '';
		nivel = 'masters';
		projetoId = null;
		orientadorId = null;
		ingresso = '';
		prazo = '';
		defesa = '';
		periodoId = null;
		prazoEditado = false;
		formAberto = true;
	}

	async function excluir(aluno: Aluno) {
		erro = '';
		excluindo = aluno.id;
		const { data, error } = await api.POST('/academic/students/{student_id}/exclude', {
			params: { path: { student_id: aluno.id } }
		});
		excluindo = null;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível excluir o aluno.');
			return;
		}
		alunos = alunos.map((a) => (a.id === data.id ? data : a));
	}

	function editar(aluno: Aluno) {
		emEdicao = aluno;
		nome = aluno.person.full_name;
		email = aluno.person.primary_email;
		telefone = aluno.person.phone_number;
		limparPessoa();
		modalidade = aluno.modality as Modalidade;
		situacao = aluno.status as Situacao;
		matricula = aluno.registration_number ?? '';
		nivel = (aluno.level as Nivel | null) ?? 'masters';
		projetoId = aluno.project_id;
		orientadorId = aluno.advisor_id;
		ingresso = aluno.admission_date ?? '';
		prazo = aluno.deadline ?? '';
		defesa = aluno.defense_date ?? '';
		periodoId = aluno.term_id;
		// Prazo que já está salvo é decisão tomada: não se recalcula por baixo.
		prazoEditado = true;
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

	/**
	 * Campos que só existem no vínculo regular.
	 *
	 * Esconder campo por regra de UI é exceção neste projeto; aqui é
	 * correto porque a regra é CheckConstraint no banco: isolada e eletiva
	 * duram um semestre e exigem esses campos nulos.
	 */
	function camposDeGrau() {
		return ehRegular
			? {
					level: nivel,
					project_id: projetoId,
					advisor_id: orientadorId,
					admission_date: ingresso,
					deadline: prazo || null,
					defense_date: defesa || null,
					term_id: null
				}
			: {
					level: null,
					project_id: null,
					advisor_id: null,
					admission_date: null,
					deadline: null,
					defense_date: null,
					term_id: periodoId
				};
	}

	async function salvar(event: SubmitEvent) {
		event.preventDefault();
		erro = '';
		aviso = '';
		salvando = true;
		const vinculo = {
			status: situacao,
			registration_number: matricula || null,
			...camposDeGrau()
		};
		const alvo = emEdicao;
		const { data, error } = alvo
			? await api.PATCH('/academic/students/{student_id}/', {
					params: { path: { student_id: alvo.id } },
					body: vinculo
				})
			: await api.POST('/academic/students/', {
					body: pessoaEncontrada
						? // O telefone da pessoa que já existe não muda por aqui; quem
							// edita cadastro de pessoa é a tela de Pessoas.
							{ ...vinculo, modality: modalidade, person_id: pessoaEncontrada.id, phone_number: '' }
						: {
								...vinculo,
								modality: modalidade,
								full_name: nome,
								primary_email: email,
								phone_number: telefone
							}
				});
		salvando = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível salvar o aluno.');
			return;
		}
		alunos = alvo
			? alunos.map((a) => (a.id === data.id ? data : a))
			: [...alunos, data].sort(porNomeDaPessoa);
		fechar();
	}

	// --------------------------------------------------------- senha inicial

	let definindoSenhaDe = $state<number | null>(null);
	let senha = $state('');
	let enviandoSenha = $state(false);

	function abrirSenha(aluno: Aluno) {
		definindoSenhaDe = aluno.id;
		senha = '';
	}

	async function definirSenha(event: SubmitEvent, aluno: Aluno) {
		event.preventDefault();
		const userId = aluno.person.user_id;
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
		aviso = `Senha inicial definida para ${aluno.person.full_name}.`;
		// A ação some da tela: o backend recusa a segunda tentativa, e a
		// Secretaria não assume conta de quem já entrou no sistema.
		alunos = alunos.map((a) =>
			a.id === aluno.id ? { ...a, person: { ...a.person, needs_initial_password: false } } : a
		);
		definindoSenhaDe = null;
		senha = '';
	}

	$effect(() => {
		carregar();
	});
</script>

<svelte:head>
	<title>Alunos · PPGM</title>
</svelte:head>

<header class="flex flex-wrap items-end justify-between gap-4">
	<div>
		<p class="etiqueta">Cadastro</p>
		<h1 class="text-grafite mt-1 text-2xl font-semibold tracking-tight">Alunos</h1>
	</div>
	{#if podeCriar}
		<button class="botao-discreto" type="button" onclick={abrirNovo}>Novo aluno</button>
	{/if}
</header>

<div class="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
	<div>
		<label class="etiqueta mb-2 block" for="filtro-modalidade">Modalidade</label>
		<select id="filtro-modalidade" class="campo" bind:value={filtroModalidade}>
			<option value="">Todas</option>
			{#each MODALIDADES as opcao (opcao.valor)}
				<option value={opcao.valor}>{opcao.rotulo}</option>
			{/each}
		</select>
	</div>
	<div>
		<label class="etiqueta mb-2 block" for="filtro-situacao">Situação</label>
		<select id="filtro-situacao" class="campo" bind:value={filtroSituacao}>
			<option value="">Todas</option>
			{#each SITUACOES as opcao (opcao.valor)}
				<option value={opcao.valor}>{opcao.rotulo}</option>
			{/each}
		</select>
	</div>
	<div>
		<label class="etiqueta mb-2 block" for="filtro-nivel">Nível</label>
		<select id="filtro-nivel" class="campo" bind:value={filtroNivel}>
			<option value="">Todos</option>
			{#each NIVEIS as opcao (opcao.valor)}
				<option value={opcao.valor}>{opcao.rotulo}</option>
			{/each}
		</select>
	</div>
	<div>
		<label class="etiqueta mb-2 block" for="filtro-periodo">Período letivo</label>
		<select id="filtro-periodo" class="campo" bind:value={filtroPeriodo}>
			<option value="">Todos</option>
			{#each periodos as periodo (periodo.id)}
				<option value={periodo.id}>{periodo.label}</option>
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

{#if formAberto}
	<form class="border-borda bg-papel mt-8 border p-5" onsubmit={salvar}>
		<p class="etiqueta">{emEdicao ? 'Editar aluno' : 'Novo aluno'}</p>

		<!--
			A modalidade é a primeira decisão do formulário: ela governa quais
			campos existem daqui para baixo. Na edição fica travada — trocar a
			modalidade de um vínculo é criar um vínculo novo, não editar campo.
		-->
		<div class="mt-4 max-w-xs">
			<label class="etiqueta mb-2 block" for="aluno-modalidade">Modalidade do vínculo</label>
			<select
				id="aluno-modalidade"
				class="campo"
				bind:value={modalidade}
				disabled={emEdicao !== null}
				onchange={recalcularPrazo}
			>
				{#each MODALIDADES as opcao (opcao.valor)}
					<option value={opcao.valor}>{opcao.rotulo}</option>
				{/each}
			</select>
			{#if emEdicao}
				<p class="text-cinza mt-2 text-sm">
					A modalidade não muda por edição: cadastre um vínculo novo.
				</p>
			{/if}
		</div>

		{#if !emEdicao}
			<div class="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-[2fr_1fr_auto]">
				<div>
					<label class="etiqueta mb-2 block" for="aluno-email">E-mail</label>
					<input
						id="aluno-email"
						type="email"
						class="campo font-mono"
						bind:value={email}
						onblur={procurarPessoa}
						required
					/>
				</div>
				<div>
					<label class="etiqueta mb-2 block" for="aluno-telefone">Telefone</label>
					<input
						id="aluno-telefone"
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
						vínculo será criado para ela, sem duplicar o cadastro.
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
				<label class="etiqueta mb-2 block" for="aluno-nome">Nome completo</label>
				<input
					id="aluno-nome"
					class="campo"
					bind:value={nome}
					disabled={emEdicao !== null || pessoaEncontrada !== null}
					required
				/>
			</div>
			<div>
				<label class="etiqueta mb-2 block" for="aluno-situacao">Situação</label>
				<select id="aluno-situacao" class="campo" bind:value={situacao}>
					{#each situacoesPossiveis as opcao (opcao.valor)}
						<option value={opcao.valor}>{opcao.rotulo}</option>
					{/each}
				</select>
			</div>
			<div>
				<label class="etiqueta mb-2 block" for="aluno-matricula">Matrícula</label>
				<input id="aluno-matricula" class="campo font-mono" bind:value={matricula} />
			</div>
		</div>

		{#if ehRegular}
			<div class="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
				<div>
					<label class="etiqueta mb-2 block" for="aluno-nivel">Nível</label>
					<select id="aluno-nivel" class="campo" bind:value={nivel} onchange={recalcularPrazo}>
						{#each NIVEIS as opcao (opcao.valor)}
							<option value={opcao.valor}>{opcao.rotulo}</option>
						{/each}
					</select>
				</div>
				<div class="lg:col-span-2">
					<label class="etiqueta mb-2 block" for="aluno-projeto">Projeto coletivo</label>
					<select id="aluno-projeto" class="campo" bind:value={projetoId}>
						<option value={null}>Selecione…</option>
						{#each projetos as projeto (projeto.id)}
							<option value={projeto.id}>{projeto.name}</option>
						{/each}
					</select>
				</div>
				<div class="lg:col-span-2">
					<label class="etiqueta mb-2 block" for="aluno-orientador">Orientador</label>
					<select id="aluno-orientador" class="campo" bind:value={orientadorId}>
						<option value={null}>Sem orientador definido</option>
						{#each professores as professor (professor.id)}
							<option value={professor.id}>{professor.person.full_name}</option>
						{/each}
					</select>
				</div>
				<div>
					<label class="etiqueta mb-2 block" for="aluno-ingresso">Data de ingresso</label>
					<input
						id="aluno-ingresso"
						type="date"
						class="campo font-mono"
						bind:value={ingresso}
						onchange={recalcularPrazo}
						required
					/>
				</div>
				<div>
					<label class="etiqueta mb-2 block" for="aluno-prazo">Prazo de conclusão</label>
					<input
						id="aluno-prazo"
						type="date"
						class="campo font-mono"
						bind:value={prazo}
						oninput={() => (prazoEditado = true)}
					/>
					<p class="text-cinza mt-2 text-sm">
						Calculado a partir do ingresso ({PRAZO_EM_ANOS[nivel]} anos) e editável: prorrogação é rotina.
					</p>
				</div>
				<div>
					<label class="etiqueta mb-2 block" for="aluno-defesa">Data de defesa</label>
					<input id="aluno-defesa" type="date" class="campo font-mono" bind:value={defesa} />
				</div>
			</div>
		{:else}
			<div class="mt-4 max-w-xs">
				<label class="etiqueta mb-2 block" for="aluno-periodo">Período letivo</label>
				<select id="aluno-periodo" class="campo" bind:value={periodoId}>
					<option value={null}>Selecione…</option>
					{#each periodos as periodo (periodo.id)}
						<option value={periodo.id}>{periodo.label}</option>
					{/each}
				</select>
				<p class="text-cinza mt-2 text-sm">
					Isolada e eletiva duram um semestre: sem nível, projeto, orientador ou prazo.
				</p>
			</div>
		{/if}

		<div class="mt-6 flex gap-2">
			<button
				class="botao"
				type="submit"
				disabled={salvando || (ehRegular ? projetoId === null || !ingresso : periodoId === null)}
			>
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
				{alunos.length === 0 ? 'Nenhum aluno cadastrado ainda.' : 'Nenhum aluno com estes filtros.'}
			</p>
			<p class="text-cinza mt-1 text-sm">
				{podeCriar
					? 'Use "Novo aluno" para cadastrar.'
					: 'Peça à secretaria para fazer o cadastro.'}
			</p>
		</div>
	{:else}
		<ul class="space-y-px">
			{#each visiveis as aluno (aluno.id)}
				<li
					class="bg-papel regua-tinta px-5 py-4"
					class:opacity-55={aluno.status === 'excluded'}
					style:border-left-color={aluno.status === 'active'
						? 'var(--color-tinta)'
						: 'var(--color-borda)'}
				>
					<div class="flex flex-wrap items-center justify-between gap-4">
						<div class="min-w-0">
							<p class="text-grafite truncate text-[0.9375rem] font-medium">
								{aluno.person.full_name}
							</p>
							<p class="text-cinza mt-0.5 truncate font-mono text-[0.8125rem]">
								{aluno.person.primary_email}{aluno.registration_number
									? ` · ${aluno.registration_number}`
									: ''}
							</p>
							<p class="text-cinza mt-0.5 text-[0.8125rem]">
								{#if aluno.modality === 'regular'}
									{rotulo(NIVEIS, aluno.level)} · {aluno.project_id === null
										? 'sem projeto'
										: (nomeDoProjeto[aluno.project_id] ?? '—')} · {aluno.advisor_id === null
										? 'sem orientador'
										: (nomeDoOrientador[aluno.advisor_id] ?? '—')} · prazo {aluno.deadline ?? '—'}
								{:else}
									{aluno.term_id === null ? '—' : (rotuloDoPeriodo[aluno.term_id] ?? '—')}
								{/if}
							</p>
						</div>
						<div class="flex shrink-0 items-center gap-4">
							<!-- Modalidade e situação, sempre em colunas separadas. -->
							<span class="etiqueta">{rotulo(MODALIDADES, aluno.modality)}</span>
							<span class="etiqueta">{rotulo(SITUACOES, aluno.status)}</span>
							{#if podeDefinirSenha && aluno.person.needs_initial_password}
								<button class="botao-discreto" type="button" onclick={() => abrirSenha(aluno)}>
									Definir senha inicial
								</button>
							{/if}
							<div class="flex items-center gap-1">
								<a
									class="botao-icone"
									href={resolve('/(app)/alunos/[id]', { id: String(aluno.id) })}
									title="Detalhes de {aluno.person.full_name}"
								>
									<Icone nome="olho" rotulo="Detalhes" />
								</a>
								{#if podeEditar}
									<button
										class="botao-icone"
										type="button"
										title="Editar {aluno.person.full_name}"
										onclick={() => editar(aluno)}
									>
										<Icone nome="lapis" rotulo="Editar" />
									</button>
									<!-- Excluir aqui é encerrar o vínculo, não apagar: o histórico
									sustenta acerto de matrícula já decidido. -->
									<button
										class="botao-icone botao-icone-perigo"
										type="button"
										disabled={aluno.status === 'excluded' || excluindo === aluno.id}
										title={aluno.status === 'excluded'
											? 'Já excluído'
											: `Excluir ${aluno.person.full_name}`}
										onclick={() => excluir(aluno)}
									>
										<Icone nome="arquivo" rotulo="Excluir" />
									</button>
								{/if}
							</div>
						</div>
					</div>

					{#if definindoSenhaDe === aluno.id}
						<form
							class="border-borda mt-4 flex flex-wrap items-end gap-3 border border-dashed p-4"
							onsubmit={(event) => definirSenha(event, aluno)}
						>
							<div>
								<label class="etiqueta mb-2 block" for="senha-{aluno.id}">
									Senha do primeiro acesso
								</label>
								<input
									id="senha-{aluno.id}"
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
