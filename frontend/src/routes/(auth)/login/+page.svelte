<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { mensagemDeErro } from '$lib/api/client';
	import { sessao } from '$lib/sessao.svelte';

	let username = $state('');
	let password = $state('');
	let erro = $state('');
	let enviando = $state(false);

	async function entrar(event: SubmitEvent) {
		event.preventDefault();
		erro = '';
		enviando = true;
		try {
			await sessao.entrar(username, password);
			await goto(resolve(sessao.rotaInicial));
		} catch (falha) {
			erro = mensagemDeErro(falha, 'Não foi possível entrar. Tente novamente.');
		} finally {
			enviando = false;
		}
	}
</script>

<svelte:head>
	<title>Entrar · PPGM</title>
</svelte:head>

<div class="grid min-h-screen lg:grid-cols-[minmax(0,42%)_1fr]">
	<!-- Campo de tinta: a identidade do sistema mora aqui, e só aqui. -->
	<aside
		class="bg-tinta text-papel flex flex-col justify-between gap-10 px-8 py-10 lg:px-14 lg:py-14"
	>
		<p class="etiqueta text-papel/55">Sistema de gestão</p>

		<div class="max-w-md">
			<h1 class="text-3xl leading-[1.1] font-semibold tracking-tight lg:text-[2.75rem]">PPGM</h1>
			<p class="text-papel/70 mt-4 text-[0.9375rem] leading-relaxed">Pós-Graduação Manager</p>
		</div>

		<footer class="space-y-5">
			<p class="etiqueta text-papel/45">Secretaria, docentes, discentes e candidatos</p>

			<div class="border-papel/15 flex flex-wrap items-center gap-x-7 gap-y-4 border-t pt-5">
				<p class="text-papel/45 text-xs">
					Desenvolvido por
					<a
						class="text-papel/70 hover:text-papel underline underline-offset-2"
						href="https://labp2.direito.ufmg.br/"
						target="_blank"
						rel="noreferrer"
					>
						LabP²
					</a>
				</p>

				<!-- Marcas do laboratório e da instituição: discretas de propósito.
				     A opacidade baixa as põe no mesmo peso da etiqueta ao lado. -->
				<div class="flex items-center gap-6 opacity-40">
					<img class="h-7 w-auto" src="/logos/labp2-branco.png" alt="LabP²" />
					<img class="h-5 w-auto" src="/logos/ufmg-branco.png" alt="UFMG" />
					<img
						class="h-10 w-auto"
						src="/logos/fdufmg-branco.png"
						alt="Faculdade de Direito da UFMG"
					/>
				</div>
			</div>
		</footer>
	</aside>

	<main class="flex items-center justify-center px-6 py-12 lg:px-14">
		<form class="w-full max-w-sm" onsubmit={entrar}>
			<h2 class="text-grafite text-xl font-semibold tracking-tight">Entrar</h2>
			<p class="text-cinza mt-1.5 text-sm">Use as credenciais fornecidas pela secretaria.</p>

			{#if erro}
				<p class="aviso-erro mt-6" role="alert">{erro}</p>
			{/if}

			<div class="mt-7 space-y-5">
				<div>
					<label class="etiqueta mb-2 block" for="username">Usuário</label>
					<input
						id="username"
						class="campo font-mono"
						bind:value={username}
						autocomplete="username"
						required
					/>
				</div>

				<div>
					<label class="etiqueta mb-2 block" for="password">Senha</label>
					<input
						id="password"
						type="password"
						class="campo"
						bind:value={password}
						autocomplete="current-password"
						required
					/>
				</div>
			</div>

			<button class="botao mt-8 w-full" type="submit" disabled={enviando}>
				{enviando ? 'Entrando…' : 'Entrar'}
			</button>

			<p class="text-cinza mt-6 text-sm">
				Vai cursar disciplina isolada e ainda não tem conta?
				<a class="text-tinta underline" href={resolve('/cadastro')}>Cadastre-se</a>
			</p>
		</form>
	</main>
</div>
