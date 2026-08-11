# ADR-004: Origem única via Nginx, CORS proibido

- **Data**: 2026-07-30
- **Status**: aceito

## Contexto

O arranjo comum em projetos SPA — front em uma porta, API em outra —
obriga a configurar CORS, e CORS mal configurado é uma das fontes mais
frequentes de brecha e de tempo perdido. Com cookie de sessão (ADR-003) o
problema piora: origem cruzada exige `SameSite=None` + `Secure` +
`credentials`, e qualquer erro em um desses três quebra o login de um
jeito que o navegador reporta de forma enigmática.

Servir tudo em uma origem só é um problema que o time de infra já sabe
resolver: é uma configuração de Nginx, a mesma que ele opera em outros
sistemas.

## Decisão

Front e API sempre atrás do **mesmo Nginx, na mesma origem**. Em
desenvolvimento é `http://localhost:8080`; em produção, o host com TLS.

O `baseUrl` do cliente HTTP é **relativo** (`/api/v1`). URL absoluta de
API no front não passa em review.

**CORS é proibido.** Se surgir a necessidade de configurar CORS, o erro
está no deploy, não no código.

## Consequências

- Cookie de sessão funciona com `SameSite=Lax`, sem exceção nenhuma.
- Não existe ambiente onde "funciona local mas quebra em produção" por
  origem: o desenho é o mesmo nos dois.
- Abrir o Vite direto **quebra login e CSRF** — em dev, sempre `:8080`.
  Isso está no Makefile e no CLAUDE.md porque é a pegadinha que mais vai
  custar tempo ao time. Desde que o Vite virou serviço do Compose a
  pegadinha ficou difícil de cair: a 5173 é interna à rede da stack e não é
  publicada, então não há o que abrir por engano.
- O Nginx passa a ser peça obrigatória também em dev, o que adiciona um
  container. É uma peça que a infra já domina.
- `Host`, `X-Forwarded-Proto` e `X-Forwarded-For` precisam ser repassados
  corretamente, senão o CSRF do Django rejeita a requisição.
