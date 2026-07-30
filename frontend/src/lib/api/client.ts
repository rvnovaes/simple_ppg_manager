import createClient, { type Middleware } from 'openapi-fetch';
import type { paths } from './schema';

/**
 * Cliente único da API.
 *
 * Nenhuma tela usa `fetch` cru (Seção 8 do CLAUDE.md): tudo passa por aqui,
 * onde CSRF e credenciais são resolvidos de uma vez só.
 */

const METODOS_DE_ESCRITA = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

function lerCookie(nome: string): string | undefined {
	return document.cookie
		.split('; ')
		.find((parte) => parte.startsWith(`${nome}=`))
		?.split('=')[1];
}

const csrf: Middleware = {
	async onRequest({ request }) {
		if (METODOS_DE_ESCRITA.has(request.method)) {
			const token = lerCookie('csrftoken');
			if (token) request.headers.set('X-CSRFToken', token);
		}
		return request;
	}
};

export const api = createClient<paths>({
	// RELATIVA, sempre. URL absoluta quebra a origem única (ADR-004).
	baseUrl: '/api/v1',
	// Sem isto o cookie de sessão não acompanha a requisição.
	credentials: 'include'
});

api.use(csrf);

/**
 * Planta o cookie `csrftoken` antes da primeira escrita.
 *
 * O Django só emite o cookie quando alguém pede o token — no login ainda não
 * há sessão, então essa chamada precisa acontecer antes.
 */
export async function garantirCsrf(): Promise<void> {
	if (lerCookie('csrftoken')) return;
	await api.GET('/auth/csrf');
}

/** Extrai a mensagem padronizada `{detail, code}` do backend. */
export function mensagemDeErro(erro: unknown, padrao = 'Não foi possível concluir.'): string {
	if (erro && typeof erro === 'object' && 'detail' in erro) {
		const { detail } = erro as { detail?: unknown };
		if (typeof detail === 'string') return detail;
	}
	return padrao;
}
