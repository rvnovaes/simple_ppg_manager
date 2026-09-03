<script lang="ts">
	/**
	 * Seleção N-N para listas grandes: um campo de busca com sugestões e,
	 * abaixo, a lista do que já foi escolhido, cada item com "Remover".
	 *
	 * Checkbox funciona com dez opções; com cem professores a tela vira uma
	 * parede. Aqui o usuário digita parte do nome, escolhe na lista curta
	 * que sobra (teclado ou mouse) e o escolhido some das sugestões.
	 * Sem biblioteca: é um `<input>` com `role="combobox"` e uma `<ul>`
	 * com `role="listbox"`, o par que o leitor de tela já entende.
	 */
	type Opcao = { id: number; rotulo: string };

	let {
		opcoes,
		selecionados = $bindable(),
		id,
		placeholder = 'Buscar…',
		vazio = 'Nenhum item selecionado.',
		maximoDeSugestoes = 8
	}: {
		opcoes: Opcao[];
		selecionados: number[];
		id: string;
		placeholder?: string;
		vazio?: string;
		maximoDeSugestoes?: number;
	} = $props();

	let busca = $state('');
	let aberto = $state(false);
	let indiceAtivo = $state(0);

	function normalizar(texto: string): string {
		// Sem acento e em minúsculas, dos dois lados: "jose" acha "José".
		return texto
			.normalize('NFD')
			.replace(/[\u0300-\u036f]/g, '')
			.toLowerCase();
	}

	const escolhidos = $derived(
		selecionados
			.map((id) => opcoes.find((opcao) => opcao.id === id))
			.filter((opcao): opcao is Opcao => opcao !== undefined)
	);

	const sugestoes = $derived.by(() => {
		const termo = normalizar(busca.trim());
		return opcoes
			.filter((opcao) => !selecionados.includes(opcao.id))
			.filter((opcao) => termo === '' || normalizar(opcao.rotulo).includes(termo))
			.slice(0, maximoDeSugestoes);
	});

	function acrescentar(opcao: Opcao) {
		selecionados = [...selecionados, opcao.id];
		busca = '';
		indiceAtivo = 0;
	}

	function remover(idRemovido: number) {
		selecionados = selecionados.filter((id) => id !== idRemovido);
	}

	function aoDigitar() {
		aberto = true;
		indiceAtivo = 0;
	}

	function aoTeclar(event: KeyboardEvent) {
		if (event.key === 'ArrowDown') {
			event.preventDefault();
			aberto = true;
			indiceAtivo = Math.min(indiceAtivo + 1, sugestoes.length - 1);
		} else if (event.key === 'ArrowUp') {
			event.preventDefault();
			indiceAtivo = Math.max(indiceAtivo - 1, 0);
		} else if (event.key === 'Enter') {
			// Enter escolhe a sugestão e NÃO submete o formulário em volta.
			event.preventDefault();
			const opcao = sugestoes[indiceAtivo];
			if (aberto && opcao) acrescentar(opcao);
		} else if (event.key === 'Escape') {
			aberto = false;
		}
	}

	function aoSairDoFoco() {
		// Atraso curto para o clique numa sugestão chegar antes de fechar.
		setTimeout(() => (aberto = false), 150);
	}
</script>

<div class="relative">
	<input
		{id}
		class="campo"
		type="text"
		role="combobox"
		autocomplete="off"
		aria-expanded={aberto}
		aria-controls="{id}-sugestoes"
		aria-autocomplete="list"
		{placeholder}
		bind:value={busca}
		oninput={aoDigitar}
		onfocus={() => (aberto = true)}
		onblur={aoSairDoFoco}
		onkeydown={aoTeclar}
	/>
	{#if aberto}
		<ul
			id="{id}-sugestoes"
			role="listbox"
			class="border-borda bg-papel absolute top-full right-0 left-0 z-10 mt-1 max-h-64 overflow-y-auto border shadow-sm"
		>
			{#if sugestoes.length === 0}
				<li class="text-cinza px-3 py-2 text-sm">
					{busca.trim() ? 'Nenhum resultado.' : 'Nada mais a acrescentar.'}
				</li>
			{:else}
				{#each sugestoes as opcao, indice (opcao.id)}
					<li
						role="option"
						aria-selected={indice === indiceAtivo}
						class="text-grafite cursor-pointer px-3 py-2 text-sm"
						class:bg-fundo={indice === indiceAtivo}
						onmousedown={(event) => {
							// mousedown, e não click: o blur do input dispara antes do
							// click e fecharia a lista com a escolha no ar.
							event.preventDefault();
							acrescentar(opcao);
						}}
						onmouseenter={() => (indiceAtivo = indice)}
					>
						{opcao.rotulo}
					</li>
				{/each}
			{/if}
		</ul>
	{/if}
</div>

{#if escolhidos.length === 0}
	<p class="text-cinza mt-3 text-sm">{vazio}</p>
{:else}
	<ul class="border-borda mt-3 divide-y divide-borda border">
		{#each escolhidos as opcao (opcao.id)}
			<li class="flex items-center justify-between gap-4 px-3 py-2">
				<span class="text-grafite min-w-0 truncate text-sm">{opcao.rotulo}</span>
				<button
					class="botao-discreto shrink-0"
					type="button"
					onclick={() => remover(opcao.id)}
					aria-label="Remover {opcao.rotulo}"
				>
					Remover
				</button>
			</li>
		{/each}
	</ul>
{/if}
