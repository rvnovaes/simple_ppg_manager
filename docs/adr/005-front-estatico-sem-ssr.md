# ADR-005: Front estático (`adapter-static`), sem SSR e sem Node em produção

- **Data**: 2026-07-30
- **Status**: aceito

## Contexto

SvelteKit com `adapter-node` e SSR exige um processo Node rodando em
produção: mais um serviço para instalar, supervisionar, atualizar,
monitorar e incluir no plano de recuperação. O time de infra passaria a
operar dois runtimes (Python e Node) em vez de um.

O que SSR entrega — SEO e primeiro paint mais rápido — não tem valor aqui:
o sistema fica atrás de login, não é indexado por buscador, e o público é
interno, em rede boa.

## Decisão

Front em **SvelteKit com `adapter-static`**, SPA pura: `export const ssr =
false` no layout raiz e `fallback: 'index.html'`. O build gera arquivos
estáticos servidos diretamente pelo Nginx.

**Nenhum processo Node em produção, em nenhuma hipótese.** Node existe
apenas como ferramenta de build.

## Consequências

- Deploy do front é copiar arquivos. Rollback é copiar os arquivos
  anteriores. Não há processo para reiniciar nem porta para vigiar.
- Produção roda dois processos no total: `gunicorn` e `postgres` (mais o
  Nginx). É o desenho que a infra já opera.
- Toda a busca de dados acontece no browser, depois do carregamento —
  `+page.server.ts` e `load` com acesso a banco não existem neste projeto.
- Sem SEO e sem HTML pré-renderizado. Irrelevante para sistema atrás de
  login.
- Se SSR virar necessidade real, é **ADR novo com aprovação da infra**,
  porque cria um processo novo para operar — a decisão é tanto de operação
  quanto de código.
