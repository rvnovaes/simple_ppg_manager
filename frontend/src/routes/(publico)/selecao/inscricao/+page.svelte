<script lang="ts">
	import { resolve } from '$app/paths';
	import { api, comoFormData, garantirCsrf, mensagemDeErro } from '$lib/api/client';
	import type { components } from '$lib/api/schema';
	import {
		ROTULO_DO_DOCUMENTO_DA_INSCRICAO as DOCUMENTOS,
		documentosExigidos,
		formatarMomento,
		type TipoDeDocumentoDaInscricao
	} from '$lib/selecao';

	type Edital = components['schemas']['PublicProcessOut'];
	type Vaga = components['schemas']['PublicVacancyOut'];

	/*
	 * Inscrição no processo seletivo, aberta a quem não tem conta.
	 *
	 * A inscrição inteira vai num POST só (dados + anexos), porque sem login
	 * não haveria a quem devolver um rascunho depois — é a mesma razão
	 * anotada em `submit_public_application`. A tela ajuda a não errar
	 * (cascata nível → alvo → cota, só combinações com vaga; anexo exigido
	 * conforme tipo do edital e cota), mas a validação que vale é a do
	 * backend (Seção 8 do CLAUDE.md).
	 */

	let editais = $state<Edital[]>([]);
	let carregando = $state(true);
	let erro = $state('');
	let enviando = $state(false);

	let editalId = $state('');
	let nivel = $state('');
	let alvo = $state('');
	let cota = $state('');

	let nome = $state('');
	let email = $state('');
	let cpf = $state('');
	let nascimento = $state('');
	let telefone = $state('');

	// Um `File` por tipo de documento, na chave que o POST usa. Guardar o
	// arquivo aqui (e não só no `<input>`) é o que deixa a lista de campos
	// mudar quando a cota muda sem perder o que já foi escolhido.
	let arquivos = $state<Partial<Record<TipoDeDocumentoDaInscricao, File>>>({});

	let comprovante = $state<components['schemas']['ApplicationReceiptOut'] | null>(null);

	const edital = $derived(editais.find((e) => String(e.id) === editalId) ?? null);

	/** A chave do `<option>` de alvo: um dos dois ids é sempre nulo (XOR). */
	function chaveDoAlvo(vaga: { project_id: number | null; research_line_id: number | null }) {
		return `${vaga.project_id ?? ''}|${vaga.research_line_id ?? ''}`;
	}

	const vagas = $derived<Vaga[]>(edital?.vacancies ?? []);

	// Cascata: cada passo só oferece o que ainda tem vaga depois do passo
	// anterior. Oferecer combinação sem vaga só levaria a pessoa a preencher
	// tudo para receber `no_vacancy_for_choice` no fim.
	const niveis = $derived(
		(edital?.levels ?? []).filter((o) => vagas.some((v) => v.level === o.value))
	);

	const alvos = $derived.by(() => {
		const vistos: string[] = [];
		const lista: { chave: string; label: string }[] = [];
		for (const vaga of vagas) {
			if (vaga.level !== nivel) continue;
			const chave = chaveDoAlvo(vaga);
			if (vistos.includes(chave)) continue;
			vistos.push(chave);
			lista.push({ chave, label: vaga.target_label });
		}
		return lista;
	});

	const cotas = $derived(
		(edital?.quota_categories ?? []).filter((o) =>
			vagas.some(
				(v) => v.level === nivel && chaveDoAlvo(v) === alvo && v.quota_category === o.value
			)
		)
	);

	const vagaEscolhida = $derived(
		vagas.find((v) => v.level === nivel && chaveDoAlvo(v) === alvo && v.quota_category === cota) ??
			null
	);

	const exigidos = $derived<TipoDeDocumentoDaInscricao[]>(
		edital === null || cota === ''
			? []
			: documentosExigidos(edital.kind, cota as components['schemas']['QuotaCategory'])
	);

	const faltando = $derived(exigidos.filter((tipo) => arquivos[tipo] === undefined));

	const impedimento = $derived.by(() => {
		if (edital === null) return 'Escolha o edital.';
		if (vagaEscolhida === null) return 'Escolha nível, área e categoria de concorrência.';
		if (faltando.length > 0) {
			return `Falta anexar: ${faltando.map((tipo) => DOCUMENTOS[tipo]).join(', ')}.`;
		}
		return '';
	});

	async function carregar() {
		const { data, error } = await api.GET('/selection/public/processes');
		carregando = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível carregar os editais abertos.');
			return;
		}
		editais = data;
		if (data.length === 1) trocarEdital(String(data[0].id));
	}

	// Cada passo da cascata zera os de baixo: manter nível de um edital com
	// alvo de outro é como se monta um POST que só o servidor recusa.
	function trocarEdital(valor: string) {
		editalId = valor;
		nivel = '';
		alvo = '';
		cota = '';
		arquivos = {};
	}

	function trocarNivel(valor: string) {
		nivel = valor;
		alvo = '';
		cota = '';
	}

	function trocarAlvo(valor: string) {
		alvo = valor;
		cota = '';
	}

	function escolherArquivo(tipo: TipoDeDocumentoDaInscricao, evento: Event) {
		const campo = evento.currentTarget as HTMLInputElement;
		const arquivo = campo.files?.[0];
		arquivos = { ...arquivos, [tipo]: arquivo ?? undefined };
	}

	async function inscrever(evento: SubmitEvent) {
		evento.preventDefault();
		if (edital === null || vagaEscolhida === null || impedimento !== '') return;
		erro = '';
		enviando = true;
		// A rota é `auth=None` e ainda assim exige CSRF (`csrf_protect`
		// explícito): sem plantar o cookie antes, o POST leva 403.
		await garantirCsrf();
		const corpo: Record<string, unknown> = {
			process_id: edital.id,
			full_name: nome.trim(),
			email: email.trim(),
			cpf: cpf.trim(),
			birth_date: nascimento,
			phone_number: telefone.trim(),
			level: nivel,
			quota_category: cota,
			project_id: vagaEscolhida.project_id,
			research_line_id: vagaEscolhida.research_line_id
		};
		// `comoFormData` descarta nulo e indefinido: o alvo que não vale e os
		// anexos que este edital não exige simplesmente não viajam.
		for (const tipo of exigidos) corpo[tipo] = arquivos[tipo];
		const { data, error } = await api.POST('/selection/public/applications', {
			// O tipo gerado declara os anexos como `string` (binary no
			// OpenAPI); o cast é o preço de mandar o `File` de verdade.
			body: corpo as never,
			bodySerializer: comoFormData
		});
		enviando = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível concluir a inscrição.');
			return;
		}
		comprovante = data;
	}

	$effect(() => {
		carregar();
	});
