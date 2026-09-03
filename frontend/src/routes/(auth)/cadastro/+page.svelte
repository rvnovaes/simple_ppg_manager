<script lang="ts">
	import { resolve } from '$app/paths';
	import { api, garantirCsrf, mensagemDeErro } from '$lib/api/client';
	import {
		ORDEM_DAS_CATEGORIAS,
		ORDEM_DAS_TITULACOES,
		ORDEM_DOS_PERFIS,
		ROTULO_DA_CATEGORIA,
		ROTULO_DA_TITULACAO,
		ROTULO_DO_PERFIL,
		exigeInstituicaoDeOrigem,
		type CategoriaDocente,
		type Perfil,
		type Titulacao
	} from '$lib/acesso';
	import type { components } from '$lib/api/schema';

	// Única tela pública de escrita do sistema: quem pede acesso ao programa
	// ainda não tem conta para autenticar. Fica em (auth), e não em (app),
	// justamente por não passar pela guarda de sessão.

	type Programa = components['schemas']['PublicProgramOut'];

	let programas = $state<Programa[]>([]);
	let carregando = $state(true);

	let programaId = $state('');
	let perfil = $state<Perfil>('candidate');
	let nome = $state('');
	let email = $state('');
	let telefone = $state('');
	let senha = $state('');
	let confirmacao = $state('');
	let categoria = $state<CategoriaDocente | ''>('');
	let titulacao = $state<Titulacao | ''>('');
	let instituicao = $state('');
	let lattes = $state('');
	let erro = $state('');
	let recado = $state('');
	let enviando = $state(false);

	// Conferência de UX, não de segurança: quem manda senha fraca leva o 400
	// do backend, que é a validação que vale (Seção 8).
	const senhasDiferem = $derived(confirmacao !== '' && senha !== confirmacao);
	const ehDocente = $derived(perfil === 'teacher');
	// Instituição de origem só é exigida do colaborador externo; quem sabe
	// disso é `lib/acesso.ts`, junto com os rótulos.
	const exigeInstituicao = $derived(ehDocente && exigeInstituicaoDeOrigem(categoria));
	const semPrograma = $derived(!carregando && programas.length === 0);

	async function carregar() {
		const { data, error } = await api.GET('/programs/public');
		carregando = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível carregar os programas abertos.');
			return;
		}
		programas = data;
		if (data.length === 1) programaId = String(data[0].id);
	}

	async function cadastrar(event: SubmitEvent) {
		event.preventDefault();
		if (senhasDiferem || programaId === '') return;
		erro = '';
		recado = '';
		enviando = true;
		// A rota é `auth=None`, então o cookie de CSRF ainda não existe — sem
		// isto o POST leva 403 antes de chegar ao Ninja.
		await garantirCsrf();
		const { data, error } = await api.POST('/access/signup', {
			body: {
				program_id: Number(programaId),
				profile: perfil,
				full_name: nome.trim(),
				email: email.trim(),
				phone_number: telefone.trim(),
				password: senha,
				// Fora do docente estes campos não existem: o service os zera,
				// e mandá-los preenchidos só criaria dado que ninguém lê.
				teacher_category: ehDocente && categoria !== '' ? categoria : null,
				academic_degree: ehDocente && titulacao !== '' ? titulacao : null,
				home_institution: ehDocente ? instituicao.trim() : '',
				lattes_url: ehDocente ? lattes.trim() : ''
			}
		});
		enviando = false;
		if (error || !data) {
			erro = mensagemDeErro(error, 'Não foi possível concluir o cadastro.');
			return;
		}
		// O backend responde a mesma coisa para e-mail novo e já cadastrado —
		// exibir o texto dele é o que mantém a tela sem virar um verificador
		// de contas.
		recado = data.detail;
		senha = '';
		confirmacao = '';
	}

	$effect(() => {
		carregar();
	});
</script>

<svelte:head>
	<title>Criar conta · PPGM</title>
</svelte:head>

