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
	 * Para onde mandar a pessoa depois de entrar.
	 *
	 * O Candidato da isolada não tem `people.view_person` (ver
	 * `academic.0011_papeis_da_isolada`): jogá-lo em /pessoas seria abrir a
	 * sessão com um 403 na cara. A escolha é por permissão, e não por papel,
	 * porque o que decide é o que a tela de destino exige.
	 */
	get rotaInicial(): '/pessoas' | '/inscricao' {
		return this.pode('people.view_person') ? '/pessoas' : '/inscricao';
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
