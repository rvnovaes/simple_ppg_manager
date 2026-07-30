/*
 * O Ninja escreve os caminhos do OpenAPI com o prefixo completo
 * ("/api/v1/auth/login"), mas o client já tem baseUrl "/api/v1". Sem esta
 * normalização toda chamada viraria "/api/v1/api/v1/...".
 *
 * Roda antes do openapi-typescript, dentro de `npm run gen:api`.
 */
import { readFileSync, writeFileSync } from 'node:fs';

const ARQUIVO = new URL('../src/lib/api/openapi.json', import.meta.url);
const PREFIXO = '/api/v1';

const schema = JSON.parse(readFileSync(ARQUIVO, 'utf8'));

const paths = Object.fromEntries(
	Object.entries(schema.paths ?? {}).map(([caminho, valor]) => [
		caminho.startsWith(PREFIXO) ? caminho.slice(PREFIXO.length) || '/' : caminho,
		valor
	])
);

writeFileSync(ARQUIVO, JSON.stringify({ ...schema, paths }, null, 2) + '\n');

console.log(`openapi.json normalizado: ${Object.keys(paths).length} caminhos sem "${PREFIXO}".`);
