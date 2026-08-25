<script lang="ts">
	import { api, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';
	import { formatarMomento } from '$lib/selecao';
	import { sessao } from '$lib/sessao.svelte';

	type Edital = components['schemas']['SelectionProcessOut'];
	type Etapa = components['schemas']['SelectionStageOut'];
	type Convocavel = components['schemas']['ConvocableApplicationOut'];
	type Lote = components['schemas']['ConvocationOut'];
	type LoteDetalhado = components['schemas']['ConvocationDetailOut'];
	type Destinatario = components['schemas']['ConvocationEmailOut'];

	let editais = $state<Edital[]>([]);
	let etapas = $state<Etapa[]>([]);
	let convocaveis = $state<Convocavel[]>([]);
	let lotes = $state<Lote[]>([]);
	// Os destinatários de cada lote aberto. A listagem devolve só a
	// contagem — abrir um lote é uma consulta a mais, e por isso fica
	// guardado por id em vez de recarregar a cada clique.
	let destinatarios = $state<Record<number, Destinatario[]>>({});
	let abertos = $state<number[]>([]);

	let carregando = $state(true);
	let enviando = $state(false);
	let reenviando = $state<number | null>(null);
	let erro = $state('');
	let aviso = $state('');

	let editalEscolhido = $state<number | ''>('');
	let etapaEscolhida = $state<number | ''>('');

	// Disparar é `add_convocation`, que só a Secretaria tem (migration
	// 0006): Coordenação e Comissão acompanham os lotes sem convocar. Quem
	// recusa continua sendo o backend; esta checagem existe para a tela não
	// oferecer o botão que dá 403.
	const podeConvocar = $derived(sessao.pode('selection.add_convocation'));

	/** Quem o próximo disparo vai chamar: o lote pula quem já recebeu
	 * e-mail nesta etapa, em lote nenhum (`_abrir_lote`). */
	const novos = $derived(convocaveis.filter((c) => !c.already_convoked));

	// --- carregamento ------------------------------------------------------

	async function carregarEditais() {
		const { data, error } = await api.GET('/selection/processes/');
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar os editais do programa.');
			return;
		}
		editais = data?.items ?? [];
	}

	async function carregarEtapas(processId: number) {
		const { data, error } = await api.GET('/selection/processes/{process_id}/stages/', {
			params: { path: { process_id: processId } }
		});
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar as etapas do edital.');
			return;
		}
		etapas = data ?? [];
	}

	/**
	 * Convocáveis e lotes da etapa escolhida.
	 *
	 * Quem é convocável é resposta do servidor (`convocable_for`): na
	 * etapa 1, quem está vivo; da 2 em diante, só as chaves cuja ata
	 * anterior está assinada. A tela não refaz essa conta — lista vazia
	 * aqui costuma ser ata pendente, e é isso que ela diz.
	 */
	async function carregarEtapaEscolhida() {
		destinatarios = {};
		abertos = [];
		if (editalEscolhido === '' || etapaEscolhida === '') {
			convocaveis = [];
			lotes = [];
			return;
		}
		// Desestruturação, e não `resposta.error`: rota que só documenta o
		// 200 tipa `error` como `never`, e o `svelte-check` recusa a leitura.
		const { data, error } = await api.GET(
			'/selection/processes/{process_id}/stages/{stage_id}/convocable',
			{ params: { path: { process_id: editalEscolhido, stage_id: etapaEscolhida } } }
		);
		if (error) {
			erro = mensagemDeErro(
				error,
				'Não foi possível carregar os candidatos convocáveis desta etapa.'
			);
			return;
		}
		convocaveis = data ?? [];
		await carregarLotes();
	}

	async function carregarLotes() {
		if (editalEscolhido === '' || etapaEscolhida === '') return;
		const { data, error } = await api.GET(
			'/selection/processes/{process_id}/stages/{stage_id}/convocations',
			{ params: { path: { process_id: editalEscolhido, stage_id: etapaEscolhida } } }
		);
		if (error) {
			erro = mensagemDeErro(error, 'Não foi possível carregar os lotes já disparados.');
			return;
		}
		lotes = data ?? [];
	}

	async function trocarEdital() {
		etapaEscolhida = '';
		etapas = [];
		erro = '';
		aviso = '';
		carregando = true;
		if (editalEscolhido !== '') await carregarEtapas(editalEscolhido);
		await carregarEtapaEscolhida();
		carregando = false;
	}

	async function trocarEtapa() {
		erro = '';
		aviso = '';
		carregando = true;
		await carregarEtapaEscolhida();
		carregando = false;
	}

	// --- disparo e reenvio --------------------------------------------------

	/** Guarda o lote que voltou do disparo/reenvio já aberto: é o que a
	 * secretaria quer ver na hora — quem ficou de fora. */
	function guardar(lote: LoteDetalhado) {
		destinatarios = { ...destinatarios, [lote.id]: lote.emails };
		if (!abertos.includes(lote.id)) abertos = [...abertos, lote.id];
	}

	async function enviarLote() {
		if (editalEscolhido === '' || etapaEscolhida === '' || enviando) return;
		erro = '';
		aviso = '';
		enviando = true;
		const { data, error } = await api.POST(
			'/selection/processes/{process_id}/stages/{stage_id}/convocations',
			{ params: { path: { process_id: editalEscolhido, stage_id: etapaEscolhida } } }
		);
		enviando = false;
		if (error || !data) {
			// `no_convocable_applications` é o caso corriqueiro (todo mundo
			// já foi chamado, ou a ata anterior não foi assinada) — o
			// servidor já explica os dois em português.
			erro = mensagemDeErro(error, 'Não foi possível disparar a convocação desta etapa.');
			return;
		}
		aviso =
			data.failed > 0
				? `Lote disparado: ${data.sent} enviado(s), ${data.failed} falhou(aram).`
				: `Lote disparado: ${data.sent} e-mail(s) enviado(s).`;
		// A recarga é depois do disparo porque quem foi chamado agora deixa
		// de ser "a convocar" na lista de cima — e ela zera os lotes
		// abertos, então o lote recém-disparado é reaberto em seguida.
		await carregarEtapaEscolhida();
		guardar(data);
	}

	async function reenviarFalhas(lote: Lote) {
		if (reenviando !== null) return;
		erro = '';
		aviso = '';
		reenviando = lote.id;
		const { data, error } = await api.POST('/selection/convocations/{convocation_id}/resend', {
			params: { path: { convocation_id: lote.id } }
		});
		reenviando = null;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível reenviar os e-mails que falharam.');
			return;
		}
		// A linha é trocada pelo que voltou, sem recarregar a lista: o
		// reenvio mexe num lote só, e o resto da tela não mudou.
		lotes = lotes.map((l) => (l.id === data.id ? data : l));
		guardar(data);
		aviso =
			data.failed > 0
				? `Reenvio feito: ${data.failed} ainda falhou(aram) — confira o endereço.`
				: 'Reenvio feito: nenhum e-mail deste lote está falhando.';
	}

	async function alternar(lote: Lote) {
		if (abertos.includes(lote.id)) {
			abertos = abertos.filter((id) => id !== lote.id);
			return;
		}
		abertos = [...abertos, lote.id];
		if (destinatarios[lote.id] !== undefined) return;
		const { data, error } = await api.GET('/selection/convocations/{convocation_id}', {
			params: { path: { convocation_id: lote.id } }
		});
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível abrir os destinatários deste lote.');
			return;
		}
		destinatarios = { ...destinatarios, [data.id]: data.emails };
	}

	$effect(() => {
		carregando = true;
		carregarEditais().then(() => {
			carregando = false;
		});
	});
