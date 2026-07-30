# ADR-002: Model é a entidade de domínio

- **Data**: 2026-07-30
- **Status**: aceito

## Contexto

Arquiteturas em camadas (Repository, Mapper, Unit of Work, entidade de
domínio separada do model, Protocols para inversão de dependência) existem
para desacoplar o domínio de um ORM pobre e para permitir trocar o banco.
Nenhuma das duas motivações se aplica aqui: o Django ORM já é repositório
e mapper, e não há cenário em que o PostgreSQL seja trocado.

O custo dessas camadas, por outro lado, é imediato: cada campo novo passa
a exigir alteração em quatro ou cinco arquivos, e quem está aprendendo
perde a noção de onde a regra realmente mora.

## Decisão

O **model é a entidade**. Regra de negócio que protege invariante vive em
método do próprio model (`Person.archive()`), e o teste dessa regra
instancia o model em memória, sem banco e sem mock.

`services.py` existe por app, **opcional**, e só quando uma operação
escreve em mais de um model e precisa ser atômica — função simples com
`@transaction.atomic`. Operação que toca um model só é chamada direto do
router.

Proibidos: Repository, Mapper, Unit of Work, entidade paralela ao model,
Protocols/interfaces por antecipação.

## Consequências

- Campo novo custa ~6 arquivos ponta a ponta (Seção 6 do CLAUDE.md). Se
  custar mais, é sinal de que a arquitetura foi violada — é o alarme.
- O router fica fino de propósito: schema de entrada, permissão, chamada,
  schema de saída. Regra de negócio em router não passa em review.
- Testar invariante fica barato (sem banco), o que aumenta a chance de o
  teste existir.
- Perde-se portabilidade teórica de banco e a possibilidade de testar
  domínio sem Django instalado. Ambas são irrelevantes neste projeto.
- Um service que só encaminha para um model é code smell: apague.
