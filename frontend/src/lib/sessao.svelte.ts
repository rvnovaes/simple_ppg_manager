import { api, garantirCsrf } from './api/client';
import type { components } from './api/schema';

export type Usuario = components['schemas']['UserOut'];

/**
 * Sessão do usuário — estado global da SPA, em runas do Svelte 5.
 *
 * A verdade sobre quem está logado mora no cookie de sessão do Django; isto
 * aqui é só o reflexo dele em memória, para as telas não perguntarem ao
 * servidor a cada render.
 */
class Sessao {
	usuario = $state<Usuario | null>(null);
	carregando = $state(true);

	get autenticado(): boolean {
		return this.usuario !== null;
	}

	pode(permissao: string): boolean {
		return this.usuario?.permissions.includes(permissao) ?? false;
	}

	/**
	 * Se a sessão está em algum dos papéis (Groups) informados.
	 *
	 * Só para o caso em que a permissão não distingue o público: os quatro
	 * papéis têm `academic.view_enrollmentadjustmentrequest`, e o que muda é
	 * o recorte que o backend aplica por papel. Onde existir permissão
	 * exclusiva, `pode()` continua sendo o critério certo.
	 */
	temPapel(...papeis: string[]): boolean {
		return this.usuario?.groups.some((papel) => papeis.includes(papel)) ?? false;
	}

	/**
	 * Se a conta está esperando a secretaria confirmar o cadastro.
	 *
	 * O papel sozinho não basta, e o furo é este: o Group "Cadastro pendente"
	 * é do `User`, que é global, enquanto a `Person` e a solicitação são por
	 * programa. Quem já trabalha num programa e pede acesso a outro carrega o
	 * marcador sem estar pendente onde já atua — mandá-lo para a tela de
	 * espera tiraria dele o sistema inteiro. A ausência de QUALQUER permissão
	 * separa os dois casos: quem só tem o marcador ainda não recebeu papel de
	 * domínio nenhum, aqui nem em lugar algum.
	 */
	get pendenteDeConfirmacao(): boolean {
		return this.temPapel('Cadastro pendente') && (this.usuario?.permissions.length ?? 0) === 0;
	}

	/**
	 * Para onde mandar a pessoa depois de entrar.
	 *
	 * O pendente vem antes de tudo: sem permissão nenhuma, qualquer tela de
	 * (app) lhe daria 403 — a de espera é a única que ele consegue ler.
	 *
	 * O Candidato da isolada não tem `people.view_person` (ver
	 * `academic.0011_papeis_da_isolada`): jogá-lo em /pessoas seria abrir a
	 * sessão com um 403 na cara. A escolha é por permissão, e não por papel,
	 * porque o que decide é o que a tela de destino exige.
	 */
	get rotaInicial(): '/aguardando-confirmacao' | '/pessoas/administrativo' | '/inscricao' {
		if (this.pendenteDeConfirmacao) return '/aguardando-confirmacao';
		return this.pode('people.view_person') ? '/pessoas/administrativo' : '/inscricao';
	}

	/** Pergunta ao backend quem é o usuário da sessão atual. */
	async carregar(): Promise<void> {
		this.carregando = true;
		const { data } = await api.GET('/auth/me');
		this.usuario = data ?? null;
		this.carregando = false;
	}

	async entrar(username: string, password: string): Promise<Usuario> {
		await garantirCsrf();
		const { data, error } = await api.POST('/auth/login', {
			body: { username, password }
		});
		if (error || !data) throw error ?? new Error('Falha no login.');
		this.usuario = data;
		return data;
	}

	async sair(): Promise<void> {
		await api.POST('/auth/logout');
		this.usuario = null;
	}
}

export const sessao = new Sessao();
