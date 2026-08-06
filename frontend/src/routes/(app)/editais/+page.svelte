<script lang="ts">
	import { api, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';
	import { formatarPrazo } from '$lib/isolada';
	import { sessao } from '$lib/sessao.svelte';

	type Ciclo = components['schemas']['IsolatedCycleOut'];
	type Oferta = components['schemas']['DisciplineOfferingOut'];
	type Disciplina = components['schemas']['DisciplineOut'];
	type Professor = components['schemas']['TeacherOut'];
	type Periodo = components['schemas']['AcademicTermOut'];

	let ciclos = $state<Ciclo[]>([]);
	let ofertas = $state<Oferta[]>([]);
	let periodos = $state<Periodo[]>([]);
	let disciplinas = $state<Disciplina[]>([]);
	let professores = $state<Professor[]>([]);

	let carregando = $state(true);
	let erro = $state('');
	let aviso = $state('');
	let salvando = $state(false);

	let cicloId = $state<number | null>(null);
	const ciclo = $derived(ciclos.find((c) => c.id === cicloId) ?? null);

	// Coordenação acompanha o edital em modo somente leitura: sem a
	// permissão de escrita o formulário e os botões nem existem na tela (a
	// checagem que vale continua sendo a do backend).
	const podeMontar = $derived(sessao.pode('academic.add_isolatedenrollmentcycle'));
	const podeCorrigir = $derived(sessao.pode('academic.change_isolatedenrollmentcycle'));
	const podeOfertar = $derived(sessao.pode('academic.add_disciplineoffering'));
	const podeCorrigirOferta = $derived(sessao.pode('academic.change_disciplineoffering'));

	/**
	 * ISO do servidor -> valor de `<input type="datetime-local">`.
	 *
	 * O input não aceita fuso: ele fala no relógio de quem preenche. A
	 * conversão nos dois sentidos mora aqui para o formulário mandar sempre
	 * ISO com fuso, que é o que o schema Ninja recebe.
	 */
	function isoParaLocal(iso: string): string {
		const data = new Date(iso);
		const deslocado = new Date(data.getTime() - data.getTimezoneOffset() * 60_000);
		return deslocado.toISOString().slice(0, 16);
	}

	function localParaIso(local: string): string {
		return new Date(local).toISOString();
	}

	async function carregarCiclos(selecionar?: number) {
		const { data, error } = await api.GET('/academic/isolated/cycles/');
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar os editais do programa.');
			return;
		}
		ciclos = data ?? [];
		// O servidor devolve do semestre mais recente para o mais antigo.
		cicloId = selecionar ?? ciclos[0]?.id ?? null;
	}

	async function carregarOfertas(alvo: number) {
		// `?cycle_id=`: a lista da secretaria é a do edital escolhido, e não
		// a do que está com inscrição aberta agora.
		const { data, error } = await api.GET('/academic/isolated/offerings/', {
			params: { query: { cycle_id: alvo } }
		});
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar as ofertas do edital.');
			return;
		}
		ofertas = data ?? [];
	}

	async function carregarApoio() {
		const [semestres, catalogo, docentes] = await Promise.all([
			api.GET('/programs/terms/'),
			api.GET('/programs/disciplines/'),
			api.GET('/academic/teachers/')
		]);
		const falha = semestres.error ?? catalogo.error ?? docentes.error;
		if (falha) {
			erro = mensagemDeErro(falha, 'Não foi possível carregar períodos, disciplinas e docentes.');
			return;
		}
		periodos = semestres.data?.items ?? [];
		disciplinas = (catalogo.data?.items ?? []).filter((d) => d.is_active);
		professores = docentes.data?.items ?? [];
	}

	async function carregar() {
		carregando = true;
		erro = '';
		await Promise.all([carregarCiclos(), carregarApoio()]);
		if (cicloId !== null) await carregarOfertas(cicloId);
		carregando = false;
	}

	async function trocarDeCiclo(alvo: number) {
		cicloId = alvo;
		ofertas = [];
		aviso = '';
		await carregarOfertas(alvo);
	}

	// --- formulário do edital -------------------------------------------

	let formDoCiclo = $state(false);
	let editandoCiclo = $state<Ciclo | null>(null);
	let termId = $state<number | null>(null);
	let inscricaoAbre = $state('');
	let inscricaoFecha = $state('');
	let resultadoEm = $state('');
	let recursoAbre = $state('');
	let recursoFecha = $state('');
	let resultadoFinalEm = $state('');
	let pagamentoFecha = $state('');

	function abrirNovoCiclo() {
		editandoCiclo = null;
		termId = periodos[0]?.id ?? null;
		inscricaoAbre = '';
		inscricaoFecha = '';
		resultadoEm = '';
		recursoAbre = '';
		recursoFecha = '';
		resultadoFinalEm = '';
		pagamentoFecha = '';
		formDoCiclo = true;
	}

	function editarCiclo(alvo: Ciclo) {
		editandoCiclo = alvo;
		termId = alvo.term_id;
		inscricaoAbre = isoParaLocal(alvo.submission_opens_at);
		inscricaoFecha = isoParaLocal(alvo.submission_closes_at);
		resultadoEm = alvo.result_published_on;
		recursoAbre = isoParaLocal(alvo.appeal_opens_at);
		recursoFecha = isoParaLocal(alvo.appeal_closes_at);
		resultadoFinalEm = alvo.final_result_on;
		pagamentoFecha = isoParaLocal(alvo.payment_closes_at);
		formDoCiclo = true;
	}

	/**
	 * A mesma ordem que `IsolatedEnrollmentCycle.clean()` cobra.
	 *
	 * É validação de UX, e não a que vale: o 400 `invalid_cycle_dates` do
	 * backend continua sendo a palavra final (Seção 8). Adiantá-la aqui
	 * poupa a secretaria de descobrir o erro depois de preencher sete datas.
	 */
	function calendarioForaDeOrdem(): string {
		const abre = new Date(inscricaoAbre).getTime();
		const fecha = new Date(inscricaoFecha).getTime();
		const recurso = new Date(recursoAbre).getTime();
		const fimDoRecurso = new Date(recursoFecha).getTime();
		const pagamento = new Date(pagamentoFecha).getTime();
		if (!(abre < fecha)) return 'As inscrições precisam fechar depois de abrir.';
		if (!(fecha <= recurso)) return 'O recurso não pode abrir antes de as inscrições fecharem.';
		if (!(recurso < fimDoRecurso)) return 'O recurso precisa fechar depois de abrir.';
		if (!(fimDoRecurso <= pagamento))
			return 'O prazo de pagamento não pode terminar antes de o recurso fechar.';
		return '';
	}

	async function salvarCiclo(event: SubmitEvent) {
		event.preventDefault();
		erro = '';
		aviso = '';
		const desordem = calendarioForaDeOrdem();
		if (desordem !== '') {
			erro = desordem;
			return;
		}
		if (termId === null) {
			erro = 'Escolha o período letivo do edital.';
			return;
		}
		salvando = true;
		const corpo = {
			term_id: termId,
			submission_opens_at: localParaIso(inscricaoAbre),
			submission_closes_at: localParaIso(inscricaoFecha),
			result_published_on: resultadoEm,
			appeal_opens_at: localParaIso(recursoAbre),
			appeal_closes_at: localParaIso(recursoFecha),
			final_result_on: resultadoFinalEm,
			payment_closes_at: localParaIso(pagamentoFecha)
		};
		const alvo = editandoCiclo;
		const resposta = alvo
			? await api.PATCH('/academic/isolated/cycles/{cycle_id}/', {
					params: { path: { cycle_id: alvo.id } },
					body: corpo
				})
			: await api.POST('/academic/isolated/cycles/', { body: corpo });
		salvando = false;
		// A falha sai para uma const ANTES do `if`: dentro dele o objeto
		// inteiro é estreitado e `resposta.error` viraria `never`.
		const falha = resposta.error;
		if (falha || !resposta.data) {
			erro = mensagemDeErro(falha, 'Não foi possível salvar o edital.');
			return;
		}
		formDoCiclo = false;
		editandoCiclo = null;
		await carregarCiclos(resposta.data.id);
		await carregarOfertas(resposta.data.id);
	}

	// --- formulário da oferta -------------------------------------------

	let formDaOferta = $state(false);
	let editandoOferta = $state<Oferta | null>(null);
	let disciplinaId = $state<number | null>(null);
	let docenteId = $state<number | null>(null);
	let vagas = $state(1);

	function abrirNovaOferta() {
		editandoOferta = null;
		disciplinaId = disciplinas[0]?.id ?? null;
		docenteId = professores[0]?.id ?? null;
		vagas = 1;
		formDaOferta = true;
	}

	function editarOferta(alvo: Oferta) {
		editandoOferta = alvo;
		disciplinaId = alvo.discipline_id;
		docenteId = alvo.teacher_id;
		vagas = alvo.seats;
		formDaOferta = true;
	}

	async function salvarOferta(event: SubmitEvent) {
		event.preventDefault();
		erro = '';
		aviso = '';
		if (cicloId === null || disciplinaId === null || docenteId === null) {
			erro = 'Escolha a disciplina e o docente responsável.';
			return;
		}
		salvando = true;
		const alvo = editandoOferta;
		const resposta = alvo
			? await api.PATCH('/academic/isolated/offerings/{offering_id}/', {
					params: { path: { offering_id: alvo.id } },
					body: { discipline_id: disciplinaId, teacher_id: docenteId, seats: vagas }
				})
			: await api.POST('/academic/isolated/offerings/', {
					body: {
						cycle_id: cicloId,
						discipline_id: disciplinaId,
						teacher_id: docenteId,
						seats: vagas
					}
				});
		salvando = false;
		const falha = resposta.error;
		if (falha || !resposta.data) {
			erro = mensagemDeErro(falha, 'Não foi possível salvar a oferta.');
			return;
		}
		const salva = resposta.data;
		ofertas = alvo
			? ofertas.map((o) => (o.id === salva.id ? salva : o))
			: [...ofertas, salva].sort((a, b) => a.discipline_code.localeCompare(b.discipline_code));
		formDaOferta = false;
		editandoOferta = null;
	}

	// --- encerramento ----------------------------------------------------

	// Confirmação em dois passos: encerrar exclui vínculo de aluno e não tem
	// desfazer pelo caminho normal. `students_to_exclude` vem do servidor —
	// a tela não conta aluno por conta própria.
	let confirmandoEncerramento = $state(false);

	async function encerrar() {
		if (ciclo === null) return;
		erro = '';
		aviso = '';
		salvando = true;
		const { data, error } = await api.POST('/academic/isolated/cycles/{cycle_id}/close', {
			params: { path: { cycle_id: ciclo.id } }
		});
		salvando = false;
		confirmandoEncerramento = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível encerrar o período.');
			return;
		}
		aviso =
			data.students_excluded === 0
				? 'Período encerrado. Nenhum aluno de isolada estava ativo neste semestre.'
				: `Período encerrado. ${data.students_excluded} aluno(s) de isolada marcados como excluídos.`;
		await carregarCiclos(data.cycle_id);
	}

	$effect(() => {
		carregar();
	});
