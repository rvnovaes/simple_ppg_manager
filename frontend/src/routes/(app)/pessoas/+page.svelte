<script lang="ts">
	import { api, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';
	import { sessao } from '$lib/sessao.svelte';

	type Pessoa = components['schemas']['PersonOut'];
	type Programa = components['schemas']['ProgramOut'];

	let pessoas = $state<Pessoa[]>([]);
	let programas = $state<Programa[]>([]);
	let carregando = $state(true);
	let erro = $state('');

	// Formulário de cadastro
	let nome = $state('');
	let email = $state('');
	let telefone = $state('');
	let programaId = $state<number | null>(null);
	let salvando = $state(false);
	let arquivando = $state<number | null>(null);

	const podeCriar = $derived(sessao.pode('people.add_person'));
	const podeArquivar = $derived(sessao.pode('people.change_person'));

	async function carregar() {
		carregando = true;
		erro = '';
		const [listaPessoas, listaProgramas] = await Promise.all([
			api.GET('/people/'),
			api.GET('/programs/')
		]);
		if (listaPessoas.error || listaProgramas.error) {
			erro = mensagemDeErro(
				listaPessoas.error ?? listaProgramas.error,
				'Não foi possível carregar os dados.'
			);
		} else {
			pessoas = listaPessoas.data?.items ?? [];
			programas = listaProgramas.data ?? [];
			programaId ??= programas[0]?.id ?? null;
		}
		carregando = false;
	}

	async function cadastrar(event: SubmitEvent) {
		event.preventDefault();
		if (programaId === null) return;
		erro = '';
		salvando = true;
		const { data, error } = await api.POST('/people/', {
			body: {
				program_id: programaId,
				full_name: nome,
				primary_email: email,
				phone_number: telefone
			}
		});
		salvando = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível cadastrar a pessoa.');
			return;
		}
		pessoas = [...pessoas, data].sort((a, b) => a.full_name.localeCompare(b.full_name, 'pt-BR'));
		nome = '';
		email = '';
		telefone = '';
	}

	async function arquivar(pessoa: Pessoa) {
		erro = '';
		arquivando = pessoa.id;
		const { data, error } = await api.POST('/people/{person_id}/archive', {
			params: { path: { person_id: pessoa.id } }
		});
		arquivando = null;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível arquivar a pessoa.');
			return;
		}
		pessoas = pessoas.map((p) => (p.id === data.id ? data : p));
	}

	$effect(() => {
		carregar();
	});
</script>

<svelte:head>
	<title>Pessoas · PPGD Manager</title>
</svelte:head>

<header class="flex flex-wrap items-end justify-between gap-4">
	<div>
		<p class="etiqueta">Cadastro</p>
		<h1 class="text-grafite mt-1 text-2xl font-semibold tracking-tight">Pessoas</h1>
	</div>
	<p class="text-cinza font-mono text-sm">{pessoas.length} registros</p>
</header>

{#if erro}
	<p class="aviso-erro mt-6" role="alert">{erro}</p>
{/if}

{#if podeCriar}
	<form class="border-borda bg-papel mt-8 border p-5" onsubmit={cadastrar}>
		<p class="etiqueta">Nova pessoa</p>
		<div class="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
			<div class="lg:col-span-2">
				<label class="etiqueta mb-2 block" for="nome">Nome completo</label>
				<input id="nome" class="campo" bind:value={nome} required />
			</div>
			<div>
				<label class="etiqueta mb-2 block" for="email">E-mail</label>
				<input id="email" type="email" class="campo font-mono" bind:value={email} required />
			</div>
			<div>
				<label class="etiqueta mb-2 block" for="telefone">Telefone</label>
				<input id="telefone" class="campo font-mono" bind:value={telefone} />
			</div>
			<div>
				<label class="etiqueta mb-2 block" for="programa">Programa</label>
				<select id="programa" class="campo" bind:value={programaId}>
					{#each programas as programa (programa.id)}
						<option value={programa.id}>{programa.acronym}</option>
					{/each}
				</select>
			</div>
			<div class="flex items-end">
				<button class="botao w-full" type="submit" disabled={salvando || programaId === null}>
					{salvando ? 'Cadastrando…' : 'Cadastrar'}
				</button>
			</div>
		</div>
	</form>
{/if}

<section class="mt-10">
	{#if carregando}
		<p class="etiqueta">Carregando…</p>
	{:else if pessoas.length === 0}
		<div class="border-borda bg-papel border border-dashed p-10 text-center">
			<p class="text-grafite text-[0.9375rem]">Nenhuma pessoa cadastrada ainda.</p>
			<p class="text-cinza mt-1 text-sm">
				{podeCriar
					? 'Use o formulário acima para cadastrar a primeira.'
					: 'Peça à secretaria para fazer o primeiro cadastro.'}
			</p>
		</div>
	{:else}
		<ul class="space-y-px">
			{#each pessoas as pessoa (pessoa.id)}
				<!--
					A régua de tinta marca cada registro oficial — mesmo traço do
					cartão de acesso. Arquivado perde a tinta e ganha opacidade.
				-->
				<li
					class="bg-papel regua-tinta flex flex-wrap items-center justify-between gap-4 px-5 py-4"
					class:opacity-55={pessoa.status === 'archived'}
					style:border-left-color={pessoa.status === 'archived'
						? 'var(--color-borda)'
						: 'var(--color-tinta)'}
				>
					<div class="min-w-0">
						<p class="text-grafite truncate text-[0.9375rem] font-medium">{pessoa.full_name}</p>
						<p class="text-cinza mt-0.5 truncate font-mono text-[0.8125rem]">
							{pessoa.primary_email}{pessoa.phone_number ? ` · ${pessoa.phone_number}` : ''}
						</p>
					</div>

					<div class="flex shrink-0 items-center gap-4">
						<span class="etiqueta">
							{pessoa.status === 'archived' ? 'Arquivada' : 'Ativa'}
						</span>
						{#if podeArquivar && pessoa.status !== 'archived'}
							<button
								class="botao-discreto"
								type="button"
								disabled={arquivando === pessoa.id}
								onclick={() => arquivar(pessoa)}
							>
								{arquivando === pessoa.id ? 'Arquivando…' : 'Arquivar'}
							</button>
						{/if}
					</div>
				</li>
			{/each}
		</ul>
	{/if}
</section>
