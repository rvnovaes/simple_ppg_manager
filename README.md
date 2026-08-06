# PPGD Manager

Sistema de gestão para programa de pós-graduação. Multi-tenant desde a
primeira migração: todo dado de negócio carrega a chave do programa.

Backend em Django + Django Ninja, frontend em SvelteKit como SPA estática,
tudo servido por um Nginx em **uma origem só**.

> **As regras do projeto estão no [CLAUDE.md](CLAUDE.md)**, não aqui. Este
> arquivo é o "como rodar" e o "como o sistema é por dentro"; aquele é o
> "como fazer". Em caso de conflito, o CLAUDE.md vence. As decisões de
> arquitetura estão em [`docs/adr/`](docs/adr/).

Este README tem duas partes independentes. Leia a que corresponde ao seu
papel:

- **[Manual do Usuário](#manual-do-usuário)** — para quem usa o sistema:
  secretaria, coordenação, docentes e discentes.
- **[Manual do Desenvolvedor](#manual-do-desenvolvedor)** — para quem
  escreve código.

---

# Manual do Usuário

Para quem usa o sistema: secretaria, coordenação, docentes, discentes e
candidatos a disciplina isolada. Nada aqui pressupõe conhecimento técnico.

## Sumário

- [Como entrar](#como-entrar)
- [O que cada perfil enxerga](#o-que-cada-perfil-enxerga)
- [Duas convenções que valem para o sistema inteiro](#duas-convenções-que-valem-para-o-sistema-inteiro)
- [Secretaria e coordenação](#secretaria-e-coordenação)
- [Docente](#docente)
- [Discente](#discente)
- [Candidato a disciplina isolada](#candidato-a-disciplina-isolada)
- [Quando algo dá errado](#quando-algo-dá-errado)

## Como entrar

Acesse o endereço que a secretaria informou e entre com **o seu e-mail
completo** (não a parte antes do `@`) e a sua senha.

**Primeiro acesso.** Quem trabalha no programa — secretaria, coordenação,
docentes e discentes — não cria a própria conta. A secretaria cadastra a
pessoa e define a senha do primeiro acesso, que ela informa a você. Depois
disso, a senha é sua: nem a secretaria pode trocá-la sozinha.

**Candidato a disciplina isolada é a exceção**: essa conta você mesmo cria,
e só enquanto houver um edital com inscrições abertas. Veja
[Candidato a disciplina isolada](#candidato-a-disciplina-isolada).

Para sair, use o botão **Sair** no canto superior direito.

## O que cada perfil enxerga

O menu superior muda conforme o seu papel — você só vê o que pode usar.
Alguns itens abrem submenus.

| Menu                              | Submenu                                         | Quem vê                                      |
| --------------------------------- | ----------------------------------------------- | -------------------------------------------- |
| **Pessoas**                       | Professores, Alunos, Candidatos, Administrativo | Secretaria e coordenação                     |
| **Estrutura**                     | —                                               | Secretaria e coordenação                     |
| **Disciplinas**                   | —                                               | Secretaria e coordenação                     |
| **Disciplina isolada**            | Análise, Editais                                | Secretaria (análise) e coordenação (leitura) |
| **Inscrição**, **Acompanhamento** | —                                               | Candidato                                    |
| **Classificação**                 | —                                               | Docente responsável por oferta               |
| **Acerto de matrícula**           | Meus acertos, Orientandos, Do programa          | Cada papel vê só a sua parte                 |

Se um item que você espera não aparece, o motivo quase sempre é o papel da
sua conta. Fale com a secretaria — link que só levaria a uma tela negada
não é exibido de propósito.

## Duas convenções que valem para o sistema inteiro

**1. O sistema não apaga ninguém.** Onde você lê "excluir", "arquivar" ou
"descredenciar", o registro continua existindo e apenas muda de situação:

- **professor** → recebe uma data de descredenciamento;
- **aluno** → passa para a situação _Excluído_;
- **pessoa** (candidato, administrativo) → passa para _Arquivada_.

Isso é intencional. O professor descredenciado continua sendo quem
orientou os alunos dele, e o aluno desligado continua sendo quem cursou o
que cursou. Nenhum histórico se perde.

**2. Modalidade e situação são coisas separadas** no cadastro do aluno:

- **modalidade**: Regular, Isolada ou Eletiva — como a pessoa está no
  programa;
- **situação**: Ativo, Trancado ou Excluído — como está esse vínculo agora.

Um aluno pode ser _Regular_ e _Trancado_ ao mesmo tempo. Trancamento só se
aplica ao regular; isolada e eletiva duram um semestre e terminam
excluídas.

**Os três botões das listagens.** Em Professores, Alunos, Candidatos e
Administrativo, cada linha traz até três ícones à direita:

| Ícone | O que faz                                                   |
| ----- | ----------------------------------------------------------- |
| 👁     | abre a página de detalhes, com todos os dados do registro   |
| ✏️    | abre o formulário de edição, na própria lista               |
| 🗄     | desativa (arquiva, descredencia ou exclui, conforme o caso) |

Quando o registro já está desativado, o terceiro botão aparece
desabilitado — passe o mouse para ver o motivo.

## Secretaria e coordenação

A secretaria opera; a coordenação acompanha, em geral apenas lendo.

### Estrutura do programa

Menu **Estrutura**. É a base de tudo, e costuma ser o primeiro cadastro do
semestre:

- **Linhas de pesquisa** — agrupam os projetos.
- **Projetos coletivos** — pertencem a uma linha; é o projeto que
  professores e alunos citam no vínculo.
- **Períodos letivos** — o semestre, escrito sempre como `2026/1`. O
  período é da instituição inteira, não do programa: o mesmo `2026/1` vale
  para todos os cursos.

Linhas e projetos podem ser **desativados** em vez de apagados; quem já se
vinculou a eles continua vinculado.

### Catálogo de disciplinas

Menu **Disciplinas**. Cada disciplina tem código (por exemplo `DIR801`) e
nome. É deste catálogo que saem tanto as disciplinas do acerto de
matrícula quanto as ofertas do edital de isoladas. O código não se repete
dentro do programa.

### Cadastro de professores

Menu **Pessoas → Professores**. Ao cadastrar, informe categoria CAPES
(permanente, colaborador ou visitante), titulação, data de credenciamento
e, se quiser, Lattes e instituição de origem. Também é aqui que se marcam
as linhas de pesquisa e os projetos do professor.

Se a pessoa **já existe** no programa, digite o e-mail e use **Procurar**
antes de preencher o resto: o sistema reaproveita o cadastro em vez de
criar outro. Quando a conta ainda não tem senha, aparece o botão **Definir
senha inicial**.

Para descredenciar, use o terceiro ícone da linha. A data registrada é a
de hoje; se a portaria for retroativa, use a edição e informe a data
correta em "credenciado até".

### Cadastro de alunos

Menu **Pessoas → Alunos**. O formulário muda conforme a modalidade:

- **Regular** exige nível (mestrado ou doutorado), projeto coletivo e data
  de ingresso. O prazo de conclusão é calculado sozinho — 2 anos no
  mestrado, 4 no doutorado — e pode ser editado depois, no caso de
  prorrogação.
- **Isolada** e **Eletiva** exigem o período letivo e não têm campos de
  grau.

### Candidatos e administrativo

Menu **Pessoas → Candidatos** e **Pessoas → Administrativo**. As duas são
listas de leitura, e cada uma explica na própria tela de onde vêm os
nomes:

- **Candidatos** são as pessoas que se inscreveram em disciplina isolada.
  Quem já virou aluno continua aparecendo — o requerimento não deixa de
  existir quando a matrícula sai.
- **Administrativo** são as contas com papel de Secretaria ou Coordenação.
  Esse papel é atribuído pela equipe que opera a plataforma, não por esta
  tela.

As quatro listas de Pessoas **não são exclusivas**: quem coordena e dá
aula aparece em Professores _e_ em Administrativo, porque é uma pessoa só
com dois vínculos.

### Edital de disciplina isolada

Menu **Disciplina isolada → Editais**. Um edital por semestre. O
calendário tem seis marcos, e é ele que faz o sistema aceitar ou recusar
cada ação na data certa, sem ninguém conferir à mão:

1. abertura das inscrições;
2. encerramento das inscrições;
3. publicação do resultado;
4. abertura dos recursos;
5. encerramento dos recursos;
6. prazo final de pagamento da GRU.

As datas precisam estar em ordem — o sistema recusa um calendário em que a
janela de recurso abra antes de as inscrições fecharem.

Na mesma tela ficam as **disciplinas ofertadas**: cada oferta tem uma
disciplina do catálogo, o docente responsável (que será quem classifica os
candidatos) e o número de vagas.

**Encerrar o período** fecha o edital e desliga os alunos de isolada
daquele semestre. Antes de confirmar, o sistema informa quantos vínculos
serão encerrados. Não há encerramento automático por data: a decisão é da
secretaria.

### Análise das inscrições

Menu **Disciplina isolada → Análise**. É a fila de trabalho da secretaria.
Para cada inscrição você vê os documentos anexados e decide:

- **Deferir** — reserva a vaga. Informe o link da GRU para o candidato
  pagar. Servidor da UFMG entra como isento automaticamente.
- **Indeferir** — exige motivo. O motivo é o que o candidato lê e o que
  ele contesta no recurso, então escreva o que precisa ser corrigido.
- **Cancelar** — devolve a vaga à fila. É a única saída de um deferido que
  não pagou; nada expira sozinho.

Duas travas que você vai encontrar: não é possível deferir enquanto **o
docente não tiver classificado** os candidatos da oferta, nem quando a
oferta **não tem mais vaga**.

Depois do pagamento, a matrícula é efetivada e o candidato vira aluno de
isolada naquele semestre.

### Acompanhar acertos de matrícula

Menu **Acerto de matrícula → Do programa**. Lista, apenas para leitura,
de todas as solicitações do programa em um período, com a situação de cada
uma. Quem decide é o orientador.

## Docente

### Classificar candidatos das suas ofertas

Menu **Classificação**. Aparece para o docente responsável por alguma
oferta do edital. A tela separa **o que falta classificar** do que você já
respondeu.

Classificar é ordenar os inscritos: 1º, 2º, 3º. Essa ordem é o que a
secretaria usa para cortar pelas vagas disponíveis. Enquanto uma oferta
não estiver classificada, nenhuma inscrição dela pode ser deferida.

### Decidir os acertos dos seus orientandos

Menu **Acerto de matrícula → Orientandos**. Cada solicitação mostra o
aluno, o período, a justificativa e a lista de disciplinas a incluir ou
excluir. Você **aprova** ou **recusa**:

- aprovar não exige justificativa;
- recusar **exige motivo** — é o que o aluno lê para saber o que fazer.

A decisão é definitiva: uma solicitação já decidida não volta a ficar
aberta. Se algo mudar, o aluno abre outra.

## Discente

### Pedir acerto de matrícula

Menu **Acerto de matrícula → Meus acertos**. Use **Nova solicitação** para
montar um pedido: escolha o período, escreva a justificativa e liste as
disciplinas que quer **incluir** e as que quer **excluir**. Tudo vai num
pedido só, para o orientador decidir de uma vez.

Duas condições para abrir uma solicitação, e a tela avisa quando faltam:

- você precisa ser **aluno regular** — isolada e eletiva não abrem acerto;
- você precisa **ter orientador** — sem ele não haveria quem decidisse.

Depois de enviada, a solicitação fica _Aberta_ até o orientador decidir.
Quando ele decide, a situação passa a _Aprovada_ ou _Recusada_, e a recusa
sempre vem com o motivo.

## Candidato a disciplina isolada

Fluxo de quem não tem vínculo com a instituição e quer cursar até **duas
disciplinas** da pós num semestre.

### 1. Criar a conta

Só é possível enquanto houver edital com inscrições abertas. Na tela de
login, embaixo do botão **Entrar**, clique em **Cadastre-se** ("Vai cursar
disciplina isolada e ainda não tem conta?") e informe nome, e-mail e
senha.

### 2. Fazer a inscrição

Menu **Inscrição**. Escolha uma ou duas disciplinas entre as ofertadas e
anexe a documentação:

- identidade e CPF;
- diploma de graduação ou certidão de conclusão;
- currículo Lattes em PDF;
- comprovante de endereço.

**Servidor da UFMG** marca essa condição e anexa também contracheque e
autorização da chefia — em troca, fica isento da taxa.

Os arquivos são PDF, JPG ou PNG, de até 10 MB cada. Só é possível **enviar
a inscrição com toda a documentação anexada**, e só dentro do prazo do
edital. Enquanto ela for um rascunho, você pode trocar disciplinas e
documentos; depois de enviada, não.

### 3. Acompanhar

Menu **Acompanhamento**. Mostra a situação da sua inscrição:

| Situação    | O que significa                      |
| ----------- | ------------------------------------ |
| Rascunho    | montada, ainda não enviada           |
| Inscrito    | enviada, aguardando decisão          |
| Deferido    | aceito — falta pagar a taxa          |
| Indeferido  | recusado, com o motivo escrito       |
| Cancelado   | encerrado; a vaga voltou para a fila |
| Matriculado | matrícula efetivada                  |

**Deferido**: use o link da GRU disponível na tela, pague dentro do prazo
e anexe o comprovante. Quem é isento pula essa etapa.

**Indeferido**: cabe recurso, dentro da janela do edital. Escreva as
razões e, se o problema foi documentação, anexe a página que faltou — esse
é o único momento depois da inscrição em que dá para trocar um documento.

## Quando algo dá errado

**Não vejo um item de menu que deveria ver.** O menu reflete o papel da
sua conta. Fale com a secretaria.

**Uma tela diz que não tenho permissão.** Mesma coisa: seu papel não
alcança aquela ação. Nada foi perdido.

**Esqueci minha senha.** Fale com a secretaria. Ela define a senha do
_primeiro_ acesso; se a sua conta já tem senha, quem faz a redefinição é a
equipe que opera a plataforma.

**O sistema recusou uma data.** Datas de edital seguem uma ordem
obrigatória, e prazos são conferidos contra o calendário publicado. A
mensagem diz qual regra foi violada.

**"Já existe uma pessoa com este e-mail".** O cadastro já está no sistema.
Procure pelo e-mail antes de criar outro — o formulário reaproveita a
pessoa existente.

**Fui deslogado sozinho.** A sessão expirou. Entre de novo; nada do que
você salvou se perde.

---

# Manual do Desenvolvedor

Escrito para quem está começando. Nenhum passo é considerado óbvio, e cada
decisão vem com o porquê — porque saber _por que_ algo é assim é o que
evita desfazê-lo sem querer.

## Sumário

1. [A regra que economiza mais tempo](#1-a-regra-que-economiza-mais-tempo)
2. [O que você precisa ter instalado](#2-o-que-você-precisa-ter-instalado)
3. [Subindo pela primeira vez](#3-subindo-pela-primeira-vez)
4. [A estrutura da aplicação, do banco à tela](#4-a-estrutura-da-aplicação-do-banco-à-tela)
5. [As decisões de arquitetura](#5-as-decisões-de-arquitetura)
6. [Cada comando do Makefile](#6-cada-comando-do-makefile)
7. [O Vite em desenvolvimento e em produção](#7-o-vite-em-desenvolvimento-e-em-produção)
8. [Quem entra onde](#8-quem-entra-onde)
9. [Armadilhas conhecidas](#9-armadilhas-conhecidas)

---

## 1. A regra que economiza mais tempo

**Acesse sempre `http://localhost:8080`.**

Abrir o Vite direto em `:5173` faz o login e o CSRF quebrarem de um jeito
que o navegador reporta de forma enigmática. Não é bug: front e API
precisam compartilhar a mesma origem, e quem garante isso é o Nginx na 8080. Ver [ADR-004](docs/adr/004-origem-unica-sem-cors.md).

Se você só decorar uma frase deste manual, que seja esta.

---

## 2. O que você precisa ter instalado

|                                    | Para quê                                                                            |
| ---------------------------------- | ----------------------------------------------------------------------------------- |
| [`uv`](https://docs.astral.sh/uv/) | dependências do backend — **instala o Python sozinho**, você não precisa ter Python |
| Node 20+ e `npm`                   | dependências e build do frontend                                                    |
| Docker + Compose v2                | banco, backend e Nginx                                                              |
| `make`                             | atalho para tudo                                                                    |

O `uv` merece uma nota: ele resolve dependências e gerencia a versão do
Python do projeto. Por isso todo comando Python daqui roda como
`uv run python ...`, e não `python ...` — o `python` do sistema não
enxerga as dependências do projeto.

---

## 3. Subindo pela primeira vez

```bash
cp .env.example .env      # ajuste se precisar; o .env nunca vai pro git
make install              # dependências do backend
make install-web          # dependências do frontend
make up                   # sobe db + backend + nginx
make migrate              # cria as tabelas
make superuser            # crie a SUA conta de sysadmin
```

Em **outro terminal**, e deixe rodando:

```bash
make web                  # servidor de desenvolvimento do frontend
```

Pronto:

- **Sistema** → http://localhost:8080
- **Admin** → http://localhost:8080/admin/ (só superusuário — veja a seção 8)
- **Documentação da API** → http://localhost:8080/api/v1/docs

O motivo de serem dois terminais está na [seção 7](#7-o-vite-em-desenvolvimento-e-em-produção).

---

## 4. A estrutura da aplicação, do banco à tela

Esta seção segue **um dado só** — uma pessoa cadastrada — desde a tabela
no Postgres até o pixel na tela. Todo recurso do sistema percorre esse
mesmo caminho; aprender uma vez basta.

### O mapa em uma imagem

```
  navegador
     │
     │  http://localhost:8080
     ▼
  ┌─────────────────────────────────────────────────┐
  │ Nginx  (origem única — ADR-004)                 │
  │                                                 │
  │  /api/     ──► backend  (Django)                │
  │  /admin/   ──► backend  (Django)                │
  │  /static/  ──► backend  (Django)                │
  │  /media/   ──► backend  (Django)                │
  │  /         ──► Vite em dev · arquivos em prod   │
  └─────────────────────────────────────────────────┘
        │                              │
        ▼                              ▼
  ┌───────────────┐            ┌──────────────────────┐
  │ Django        │            │ SvelteKit (SPA)      │
  │  router.py    │            │  +page.svelte        │
  │  schemas.py   │            │  sessao.svelte.ts    │
  │  services.py  │            │  lib/api/client.ts   │
  │  models.py    │            │  lib/api/schema.d.ts │
  └───────────────┘            └──────────────────────┘
        │                              ▲
        ▼                              │
  ┌───────────────┐                    │
  │ PostgreSQL    │      OpenAPI ──────┘
  └───────────────┘   (make gen-api)
```

Repare que a seta do OpenAPI aponta **do backend para o frontend**. Isso é
importante: os tipos do front não são escritos à mão, são gerados a partir
da API. Voltaremos a isso.

### Camada 1 — o banco

PostgreSQL, num container, com volume nomeado. Você quase nunca escreve
SQL: quem cria e altera tabela são as _migrations_ do Django, que são
arquivos Python versionados em `backend/apps/<app>/migrations/`.

Duas regras que valem desde já:

- **Toda tabela de negócio tem `program_id`.** É a chave de tenant. O
  sistema nasce para o PPGD, mas o dado já vem preparado para vários
  programas, porque acrescentar essa coluna depois, com dados em produção,
  é caro.
- **Nunca edite uma migration já aplicada.** Gere uma nova.

### Camada 2 — o model, que é a entidade

`backend/apps/people/models.py`. Aqui mora **a definição do dado e a regra
de negócio**, juntos. Não existe uma "entidade de domínio" separada do
model — ver [ADR-002](docs/adr/002-model-como-entidade.md).

```python
class Person(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Ativa"
        ARCHIVED = "archived", "Arquivada"

    program = models.ForeignKey("programs.Program", on_delete=models.PROTECT, ...)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, ...)
    full_name = models.CharField("nome completo", max_length=200)
    ...

    def archive(self) -> None:
        """Invariante: arquivar só faz sentido a partir de ACTIVE."""
        if self.status == self.Status.ARCHIVED:
            raise InvalidStateTransition("Pessoa já está arquivada.")
        self.status = self.Status.ARCHIVED
```

Três coisas para observar, porque cada uma é um padrão que se repete:

**`archive()` é um método, não um `update` solto.** A regra "não arquivar
duas vezes" fica _dentro_ do model, então qualquer caminho que arquive uma
pessoa passa por ela. Testar essa regra é barato — instancia o objeto em
memória, sem banco e sem mock.

**Escolha fechada é `TextChoices`.** Nunca se repete a string `"archived"`
espalhada pelo código; importa-se `Person.Status.ARCHIVED`.

**`QuerySet` customizado guarda consulta recorrente.** `Person.objects.active()`
e `.for_program(p)` moram no `PersonQuerySet`, não copiadas em cada view.

O `people` é o **exemplo de referência**. App novo: copie a estrutura dele.

### Camada 3 — o service, só quando precisa

`backend/apps/people/services.py`. Existe **um** service no projeto
inteiro, e o próprio arquivo explica por quê:

> Este arquivo só existe porque `create_person_with_user` escreve em três
> models e precisa ser atômico (ADR-002). Operação que toca um model só é
> chamada direto do router — não crie service "por simetria".

Ou seja: service não é camada obrigatória. É a exceção para operação que
precisa de `@transaction.atomic` cruzando models. **Service que só
encaminha para um model é code smell — apague.**

### Camada 4 — o router, a borda HTTP

`backend/apps/people/router.py`. Django Ninja, não DRF
([ADR-001](docs/adr/001-django-sincrono-com-ninja.md)). O router é **fino
de propósito** e sempre tem a mesma forma:

```python
@router.post("/{int:person_id}/archive", response=PersonOut)
def archive_person(request: HttpRequest, person_id: int):
    require_perm(request, "people.change_person")     # 1. permissão, sempre na 1ª linha
    person = get_object_or_404(Person, pk=person_id)  # 2. busca
    with transaction.atomic():
        person.archive()                              # 3. a REGRA mora no model
        person.save(update_fields=["status", "updated_at"])
        audit.record("people.archive", request=request, target=person)  # 4. auditoria
    return person                                     # 5. schema de saída explícito
```

Quatro regras de review saem daí:

1. **`require_perm` na primeira linha de toda rota.** Rota sem checagem só
   passa marcada com `# público` e justificativa.
2. **Zero regra de negócio no router.** Se você escreveu um `if` de
   domínio aqui, ele pertence ao model.
3. **Auditoria dentro do mesmo `atomic` da escrita.** Nunca se cria
   `AuditLog` direto — chama-se `audit.record()`.
4. **Nada de `try/except` no router.** `backend/api.py` tem handlers
   centrais que traduzem `DomainError` em 4xx com corpo padronizado
   `{detail, code}`.

### Camada 5 — os schemas

`backend/apps/people/schemas.py`. Classes Pydantic que definem o que
**entra** (`PersonIn`) e o que **sai** (`PersonOut`) da API. São elas que
geram o OpenAPI, e é do OpenAPI que o frontend gera seus tipos.

Consequência prática: mudar um `PersonOut` sem rodar `make gen-api` deixa
o front tipado com uma versão que não existe mais.

### Camada 6 — a montagem da API

`backend/api.py` junta os routers e define o padrão de autenticação:

```python
api = NinjaAPI(..., auth=django_auth)
api.add_router("/auth/", accounts_router)
api.add_router("/programs/", programs_router)
api.add_router("/people/", people_router)
```

`auth=django_auth` significa **sessão do Django em toda rota por padrão**
([ADR-003](docs/adr/003-sessao-e-csrf-sem-jwt.md)). Rota pública precisa
declarar `auth=None` explicitamente e se justificar.

### Camada 7 — a ponte de tipos

```bash
make gen-api
```

Exporta o OpenAPI do Django para `frontend/src/lib/api/openapi.json` e
gera `schema.d.ts` a partir dele. **Rode sempre que mexer em schema ou em
rota.** É o que faz o TypeScript acusar, em tempo de escrita, que um campo
que você usa na tela não existe mais na API.

### Camada 8 — o cliente HTTP do front

`frontend/src/lib/api/client.ts`. Existe **um** cliente, e nenhuma tela usa
`fetch` cru:

```ts
export const api = createClient<paths>({
  baseUrl: "/api/v1", // RELATIVA, sempre (ADR-004)
  credentials: "include", // sem isto o cookie de sessão não vai junto
});
api.use(csrf); // injeta X-CSRFToken em POST/PUT/PATCH/DELETE
```

O middleware de CSRF resolve o header **de uma vez só**. Nenhuma tela lida
com CSRF, e é por isso que ninguém deve chamar `fetch` diretamente: quem
faz isso perde o CSRF e as credenciais, e o erro aparece longe da causa.

Há também `garantirCsrf()`, que planta o cookie antes da primeira escrita —
no login ainda não há sessão, então o token precisa ser pedido antes.

### Camada 9 — a tela

`frontend/src/routes/`. SvelteKit em modo SPA pura:

```
routes/
  +layout.ts            ssr = false, prerender = false  (ADR-005)
  +layout.svelte        casca comum
  +page.svelte          raiz
  (auth)/login/         grupo de rotas sem sessão
  (app)/                grupo de rotas autenticadas
    pessoas/+page.svelte
```

Os parênteses em `(auth)` e `(app)` são **grupos de rota** do SvelteKit:
organizam arquivos e permitem um layout por grupo, sem aparecer na URL.

`frontend/src/lib/sessao.svelte.ts` guarda o estado do usuário logado.

Como `ssr = false`, **toda busca de dado acontece no navegador**, depois do
carregamento. `+page.server.ts` e `load` com acesso a banco não existem
neste projeto — se você viu isso num tutorial de SvelteKit, não se aplica
aqui.

### O caminho completo, resumido

Um clique em "Arquivar" na tela de pessoas percorre:

```
+page.svelte  →  api.POST('/people/{id}/archive')  →  client.ts injeta CSRF
   →  Nginx :8080  →  /api/ vai para o backend
   →  router.archive_person()  →  require_perm  →  Person.archive()
   →  save() + audit.record()  →  PostgreSQL
   →  PersonOut  →  JSON  →  a tela atualiza
```

### Onde mora cada coisa

```
backend/
  api.py                    monta a API e traduz erros
  config/
    settings/base.py        configuração comum
    settings/dev.py         desenvolvimento
    settings/prod.py        produção
    urls.py                 /api/v1/ e /admin/
    wsgi.py                 ponto de entrada (WSGI, não ASGI — ADR-001)
  apps/
    core/                   permissions.py, audit.py, exceptions.py
    accounts/               login, logout, CSRF
    programs/               Program — a chave de tenant
    people/                 Person — o exemplo de referência
    audit/                  AuditLog
frontend/src/
  lib/api/client.ts         o cliente único
  lib/api/schema.d.ts       tipos GERADOS — não edite à mão
  lib/sessao.svelte.ts      estado da sessão
  routes/                   as telas
nginx/                      configuração da origem única
docs/adr/                   as decisões de arquitetura
```

Cada app do Django tem `models.py`, `admin.py`, `router.py`, `schemas.py`,
`migrations/` e `tests/`. "App" aqui é o termo do Django — um módulo do
backend, sem relação com as telas do frontend.

### Quanto custa um campo novo

Cerca de **6 arquivos**, ponta a ponta: model, migration, schema, router
(se mudar a assinatura), `make gen-api`, tela. Se custar muito mais que
isso, é sinal de que a arquitetura foi violada em algum ponto — é o alarme
combinado no ADR-002.

**Entidade nova é diferente e é cara**: fatia vertical inteira, incluindo
permissão e auditoria. Ver [ADR-006](docs/adr/006-admin-so-para-sysadmin.md).

---

## 5. As decisões de arquitetura

Estão em [`docs/adr/`](docs/adr/), um arquivo por decisão, no formato
ADR — contexto, decisão, consequências. **Leia os seis antes de propor
mudança estrutural.** Eles registram não só o que foi escolhido, mas o que
foi descartado e por quê, o que evita reabrir discussão já encerrada.

Resumo, com o que cada um significa no seu dia a dia:

### [ADR-001](docs/adr/001-django-sincrono-com-ninja.md) — Django síncrono com Django Ninja

**Decisão:** Django 5.x **síncrono**, sem nenhuma view `async`, com Django
Ninja para a API em `/api/v1/`.

**Por quê:** o sistema atende dezenas de usuários simultâneos, não
milhares — o custo dominante do projeto é erro humano, não CPU. Código
async cria uma classe de bug que não existe no síncrono (`await`
esquecido, ORM fora do event loop, biblioteca bloqueante) e que quebra
_sob carga_, o pior formato para quem está aprendendo. Ninja em vez de DRF
porque usa type hints e Pydantic, que o time já precisa conhecer, em vez
de um vocabulário próprio (serializers, viewsets, routers).

**No seu dia a dia:** nunca escreva `async def` numa view. O deploy é WSGI
(`gunicorn`) — o projeto **deliberadamente não tem `asgi.py`**.

### [ADR-002](docs/adr/002-model-como-entidade.md) — Model é a entidade de domínio

**Decisão:** a regra de negócio mora no model. `services.py` é opcional e
só para operação atômica que cruza models.

**Por quê:** Repository, Mapper e Unit of Work existem para desacoplar de
um ORM pobre e permitir trocar de banco. O ORM do Django já é repositório
e mapper, e o PostgreSQL não vai ser trocado. O custo dessas camadas é
imediato: campo novo passando por cinco arquivos e ninguém sabendo onde a
regra mora.

**No seu dia a dia:** proibidos Repository, Mapper, Unit of Work, entidade
paralela ao model e Protocols criados por antecipação. Regra de negócio em
router não passa em review.

### [ADR-003](docs/adr/003-sessao-e-csrf-sem-jwt.md) — Sessão do Django, sem JWT

**Decisão:** sessão em cookie `HttpOnly`, CSRF sempre ativo, permissões e
grupos **nativos** do Django. Papel de domínio ("Secretaria",
"Coordenação") é `Group` criado por data migration, não um RBAC próprio.

**Por quê:** JWT resolve origem cruzada e múltiplos consumidores — não é o
caso aqui. Onde há origem única, JWT é _downgrade_: o token fica no
browser (`localStorage` é vulnerável a XSS), não dá para revogar sem
inventar denylist, e a renovação exige um segundo fluxo.

**No seu dia a dia:** toda escrita precisa do header `X-CSRFToken`, e isso
já está resolvido no `client.ts`. Logout revoga de verdade, no servidor.
Admin e API compartilham a mesma sessão.

### [ADR-004](docs/adr/004-origem-unica-sem-cors.md) — Origem única via Nginx, CORS proibido

**Decisão:** front e API sempre atrás do mesmo Nginx, na mesma origem. O
`baseUrl` do cliente é **relativo** (`/api/v1`).

**Por quê:** CORS mal configurado é fonte frequente de brecha e de tempo
perdido. Com cookie de sessão, origem cruzada exigiria `SameSite=None` +
`Secure` + `credentials`, e errar um dos três quebra o login de forma
enigmática.

**No seu dia a dia:** **CORS é proibido** — se você sentiu necessidade de
configurar CORS, o erro está no deploy, não no código. URL absoluta de API
no front não passa em review. E: sempre `:8080`, nunca `:5173`.

### [ADR-005](docs/adr/005-front-estatico-sem-ssr.md) — Front estático, sem SSR e sem Node em produção

**Decisão:** SvelteKit com `adapter-static`, SPA pura, `ssr = false`.
Nenhum processo Node em produção, em nenhuma hipótese.

**Por quê:** `adapter-node` + SSR exigiria um processo Node rodando em
produção — mais um runtime para a infra instalar, supervisionar, atualizar
e incluir no plano de recuperação. O que SSR entrega (SEO, primeiro paint)
não tem valor num sistema atrás de login, interno, em rede boa.

**No seu dia a dia:** toda busca de dado é no browser. Nada de
`+page.server.ts`. Ver a [seção 7](#7-o-vite-em-desenvolvimento-e-em-produção).

### [ADR-006](docs/adr/006-admin-so-para-sysadmin.md) — Admin só para sysadmin

**Decisão:** o Django Admin é ferramenta de operação da plataforma,
restrita a superusuários. Todo usuário de negócio é atendido pelo
frontend.

**Por quê:** este ADR **substitui** uma orientação anterior, e a razão é
instrutiva. O Admin edita campos direto: arquivar uma pessoa lá é trocar
`status` num `<select>` — `Person.archive()` nunca é chamado, e o
invariante que ele protege deixa de existir naquele caminho. Seriam duas
portas para o mesmo dado, uma delas ignorando as regras do model. Somado a
isso, a escrita pelo Admin não gerava `AuditLog`, e a diferença visual
fazia o usuário perceber dois sistemas.

**No seu dia a dia:** a trava é de código — `admin.site.has_permission`
exige `is_superuser`; `is_staff` sozinho não abre a porta. Papel de
domínio nunca recebe `is_staff` nem `is_superuser`. Falta tela para
alguma coisa? O trabalho é escrever a tela, não dar acesso ao Admin —
inclusive quando o prazo aperta. Há um **período de desconforto
deliberado** aqui, e reabrir o Admin "temporariamente" é exatamente o que
o ADR proíbe.

### Como escrever um ADR novo

Copie [`docs/adr/000-template.md`](docs/adr/000-template.md). Contexto são
**fatos, não opiniões**: qual problema apareceu, que restrição existe, o
que já foi tentado. A decisão vai no presente ("usamos X"). Alternativa
séria descartada entra com uma linha dizendo por quê.

---

## 6. Cada comando do Makefile

O `Makefile` é a **fonte da verdade**: comando novo entra lá, não só no
README. `make` sozinho lista todos (é o `.DEFAULT_GOAL`).

Dois atalhos internos que aparecem em todo alvo:

- `$(UV)` = `cd backend && uv run` — roda no ambiente Python do projeto.
- `$(NPM)` = `cd frontend && npm` — roda no frontend.

### Instalação

| Comando            | O que faz                                                                                                                                                                           |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `make ajuda`       | Lista os comandos com a descrição. É o padrão do `make` sem argumento.                                                                                                              |
| `make install`     | `uv sync` no backend. Resolve as dependências Python **e instala o próprio Python** na versão do projeto. Rode depois de todo `git pull` que mexa em `pyproject.toml` ou `uv.lock`. |
| `make install-web` | `npm install` no frontend. Mesma lógica para `package.json`.                                                                                                                        |

### Subir e derrubar

| Comando     | O que faz                                                                                                                                          |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `make db`   | Sobe **só o Postgres** (`docker compose up -d db`). Use com `make run` quando quiser o Django nativo, com reload mais rápido e depurador acoplado. |
| `make up`   | Sobe `db` + `backend` + `nginx`, com `--build`. É o modo normal de trabalho. Termina lembrando de rodar `make web` em outro terminal.              |
| `make down` | `docker compose down`. Derruba os containers e **preserva o volume** — o banco continua lá.                                                        |

Note que `make up` **não sobe o frontend**: ele não é um serviço do
Compose. Ver a [seção 7](#7-o-vite-em-desenvolvimento-e-em-produção).

### Rodar em modo desenvolvimento

| Comando    | O que faz                                                                                                                                                                        |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `make run` | `runserver` do Django **nativo**, fora do container, na 8000. Precisa de `make db` antes. Alternativa ao `backend` do Compose quando você quer depurar com breakpoint no editor. |
| `make web` | `npm run dev` — o servidor do Vite na 5173, com hot reload. **Precisa ficar rodando** enquanto você trabalha no front. Acesse pela 8080, nunca pela 5173.                        |

### Banco de dados

| Comando           | O que faz                                                                                                                                                                                |
| ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `make migrations` | `makemigrations` — gera os arquivos de migração a partir das mudanças nos models. **Leia o arquivo gerado antes de commitar**: o Django às vezes infere algo diferente do que você quis. |
| `make migrate`    | `migrate` — aplica as migrações pendentes no banco.                                                                                                                                      |
| `make superuser`  | `createsuperuser` — cria uma conta de sysadmin, a única que entra no Admin (ADR-006).                                                                                                    |

Em produção a ordem é **migração primeiro, sempre**, e a migração precisa
ser retrocompatível com o código anterior: campo novo entra `null=True` ou
com default.

### A ponte de tipos

| Comando        | O que faz                                                                                                  |
| -------------- | ---------------------------------------------------------------------------------------------------------- |
| `make gen-api` | Exporta o OpenAPI do Django para `frontend/src/lib/api/openapi.json` e gera o `schema.d.ts` a partir dele. |

Rode **sempre que mexer em schema ou em rota**. Sem isso o front continua
tipado contra uma API que mudou, e o erro só aparece em runtime — que é
exatamente o que a geração de tipos existe para evitar.

### Qualidade

| Comando          | O que faz                                                                                                                                           |
| ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `make test`      | `pytest` no backend. **O Postgres precisa estar de pé** (`make db` ou `make up`).                                                                   |
| `make lint`      | `ruff format` + `ruff check --fix` no backend, `npm run format` + `npm run lint` no frontend. Formata **e corrige** o que dá para corrigir sozinho. |
| `make typecheck` | `mypy` no backend e `svelte-check` no frontend.                                                                                                     |
| **`make ready`** | `lint` + `typecheck` + `test`, nessa ordem. **Verde é pré-condição de qualquer commit.**                                                            |

`make ready` é o único que você precisa lembrar antes de commitar — ele
chama os outros três. Se ele estiver vermelho, o commit não sai.

---

## 7. O Vite em desenvolvimento e em produção

Esta é a parte que mais confunde quem chega, então vale a explicação
completa.

### Vite não é "um tipo de Node"

- **Node** é o _runtime_: executa JavaScript fora do navegador. É o
  "python" da analogia.
- **Vite** é um programa escrito em JavaScript que precisa do Node para
  rodar. É o "django" da analogia.

A cadeia completa do nosso front é:

**Svelte** (a linguagem de componente) → **SvelteKit** (o framework de
rotas) → **adapter-static** (a peça que manda o SvelteKit gerar arquivos
parados em vez de um servidor Node) → **Vite** (quem executa a
compilação) → **Node** (quem executa o Vite).

### O Vite faz duas coisas bem diferentes

**1. Servidor de desenvolvimento** — `npm run dev`, ou seja, `make web`.

Fica no ar em `:5173` e serve o código-fonte ao navegador quase sem
transformação, usando módulos ES nativos. Quando você salva um `.svelte`,
ele empurra só aquele módulo para a página já aberta — é o _hot reload_.
Este é o processo Node que precisa ficar vivo enquanto você trabalha.

**2. Empacotador** — `npm run build`.

Roda uma vez, lê todo o `frontend/`, compila os `.svelte` para JavaScript,
junta, minifica e produz uma pasta de `.html`, `.js` e `.css`. Terminou, o
processo morre.

### Em desenvolvimento

O Nginx do Compose faz proxy para o Vite que roda **fora** do Docker:

```nginx
upstream vite { server host.docker.internal:5173; }

location / {
    proxy_pass http://vite;
    # ... cabeçalhos de upgrade para o WebSocket do hot reload
}
```

`host.docker.internal` é como o container alcança a máquina hospedeira — é
para isso que existe o `extra_hosts: host.docker.internal:host-gateway` no
serviço `nginx`.

Daí os dois terminais: um com `make up` (containers), outro com `make web`
(Vite nativo). Sem `make web`, o `location /` bate num upstream morto e a
SPA não carrega — mas `/api/` e `/admin/` continuam funcionando, porque
vão para o `backend`, que é container.

Por que o Vite não é um serviço do Compose: hot reload dentro de container
com bind mount é lento e o _file watching_ costuma falhar em silêncio.
Rodar nativo dá reload instantâneo. O custo é o passo manual, e é por isso
que o próprio `make up` termina imprimindo o lembrete.

### Em produção

**Nenhum processo Node**, em nenhuma hipótese (ADR-005). O front vira
arquivo parado:

```bash
npm run build     # gera os estáticos com o adapter-static
# copiar a saída para o diretório servido pelo Nginx
```

E o `location /` do Nginx troca de proxy para disco — o bloco já está
escrito em comentário no `nginx/nginx.conf`:

```nginx
location / {
    root      /var/www/ppgd;      # saída de `npm run build`
    try_files $uri $uri/ /index.html;
}
```

O `try_files ... /index.html` é o que faz uma SPA funcionar com URL
direta: qualquer caminho desconhecido devolve o `index.html`, e o
roteamento acontece no navegador.

### O quadro comparativo

|                        | Desenvolvimento                   | Produção                                             |
| ---------------------- | --------------------------------- | ---------------------------------------------------- |
| SPA                    | Vite em `:5173`, Nginx faz proxy  | Arquivos estáticos, Nginx serve do disco             |
| Processo Node contínuo | sim (`make web`)                  | **nenhum**                                           |
| Django                 | `runserver` (container ou nativo) | `gunicorn`, WSGI                                     |
| Deploy do front        | —                                 | copiar arquivos; rollback é copiar os anteriores     |
| Deploy do back         | —                                 | `migrate` **primeiro**, depois recarregar o gunicorn |

Não há contradição entre "o front é feito com Vite" e "sem Node em
produção": em produção o Vite é usado no **modo 2**, na sua máquina ou na
esteira de CI. O que vai para o servidor é a pasta de arquivos.

Produção roda, no total, `gunicorn` + `postgres` + `nginx`. É o desenho
que a infra já opera.

> O `docker-compose.yml` deste repositório é **o perfil de desenvolvimento**
> (`db` + `backend` + `nginx`). Não existe compose de produção aqui: a
> infra de produção está descrita na seção 10 do `CLAUDE.md`, a alinhar
> com o time de infra.

---

## 8. Quem entra onde

O Django Admin é ferramenta de **operação da plataforma**: criar programas
novos, ler auditoria e corrigir dado quando o sistema errou. Só
superusuário entra, e a trava é de código, não combinado.

Todo usuário do programa — secretaria, coordenação, docentes, discentes —
é atendido **pelo frontend**. Se falta tela para alguma coisa, o trabalho
é escrever a tela, não dar acesso ao Admin. Ver
[ADR-006](docs/adr/006-admin-so-para-sysadmin.md).

Correção de dado pelo Admin é **quebra-vidro**, não rotina, e é sempre
auditada.

---

## 9. Armadilhas conhecidas

Todas estas já custaram tempo a alguém. Comece por aqui quando algo não
funcionar.

**A tela não carrega, ou o login falha sem motivo aparente.**
Você abriu `:5173`. Use `:8080`.

**A tela não carrega e a 8080 devolve erro de gateway.**
O `make web` não está rodando, ou caiu. O Nginx está fazendo proxy para um
Vite que não existe.

**`/admin` devolve a SPA ou uma página estranha.**
Falta a barra final: `/admin/`.

**Mudei o `nginx.conf` e nada aconteceu.**
O arquivo é montado, mas o Nginx só relê a configuração ao recarregar:

```bash
docker compose up -d --force-recreate nginx
```

**O Postgres não sobe, erro de porta já alocada.**
A 5432 desta máquina costuma estar ocupada por outro projeto. O nosso usa
a **5433** no host (`DB_HOST_PORT` no `.env`); dentro do Compose continua
sendo `db:5432`.

**Trocar a versão _major_ do Postgres quebra o banco.**
O Postgres não lê um data dir criado por outra major. O caminho é
`pg_dump` → remover o volume → subir a nova imagem → restaurar. Nunca só
trocar a tag.

**`ModuleNotFoundError: No module named 'django'` dentro do container.**
O `python` do container é o do sistema; o ambiente do projeto está em
outro lugar. Use `uv run python ...`.

**`make test` falha sem conseguir conectar no banco.**
O Postgres precisa estar de pé: `make db`.

**O TypeScript reclama de um campo que existe na API.**
Você mexeu no schema e não rodou `make gen-api`. O `schema.d.ts` é gerado
— nunca o edite à mão.

**A regra de negócio "não pegou" numa edição feita pelo Admin.**
Comportamento esperado e documentado: o Admin edita campo direto e não
passa pelos métodos do model. É exatamente por isso que ele é restrito a
sysadmin (ADR-006).
