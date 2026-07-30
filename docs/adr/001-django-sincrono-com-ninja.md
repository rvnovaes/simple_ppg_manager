# ADR-001: Django síncrono com Django Ninja

- **Data**: 2026-07-30
- **Status**: aceito

## Contexto

O sistema atende uma instituição: dezenas de usuários simultâneos no
pico, não milhares. O time é sênior em infraestrutura e iniciante em
desenvolvimento — o custo dominante do projeto é erro humano, não CPU.

Código async em Python cria uma classe inteira de bug que não existe no
código síncrono: `await` esquecido devolvendo corrotina, acesso a objeto
do ORM fora do event loop, biblioteca síncrona bloqueando o loop. São bugs
que não quebram na hora, quebram sob carga — o pior formato possível para
quem está aprendendo.

Para a camada HTTP, DRF traz um vocabulário próprio (serializers,
viewsets, routers, permissions) que é mais uma coisa a aprender além do
Django. Django Ninja usa type hints e Pydantic v2, que o time já precisa
conhecer para escrever Python moderno.

## Decisão

Backend em **Django 5.x síncrono**, com **Django Ninja** para a API REST
em `/api/v1/`. Nenhuma view `async`. Descartados: FastAPI e Litestar
(exigiriam ORM e admin separados), Flask (monta-se tudo à mão), DRF
(vocabulário extra), GraphQL (complexidade sem demanda).

## Consequências

- Uma única forma de escrever view. O que vale no Admin vale no router.
- Ganho de Ninja sobre DRF: schema de entrada e saída são classes
  Pydantic, e o OpenAPI sai de graça — é dele que o front gera os tipos.
- Perde-se concorrência de I/O em requisições longas. Se aparecer gargalo
  real, mede-se primeiro; a saída provável é worker em background, não
  reescrever em async.
- Deploy é WSGI (`gunicorn`), sem ASGI, sem servidor extra. O projeto
  deliberadamente não tem `asgi.py`.
- Reabrir exige medição de carga mostrando que o gargalo é I/O e que
  processos adicionais não resolvem.
