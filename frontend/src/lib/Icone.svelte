<script lang="ts">
	/**
	 * Ícones do Lucide (lucide.dev), copiados como markup em vez de trazidos
	 * por biblioteca: o projeto tem uma dependência de front só
	 * (openapi-fetch), e @iconify/svelte buscaria o SVG pela rede em
	 * runtime — furo na origem única (ADR-004). Licença ISC permite a cópia.
	 *
	 * Ícone novo: copie o conteúdo do <svg> de
	 * unpkg.com/lucide-static/icons/<nome>.svg e acrescente ao mapa, com o
	 * nome original do Lucide no comentário. Todos vêm do mesmo grid de 24
	 * e do mesmo traço de 2 — é isso que mantém o conjunto coerente.
	 */
	type Nome =
		| 'olho'
		| 'lapis'
		| 'arquivo'
		| 'pessoas'
		| 'professor'
		| 'aluno'
		| 'candidato'
		| 'administrativo'
		| 'estrutura'
		| 'inscricao'
		| 'acompanhamento'
		| 'classificacao'
		| 'isolada'
		| 'analise'
		| 'edital'
		| 'acerto'
		| 'documento'
		| 'orientandos'
		| 'programa'
		| 'disciplinas'
		| 'selecao'
		| 'banca'
		| 'ata';

	const FORMAS: Record<Nome, string> = {
		// eye
		olho: '<path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"/><circle cx="12" cy="12" r="3"/>',
		// pencil
		lapis:
			'<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/>',
		// archive
		arquivo:
			'<rect width="20" height="5" x="2" y="3" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/><path d="M10 12h4"/>',
		// users
		pessoas:
			'<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><path d="M16 3.128a4 4 0 0 1 0 7.744"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><circle cx="9" cy="7" r="4"/>',
		// user-round
		professor: '<circle cx="12" cy="8" r="5"/><path d="M20 21a8 8 0 0 0-16 0"/>',
		// graduation-cap
		aluno:
			'<path d="M21.42 10.922a1 1 0 0 0-.019-1.838L12.83 5.18a2 2 0 0 0-1.66 0L2.6 9.08a1 1 0 0 0 0 1.832l8.57 3.908a2 2 0 0 0 1.66 0z"/><path d="M22 10v6"/><path d="M6 12.5V16a6 3 0 0 0 12 0v-3.5"/>',
		// user-round-plus
		candidato:
			'<path d="M2 21a8 8 0 0 1 13.292-6"/><circle cx="10" cy="8" r="5"/><path d="M19 16v6"/><path d="M22 19h-6"/>',
		// briefcase
		administrativo:
			'<path d="M16 20V4a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/><rect width="20" height="14" x="2" y="6" rx="2"/>',
		// network
		estrutura:
			'<rect x="16" y="16" width="6" height="6" rx="1"/><rect x="2" y="16" width="6" height="6" rx="1"/><rect x="9" y="2" width="6" height="6" rx="1"/><path d="M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3"/><path d="M12 12V8"/>',
		// file-plus
		inscricao:
			'<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"/><path d="M14 2v5a1 1 0 0 0 1 1h5"/><path d="M9 15h6"/><path d="M12 18v-6"/>',
		// list-checks
		acompanhamento:
			'<path d="M13 5h8"/><path d="M13 12h8"/><path d="M13 19h8"/><path d="m3 17 2 2 4-4"/><path d="m3 7 2 2 4-4"/>',
		// list-ordered
		classificacao:
			'<path d="M11 5h10"/><path d="M11 12h10"/><path d="M11 19h10"/><path d="M4 4h1v5"/><path d="M4 9h2"/><path d="M6.5 20H3.4c0-1 2.6-1.925 2.6-3.5a1.5 1.5 0 0 0-2.6-1.02"/>',
		// book-open
		isolada:
			'<path d="M12 5v16"/><path d="M20.001 19A2 2 0 0 0 22 17V5a2 2 0 0 0-1.999-2L16 3.002A5 5 0 0 0 12 5a5 5 0 0 0-4-2H4a2 2 0 0 0-2 2v12a2 2 0 0 0 1.999 2H8a5 5 0 0 1 4 2 5 5 0 0 1 4-2z"/>',
		// clipboard-check
		analise:
			'<rect width="8" height="4" x="8" y="2" rx="1" ry="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="m9 14 2 2 4-4"/>',
		// scroll-text
		edital:
			'<path d="M15 12h-5"/><path d="M15 8h-5"/><path d="M19 17V5a2 2 0 0 0-2-2H4"/><path d="M8 21h12a2 2 0 0 0 2-2v-1a1 1 0 0 0-1-1H11a1 1 0 0 0-1 1v1a2 2 0 1 1-4 0V5a2 2 0 1 0-4 0v2a1 1 0 0 0 1 1h3"/>',
		// file-pen
		acerto:
			'<path d="M12.659 22H18a2 2 0 0 0 2-2V8a2.4 2.4 0 0 0-.706-1.706l-3.588-3.588A2.4 2.4 0 0 0 14 2H6a2 2 0 0 0-2 2v9.34"/><path d="M14 2v5a1 1 0 0 0 1 1h5"/><path d="M10.378 12.622a1 1 0 0 1 3 3.003L8.36 20.637a2 2 0 0 1-.854.506l-2.867.837a.5.5 0 0 1-.62-.62l.836-2.869a2 2 0 0 1 .506-.853z"/>',
		// file-text
		documento:
			'<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"/><path d="M14 2v5a1 1 0 0 0 1 1h5"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
		// user-check
		orientandos:
			'<path d="m16 11 2 2 4-4"/><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>',
		// building-2
		programa:
			'<path d="M10 12h4"/><path d="M10 8h4"/><path d="M14 21v-3a2 2 0 0 0-4 0v3"/><path d="M6 10H4a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-2"/><path d="M6 21V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v16"/>',
		// book-marked
		disciplinas:
			'<path d="M10 2v8l3-3 3 3V2"/><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H19a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H6.5a1 1 0 0 1 0-5H20"/>',
		// target
		selecao:
			'<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
		// users-round
		banca:
			'<path d="M18 21a8 8 0 0 0-16 0"/><circle cx="10" cy="8" r="5"/><path d="M22 20c0-3.37-2-6.5-4-8a5 5 0 0 0-.45-8.3"/>',
		// file-check
		ata: '<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"/><path d="M14 2v5a1 1 0 0 0 1 1h5"/><path d="m9 15 2 2 4-4"/>'
	};

	// `rotulo` só existe onde o ícone é o único conteúdo do controle (os
	// botões das listagens). No menu ele está ao lado do texto, e um
	// <title> ali faria o leitor de tela anunciar o item duas vezes.
	let {
		nome,
		rotulo = '',
		tamanho = 16
	}: { nome: Nome; rotulo?: string; tamanho?: number } = $props();
</script>

<!--
	aria-hidden + o rótulo no title do controle: o ícone é decoração de algo
	que já se anuncia. Duas etiquetas fariam o leitor de tela repetir.

	{@html} com literal do próprio módulo, nunca com dado de fora: é o mapa
	acima e mais nada. Sem ele, cada forma (path, circle, rect) viraria um
	bloco condicional e o SVG copiado do Lucide deixaria de ser fiel.
-->
<svg
	xmlns="http://www.w3.org/2000/svg"
	width={tamanho}
	height={tamanho}
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
	{#if rotulo}<title>{rotulo}</title>{/if}
	<!--
		A regra existe porque {@html} com dado de fora é XSS. Aqui a fonte é
		`FORMAS`, literal deste módulo e indexado por um union de nomes — não
		há caminho para conteúdo externo chegar aqui, e o `Nome` impede até um
		nome arbitrário. Se um dia o mapa passar a ser alimentado de fora,
		este disable tem de cair junto.
	-->
	<!-- eslint-disable-next-line svelte/no-at-html-tags -->
	{@html FORMAS[nome]}
</svg>
