<script lang="ts">
	import { resolve } from '$app/paths';
	import { api, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';
	import {
		PAPEIS_DA_BANCA,
		ehAContaLogada,
		formatarMomento,
		rotuloDoExaminador
	} from '$lib/selecao';
	import { sessao } from '$lib/sessao.svelte';

	type MinhaBanca = components['schemas']['MyBoardOut'];

	// `boards/mine` é a lista inteira, sem paginação nem filtro: um docente
	// compõe poucas bancas, e é a rota que embute as etapas — o Docente não
	// tem `view_selectionstage` (migration 0006), então sem elas esta tela
	// não teria como listar as sessões.
	let bancas = $state<MinhaBanca[]>([]);
	let carregando = $state(true);
	let erro = $state('');

	const pessoas = $derived(sessao.usuario?.people ?? []);

	/** O papel da conta logada nesta banca — dica de tela, ver `ehAContaLogada`. */
	function meuPapel(banca: MinhaBanca): string {
		const papel = PAPEIS_DA_BANCA.find((p) => ehAContaLogada(banca[p.campo].full_name, pessoas));
		return papel?.rotulo ?? '';
	}

	$effect(() => {
		carregando = true;
		api.GET('/selection/boards/mine').then(({ data, error }) => {
			carregando = false;
			if (error) {
				erro = mensagemDeErro(error, 'Não foi possível carregar as suas bancas.');
				return;
			}
			bancas = data ?? [];
		});
	});
</script>

<svelte:head>
	<title>Minhas bancas · PPGD Manager</title>
</svelte:head>

<header>
	<p class="etiqueta">Processo seletivo</p>
	<h1 class="text-grafite mt-1 text-2xl font-semibold tracking-tight">Minhas bancas</h1>
	<p class="text-cinza mt-2 text-sm">
		As bancas de seleção que você compõe. Abra uma para lançar as notas da etapa, montar a ata e
		assiná-la.
	</p>
</header>

{#if erro}
	<p class="aviso-erro mt-6" role="alert">{erro}</p>
{/if}

{#if carregando}
	<p class="etiqueta mt-6">Carregando…</p>
{:else if bancas.length === 0}
	<div class="border-borda bg-papel mt-6 border border-dashed p-10 text-center">
		<p class="text-grafite text-[0.9375rem]">Você não compõe nenhuma banca de seleção.</p>
		<p class="text-cinza mt-1 text-sm">
			Quem monta as bancas é a secretaria, na tela de bancas do edital.
		</p>
	</div>
{:else}
	<ul class="mt-6 space-y-px">
		{#each bancas as banca (banca.id)}
			<li class="bg-papel regua-tinta px-5 py-4">
				<div class="flex flex-wrap items-start justify-between gap-4">
					<div class="min-w-0">
						<p class="text-grafite text-[0.9375rem] font-medium">
							{banca.level_label} · {banca.target_label || '—'}
						</p>
						<p class="text-cinza mt-0.5 text-sm">{banca.process_title}</p>
					</div>
					<div class="flex items-center gap-4">
						{#if meuPapel(banca)}
							<span class="etiqueta">Você: {meuPapel(banca)}</span>
						{/if}
						<a
							class="botao-discreto shrink-0"
							href={resolve('/(app)/selecao/minhas-bancas/[id]', { id: String(banca.id) })}
						>
							Abrir
						</a>
					</div>
				</div>

				<dl class="mt-3 grid gap-x-6 gap-y-1 sm:grid-cols-2 lg:grid-cols-4">
					{#each PAPEIS_DA_BANCA as papel (papel.campo)}
						<div>
							<dt class="etiqueta">{papel.rotulo}</dt>
							<dd class="text-grafite text-[0.8125rem]">
								{rotuloDoExaminador(banca[papel.campo])}
							</dd>
						</div>
					{/each}
				</dl>

				<div class="border-borda mt-3 border-t pt-3">
					<p class="etiqueta">Etapas</p>
					{#if banca.stages.length === 0}
						<p class="text-cinza mt-1 text-sm">Este edital ainda não tem etapas.</p>
					{:else}
						<ul class="mt-1 space-y-0.5">
							{#each banca.stages as etapa (etapa.id)}
								<li class="text-cinza text-sm">
									{etapa.order}. {etapa.name} · {formatarMomento(etapa.session_at)}
									{#if etapa.location}· {etapa.location}{/if}
								</li>
							{/each}
						</ul>
					{/if}
				</div>
			</li>
		{/each}
	</ul>
{/if}