</script>

<svelte:head>
	<title>Editais de isolada · PPGD Manager</title>
</svelte:head>

<header class="flex flex-wrap items-end justify-between gap-4">
	<div>
		<p class="etiqueta">Disciplina isolada</p>
		<h1 class="text-grafite mt-1 text-2xl font-semibold tracking-tight">Edital do semestre</h1>
	</div>
	{#if podeMontar}
		<button class="botao-discreto" type="button" onclick={abrirNovoCiclo}>Novo edital</button>
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

{#if formDoCiclo}
	<form class="border-borda bg-papel mt-6 border p-5" onsubmit={salvarCiclo}>
		<p class="etiqueta">{editandoCiclo ? 'Corrigir calendário' : 'Novo edital'}</p>
		<div class="mt-4 grid gap-4 sm:grid-cols-2">
			<div>
				<label class="etiqueta mb-2 block" for="edital-periodo">Período letivo</label>
				<select id="edital-periodo" class="campo" bind:value={termId} required>
					{#each periodos as periodo (periodo.id)}
						<option value={periodo.id}>{periodo.label}</option>
					{/each}
				</select>
			</div>
			<div></div>
			<div>
				<label class="etiqueta mb-2 block" for="edital-inscricao-abre">Inscrições abrem em</label>
				<input
					id="edital-inscricao-abre"
					class="campo"
					type="datetime-local"
					bind:value={inscricaoAbre}
					required
				/>
			</div>
			<div>
				<label class="etiqueta mb-2 block" for="edital-inscricao-fecha">
					Inscrições encerram em
				</label>
				<input
					id="edital-inscricao-fecha"
					class="campo"
					type="datetime-local"
					bind:value={inscricaoFecha}
					required
				/>
			</div>
			<div>
				<label class="etiqueta mb-2 block" for="edital-resultado">Resultado publicado em</label>
				<input id="edital-resultado" class="campo" type="date" bind:value={resultadoEm} required />
			</div>
			<div>
				<label class="etiqueta mb-2 block" for="edital-resultado-final">Resultado final em</label>
				<input
					id="edital-resultado-final"
					class="campo"
					type="date"
					bind:value={resultadoFinalEm}
					required
				/>
			</div>
			<div>
				<label class="etiqueta mb-2 block" for="edital-recurso-abre">Recursos abrem em</label>
				<input
					id="edital-recurso-abre"
					class="campo"
					type="datetime-local"
					bind:value={recursoAbre}
					required
				/>
			</div>
			<div>
				<label class="etiqueta mb-2 block" for="edital-recurso-fecha">Recursos encerram em</label>
				<input
					id="edital-recurso-fecha"
					class="campo"
					type="datetime-local"
					bind:value={recursoFecha}
					required
				/>
			</div>
			<div>
				<label class="etiqueta mb-2 block" for="edital-pagamento">Pagamento da GRU encerra em</label
				>
				<input
					id="edital-pagamento"
					class="campo"
					type="datetime-local"
					bind:value={pagamentoFecha}
					required
				/>
			</div>
		</div>
		<div class="mt-4 flex items-center gap-2">
			<button class="botao" type="submit" disabled={salvando}>
				{salvando ? 'Salvando…' : 'Salvar edital'}
			</button>
			<button class="botao-discreto" type="button" onclick={() => (formDoCiclo = false)}>
				Cancelar
			</button>
		</div>
	</form>
{/if}

{#if carregando}
	<p class="etiqueta mt-6">Carregando…</p>
{:else if ciclos.length === 0}
	<div class="border-borda bg-papel mt-6 border border-dashed p-10 text-center">
		<p class="text-grafite text-[0.9375rem]">Nenhum edital cadastrado ainda.</p>
		<p class="text-cinza mt-1 text-sm">
			{podeMontar
				? 'O edital é o calendário do semestre: sem ele ninguém se inscreve.'
				: 'A secretaria ainda não publicou o edital deste semestre.'}
		</p>
	</div>
{:else}
	<div class="mt-8 grid gap-4 sm:grid-cols-[1fr_auto]">
		<div>
			<label class="etiqueta mb-2 block" for="edital-selecao">Edital</label>
			<select
				id="edital-selecao"
				class="campo"
				value={cicloId}
				onchange={(e) => trocarDeCiclo(Number(e.currentTarget.value))}
			>
				{#each ciclos as opcao (opcao.id)}
					<option value={opcao.id}>
						{opcao.term_label}{opcao.is_active ? '' : ' (encerrado)'}
					</option>
				{/each}
			</select>
		</div>
		{#if ciclo && podeCorrigir}
			<div class="flex items-end gap-2">
				<button class="botao-discreto" type="button" onclick={() => editarCiclo(ciclo)}>
					Corrigir calendário
				</button>
				{#if ciclo.is_active}
					<button
						class="botao-discreto"
						type="button"
						onclick={() => (confirmandoEncerramento = true)}
					>
						Encerrar período
					</button>
				{/if}
			</div>
		{/if}
	</div>

	{#if ciclo}
		<section class="border-borda bg-papel mt-6 border p-5">
			<div class="flex flex-wrap items-center justify-between gap-4">
				<p class="etiqueta">Calendário de {ciclo.term_label}</p>
				<span class="etiqueta">
					{ciclo.is_active ? (ciclo.submission_open ? 'Inscrições abertas' : 'Ativo') : 'Encerrado'}
				</span>
			</div>
			<dl class="text-grafite mt-4 grid gap-3 text-sm sm:grid-cols-2">
				<div>
					<dt class="etiqueta">Inscrições</dt>
					<dd>
						{formatarPrazo(ciclo.submission_opens_at)} até {formatarPrazo(
							ciclo.submission_closes_at
						)}
					</dd>
				</div>
				<div>
					<dt class="etiqueta">Recursos</dt>
					<dd>
						{formatarPrazo(ciclo.appeal_opens_at)} até {formatarPrazo(ciclo.appeal_closes_at)}
					</dd>
				</div>
				<div>
					<dt class="etiqueta">Resultado</dt>
					<dd>{ciclo.result_published_on} · final em {ciclo.final_result_on}</dd>
				</div>
				<div>
					<dt class="etiqueta">Pagamento da GRU</dt>
					<dd>até {formatarPrazo(ciclo.payment_closes_at)}</dd>
				</div>
			</dl>
		</section>

		{#if confirmandoEncerramento}
			<section class="border-borda bg-papel mt-4 border p-5" role="alertdialog">
				<p class="etiqueta">Encerrar o período de {ciclo.term_label}</p>
				<p class="text-grafite mt-3 text-sm">
					{#if ciclo.students_to_exclude === 0}
						Nenhum aluno de isolada ativo neste semestre será alterado. O edital sai do ar e não
						recebe mais nada.
					{:else}
						<strong>{ciclo.students_to_exclude} aluno(s)</strong> de isolada deste semestre serão marcados
						como excluídos, e o edital sai do ar. Não há como desfazer pela tela.
					{/if}
				</p>
				<div class="mt-4 flex items-center gap-2">
					<button class="botao" type="button" disabled={salvando} onclick={encerrar}>
						{salvando ? 'Encerrando…' : 'Encerrar mesmo assim'}
					</button>
					<button
						class="botao-discreto"
						type="button"
						onclick={() => (confirmandoEncerramento = false)}
					>
						Cancelar
					</button>
				</div>
			</section>
		{/if}

		<section class="mt-8">
			<div class="flex flex-wrap items-end justify-between gap-4">
				<h2 class="text-grafite text-lg font-semibold tracking-tight">Disciplinas ofertadas</h2>
				{#if podeOfertar && ciclo.is_active}
					<button class="botao-discreto" type="button" onclick={abrirNovaOferta}>
						Nova oferta
					</button>
				{/if}
			</div>

			{#if formDaOferta}
				<form class="border-borda bg-papel mt-4 border p-5" onsubmit={salvarOferta}>
					<p class="etiqueta">{editandoOferta ? 'Editar oferta' : 'Nova oferta'}</p>
					<div class="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-[1fr_1fr_auto_auto]">
						<div>
							<label class="etiqueta mb-2 block" for="oferta-disciplina">Disciplina</label>
							<select id="oferta-disciplina" class="campo" bind:value={disciplinaId} required>
								{#each disciplinas as disciplina (disciplina.id)}
									<option value={disciplina.id}>{disciplina.code} · {disciplina.name}</option>
								{/each}
							</select>
						</div>
						<div>
							<label class="etiqueta mb-2 block" for="oferta-docente">Docente responsável</label>
							<select id="oferta-docente" class="campo" bind:value={docenteId} required>
								{#each professores as professor (professor.id)}
									<option value={professor.id}>{professor.person.full_name}</option>
								{/each}
							</select>
						</div>
						<div>
							<label class="etiqueta mb-2 block" for="oferta-vagas">Vagas</label>
							<input
								id="oferta-vagas"
								class="campo w-24"
								type="number"
								min="1"
								bind:value={vagas}
								required
							/>
						</div>
						<div class="flex items-end gap-2">
							<button class="botao" type="submit" disabled={salvando}>
								{salvando ? 'Salvando…' : 'Salvar'}
							</button>
							<button class="botao-discreto" type="button" onclick={() => (formDaOferta = false)}>
								Cancelar
							</button>
						</div>
					</div>
				</form>
			{/if}

			{#if ofertas.length === 0}
				<div class="border-borda bg-papel mt-4 border border-dashed p-10 text-center">
					<p class="text-grafite text-[0.9375rem]">Nenhuma disciplina neste edital.</p>
					<p class="text-cinza mt-1 text-sm">
						Sem oferta, o candidato abre o requerimento e não tem o que escolher.
					</p>
				</div>
			{:else}
				<ul class="mt-4 space-y-px">
					{#each ofertas as oferta (oferta.id)}
						<li
							class="bg-papel regua-tinta flex flex-wrap items-center justify-between gap-4 px-5 py-4"
						>
							<div class="min-w-0">
								<p class="text-grafite font-mono text-[0.9375rem] font-medium">
									{oferta.discipline_code}
								</p>
								<p class="text-cinza mt-0.5 truncate text-sm">
									{oferta.discipline_name} · {oferta.teacher_name}
								</p>
							</div>
							<div class="flex shrink-0 items-center gap-4">
								<span class="etiqueta">
									{oferta.seats_available} de {oferta.seats} vaga(s)
								</span>
								{#if oferta.needs_ranking}
									<span class="etiqueta">Falta classificar</span>
								{/if}
								{#if podeCorrigirOferta && ciclo.is_active}
									<button class="botao-discreto" type="button" onclick={() => editarOferta(oferta)}>
										Editar
									</button>
								{/if}
							</div>
						</li>
					{/each}
				</ul>
			{/if}
		</section>
	{/if}
{/if}