</script>

<svelte:head>
	<title>Inscrição no processo seletivo · PPGD Manager</title>
</svelte:head>

{#if comprovante}
	<section class="border-borda bg-papel border p-8">
		<p class="etiqueta">Inscrição recebida</p>
		<h1 class="text-grafite mt-2 text-2xl font-semibold tracking-tight">Guarde seu protocolo</h1>
		<p class="text-tinta mt-6 font-mono text-3xl tracking-tight">{comprovante.protocol}</p>
		<p class="text-cinza mt-3 text-sm">
			Enviada em {formatarMomento(comprovante.submitted_at)}. O protocolo é o único jeito de
			consultar a situação da inscrição — anote-o antes de fechar esta página.
		</p>
		<a class="botao mt-7 inline-flex" href={resolve('/selecao/protocolo')}>Consultar a situação</a>
	</section>
{:else}
	<h1 class="text-grafite text-2xl font-semibold tracking-tight">Inscrição no processo seletivo</h1>
	<p class="text-cinza mt-2 text-sm">
		Preencha os dados, escolha a vaga e anexe a documentação exigida pelo edital. É um envio só: não
		há como voltar depois para completar.
	</p>

	{#if erro}
		<p class="aviso-erro mt-6" role="alert">{erro}</p>
	{/if}

	{#if carregando}
		<p class="text-cinza mt-8 text-sm">Carregando editais…</p>
	{:else if editais.length === 0}
		<p class="border-borda bg-papel text-grafite mt-8 border border-dashed p-6 text-[0.9375rem]">
			Nenhum edital com inscrição aberta no momento.
		</p>
	{:else}
		<form class="mt-8 space-y-8" onsubmit={inscrever}>
			<section class="border-borda bg-papel border p-6">
				<p class="etiqueta">A vaga</p>

				<div class="mt-5 space-y-5">
					<div>
						<label class="etiqueta mb-2 block" for="inscricao-edital">Edital</label>
						<select
							id="inscricao-edital"
							class="campo"
							value={editalId}
							onchange={(e) => trocarEdital(e.currentTarget.value)}
							required
						>
							<option value="">Escolha…</option>
							{#each editais as opcao (opcao.id)}
								<option value={String(opcao.id)}>
									{opcao.program_acronym} · {opcao.title} ({opcao.kind_label})
								</option>
							{/each}
						</select>
					</div>

					{#if edital}
						<div class="border-borda border-l-2 pl-4">
							<p class="text-cinza text-sm">
								Inscrições até {formatarMomento(edital.submission_closes_at)}.
							</p>
							{#if edital.notice_url}
								<!-- O PDF do edital sai do MEDIA pelo Nginx: não é rota da
								SPA, e `resolve()` não se aplica. -->
								<!-- eslint-disable svelte/no-navigation-without-resolve -->
								<a
									class="text-tinta mt-1 inline-block text-sm underline"
									href={edital.notice_url}
									target="_blank"
									rel="noopener"
								>
									Ler o edital em PDF
								</a>
								<!-- eslint-enable svelte/no-navigation-without-resolve -->
							{/if}
							{#if edital.stages.length > 0}
								<ul class="text-cinza mt-3 space-y-1 text-sm">
									{#each edital.stages as etapa (etapa.order)}
										<li>
											{etapa.order}. {etapa.name}
											{#if etapa.session_at}· {formatarMomento(etapa.session_at)}{/if}
											{#if etapa.location}· {etapa.location}{/if}
										</li>
									{/each}
								</ul>
							{/if}
						</div>

						<div class="grid gap-5 sm:grid-cols-3">
							<div>
								<label class="etiqueta mb-2 block" for="inscricao-nivel">Nível</label>
								<select
									id="inscricao-nivel"
									class="campo"
									value={nivel}
									onchange={(e) => trocarNivel(e.currentTarget.value)}
									required
								>
									<option value="">Escolha…</option>
									{#each niveis as opcao (opcao.value)}
										<option value={opcao.value}>{opcao.label}</option>
									{/each}
								</select>
							</div>

							<div>
								<label class="etiqueta mb-2 block" for="inscricao-alvo">
									{edital.kind === 'regular' ? 'Projeto' : 'Linha de pesquisa'}
								</label>
								<select
									id="inscricao-alvo"
									class="campo"
									value={alvo}
									onchange={(e) => trocarAlvo(e.currentTarget.value)}
									disabled={nivel === ''}
									required
								>
									<option value="">Escolha…</option>
									{#each alvos as opcao (opcao.chave)}
										<option value={opcao.chave}>{opcao.label}</option>
									{/each}
								</select>
							</div>

							<div>
								<label class="etiqueta mb-2 block" for="inscricao-cota">Concorrência</label>
								<select
									id="inscricao-cota"
									class="campo"
									bind:value={cota}
									disabled={alvo === ''}
									required
								>
									<option value="">Escolha…</option>
									{#each cotas as opcao (opcao.value)}
										<option value={opcao.value}>{opcao.label}</option>
									{/each}
								</select>
							</div>
						</div>

						{#if vagaEscolhida}
							<p class="text-cinza text-sm">
								{vagaEscolhida.quantity}
								{vagaEscolhida.quantity === 1 ? 'vaga' : 'vagas'} em
								{vagaEscolhida.target_label} ({vagaEscolhida.level_label},
								{vagaEscolhida.quota_category_label}).
							</p>
						{/if}
					{/if}
				</div>
			</section>

			{#if edital}
				<section class="border-borda bg-papel border p-6">
					<p class="etiqueta">Seus dados</p>

					<div class="mt-5 grid gap-5 sm:grid-cols-2">
						<div class="sm:col-span-2">
							<label class="etiqueta mb-2 block" for="inscricao-nome">Nome completo</label>
							<input
								id="inscricao-nome"
								class="campo"
								bind:value={nome}
								autocomplete="name"
								required
							/>
						</div>

						<div>
							<label class="etiqueta mb-2 block" for="inscricao-email">E-mail</label>
							<input
								id="inscricao-email"
								type="email"
								class="campo"
								bind:value={email}
								autocomplete="email"
								required
							/>
						</div>

						<div>
							<label class="etiqueta mb-2 block" for="inscricao-telefone">
								Telefone (opcional)
							</label>
							<input
								id="inscricao-telefone"
								class="campo"
								bind:value={telefone}
								autocomplete="tel"
							/>
						</div>

						<div>
							<label class="etiqueta mb-2 block" for="inscricao-cpf">CPF</label>
							<input
								id="inscricao-cpf"
								class="campo font-mono"
								bind:value={cpf}
								inputmode="numeric"
								placeholder="000.000.000-00"
								required
							/>
						</div>

						<div>
							<label class="etiqueta mb-2 block" for="inscricao-nascimento">
								Data de nascimento
							</label>
							<input
								id="inscricao-nascimento"
								type="date"
								class="campo"
								bind:value={nascimento}
								required
							/>
						</div>
					</div>
				</section>

				<section class="border-borda bg-papel border p-6">
					<p class="etiqueta">Documentação</p>
					{#if cota === ''}
						<p class="text-cinza mt-4 text-sm">
							Escolha a vaga acima: os documentos exigidos dependem do tipo do edital e da
							concorrência.
						</p>
					{:else}
						<p class="text-cinza mt-2 text-sm">Um arquivo por documento, em PDF, até 10 MB cada.</p>
						<div class="mt-5 space-y-5">
							{#each exigidos as tipo (tipo)}
								<div>
									<label class="etiqueta mb-2 block" for={`inscricao-${tipo}`}>
										{DOCUMENTOS[tipo]}
									</label>
									<input
										id={`inscricao-${tipo}`}
										type="file"
										class="campo"
										accept="application/pdf"
										onchange={(e) => escolherArquivo(tipo, e)}
										required
									/>
								</div>
							{/each}
						</div>
					{/if}
				</section>

				<div class="flex flex-wrap items-center gap-4">
					<button class="botao" type="submit" disabled={enviando || impedimento !== ''}>
						{enviando ? 'Enviando…' : 'Enviar inscrição'}
					</button>
					{#if impedimento}
						<p class="text-cinza text-sm">{impedimento}</p>
					{/if}
				</div>
			{/if}
		</form>
	{/if}
{/if}
