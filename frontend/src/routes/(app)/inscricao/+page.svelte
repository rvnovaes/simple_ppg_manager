<script lang="ts">
	import { resolve } from '$app/paths';
	import { api, codigoDeErro, comoFormData, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';
	import {
		ORDEM_DO_EDITAL,
		ROTULO_DO_DOCUMENTO as TIPOS,
		formatarTamanho as tamanho,
		type TipoDeDocumento
	} from '$lib/isolada';

	type Oferta = components['schemas']['DisciplineOfferingOut'];
	type Requerimento = components['schemas']['IsolatedRequestOut'];
	type Documento = components['schemas']['RequestDocumentOut'];

	// Máximo de disciplinas por requerimento. O backend cobra o mesmo em
	// `submit()` e no schema de entrada; aqui a UI simplesmente não deixa
	// marcar a terceira, em vez de aceitar e falhar no envio.
	const MAXIMO_DE_DISCIPLINAS = 2;

	let ofertas = $state<Oferta[]>([]);
	let requerimentos = $state<Requerimento[]>([]);
	let documentos = $state<Documento[]>([]);
	let carregando = $state(true);
	let erro = $state('');
	// Preenchido quando a listagem de ofertas volta `no_open_cycle`: não é
	// falha da tela, é o edital fora da janela de inscrição.
	let janelaFechada = $state('');
	let salvando = $state(false);
	let enviandoAnexo = $state<string>('');

	// Um requerimento por ciclo (UniqueConstraint), e a inscrição só existe
	// enquanto ele é rascunho — depois de enviado o lugar é a tela de
	// acompanhamento.
	const rascunho = $derived(requerimentos.find((r) => r.status === 'draft') ?? null);
	const enviado = $derived(requerimentos.find((r) => r.status !== 'draft') ?? null);

	const escolhidas = $derived(new Set((rascunho?.items ?? []).map((item) => item.offering_id)));

	// A lista exibida na área de upload: o que falta (resposta do servidor)
	// mais o que já foi anexado, na ordem do edital. Marcar "servidor da
	// UFMG" faz o servidor acrescentar contracheque e autorização, e a lista
	// cresce sozinha no PATCH.
	const anexadoPorTipo = $derived.by(() => {
		const mapa: Record<string, Documento> = {};
		for (const documento of documentos) mapa[documento.kind] = documento;
		return mapa;
	});

	const exigidos = $derived.by(() => {
		if (rascunho === null) return [] as TipoDeDocumento[];
		const faltando = new Set(rascunho.missing_documents);
		return ORDEM_DO_EDITAL.filter((tipo) => faltando.has(tipo) || tipo in anexadoPorTipo);
	});

	// Por que o envio não pode acontecer — dito antes de a pessoa clicar, e
	// não como 4xx depois. Os três motivos são os mesmos que o backend
	// cobraria em `submit()`.
	const impedimento = $derived.by(() => {
		if (rascunho === null) return '';
		if (janelaFechada) return janelaFechada;
		if (rascunho.items.length === 0) return 'Escolha ao menos uma disciplina.';
		if (rascunho.missing_documents.length > 0) {
			const nomes = rascunho.missing_documents.map((tipo) => TIPOS[tipo] ?? tipo);
			return `Falta anexar: ${nomes.join(', ')}.`;
		}
		return '';
	});

	function porCodigo(a: Oferta, b: Oferta): number {
		return a.discipline_code.localeCompare(b.discipline_code, 'pt-BR');
	}

	async function carregarDocumentos(requerimentoId: number) {
		const { data, error } = await api.GET('/academic/isolated/requests/{request_id}/documents', {
			params: { path: { request_id: requerimentoId } }
		});
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar seus anexos.');
			return;
		}
		documentos = data ?? [];
	}

	async function carregar() {
		carregando = true;
		erro = '';
		janelaFechada = '';
		const [respOfertas, respRequerimentos] = await Promise.all([
			api.GET('/academic/isolated/offerings/'),
			api.GET('/academic/isolated/requests/')
		]);
		// A falha sai do objeto ANTES do `if`: o tipo gerado não declara
		// resposta de erro para estas rotas, então dentro do bloco o próprio
		// objeto é estreitado para `never` e `.error` já não existe nele.
		const falhaOfertas = respOfertas.error;
		const falhaRequerimentos = respRequerimentos.error;
		if (falhaOfertas) {
			// `no_open_cycle` é situação normal do calendário; qualquer outro
			// código é falha de verdade e vai para a faixa de erro.
			if (codigoDeErro(falhaOfertas) === 'no_open_cycle') {
				janelaFechada = mensagemDeErro(falhaOfertas, 'O edital não está aberto agora.');
			} else {
				erro = mensagemDeErro(falhaOfertas, 'Não foi possível carregar as disciplinas.');
			}
		} else {
			ofertas = (respOfertas.data ?? []).slice().sort(porCodigo);
		}
		if (falhaRequerimentos) {
			erro = mensagemDeErro(falhaRequerimentos, 'Não foi possível carregar sua inscrição.');
		} else {
			requerimentos = respRequerimentos.data?.items ?? [];
		}
		const meu = requerimentos.find((r) => r.status === 'draft');
		if (meu) await carregarDocumentos(meu.id);
		carregando = false;
	}

	async function iniciar() {
		erro = '';
		salvando = true;
		const { data, error } = await api.POST('/academic/isolated/requests/', {
			body: { is_ufmg_staff: false, items: [] }
		});
		salvando = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível iniciar sua inscrição.');
			return;
		}
		requerimentos = [data, ...requerimentos];
	}

	/** Grava o rascunho e recoloca a versão do servidor no lugar da antiga. */
	async function atualizar(corpo: { is_ufmg_staff?: boolean; items?: { offering_id: number }[] }) {
		if (rascunho === null) return;
		erro = '';
		salvando = true;
		const { data, error } = await api.PATCH('/academic/isolated/requests/{request_id}/', {
			params: { path: { request_id: rascunho.id } },
			body: corpo
		});
		salvando = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível salvar sua escolha.');
			return;
		}
		requerimentos = requerimentos.map((r) => (r.id === data.id ? data : r));
	}

	function alternarOferta(oferta: Oferta) {
		if (rascunho === null) return;
		const atuais = rascunho.items.map((item) => item.offering_id);
		const proximas = escolhidas.has(oferta.id)
			? atuais.filter((id) => id !== oferta.id)
			: [...atuais, oferta.id];
		atualizar({ items: proximas.map((offering_id) => ({ offering_id })) });
	}

	function alternarServidor(event: Event) {
		// Salva na hora: é a marcação que acrescenta contracheque e
		// autorização da chefia à lista de anexos, e a lista vem do servidor.
		atualizar({ is_ufmg_staff: (event.currentTarget as HTMLInputElement).checked });
	}

	async function anexar(tipo: TipoDeDocumento, event: Event) {
		const campo = event.currentTarget as HTMLInputElement;
		const arquivo = campo.files?.[0];
		if (rascunho === null || !arquivo) return;
		erro = '';
		enviandoAnexo = tipo;
		const { error } = await api.POST('/academic/isolated/requests/{request_id}/documents', {
			params: { path: { request_id: rascunho.id } },
			// O tipo gerado declara `file: string` (binary no OpenAPI); o cast
			// é o preço de mandar o File de verdade pelo FormData.
			body: { kind: tipo, file: arquivo as unknown as string },
			bodySerializer: comoFormData
		});
		enviandoAnexo = '';
		// Sempre limpa o campo: sucesso ou falha, deixar o nome do arquivo ali
		// impede reenviar o mesmo arquivo depois de corrigir algo.
		campo.value = '';
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível anexar o documento.');
			return;
		}
		// Duas recargas: a lista de anexos e o requerimento, porque
		// `missing_documents` é calculado no servidor.
		await carregarDocumentos(rascunho.id);
		const { data } = await api.GET('/academic/isolated/requests/');
		requerimentos = data?.items ?? requerimentos;
	}

	async function enviar() {
		if (rascunho === null || impedimento !== '') return;
		erro = '';
		salvando = true;
		const { data, error } = await api.POST('/academic/isolated/requests/{request_id}/submit', {
			params: { path: { request_id: rascunho.id } }
		});
		salvando = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível enviar sua inscrição.');
			return;
		}
		requerimentos = requerimentos.map((r) => (r.id === data.id ? data : r));
	}

	$effect(() => {
		carregar();
	});