</script>

<svelte:head>
	<title>Convocações · PPGD Manager</title>
</svelte:head>

<header>
	<p class="etiqueta">Processo seletivo</p>
	<h1 class="text-grafite mt-1 text-2xl font-semibold tracking-tight">Convocações</h1>
	<p class="text-cinza mt-2 text-sm">
		O e-mail que chama os candidatos para a etapa, com data, hora e local da sessão. Disparar de
		novo é seguro: quem já foi chamado nesta etapa fica de fora do lote seguinte.
	</p>
</header>

<div class="mt-6 flex flex-wrap items-end gap-3">
	<div>
		<label class="etiqueta mb-1 block" for="filtro-edital">Edital</label>
		<select
			id="filtro-edital"
			class="campo w-72"
			bind:value={editalEscolhido}
			onchange={trocarEdital}
		>
			<option value="">Escolha um edital</option>
			{#each editais as opcao (opcao.id)}
				<option value={opcao.id}>{opcao.title}</option>
			{/each}
		</select>
	</div>
	<div>
		<label class="etiqueta mb-1 block" for="filtro-etapa">Etapa</label>
		<select
			id="filtro-etapa"
			class="campo w-64"
			bind:value={etapaEscolhida}
			onchange={trocarEtapa}
			disabled={editalEscolhido === ''}
		>
			<option value="">Escolha uma etapa</option>
			{#each etapas as opcao (opcao.id)}
				<option value={opcao.id}>{opcao.order}. {opcao.name}</option>
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

{#if carregando}
	<p class="etiqueta mt-6">Carregando…</p>
{:else if editalEscolhido === '' || etapaEscolhida === ''}
	<div class="border-borda bg-papel mt-6 border border-dashed p-10 text-center">
		<p class="text-grafite text-[0.9375rem]">Escolha o edital e a etapa para convocar.</p>
		<p class="text-cinza mt-1 text-sm">
			A convocação é sempre de uma etapa: é dela que saem a data, a hora e o local do e-mail.
		</p>
	</div>
{:else}
	<section class="bg-papel regua-tinta mt-6 px-5 py-4">
		<div class="flex flex-wrap items-center justify-between gap-4">
			<div>
				<h2 class="text-grafite text-[0.9375rem] font-medium">
					Convocáveis nesta etapa: {convocaveis.length}
				</h2>
				<p class="text-cinza mt-0.5 text-sm">
					{novos.length} ainda não recebeu(ram) e-mail — é quem o próximo disparo chama.
				</p>
			</div>
			{#if podeConvocar}
				<button
					class="botao"
					type="button"
					disabled={enviando || novos.length === 0}
					onclick={enviarLote}
				>
					{enviando ? 'Enviando…' : `Enviar convocação (${novos.length})`}
				</button>
			{/if}
		</div>

		{#if convocaveis.length === 0}
			<p class="text-cinza mt-3 text-sm">
				Ninguém é convocável nesta etapa. Da segunda etapa em diante, quem promove é a ata assinada
				da etapa anterior — enquanto ela não for assinada, não há quem chamar.
			</p>
		{:else}
			<ul class="mt-4 space-y-px">
				{#each convocaveis as candidato (candidato.id)}
					<li
						class="border-borda flex flex-wrap items-center justify-between gap-4 border-b py-2 last:border-0"
					>
						<div class="min-w-0">
							<p class="text-grafite text-[0.9375rem]">
								{candidato.full_name}
								<span class="text-cinza font-mono text-xs">· {candidato.protocol}</span>
							</p>
							<p class="text-cinza mt-0.5 text-sm">
								{candidato.email} · {candidato.level_label} · {candidato.target_label || '—'} · {candidato.quota_category_label}
							</p>
						</div>
						<span class="etiqueta shrink-0">
							{candidato.already_convoked ? 'Já convocado' : 'A convocar'}
						</span>
					</li>
				{/each}
			</ul>
		{/if}
	</section>

	<section class="mt-8">
		<h2 class="etiqueta">Lotes disparados</h2>
		{#if lotes.length === 0}
			<div class="border-borda bg-papel mt-3 border border-dashed p-10 text-center">
				<p class="text-grafite text-[0.9375rem]">Nenhum lote disparado nesta etapa.</p>
			</div>
		{:else}
			<ul class="mt-3 space-y-px">
				{#each lotes as lote (lote.id)}
					<li
						class="bg-papel regua-tinta px-5 py-4"
						style:border-left-color={lote.failed > 0
							? 'var(--color-carimbo)'
							: 'var(--color-tinta)'}
					>
						<div class="flex flex-wrap items-center justify-between gap-4">
							<div class="min-w-0">
								<p class="text-grafite text-[0.9375rem] font-medium">
									{formatarMomento(lote.created_at)} · {lote.total} destinatário(s)
								</p>
								<p class="text-cinza mt-0.5 text-sm">
									{lote.sent} enviado(s) · {lote.failed} falhou(aram) · {lote.pending} pendente(s)
									{#if lote.sent_by_name}
										· disparado por {lote.sent_by_name}
									{/if}
								</p>
							</div>
							<div class="flex shrink-0 items-center gap-3">
								<button class="botao-discreto" type="button" onclick={() => alternar(lote)}>
									{abertos.includes(lote.id) ? 'Ocultar destinatários' : 'Ver destinatários'}
								</button>
								{#if podeConvocar && lote.failed > 0}
									<button
										class="botao-discreto"
										type="button"
										disabled={reenviando !== null}
										onclick={() => reenviarFalhas(lote)}
									>
										{reenviando === lote.id ? 'Reenviando…' : `Reenviar falhas (${lote.failed})`}
									</button>
								{/if}
							</div>
						</div>

						{#if abertos.includes(lote.id)}
							{@const linhas = destinatarios[lote.id] ?? []}
							<div class="border-borda mt-4 border-t pt-3">
								<p class="text-cinza text-sm">Assunto do lote: {lote.subject}</p>
								<ul class="mt-2 space-y-px">
									{#each linhas as linha (linha.id)}
										<li
											class="border-borda flex flex-wrap items-center justify-between gap-4 border-b py-2 last:border-0"
										>
											<div class="min-w-0">
												<p class="text-grafite text-[0.9375rem]">
													{linha.full_name}
													<span class="text-cinza font-mono text-xs">· {linha.protocol}</span>
												</p>
												<p class="text-cinza mt-0.5 text-sm">
													{linha.to_email}
													{#if linha.sent_at}
														· enviado em {formatarMomento(linha.sent_at)}
													{/if}
													{#if linha.attempts > 1}
														· {linha.attempts} tentativas
													{/if}
												</p>
												{#if linha.error}
													<p class="text-carimbo mt-0.5 text-sm">{linha.error}</p>
												{/if}
											</div>
											<span class="etiqueta shrink-0">{linha.status_label}</span>
										</li>
									{/each}
								</ul>
								{#if linhas.length === 0}
									<p class="text-cinza mt-2 text-sm">Carregando destinatários…</p>
								{/if}
							</div>
						{/if}
					</li>
				{/each}
			</ul>
		{/if}
	</section>
{/if}
