# ADR-003: Autenticação por sessão do Django, sem JWT

- **Data**: 2026-07-30
- **Status**: aceito

## Contexto

JWT é o padrão de fato quando API e front vivem em domínios diferentes ou
quando há múltiplos serviços consumindo a mesma API. Não é o caso: front e
API ficam atrás do mesmo Nginx, na mesma origem (ADR-004), e há um único
consumidor.

Onde há origem única, JWT é um downgrade de segurança operacional: o token
precisa ser guardado em algum lugar do browser (`localStorage` é
vulnerável a XSS), não dá para revogar sem inventar uma denylist, e a
renovação exige um segundo fluxo (refresh token) para escrever e manter.
Tudo isso já vem pronto e testado na sessão do Django.

## Decisão

**Sessão do Django** em cookie `HttpOnly`, com o **CSRF do Django sempre
ativo**. Login e logout são endpoints Ninja
(`POST /api/v1/auth/login`, `POST /api/v1/auth/logout`) que chamam
`django.contrib.auth.authenticate/login/logout`.

Autorização usa `Permission` e `Group` **nativos**. Papéis do domínio
("Secretaria", "Coordenação") são Groups criados por data migration, não
um RBAC próprio. Toda rota faz checagem explícita via `require_perm()`.

Descartados: JWT, tokens próprios, OAuth caseiro, sistema de papéis
próprio.

## Consequências

- O cookie de sessão é `HttpOnly`: JavaScript não o alcança, então XSS não
  vira roubo de sessão.
- Logout revoga de verdade, no servidor. Banir um usuário tem efeito
  imediato.
- Em troca, toda escrita precisa do header `X-CSRFToken`. Isso é resolvido
  **uma vez** em `frontend/src/lib/api/client.ts`; nenhuma tela lida com
  CSRF.
- A sessão exige o mesmo domínio (ADR-004). Os dois ADRs caem juntos.
- Admin e API compartilham a mesma sessão: quem entra no Admin já está
  autenticado na API, sem ponte nenhuma.
- Se um dia houver cliente móvel ou integração externa de terceiro, é ADR
  novo — provavelmente token de serviço com escopo, não JWT de usuário.
