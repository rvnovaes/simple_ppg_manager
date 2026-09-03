<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import Icone from '$lib/Icone.svelte';
	import { sessao } from '$lib/sessao.svelte';

	let { children } = $props();

	// Navegar dentro da SPA não recarrega a página, então o <details> ficaria
	// aberto por cima do conteúdo novo depois do clique. Fecha o submenu do
	// próprio link, e por isso serve para todos sem uma referência por menu.
	function fecharSubmenu(event: MouseEvent) {
		(event.currentTarget as HTMLElement).closest('details')?.removeAttribute('open');
	}

	// Guarda das telas internas: sem sessão, volta para o login; com o
	// cadastro ainda pendente de confirmação, vai para a tela de espera —
	// nenhuma tela daqui é legível por quem não tem permissão alguma.
	$effect(() => {
		if (sessao.carregando) return;
		if (sessao.usuario === null) {
			goto(resolve('/login'), { replaceState: true });
		} else if (sessao.pendenteDeConfirmacao) {
			goto(resolve('/aguardando-confirmacao'), { replaceState: true });
		}
	});

	$effect(() => {
		if (sessao.usuario === null && sessao.carregando) sessao.carregar();
	});

	async function sair() {
		await sessao.sair();
		await goto(resolve('/login'));
	}
</script>

