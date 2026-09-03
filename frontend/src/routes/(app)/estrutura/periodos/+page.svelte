<script lang="ts">
	import { api, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';
	import { sessao } from '$lib/sessao.svelte';

	type Periodo = components['schemas']['AcademicTermOut'];

	let periodos = $state<Periodo[]>([]);
	let carregando = $state(true);
	let erro = $state('');

	// Coordenação só lê: sem a permissão de escrita, o formulário nem existe
	// na tela (a checagem que vale continua sendo a do backend).
	const podeCriarPeriodo = $derived(sessao.pode('programs.add_academicterm'));
	const podeEditarPeriodo = $derived(sessao.pode('programs.change_academicterm'));

	async function carregar() {
		carregando = true;
		erro = '';
		const { data, error } = await api.GET('/programs/terms/');
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar os períodos letivos.');
		} else {
			periodos = data?.items ?? [];
		}
		carregando = false;
	}

	let periodoEmEdicao = $state<Periodo | null>(null);
	let formPeriodoAberto = $state(false);
	let periodoAno = $state(new Date().getFullYear());
	let periodoSemestre = $state<1 | 2>(1);
	let periodoInicio = $state('');
	let periodoFim = $state('');
	let periodoAtivo = $state(true);
	let salvandoPeriodo = $state(false);

	function abrirNovoPeriodo() {
		periodoEmEdicao = null;
		periodoAno = new Date().getFullYear();
		periodoSemestre = 1;
		periodoInicio = '';
		periodoFim = '';
		periodoAtivo = true;
		formPeriodoAberto = true;
	}

	function editarPeriodo(periodo: Periodo) {
		periodoEmEdicao = periodo;
		periodoAno = periodo.year;
		periodoSemestre = periodo.half === 2 ? 2 : 1;
		periodoInicio = periodo.starts_on;
		periodoFim = periodo.ends_on;
		periodoAtivo = periodo.is_active;
		formPeriodoAberto = true;
	}

	function fecharFormPeriodo() {
		formPeriodoAberto = false;
		periodoEmEdicao = null;
	}

	async function salvarPeriodo(event: SubmitEvent) {
		event.preventDefault();
		erro = '';
		salvandoPeriodo = true;
		const corpo = {
			year: periodoAno,
			half: periodoSemestre,
			starts_on: periodoInicio,
			ends_on: periodoFim,
			is_active: periodoAtivo
		};
		const alvo = periodoEmEdicao;
		const { data, error } = alvo
			? await api.PATCH('/programs/terms/{academic_term_id}/', {
					params: { path: { academic_term_id: alvo.id } },
					body: corpo
				})
			: await api.POST('/programs/terms/', { body: corpo });
		salvandoPeriodo = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível salvar o período letivo.');
			return;
		}
		periodos = alvo
			? periodos.map((p) => (p.id === data.id ? data : p))
			: [...periodos, data].sort((a, b) => b.year - a.year || b.half - a.half);
		fecharFormPeriodo();
	}

	$effect(() => {
		carregar();
	});
</script>

<svelte:head>
	<title>Períodos letivos · PPGM</title>
</svelte:head>

<header class="flex flex-wrap items-end justify-between gap-4">
	<div>
		<p class="etiqueta">Estrutura</p>
		<h1 class="text-grafite mt-1 text-2xl font-semibold tracking-tight">Períodos letivos</h1>
		<p class="text-cinza mt-1 text-sm">
			Calendário institucional: vale para todos os programas, não só para este.
		</p>
	</div>
	<p class="text-cinza font-mono text-sm">{periodos.length} períodos</p>
</header>

{#if erro}
	<p class="aviso-erro mt-6" role="alert">{erro}</p>
{/if}

<section class="mt-10">
	<div class="flex flex-wrap items-center justify-end gap-3">
		{#if podeCriarPeriodo}
			<button class="botao-discreto" type="button" onclick={abrirNovoPeriodo}>Novo período</button>
		{/if}
	</div>

	{#if formPeriodoAberto}
		<form class="border-borda bg-papel mt-5 border p-5" onsubmit={salvarPeriodo}>
			<p class="etiqueta">{periodoEmEdicao ? 'Editar período' : 'Novo período letivo'}</p>
			<div class="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-6">
				<div>
					<label class="etiqueta mb-2 block" for="periodo-ano">Ano</label>
					<input
						id="periodo-ano"
						type="number"
						class="campo font-mono"
						bind:value={periodoAno}
						required
					/>
				</div>
				<div>
					<label class="etiqueta mb-2 block" for="periodo-semestre">Semestre</label>
					<select id="periodo-semestre" class="campo" bind:value={periodoSemestre}>
						<option value={1}>1</option>
						<option value={2}>2</option>
					</select>
				</div>
				<div>
					<label class="etiqueta mb-2 block" for="periodo-inicio">Início</label>
					<input
						id="periodo-inicio"
						type="date"
						class="campo font-mono"
						bind:value={periodoInicio}
						required
					/>
				</div>
				<div>
					<label class="etiqueta mb-2 block" for="periodo-fim">Fim</label>
					<input
						id="periodo-fim"
						type="date"
						class="campo font-mono"
						bind:value={periodoFim}
						required
					/>
				</div>
				<label class="text-grafite flex items-end gap-2 pb-3 text-sm">
					<input type="checkbox" bind:checked={periodoAtivo} />
					Ativo
				</label>
				<div class="flex items-end gap-2">
					<button class="botao" type="submit" disabled={salvandoPeriodo}>
						{salvandoPeriodo ? 'Salvando…' : 'Salvar'}
					</button>
					<button class="botao-discreto" type="button" onclick={fecharFormPeriodo}>Cancelar</button>
				</div>
			</div>
		</form>
	{/if}

	{#if carregando}
		<p class="etiqueta mt-6">Carregando…</p>
	{:else if periodos.length === 0}
		<div class="border-borda bg-papel mt-6 border border-dashed p-10 text-center">
			<p class="text-grafite text-[0.9375rem]">Nenhum período letivo cadastrado ainda.</p>
		</div>
	{:else}
		<ul class="mt-6 space-y-px">
			{#each periodos as periodo (periodo.id)}
				<li
					class="bg-papel regua-tinta flex flex-wrap items-center justify-between gap-4 px-5 py-4"
					class:opacity-55={!periodo.is_active}
					style:border-left-color={periodo.is_active ? 'var(--color-tinta)' : 'var(--color-borda)'}
				>
					<div class="min-w-0">
						<!-- O rótulo canônico "2026/1" é como o período é chamado no dia a dia. -->
						<p class="text-grafite font-mono text-[0.9375rem] font-medium">{periodo.label}</p>
						<p class="text-cinza mt-0.5 font-mono text-[0.8125rem]">
							{periodo.starts_on} → {periodo.ends_on}
						</p>
					</div>
					<div class="flex shrink-0 items-center gap-4">
						<span class="etiqueta">{periodo.is_active ? 'Ativo' : 'Inativo'}</span>
						{#if podeEditarPeriodo}
							<button class="botao-discreto" type="button" onclick={() => editarPeriodo(periodo)}>
								Editar
							</button>
						{/if}
					</div>
				</li>
			{/each}
		</ul>
	{/if}
</section>
