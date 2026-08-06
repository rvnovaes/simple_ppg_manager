<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { sessao } from '$lib/sessao.svelte';

	// A raiz não tem tela própria: manda para a listagem se há sessão, para o
	// login se não há.
	$effect(() => {
		sessao.carregar().then(() => {
			goto(resolve(sessao.autenticado ? sessao.rotaInicial : '/login'), { replaceState: true });
		});
	});
</script>