<div class="grid min-h-screen lg:grid-cols-[minmax(0,42%)_1fr]">
	<aside
		class="bg-tinta text-papel flex flex-col justify-between gap-10 px-8 py-10 lg:px-14 lg:py-14"
	>
		<p class="etiqueta text-papel/55">Acesso ao programa</p>

		<div class="max-w-md">
			<h1 class="text-3xl leading-[1.1] font-semibold tracking-tight lg:text-[2.75rem]">
				Cadastro no programa
			</h1>
			<p class="text-papel/70 mt-5 text-[0.9375rem] leading-relaxed">
				Crie sua conta escolhendo o programa e o que você é nele. Docente e discente passam pela
				confirmação da secretaria; candidato entra direto.
			</p>
		</div>

		<p class="etiqueta text-papel/45">Aberto enquanto o programa aceitar autocadastro</p>
	</aside>

	<main class="flex items-center justify-center px-6 py-12 lg:px-14">
		<form class="w-full max-w-sm" onsubmit={cadastrar}>
			<h2 class="text-grafite text-xl font-semibold tracking-tight">Criar conta</h2>
			<p class="text-cinza mt-1.5 text-sm">Seu e-mail será também o seu usuário de acesso.</p>

			{#if erro}
				<p class="aviso-erro mt-6" role="alert">{erro}</p>
			{/if}

			{#if semPrograma}
				<p class="border-borda bg-papel mt-6 border border-dashed p-4 text-sm" role="status">
					Nenhum programa está aceitando cadastro no momento. Procure a secretaria.
				</p>
			{/if}

			{#if recado}
				<div class="border-borda bg-papel mt-6 border border-dashed p-4" role="status">
					<p class="text-grafite text-[0.9375rem]">{recado}</p>
					<a class="text-tinta mt-3 inline-block text-sm underline" href={resolve('/login')}>
						Ir para a tela de entrada
					</a>
				</div>
			{:else}
				<div class="mt-7 space-y-5">
					<div>
						<label class="etiqueta mb-2 block" for="cadastro-programa">Programa</label>
						<select
							id="cadastro-programa"
							class="campo"
							bind:value={programaId}
							disabled={semPrograma}
							required
						>
							<option value="" disabled>Selecione…</option>
							{#each programas as programa (programa.id)}
								<option value={String(programa.id)}>{programa.acronym} — {programa.name}</option>
							{/each}
						</select>
					</div>

					<div>
						<label class="etiqueta mb-2 block" for="cadastro-perfil">Você é</label>
						<select id="cadastro-perfil" class="campo" bind:value={perfil} required>
							{#each ORDEM_DOS_PERFIS as valor (valor)}
								<option value={valor}>{ROTULO_DO_PERFIL[valor]}</option>
							{/each}
						</select>
						<p class="text-cinza mt-2 text-sm">
							Colaborador externo se cadastra como Docente e escolhe a categoria abaixo.
						</p>
					</div>

					{#if ehDocente}
						<div>
							<label class="etiqueta mb-2 block" for="cadastro-categoria">Categoria</label>
							<select id="cadastro-categoria" class="campo" bind:value={categoria} required>
								<option value="" disabled>Selecione…</option>
								{#each ORDEM_DAS_CATEGORIAS as valor (valor)}
									<option value={valor}>{ROTULO_DA_CATEGORIA[valor]}</option>
								{/each}
							</select>
						</div>

						<div>
							<label class="etiqueta mb-2 block" for="cadastro-titulacao">Titulação</label>
							<select id="cadastro-titulacao" class="campo" bind:value={titulacao} required>
								<option value="" disabled>Selecione…</option>
								{#each ORDEM_DAS_TITULACOES as valor (valor)}
									<option value={valor}>{ROTULO_DA_TITULACAO[valor]}</option>
								{/each}
							</select>
						</div>

						<div>
							<label class="etiqueta mb-2 block" for="cadastro-instituicao">
								Instituição de origem{exigeInstituicao ? '' : ' (opcional)'}
							</label>
							<input
								id="cadastro-instituicao"
								class="campo"
								bind:value={instituicao}
								required={exigeInstituicao}
							/>
						</div>

						<div>
							<label class="etiqueta mb-2 block" for="cadastro-lattes">
								Currículo Lattes (opcional)
							</label>
							<input id="cadastro-lattes" type="url" class="campo" bind:value={lattes} />
						</div>
					{/if}

					<div>
						<label class="etiqueta mb-2 block" for="cadastro-nome">Nome completo</label>
						<input
							id="cadastro-nome"
							class="campo"
							bind:value={nome}
							autocomplete="name"
							required
						/>
					</div>

					<div>
						<label class="etiqueta mb-2 block" for="cadastro-email">E-mail</label>
						<input
							id="cadastro-email"
							type="email"
							class="campo"
							bind:value={email}
							autocomplete="email"
							required
						/>
					</div>

					<div>
						<label class="etiqueta mb-2 block" for="cadastro-telefone"> Telefone (opcional) </label>
						<input id="cadastro-telefone" class="campo" bind:value={telefone} autocomplete="tel" />
					</div>

					<div>
						<label class="etiqueta mb-2 block" for="cadastro-senha">Senha</label>
						<input
							id="cadastro-senha"
							type="password"
							class="campo"
							bind:value={senha}
							autocomplete="new-password"
							required
						/>
					</div>

					<div>
						<label class="etiqueta mb-2 block" for="cadastro-confirmacao">Repita a senha</label>
						<input
							id="cadastro-confirmacao"
							type="password"
							class="campo"
							bind:value={confirmacao}
							autocomplete="new-password"
							required
						/>
						{#if senhasDiferem}
							<p class="text-carimbo mt-2 text-sm">As duas senhas precisam ser iguais.</p>
						{/if}
					</div>
				</div>

				<button
					class="botao mt-8 w-full"
					type="submit"
					disabled={enviando || senhasDiferem || semPrograma}
				>
					{enviando ? 'Enviando…' : 'Criar conta'}
				</button>

				<p class="text-cinza mt-6 text-sm">
					Já tem conta?
					<a class="text-tinta underline" href={resolve('/login')}>Entrar</a>
				</p>
			{/if}
		</form>
	</main>
</div>
