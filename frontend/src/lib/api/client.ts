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

/**
 * Serializa o corpo como `multipart/form-data`.
 *
 * O `bodySerializer` padrão do openapi-fetch é `JSON.stringify`, que não
 * serve para upload. Passar este aqui em `api.POST(..., { bodySerializer })`
 * faz o navegador montar o `Content-Type` com o boundary — definir o header
 * à mão quebraria o parsing no Django.
 *
 * O tipo gerado declara o arquivo como `string` (é `format: binary` no
 * OpenAPI), então a tela precisa de um cast na hora de montar o corpo.
 */
export function comoFormData(corpo: Record<string, unknown>): FormData {
	const dados = new FormData();
	for (const [chave, valor] of Object.entries(corpo)) {
		if (valor === undefined || valor === null) continue;
		dados.append(chave, valor instanceof Blob ? valor : String(valor));
	}
	return dados;
}

/** Extrai a mensagem padronizada `{detail, code}` do backend. */
export function mensagemDeErro(erro: unknown, padrao = 'Não foi possível concluir.'): string {
	if (erro && typeof erro === 'object' && 'detail' in erro) {
		const { detail } = erro as { detail?: unknown };
		if (typeof detail === 'string') return detail;
	}
	return padrao;
}

/**
 * Extrai o `code` estável do corpo de erro do backend.
 *
 * A mensagem é para a pessoa ler; o `code` é para a tela decidir. Só use
 * quando o desfecho muda de verdade (janela do edital fechada, por exemplo)
 * — comparar `detail` seria depender do texto.
 */
export function codigoDeErro(erro: unknown): string {
	if (erro && typeof erro === 'object' && 'code' in erro) {
		const { code } = erro as { code?: unknown };
		if (typeof code === 'string') return code;
	}
	return '';
}
