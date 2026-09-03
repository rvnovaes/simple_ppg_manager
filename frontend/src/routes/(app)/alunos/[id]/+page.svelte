<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { api, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';

	type Aluno = components['schemas']['StudentOut'];

	const MODALIDADES: Record<string, string> = {
		regular: 'Regular',
		isolated: 'Isolada',
		elective: 'Eletiva'
	};
	// Modalidade e situação são campos separados (ADR-007): "Isolada" e
	// "Trancado" não disputam o mesmo espaço.
	const SITUACOES: Record<string, string> = {
		active: 'Ativo',
		leave: 'Trancado',
		excluded: 'Excluído'
	};
	const NIVEIS: Record<string, string> = {
		masters: 'Mestrado',
		doctorate: 'Doutorado'
	};

	let aluno = $state<Aluno | null>(null);
	let carregando = $state(true);
	let erro = $state('');

	const id = $derived(Number(page.params.id));
	const regular = $derived(aluno?.modality === 'regular');

	async function carregar(studentId: number) {
		carregando = true;
		erro = '';
		const { data, error } = await api.GET('/academic/students/{student_id}/', {
			params: { path: { student_id: studentId } }
		});
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar o aluno.');
		} else {
			aluno = data ?? null;
		}
		carregando = false;
	}

	function data(valor: string | null | undefined): string {
		return valor ? new Date(`${valor}T00:00:00`).toLocaleDateString('pt-BR') : '—';
	}

	$effect(() => {
		if (!Number.isNaN(id)) carregar(id);
	});
</script>

<svelte:head>
	<title>{aluno?.person.full_name ?? 'Aluno'} · PPGM</title>
</svelte:head>

<a class="etiqueta hover:text-tinta" href={resolve('/alunos')}>← Alunos</a>

{#if erro}
	<p class="aviso-erro mt-6" role="alert">{erro}</p>
{:else if carregando}
	<p class="etiqueta mt-6">Carregando…</p>
{:else if aluno}
	<header class="mt-2 flex flex-wrap items-end justify-between gap-4">
		<div>
			<p class="etiqueta">Aluno</p>
			<h1 class="text-grafite mt-1 text-2xl font-semibold tracking-tight">
				{aluno.person.full_name}
			</h1>
		</div>
		<div class="flex items-center gap-3">
			<span class="etiqueta">{MODALIDADES[aluno.modality] ?? aluno.modality}</span>
			<span class="etiqueta">{SITUACOES[aluno.status] ?? aluno.status}</span>
		</div>
	</header>

	<dl class="border-borda bg-papel mt-8 grid gap-x-8 gap-y-5 border p-6 sm:grid-cols-2">
		<div>
			<dt class="etiqueta">E-mail</dt>
			<dd class="text-grafite mt-1 font-mono text-[0.875rem]">{aluno.person.primary_email}</dd>
		</div>
		<div>
			<dt class="etiqueta">Telefone</dt>
			<dd class="text-grafite mt-1 font-mono text-[0.875rem]">
				{aluno.person.phone_number || '—'}
			</dd>
		</div>
		<div>
			<dt class="etiqueta">Matrícula</dt>
			<dd class="text-grafite mt-1 font-mono text-[0.875rem]">
				{aluno.registration_number || '—'}
			</dd>
		</div>
		<div>
			<dt class="etiqueta">Período letivo</dt>
			<dd class="text-grafite mt-1 font-mono text-[0.875rem]">{aluno.term_label ?? '—'}</dd>
		</div>

		<!-- Campos de grau só existem no regular: a isolada e a eletiva duram
		um semestre e nem podem tê-los (CheckConstraint do model). Mostrá-los
		vazios sugeriria cadastro incompleto. -->
		{#if regular}
			<div>
				<dt class="etiqueta">Nível</dt>
				<dd class="text-grafite mt-1 text-[0.875rem]">
					{aluno.level ? (NIVEIS[aluno.level] ?? aluno.level) : '—'}
				</dd>
			</div>
			<div>
				<dt class="etiqueta">Orientador</dt>
				<dd class="text-grafite mt-1 text-[0.875rem]">{aluno.advisor_name ?? '—'}</dd>
			</div>
			<div>
				<dt class="etiqueta">Projeto coletivo</dt>
				<dd class="text-grafite mt-1 text-[0.875rem]">{aluno.project_name ?? '—'}</dd>
			</div>
			<div>
				<dt class="etiqueta">Ingresso</dt>
				<dd class="text-grafite mt-1 font-mono text-[0.875rem]">{data(aluno.admission_date)}</dd>
			</div>
			<div>
				<dt class="etiqueta">Prazo de conclusão</dt>
				<dd class="text-grafite mt-1 font-mono text-[0.875rem]">{data(aluno.deadline)}</dd>
			</div>
			<div>
				<dt class="etiqueta">Defesa</dt>
				<dd class="text-grafite mt-1 font-mono text-[0.875rem]">{data(aluno.defense_date)}</dd>
			</div>
		{/if}
	</dl>
{/if}