{#if sessao.carregando}
	<p class="etiqueta p-8">Carregando…</p>
{:else if sessao.usuario && !sessao.pendenteDeConfirmacao}
	<!-- O pendente não chega a ver o menu: o $effect acima já o está desviando,
	e renderizá-lo no intervalo mostraria por um quadro um cabeçalho que ele
	nunca vai poder usar. -->
	<div class="min-h-screen">
		<header class="border-borda bg-papel border-b">
			<div class="mx-auto flex max-w-5xl items-center justify-between gap-4 px-6 py-4">
				<div class="flex items-center gap-6">
					<a
						href={resolve(sessao.rotaInicial)}
						class="text-tinta text-[0.9375rem] font-semibold tracking-tight"
					>
						PPGM
					</a>
					<nav class="flex items-center gap-4">
						<!-- Todo item é condicional: o Candidato da isolada não tem
						permissão sobre pessoa, professor nem aluno, e link que só leva
						a 403 é pior do que link ausente.

						O ícone acompanha o rótulo, nunca o substitui: no topo há espaço
						para os dois, e ícone sozinho vira adivinhação. -->

						<!-- Pessoas agrupa os quatro recortes do mesmo cadastro. Eles NÃO
						são exclusivos: quem coordena e dá aula aparece em Professores e
						em Administrativo, porque é uma pessoa só com dois vínculos. -->
						{#if sessao.pode('people.view_person')}
							<!-- <details> em vez de estado próprio: fecha no Esc, abre no
							teclado e não precisa de listener de clique fora. -->
							<details class="group relative">
								<summary class="item-menu cursor-pointer list-none marker:content-['']">
									<Icone nome="pessoas" tamanho={14} />
									Pessoas
									<span aria-hidden="true" class="text-cinza text-[0.625rem]">▾</span>
								</summary>
								<div
									class="border-borda bg-papel absolute top-full left-0 z-10 mt-2 flex min-w-48 flex-col border py-1 shadow-sm"
								>
									{#if sessao.pode('academic.view_teacher')}
										<a class="item-submenu" href={resolve('/professores')} onclick={fecharSubmenu}>
											<Icone nome="professor" tamanho={14} />
											Professores
										</a>
									{/if}
									{#if sessao.pode('academic.view_student')}
										<a class="item-submenu" href={resolve('/alunos')} onclick={fecharSubmenu}>
											<Icone nome="aluno" tamanho={14} />
											Alunos
										</a>
									{/if}
									<a
										class="item-submenu"
										href={resolve('/pessoas/candidatos')}
										onclick={fecharSubmenu}
									>
										<Icone nome="candidato" tamanho={14} />
										Candidatos
									</a>
									<a
										class="item-submenu"
										href={resolve('/pessoas/administrativo')}
										onclick={fecharSubmenu}
									>
										<Icone nome="administrativo" tamanho={14} />
										Administrativo
									</a>
									<!-- Por permissão, e não por papel: `view_accessrequest` é de
									Secretaria e Coordenação (academic.0014) e de mais ninguém — ela
									distingue o público sozinha. -->
									{#if sessao.pode('academic.view_accessrequest')}
										<a class="item-submenu" href={resolve('/solicitacoes')} onclick={fecharSubmenu}>
											<Icone nome="analise" tamanho={14} />
											Solicitações de acesso
										</a>
									{/if}
								</div>
							</details>
						{/if}
						<!-- Estrutura: os cadastros que dão forma ao programa. O pai aparece
						se qualquer item aparecer; cada item continua com a sua permissão de
						leitura (`academic.0003_papeis_dos_cadastros`), e o submenu junta as
						telas, não as permissões. -->
						{#if sessao.pode('programs.view_researchline') || sessao.pode('programs.view_academicterm') || sessao.pode('programs.view_discipline')}
							<details class="group relative">
								<summary class="item-menu cursor-pointer list-none marker:content-['']">
									<Icone nome="estrutura" tamanho={14} />
									Estrutura
									<span aria-hidden="true" class="text-cinza text-[0.625rem]">▾</span>
								</summary>
								<div
									class="border-borda bg-papel absolute top-full left-0 z-10 mt-2 flex min-w-48 flex-col border py-1 shadow-sm"
								>
									{#if sessao.pode('programs.view_researchline')}
										<a
											class="item-submenu"
											href={resolve('/estrutura/linhas')}
											onclick={fecharSubmenu}
										>
											<Icone nome="estrutura" tamanho={14} />
											Linhas de Pesquisa
										</a>
									{/if}
									{#if sessao.pode('programs.view_academicterm')}
										<a
											class="item-submenu"
											href={resolve('/estrutura/periodos')}
											onclick={fecharSubmenu}
										>
											<Icone nome="edital" tamanho={14} />
											Períodos Letivos
										</a>
									{/if}
									{#if sessao.pode('programs.view_discipline')}
										<a class="item-submenu" href={resolve('/disciplinas')} onclick={fecharSubmenu}>
											<Icone nome="disciplinas" tamanho={14} />
											Disciplinas
										</a>
									{/if}
								</div>
							</details>
						{/if}
						{#if sessao.pode('academic.add_isolatedenrollmentrequest')}
							<a class="item-menu" href={resolve('/inscricao')}>
								<Icone nome="inscricao" tamanho={14} />
								Inscrição
							</a>
							<!-- Por papel, e não por permissão: os quatro papéis têm
							`view_isolatedenrollmentrequest`, mas esta tela é a do próprio
							candidato — a fila da secretaria é outra (US-019). -->
							{#if sessao.temPapel('Candidato')}
								<a class="item-menu" href={resolve('/acompanhamento')}>
									<Icone nome="acompanhamento" tamanho={14} />
									Acompanhamento
								</a>
							{/if}
						{/if}
						<!-- Por permissão, e não por papel: `rank_disciplineoffering` é
						exclusiva do Docente (academic.0011) e é exatamente o que esta
						tela exige. -->
						{#if sessao.pode('academic.rank_disciplineoffering')}
							<a class="item-menu" href={resolve('/classificacao')}>
								<Icone nome="classificacao" tamanho={14} />
								Classificação
							</a>
						{/if}
						<!-- Disciplina isolada agrupa o que a secretaria e a coordenação
						operam no edital. As telas do candidato (Inscrição, Acompanhamento)
						e a do docente (Classificação) ficam fora: são o trabalho de quem
						passa pelo edital, não a gestão dele. -->
						{#if sessao.pode('academic.view_isolatedenrollmentcycle')}
							<details class="group relative">
								<summary class="item-menu cursor-pointer list-none marker:content-['']">
									<Icone nome="isolada" tamanho={14} />
									Disciplina isolada
									<span aria-hidden="true" class="text-cinza text-[0.625rem]">▾</span>
								</summary>
								<div
									class="border-borda bg-papel absolute top-full left-0 z-10 mt-2 flex min-w-48 flex-col border py-1 shadow-sm"
								>
									<!-- Por papel: `change_isolatedenrollmentrequest` também é do
									Candidato (é com ela que ele monta o próprio requerimento), e
									a análise do edital é trabalho da secretaria. Coordenação fica
									de fora porque esta tela só tem controles de decisão. -->
									{#if sessao.temPapel('Secretaria')}
										<a class="item-submenu" href={resolve('/analise')} onclick={fecharSubmenu}>
											<Icone nome="analise" tamanho={14} />
											Análise
										</a>
									{/if}
									<!-- Por permissão: Secretaria monta o edital e Coordenação o
									acompanha em modo somente leitura — as duas têm
									`view_isolatedenrollmentcycle`, e nenhum outro papel tem. -->
									<a class="item-submenu" href={resolve('/editais')} onclick={fecharSubmenu}>
										<Icone nome="edital" tamanho={14} />
										Editais
									</a>
								</div>
							</details>
						{/if}
						<!-- Processo seletivo: mestrado e doutorado. Fica separado de
						"Disciplina isolada" porque é outro edital, outro público e outro
						fluxo — juntar os dois num menu só faria a secretaria escolher
						errado. `view_selectionprocess` é o que Secretaria, Coordenação e
						Comissão de Seleção têm (selection.0006_papeis_da_selecao).

						Os itens sem tela pronta apontam para um marcador de rota (um
						`+page.svelte` que só diz "ainda não construída"): `resolve()` e o
						lint `svelte/no-navigation-without-resolve` exigem que a rota
						exista, e um 404 seria pior do que a frase. A story de cada tela
						substitui o marcador. -->
						{#if sessao.pode('selection.view_selectionprocess')}
							<details class="group relative">
								<summary class="item-menu cursor-pointer list-none marker:content-['']">
									<Icone nome="selecao" tamanho={14} />
									Processo seletivo
									<span aria-hidden="true" class="text-cinza text-[0.625rem]">▾</span>
								</summary>
								<div
									class="border-borda bg-papel absolute top-full left-0 z-10 mt-2 flex min-w-48 flex-col border py-1 shadow-sm"
								>
									<a
										class="item-submenu"
										href={resolve('/selecao/editais')}
										onclick={fecharSubmenu}
									>
										<Icone nome="edital" tamanho={14} />
										Editais
									</a>
									<a class="item-submenu" href={resolve('/selecao/bancas')} onclick={fecharSubmenu}>
										<Icone nome="banca" tamanho={14} />
										Bancas
									</a>
									<a
										class="item-submenu"
										href={resolve('/selecao/inscricoes')}
										onclick={fecharSubmenu}
									>
										<Icone nome="inscricao" tamanho={14} />
										Inscrições
									</a>
									<a
										class="item-submenu"
										href={resolve('/selecao/convocacoes')}
										onclick={fecharSubmenu}
									>
										<Icone nome="acompanhamento" tamanho={14} />
										Convocações
									</a>
									<a class="item-submenu" href={resolve('/selecao/atas')} onclick={fecharSubmenu}>
										<Icone nome="ata" tamanho={14} />
										Atas
									</a>
									<a
										class="item-submenu"
										href={resolve('/selecao/resultado')}
										onclick={fecharSubmenu}
									>
										<Icone nome="classificacao" tamanho={14} />
										Resultado
									</a>
								</div>
							</details>
						{/if}
						<!-- Fora do submenu de gestão: esta é a tela de quem avalia, e
						`add_stagescore` é do Docente — quem monta o edital não a vê. -->
						{#if sessao.pode('selection.add_stagescore')}
							<a class="item-menu" href={resolve('/selecao/minhas-bancas')}>
								<Icone nome="banca" tamanho={14} />
								Minhas bancas
							</a>
						{/if}
						<!-- As três telas do mesmo fluxo, uma por papel: o aluno pede, o
						orientador decide, a secretaria acompanha. Cada item continua
						condicional, então cada papel vê só a sua — o submenu junta as
						telas, não as permissões. -->
						{#if sessao.pode('academic.add_enrollmentadjustmentrequest') || sessao.pode('academic.change_enrollmentadjustmentrequest') || sessao.temPapel('Secretaria', 'Coordenação')}
							<details class="group relative">
								<summary class="item-menu cursor-pointer list-none marker:content-['']">
									<Icone nome="acerto" tamanho={14} />
									Acerto de matrícula
									<span aria-hidden="true" class="text-cinza text-[0.625rem]">▾</span>
								</summary>
								<div
									class="border-borda bg-papel absolute top-full left-0 z-10 mt-2 flex min-w-48 flex-col border py-1 shadow-sm"
								>
									{#if sessao.pode('academic.add_enrollmentadjustmentrequest')}
										<a class="item-submenu" href={resolve('/acertos')} onclick={fecharSubmenu}>
											<Icone nome="documento" tamanho={14} />
											Meus acertos
										</a>
									{/if}
									{#if sessao.pode('academic.change_enrollmentadjustmentrequest')}
										<a class="item-submenu" href={resolve('/orientandos')} onclick={fecharSubmenu}>
											<Icone nome="orientandos" tamanho={14} />
											Orientandos
										</a>
									{/if}
									{#if sessao.temPapel('Secretaria', 'Coordenação')}
										<a
											class="item-submenu"
											href={resolve('/acertos-do-programa')}
											onclick={fecharSubmenu}
										>
											<Icone nome="programa" tamanho={14} />
											Do programa
										</a>
									{/if}
								</div>
							</details>
						{/if}
						<!-- Bolsas: um menu pai com as três telas de gestão do edital. O
						pai aparece se qualquer item aparecer, e cada item continua com a
						sua condição — o submenu junta as telas, não as permissões.

						- Edital: `view_committeemember` é de quem opera o edital — Secretaria
						  (monta) e Coordenação (acompanha), por
						  `scholarships.0008_papeis_da_bolsa`. O Discente e a Comissão de
						  Bolsas não a têm: leem a edição e o barema, mas a composição da
						  portaria não é assunto deles.
						- Análise: `review_baremeentry` é exclusiva da Comissão de Bolsas e é
						  ela que abre os formulários; Secretaria e Coordenação entram por
						  papel, porque acompanham em leitura e não há permissão que as reúna
						  sem alcançar o Discente — ele lê a observação da própria inscrição
						  em "Minha bolsa", não aqui.
						- Resultado: a lista publicada é assunto dos quatro papéis, e
						  `view_scholarshipedition` é justamente a permissão que todos
						  receberam. Quem chega cedo não vê lista nenhuma — o servidor recusa
						  a prévia ao candidato (403 `result_not_published`), e a tela
						  transforma isso em espera. -->
						{#if sessao.pode('scholarships.view_committeemember') || sessao.pode('scholarships.review_baremeentry') || sessao.pode('scholarships.view_scholarshipedition') || sessao.temPapel('Secretaria', 'Coordenação')}
							<details class="group relative">
								<summary class="item-menu cursor-pointer list-none marker:content-['']">
									<Icone nome="edital" tamanho={14} />
									Bolsas
									<span aria-hidden="true" class="text-cinza text-[0.625rem]">▾</span>
								</summary>
								<div
									class="border-borda bg-papel absolute top-full left-0 z-10 mt-2 flex min-w-48 flex-col border py-1 shadow-sm"
								>
									{#if sessao.pode('scholarships.view_committeemember')}
										<a
											class="item-submenu"
											href={resolve('/bolsas/edital')}
											onclick={fecharSubmenu}
										>
											<Icone nome="edital" tamanho={14} />
											Edital
										</a>
									{/if}
									{#if sessao.pode('scholarships.review_baremeentry') || sessao.temPapel('Secretaria', 'Coordenação')}
										<a
											class="item-submenu"
											href={resolve('/bolsas/analise')}
											onclick={fecharSubmenu}
										>
											<Icone nome="analise" tamanho={14} />
											Análise
										</a>
									{/if}
									{#if sessao.pode('scholarships.view_scholarshipedition')}
										<a
											class="item-submenu"
											href={resolve('/bolsas/resultado')}
											onclick={fecharSubmenu}
										>
											<Icone nome="classificacao" tamanho={14} />
											Resultado
										</a>
									{/if}
								</div>
							</details>
						{/if}
						<!-- A outra ponta do mesmo edital: a tela do próprio candidato.
						`add_scholarshipapplication` é exclusiva do Discente
						(`scholarships.0008_papeis_da_bolsa`) — Secretaria, Coordenação e
						Comissão de Bolsas leem a inscrição alheia, mas nenhuma delas se
						inscreve. Os dois itens nunca aparecem juntos, exceto para o
						superusuário, que enxerga tudo. -->
						{#if sessao.pode('scholarships.add_scholarshipapplication')}
							<a class="item-menu" href={resolve('/bolsas/inscricao')}>
								<Icone nome="inscricao" tamanho={14} />
								Minha bolsa
							</a>
						{/if}
						<!-- Recorrer é do candidato e de mais ninguém:
						`add_scholarshipappeal` é exclusiva do Discente, e é a mesma
						separação que faz "o aluno não julga o próprio recurso" ser 403 de
						permissão. A Comissão julga na tela de análise. -->
						{#if sessao.pode('scholarships.add_scholarshipappeal')}
							<a class="item-menu" href={resolve('/bolsas/recurso')}>
								<Icone nome="acerto" tamanho={14} />
								Recurso da bolsa
							</a>
						{/if}
					</nav>
				</div>
				<div class="flex items-center gap-4">
					<span class="etiqueta hidden sm:inline">{sessao.usuario.username}</span>
					<button class="botao-discreto" type="button" onclick={sair}>Sair</button>
				</div>
			</div>
		</header>

		<main class="mx-auto max-w-5xl px-6 py-10">
			{@render children()}
		</main>
	</div>
{/if}
