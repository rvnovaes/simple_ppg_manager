<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { api, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';

	type Pessoa = components['schemas']['PersonOut'];

	// Mesmos rótulos da listagem; a volta preserva o recorte de onde veio.
	const TITULOS: Record<string, string> = {
		candidatos: 'Candidatos',
		administrativo: 'Administrativo'
	};

	let pessoa = $state<Pessoa | null>(null);
	let carregando = $state(true);
	let erro = $state('');

	const id = $derived(Number(page.params.id));
	const vinculo = $derived(page.params.vinculo ?? 'administrativo');

	async function carregar(personId: number) {
		carregando = true;
		erro = '';
		const { data, error } = await api.GET('/people/{person_id}/', {
			params: { path: { person_id: personId } }
		});
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar a pessoa.');
		} else {
			pessoa = data ?? null;
		}
		carregando = false;
	}

	function dataHora(valor: string): string {
		return new Date(valor).toLocaleString('pt-BR');
	}

	$effect(() => {
		if (!Number.isNaN(id)) carregar(id);
	});
</script>

<svelte:head>
	<title>{pessoa?.full_name ?? 'Pessoa'} · PPGM</title>
</svelte:head>

<a class="etiqueta hover:text-tinta" href={resolve('/(app)/pessoas/[vinculo]', { vinculo })}>
	← {TITULOS[vinculo] ?? 'Pessoas'}
</a>

{#if erro}
	<p class="aviso-erro mt-6" role="alert">{erro}</p>
{:else if carregando}
	<p class="etiqueta mt-6">Carregando…</p>
{:else if pessoa}
	<header class="mt-2 flex flex-wrap items-end justify-between gap-4">
		<div>
			<p class="etiqueta">Pessoa</p>
			<h1 class="text-grafite mt-1 text-2xl font-semibold tracking-tight">{pessoa.full_name}</h1>
		</div>
		<span class="etiqueta">{pessoa.status === 'archived' ? 'Arquivada' : 'Ativa'}</span>
	</header>

	<dl class="border-borda bg-papel mt-8 grid gap-x-8 gap-y-5 border p-6 sm:grid-cols-2">
		<div>
			<dt class="etiqueta">E-mail</dt>
			<dd class="text-grafite mt-1 font-mono text-[0.875rem]">{pessoa.primary_email}</dd>
		</div>
		<div>
			<dt class="etiqueta">Telefone</dt>
			<dd class="text-grafite mt-1 font-mono text-[0.875rem]">{pessoa.phone_number || '—'}</dd>
		</div>
		<div>
			<dt class="etiqueta">Conta de acesso</dt>
			<dd class="text-grafite mt-1 text-[0.875rem]">
				<!-- Pessoa sem conta é cadastro sem acesso ao sistema: egresso,
				registro histórico, quem nunca vai entrar. -->
				{pessoa.user_id === null ? 'Sem conta' : 'Tem conta'}
			</dd>
		</div>
		<div>
			<dt class="etiqueta">Cadastrada em</dt>
			<dd class="text-grafite mt-1 font-mono text-[0.875rem]">{dataHora(pessoa.created_at)}</dd>
		</div>
	</dl>
{/if}
