<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { api, mensagemDeErro } from '$lib/api/client';
	import { sessao } from '$lib/sessao.svelte';
	import type { components } from '$lib/api/schema';

	// Tela de espera de quem se cadastrou e ainda não foi confirmado pela
	// secretaria. Fica em (auth), e NÃO em (app), para que "sem menu e sem
	// dados" seja estrutural: quem chega aqui não tem permissão nenhuma, e
	// qualquer tela interna lhe responderia 403.

	type Estado = components['schemas']['AccessStatusOut'];

	let estado = $state<Estado | null>(null);
	let carregando = $state(true);
	let erro = $state('');

	const recusado = $derived(estado?.status === 'rejected');

	async function carregar() {
		// A resposta inteira fica numa const: desestruturar `{ data, error }`
		// estreita o objeto para `never` dentro do `if (error)`, e é justamente
		// o `response.status` que precisamos ler — o 404 aqui não é erro de
		// tela, é "esta conta não tem solicitação nenhuma".
		const resposta = await api.GET('/access/me');
		const falha = resposta.error;
		const status = resposta.response.status;
		carregando = false;
		if (falha || !resposta.data) {
			erro =
				status === 404
					? 'Não encontramos uma solicitação de cadastro para esta conta. Procure a secretaria.'
					: mensagemDeErro(falha, 'Não foi possível ler o estado do seu cadastro.');
			return;
		}
		estado = resposta.data;
	}

	async function sair() {
		await sessao.sair();
		await goto(resolve('/login'));
	}

	$effect(() => {
		// A sessão pode ainda não ter sido carregada (entrada direta pela URL);
		// o botão Sair depende dela, e o estado do cadastro é do servidor.
		if (sessao.usuario === null && sessao.carregando) sessao.carregar();
	});

	$effect(() => {
		carregar();
	});
</script>

<svelte:head>
	<title>Aguardando confirmação · PPGD Manager</title>
</svelte:head>

<div class="grid min-h-screen lg:grid-cols-[minmax(0,42%)_1fr]">
	<aside
		class="bg-tinta text-papel flex flex-col justify-between gap-10 px-8 py-10 lg:px-14 lg:py-14"
	>
		<p class="etiqueta text-papel/55">PPGD · Acesso ao programa</p>

		<div class="max-w-md">
			<h1 class="text-3xl leading-[1.1] font-semibold tracking-tight lg:text-[2.75rem]">
				Cadastro em confirmação
			</h1>
			<p class="text-papel/70 mt-5 text-[0.9375rem] leading-relaxed">
				Sua conta já existe, mas o acesso ao programa só se abre depois que a secretaria confirmar o
				que você declarou.
			</p>
		</div>

		<p class="etiqueta text-papel/45">Nada mais é preciso da sua parte</p>
	</aside>

	<main class="flex items-center justify-center px-6 py-12 lg:px-14">
		<div class="w-full max-w-sm">
			<h2 class="text-grafite text-xl font-semibold tracking-tight">
				{recusado ? 'Cadastro não confirmado' : 'Aguardando a secretaria'}
			</h2>

			{#if carregando}
				<p class="etiqueta mt-6">Carregando…</p>
			{:else if erro}
				<p class="aviso-erro mt-6" role="alert">{erro}</p>
			{:else if estado}
				<p class="text-cinza mt-1.5 text-sm">
					{recusado
						? 'A secretaria analisou seu cadastro e não o confirmou.'
						: 'Assim que a secretaria confirmar, seu acesso é liberado nesta mesma conta.'}
				</p>

				<dl class="border-borda mt-7 space-y-4 border border-dashed p-4">
					<div>
						<dt class="etiqueta">Programa</dt>
						<dd class="text-grafite mt-1 text-[0.9375rem]">{estado.program_name}</dd>
					</div>
					<div>
						<dt class="etiqueta">Perfil declarado</dt>
						<!-- O rótulo vem pronto do servidor (`AccessStatusOut`): quem lê
						esta tela não tem permissão para buscar a tabela de choices. -->
						<dd class="text-grafite mt-1 text-[0.9375rem]">{estado.profile_label}</dd>
					</div>
					<div>
						<dt class="etiqueta">Situação</dt>
						<dd class="text-grafite mt-1 text-[0.9375rem]">{estado.status_label}</dd>
					</div>
					{#if recusado && estado.decision_note}
						<div>
							<dt class="etiqueta">Motivo</dt>
							<dd class="text-grafite mt-1 text-[0.9375rem]">{estado.decision_note}</dd>
						</div>
					{/if}
				</dl>

				<p class="text-cinza mt-6 text-sm">
					{recusado
						? 'Se você acha que houve engano, procure a secretaria do programa.'
						: 'Em caso de dúvida, procure a secretaria do programa.'}
				</p>
			{/if}

			<button class="botao-discreto mt-8" type="button" onclick={sair}>Sair</button>
		</div>
	</main>
</div>
