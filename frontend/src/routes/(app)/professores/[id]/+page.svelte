<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { api, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';

	type Professor = components['schemas']['TeacherOut'];
	type Linha = components['schemas']['ResearchLineOut'];
	type Projeto = components['schemas']['CollectiveProjectOut'];

	const CATEGORIAS: Record<string, string> = {
		permanent: 'Permanente',
		collaborator: 'Colaborador',
		visiting: 'Visitante'
	};
	const TITULACOES: Record<string, string> = {
		doctorate: 'Doutor',
		postdoctorate: 'Pós-doutor',
		habilitation: 'Livre-docente'
	};

	let professor = $state<Professor | null>(null);
	let linhas = $state<Linha[]>([]);
	let projetos = $state<Projeto[]>([]);
	let carregando = $state(true);
	let erro = $state('');

	const id = $derived(Number(page.params.id));

	// Os vínculos chegam como lista de id; sem os nomes a tela mostraria
	// números, que não dizem nada a quem lê.
	const nomesDasLinhas = $derived(
		(professor?.research_line_ids ?? []).map(
			(idLinha) => linhas.find((l) => l.id === idLinha)?.name ?? `#${idLinha}`
		)
	);
	const nomesDosProjetos = $derived(
		(professor?.project_ids ?? []).map(
			(idProjeto) => projetos.find((p) => p.id === idProjeto)?.name ?? `#${idProjeto}`
		)
	);

	async function carregar(teacherId: number) {
		carregando = true;
		erro = '';
		const [respProfessor, respLinhas, respProjetos] = await Promise.all([
			api.GET('/academic/teachers/{teacher_id}/', {
				params: { path: { teacher_id: teacherId } }
			}),
			api.GET('/programs/research-lines/'),
			api.GET('/programs/collective-projects/')
		]);
		const falha = respProfessor.error ?? respLinhas.error ?? respProjetos.error;
		if (falha) {
			erro = mensagemDeErro(falha, 'Não foi possível carregar o professor.');
		} else {
			professor = respProfessor.data ?? null;
			linhas = respLinhas.data?.items ?? [];
			projetos = respProjetos.data?.items ?? [];
		}
		carregando = false;
	}

	function data(valor: string | null): string {
		return valor ? new Date(`${valor}T00:00:00`).toLocaleDateString('pt-BR') : '—';
	}

	$effect(() => {
		if (!Number.isNaN(id)) carregar(id);
	});
</script>

<svelte:head>
	<title>{professor?.person.full_name ?? 'Professor'} · PPGD Manager</title>
</svelte:head>

<a class="etiqueta hover:text-tinta" href={resolve('/professores')}>← Professores</a>

{#if erro}
	<p class="aviso-erro mt-6" role="alert">{erro}</p>
{:else if carregando}
	<p class="etiqueta mt-6">Carregando…</p>
{:else if professor}
	<header class="mt-2 flex flex-wrap items-end justify-between gap-4">
		<div>
			<p class="etiqueta">Professor</p>
			<h1 class="text-grafite mt-1 text-2xl font-semibold tracking-tight">
				{professor.person.full_name}
			</h1>
		</div>
		<span class="etiqueta">
			{professor.accredited_until === null ? 'Credenciado' : 'Descredenciado'}
		</span>
	</header>

	<dl class="border-borda bg-papel mt-8 grid gap-x-8 gap-y-5 border p-6 sm:grid-cols-2">
		<div>
			<dt class="etiqueta">E-mail</dt>
			<dd class="text-grafite mt-1 font-mono text-[0.875rem]">
				{professor.person.primary_email}
			</dd>
		</div>
		<div>
			<dt class="etiqueta">Telefone</dt>
			<dd class="text-grafite mt-1 font-mono text-[0.875rem]">
				{professor.person.phone_number || '—'}
			</dd>
		</div>
		<div>
			<dt class="etiqueta">Categoria CAPES</dt>
			<dd class="text-grafite mt-1 text-[0.875rem]">
				{CATEGORIAS[professor.category] ?? professor.category}
			</dd>
		</div>
		<div>
			<dt class="etiqueta">Titulação</dt>
			<dd class="text-grafite mt-1 text-[0.875rem]">
				{TITULACOES[professor.academic_degree] ?? professor.academic_degree}
			</dd>
		</div>
		<div>
			<dt class="etiqueta">Credenciado desde</dt>
			<dd class="text-grafite mt-1 font-mono text-[0.875rem]">
				{data(professor.accredited_since)}
			</dd>
		</div>
		<div>
			<dt class="etiqueta">Credenciado até</dt>
			<dd class="text-grafite mt-1 font-mono text-[0.875rem]">
				{data(professor.accredited_until)}
			</dd>
		</div>
		<div>
			<dt class="etiqueta">Instituição de origem</dt>
			<dd class="text-grafite mt-1 text-[0.875rem]">{professor.home_institution || '—'}</dd>
		</div>
		<div>
			<dt class="etiqueta">Lattes</dt>
			<dd class="text-grafite mt-1 truncate text-[0.875rem]">
				{#if professor.lattes_url}
					<!-- URL externa (lattes.cnpq.br), gravada no cadastro: resolve()
					é para rota do próprio app e aqui não se aplica. -->
					<!-- eslint-disable svelte/no-navigation-without-resolve -->
					<a
						class="underline"
						href={professor.lattes_url}
						rel="noreferrer noopener"
						target="_blank"
					>
						{professor.lattes_url}
					</a>
					<!-- eslint-enable svelte/no-navigation-without-resolve -->
				{:else}
					—
				{/if}
			</dd>
		</div>
		<div class="sm:col-span-2">
			<dt class="etiqueta">Linhas de pesquisa</dt>
			<dd class="text-grafite mt-1 text-[0.875rem]">{nomesDasLinhas.join(' · ') || '—'}</dd>
		</div>
		<div class="sm:col-span-2">
			<dt class="etiqueta">Projetos coletivos</dt>
			<dd class="text-grafite mt-1 text-[0.875rem]">{nomesDosProjetos.join(' · ') || '—'}</dd>
		</div>
	</dl>
{/if}
