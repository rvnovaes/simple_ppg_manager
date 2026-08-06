<script lang="ts">
	/**
	 * Ícones do Lucide (lucide.dev), copiados como path em vez de trazidos
	 * por biblioteca: o projeto tem uma dependência de front só
	 * (openapi-fetch), e @iconify/svelte buscaria o SVG pela rede em
	 * runtime — furo na origem única. Licença ISC permite a cópia.
	 *
	 * Ícone novo: pegue o `d` do SVG em lucide.dev e acrescente ao mapa.
	 * Todos vêm do mesmo grid de 24 e do mesmo traço de 2, e é isso que
	 * mantém o conjunto coerente.
	 */
	type Nome = 'olho' | 'lapis' | 'arquivo';

	const CAMINHOS: Record<Nome, string[]> = {
		// lucide: eye
		olho: [
			'M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0'
		],
		// lucide: pencil
		lapis: [
			'M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z',
			'm15 5 4 4'
		],
		// lucide: archive
		arquivo: ['M20 9v11a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V9', 'M10 13h4']
	};

	// Círculos e retângulos que não cabem num <path>, por ícone.
	let { nome, rotulo }: { nome: Nome; rotulo: string } = $props();
</script>

<!--
	aria-hidden + o rótulo no title do botão: o ícone é decoração de um
	controle que já se anuncia. Duas etiquetas fariam o leitor de tela
	repetir a ação duas vezes.
-->
<svg
	xmlns="http://www.w3.org/2000/svg"
	width="16"
	height="16"
	viewBox="0 0 24 24"
	fill="none"
	stroke="currentColor"
	stroke-width="2"
	stroke-linecap="round"
	stroke-linejoin="round"
	aria-hidden="true"
	focusable="false"
	data-icone={nome}
>
	<title>{rotulo}</title>
	{#each CAMINHOS[nome] as d (d)}
		<path {d} />
	{/each}
	{#if nome === 'olho'}
		<circle cx="12" cy="12" r="3" />
	{/if}
	{#if nome === 'arquivo'}
		<rect x="2" y="3" width="20" height="5" rx="1" />
	{/if}
</svg>