</script>

<svelte:head>
	<title>Inscrição em disciplina isolada · PPGD Manager</title>
</svelte:head>

<header>
	<p class="etiqueta">Disciplina isolada</p>
	<h1 class="text-grafite mt-1 text-2xl font-semibold tracking-tight">Minha inscrição</h1>
</header>

{#if erro}
	<p class="aviso-erro mt-6" role="alert">{erro}</p>
{/if}

{#if carregando}
	<p class="etiqueta mt-6">Carregando…</p>
{:else if enviado}
	<div class="border-borda bg-papel mt-6 border border-dashed p-5">
		<p class="etiqueta">Inscrição enviada</p>
		<p class="text-grafite mt-2 text-[0.9375rem]">
			Sua inscrição já foi enviada e está em análise. O resultado, a taxa e o recurso ficam na tela
			de
			<a class="text-tinta underline" href={resolve('/acompanhamento')}>acompanhamento</a>.
		</p>
		<ul class="mt-3 space-y-1">
			{#each enviado.items as item (item.id)}
				<li class="text-cinza text-sm">
					<span class="text-grafite font-mono">{item.discipline_code}</span>
					{item.discipline_name}
				</li>
			{/each}
		</ul>
	</div>
{:else if janelaFechada && rascunho === null}
	<div class="border-borda bg-papel mt-6 border border-dashed p-5">
		<p class="etiqueta">Fora do período de inscrição</p>
		<p class="text-grafite mt-2 text-[0.9375rem]">{janelaFechada}</p>
	</div>
{:else if rascunho === null}
	<div class="border-borda bg-papel mt-6 border border-dashed p-5">
		<p class="etiqueta">Comece por aqui</p>
		<p class="text-grafite mt-2 text-[0.9375rem]">
			Você ainda não abriu sua inscrição neste edital. Depois de iniciar, escolha até {MAXIMO_DE_DISCIPLINAS}
			disciplinas e anexe a documentação.
		</p>
		<button class="botao mt-4" type="button" onclick={iniciar} disabled={salvando}>
			{salvando ? 'Abrindo…' : 'Iniciar inscrição'}
		</button>
	</div>
{:else}
	<section class="mt-8">
		<h2 class="etiqueta">
			Disciplinas ({rascunho.items.length} de {MAXIMO_DE_DISCIPLINAS})
		</h2>
		{#if ofertas.length === 0}
			<p class="text-cinza mt-2 text-sm">
				O edital aberto ainda não tem disciplina ofertada. Procure a secretaria.
			</p>
		{:else}
			<ul class="mt-2 space-y-px">
				{#each ofertas as oferta (oferta.id)}
					{@const marcada = escolhidas.has(oferta.id)}
					{@const cheia = rascunho.items.length >= MAXIMO_DE_DISCIPLINAS && !marcada}
					<li
						class="border-borda flex flex-wrap items-center justify-between gap-4 border-b px-1 py-3"
					>
						<div class="min-w-0">
							<p class="text-grafite font-mono text-[0.9375rem]">{oferta.discipline_code}</p>
							<p class="text-cinza mt-0.5 truncate text-sm">{oferta.discipline_name}</p>
							<p class="text-cinza mt-0.5 text-sm">
								{oferta.teacher_name} · {oferta.seats_available} de {oferta.seats} vaga(s)
							</p>
						</div>
						<button
							class="botao-discreto shrink-0"
							type="button"
							aria-pressed={marcada}
							style:border-color={marcada ? 'var(--color-tinta)' : undefined}
							disabled={salvando || cheia}
							onclick={() => alternarOferta(oferta)}
						>
							{marcada ? 'Escolhida' : 'Escolher'}
						</button>
					</li>
				{/each}
			</ul>
			{#if rascunho.items.length >= MAXIMO_DE_DISCIPLINAS}
				<p class="text-cinza mt-2 text-sm">
					Você já escolheu o máximo de {MAXIMO_DE_DISCIPLINAS} disciplinas. Desmarque uma para trocar.
				</p>
			{/if}
		{/if}
	</section>

	<section class="border-borda bg-papel mt-8 border p-5">
		<label class="text-grafite flex items-center gap-3 text-[0.9375rem]">
			<input
				type="checkbox"
				checked={rascunho.is_ufmg_staff}
				disabled={salvando}
				onchange={alternarServidor}
			/>
			Sou servidor da UFMG
		</label>
		<p class="text-cinza mt-2 text-sm">
			Servidor da UFMG é isento da taxa e precisa anexar contracheque e autorização da chefia.
		</p>
	</section>

	<section class="mt-8">
		<h2 class="etiqueta">Documentação</h2>
		<ul class="mt-2 space-y-px">
			{#each exigidos as tipo (tipo)}
				{@const anexo = anexadoPorTipo[tipo]}
				<li
					class="border-borda flex flex-wrap items-center justify-between gap-4 border-b px-1 py-3"
				>
					<div class="min-w-0">
						<p class="text-grafite text-[0.9375rem]">{TIPOS[tipo] ?? tipo}</p>
						{#if anexo}
							<p class="text-cinza mt-0.5 truncate text-sm">
								{anexo.filename} · {tamanho(anexo.size)}
							</p>
						{:else}
							<p class="text-carimbo mt-0.5 text-sm">Falta anexar</p>
						{/if}
					</div>
					<div class="flex shrink-0 items-center gap-3">
						<label class="etiqueta cursor-pointer">
							<span class="botao-discreto inline-block">
								{#if enviandoAnexo === tipo}
									Enviando…
								{:else}
									{anexo ? 'Substituir' : 'Anexar'}
								{/if}
							</span>
							<input
								class="sr-only"
								type="file"
								disabled={enviandoAnexo !== ''}
								onchange={(event) => anexar(tipo, event)}
							/>
						</label>
					</div>
				</li>
			{/each}
		</ul>
	</section>

	<section class="mt-8">
		{#if impedimento}
			<p class="text-cinza text-sm">{impedimento}</p>
		{/if}
		<button
			class="botao mt-3"
			type="button"
			disabled={salvando || enviandoAnexo !== '' || impedimento !== ''}
			onclick={enviar}
		>
			{salvando ? 'Enviando…' : 'Enviar inscrição'}
		</button>
	</section>
{/if}
