<script lang="ts">
	// A listagem geral de pessoas deixou de existir: quem é professor ou
	// aluno tem tela própria, e o resto se divide entre candidatos e
	// administrativo. A rota sobrevive só para não quebrar link salvo.
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';

	$effect(() => {
		goto(resolve('/pessoas/administrativo'), { replaceState: true });
	});
</script>

<p class="etiqueta">Redirecionando…</p>
