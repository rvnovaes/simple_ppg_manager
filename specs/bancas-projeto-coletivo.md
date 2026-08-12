# Spec — Cadastro de bancas examinadoras por projeto coletivo

Date: 2026-08-12 · Status: **spec fechada, com pontos em aberto marcados**
Origem: sessão `/grill-me` com o usuário (Q1–Q5 respondidas) + leitura dos
editais e das relações nominais publicadas pelo PPGD/UFMG.

---

## 1. Objetivo

Cadastrar, no sistema, a **banca examinadora do processo seletivo** — os 4
docentes que julgam os candidatos de um projeto coletivo num nível (mestrado ou
doutorado) num dado processo seletivo. Hoje esse dado vive num documento que a
secretaria monta à mão e publica em PDF na página do Programa.

**Só cadastro.** Nada de nota, etapa, candidato, classificação ou resultado.

### Escopo desta fatia

Dentro:
- Banca do **edital regular**, pendurada em **projeto coletivo**.
- Composição fixa: presidente + 2 titulares + 1 suplente, todos docentes do programa.
- Identificação por **ano do processo seletivo** (inteiro).
- Tela de cadastro/edição/listagem, endpoints, permissões e auditoria.

Fora (decisões explícitas, não esquecimento):
- **Banca do edital suplementar** — pendura em linha de pesquisa, não em projeto
  coletivo (ver §3). Decisão do usuário: fica para outra fatia.
- Banca de defesa / qualificação / dissertação / tese.
- Banca de Heteroidentificação e Banca de Verificação e Validação (são da UFMG,
  não do PPGD).
- Modelagem de processo seletivo, edital, candidato, inscrição, nota, etapa.
- Declaração de impedimento/suspeição dos examinadores (ver flag F3).

---

## 2. Glossário — "banca" é ambíguo neste domínio

| Termo | O que é | Neste cadastro? |
|---|---|---|
| **Banca Examinadora** | Do PPGD. 3 titulares + 1 suplente. Julga candidatos de um projeto coletivo num nível. | **Sim — é esta.** |
| Banca/Comissão de Heteroidentificação | Da UFMG (Comissão Permanente de Ações Afirmativas e Inclusão). Verifica autodeclaração racial. | Não |
| Banca de Verificação e Validação | Da UFMG. Equipe multiprofissional. Verifica condição de deficiência. | Não |
| Comissão de Processo Seletivo | Instância do Programa citada no edital, distinta da banca. | Não |
| Certame / PS | "Processo Seletivo 2027": publicado em 2026, ingresso em 2027. | É a chave temporal |

---

## 3. Fontes primárias (lidas na íntegra, 2026-08-12)

Página: `https://pos.direito.ufmg.br/processo-seletivo/processo-seletivo-atual/`
(certificado não valida no WebFetch; baixado com `curl -k`).

### 3.1 Editais do PS 2027

- **Edital Regular** — SEI 5294767 / Edital 1539.
- **Edital Suplementar** — SEI 5294775 / Edital 1540.

**Item 5.1 do Regular** (verbatim):
> "Serão designadas bancas examinadoras constituídas por 3 (três) membros
> titulares e 1 (um) membro suplente **para cada projeto coletivo**. O suplente
> somente participará do processo seletivo em caso de impedimento de um dos
> membros titulares."

**Item 4.1 do Suplementar** (verbatim):
> "Serão designadas bancas examinadoras constituídas por 3 (três) membros
> titulares e 1 (um) membro suplente **para cada linha de pesquisa**."

→ O alvo da banca **difere por edital**. É por isso que o suplementar saiu do
escopo: ele não pendura em projeto coletivo.

**Itens 5.2 / 4.2** — os dois editais mandam divulgar "a relação nominal dos
membros titulares e suplentes das bancas examinadoras" na página do Programa, e
no mesmo prazo disponibilizar "as declarações de inexistência de impedimento ou
de suspeição firmadas pelos examinadores, **em função dos candidatos inscritos**".

**Cronograma** — "Divulgação das bancas: **13/08/2026**" (item de cronograma nos
dois editais; no PS2027, é o dia seguinte a esta spec).

### 3.2 A relação nominal publicada — o formato-alvo

Arquivos: `REGULAR-MESTRADO-1.pdf`, `REGULAR-DOUTORADO-1.pdf`,
`BANCAS-SUPLEMENTAR.pdf` (via "Editais Anteriores").

Cabeçalho literal da tabela:

```
LINHA DE PESQUISA | PROJETO COLETIVO | PRESIDENTE DA BANCA | TITULAR 1 | TITULAR 2 | SUPLENTE
```

**É este documento que o cadastro precisa ser capaz de reproduzir.**

### 3.3 O que a evidência provou

1. **Banca é por (projeto coletivo × nível).** Existem dois documentos separados —
   "BANCAS EXAMINADORAS EDITAL REGULAR MESTRADO" e "...DOUTORADO" — e a
   composição **difere** para o mesmo projeto. Verificado no projeto "Direito
   Administrativo: entre a tradição e as tendências contemporâneas": presidente
   no mestrado = Maria Tereza Fonseca Dias; no doutorado = Luciano de Araújo
   Ferraz, com titulares também distintos.
   *(Isto contradiz a leitura literal do item 5.1 e confirma a premissa original
   do usuário.)*
2. **Existe PRESIDENTE DA BANCA.** Os 3 titulares não são intercambiáveis; o
   presidente é coluna nomeada no documento oficial.
3. **Um docente participa de várias bancas.** Fabiano Teodoro de Rezende Lara é
   presidente de duas bancas do mestrado e ainda aparece no doutorado. Não existe
   unicidade de professor por processo seletivo.
4. **Modalidade de concorrência não é eixo da banca.** A tabela não tem coluna de
   cota; a mesma banca julga ampla concorrência e cotistas. Os PDFs "BANCA 6A
   MESTRADO AMPLA CONCORRÊNCIA" / "6A MESTRADO COTAS RACIAIS" são *resultados*
   segmentados, produzidos pela mesma banca.
5. **Sem coluna de instituição** — todos os membros são docentes do programa.
6. A **linha de pesquisa** aparece só como agrupamento visual; é derivável de
   `CollectiveProject.research_line` e não deve ser armazenada na banca.

### 3.4 Volume (Anexo II do Regular, PS2027)

**6 linhas de pesquisa**, **~36 projetos coletivos** (códigos `1-A`..`1-F`,
`2-A`..`2-H`, `3-A`..`3-H`, `4-A`..`4-H`, `5-A`..`5-F`, `6-B`..`6-E`).

Com nível como eixo: **até ~72 bancas por processo seletivo**, ~288 vínculos de
docente. Isso é o argumento de projeto de tela: cadastro precisa ser rápido e em
lote-visual, não um wizard de vários passos.

Observado na página: retificação real excluindo o projeto coletivo
"4E – Justiça: teoria e realidade" com realocação de vagas para
"4F – Macrofilosofia do Estado de Direito". **Editais são retificados no meio do
processo** — a banca de um projeto extinto precisa sobreviver como histórico.

---

## 4. Decisões tomadas (Q1–Q5)

| # | Pergunta | Decisão | Observação |
|---|---|---|---|
| Q1 | Banca de seleção ou de defesa? | **Seleção** | Confirmado pelo usuário |
| Q2 | Perene ou por certame? | **Por certame**, com histórico preservado | |
| Q3 | Certame = semestre ou ano? | **Ano, inteiro** (ex. `2027`) | Recomendei FK `AcademicTerm`; usuário escolheu inteiro |
| Q4 | Alvo duplo (projeto × linha)? | **Só o edital regular**, FK obrigatória para projeto coletivo | Recomendei duas FKs + constraint; usuário escolheu reduzir escopo |
| Q5 | Composição: through-model ou FKs? | **Quatro FKs diretas** no `Board` | Sem model `BoardMember` |

### Preços aceitos explicitamente

- **Q3** — passam a existir duas noções de tempo no sistema (o `AcademicTerm` do
  calendário letivo e o ano do certame), sem nada que as amarre. Mitigação: o
  rótulo na tela é **"ano do processo seletivo"**, nunca "ano" solto — senão
  alguém digita 2026, o ano da publicação, em vez de 2027.
- **Q4** — na divulgação, a secretaria cadastra ~72 bancas no sistema e resolve as
  do suplementar fora dele.
- **Q5** — "de quais bancas o professor X participa" vira um `Q()` de quatro
  ramos (escrito uma vez num método de manager); e substituir um membro
  sobrescreve a coluna: o histórico da troca fica só no `AuditLog`.

---

## 5. Modelo de dados

Um model, em `backend/apps/academic/models.py` (onde já vivem `Teacher` e
`Student`). **Nenhum app novo, nenhum through-model, nenhum `services.py`** — a
escrita toca um model só, então o router chama o manager direto (CLAUDE.md §3.3).

```python
class BoardQuerySet(models.QuerySet):
    def for_program(self, program) -> "BoardQuerySet":
        return self.filter(program=program)

    def for_year(self, year: int) -> "BoardQuerySet":
        return self.filter(selection_year=year)

    def with_teacher(self, teacher) -> "BoardQuerySet":
        # Q5: o preço das quatro FKs, pago uma vez e só aqui.
        return self.filter(
            Q(president=teacher)
            | Q(member_1=teacher)
            | Q(member_2=teacher)
            | Q(alternate=teacher)
        )


class Board(models.Model):
    """Banca examinadora do processo seletivo, edital regular.

    Uma banca por (projeto coletivo, nível, ano do processo seletivo) — não
    por projeto apenas: a relação nominal publicada pelo PPGD traz mestrado e
    doutorado em documentos separados, com composições diferentes para o mesmo
    projeto.

    Os quatro papéis são colunas, e não linhas de um through-model, porque o
    3+1 é norma do edital (item 5.1) e não configuração: banca com cinco
    membros ou com dois presidentes não deve ter onde ser gravada.
    """

    class Level(models.TextChoices):
        MASTERS = "masters", "Mestrado"
        DOCTORATE = "doctorate", "Doutorado"

    program = models.ForeignKey(
        "programs.Program", on_delete=models.PROTECT,
        related_name="boards", verbose_name="programa",
    )
    project = models.ForeignKey(
        "programs.CollectiveProject", on_delete=models.PROTECT,
        related_name="boards", verbose_name="projeto coletivo",
    )
    level = models.CharField("nível", max_length=20, choices=Level)
    # Ano do PROCESSO SELETIVO (o PS2027 é publicado em 2026) — Q3.
    selection_year = models.PositiveSmallIntegerField("ano do processo seletivo")

    president = models.ForeignKey(
        "academic.Teacher", on_delete=models.PROTECT,
        related_name="boards_as_president", verbose_name="presidente da banca",
    )
    member_1 = models.ForeignKey(
        "academic.Teacher", on_delete=models.PROTECT,
        related_name="boards_as_member_1", verbose_name="titular 1",
    )
    member_2 = models.ForeignKey(
        "academic.Teacher", on_delete=models.PROTECT,
        related_name="boards_as_member_2", verbose_name="titular 2",
    )
    alternate = models.ForeignKey(
        "academic.Teacher", on_delete=models.PROTECT,
        related_name="boards_as_alternate", verbose_name="suplente",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = BoardQuerySet.as_manager()

    class Meta:
        verbose_name = "banca examinadora"
        verbose_name_plural = "bancas examinadoras"
        ordering = ["-selection_year", "project__name", "level"]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "level", "selection_year"],
                name="unique_banca_por_projeto_nivel_e_ano",
            ),
        ]
```

`on_delete=PROTECT` em tudo, como no resto do projeto: professor
descredenciado continua sendo quem julgou aquela seleção.

### Invariantes (métodos do model, testáveis sem banco)

1. **Os quatro membros são distintos.** É o único invariante que as FKs não
   garantem sozinhas. `DomainError(code="duplicate_board_member")`.
2. **`program` bate com `project.program`** — mesmo `clean()` que
   `CollectiveProject` e `Teacher` já fazem (ADR-007 dec. 5, senão o `AuditLog`
   grava a chave de tenant errada). `code="program_mismatch"`.
3. **Todo membro é `Teacher` do mesmo programa.** `code="teacher_from_other_program"`.
4. **Todo membro está credenciado** (`Teacher.is_accredited`) no momento do
   cadastro — ver flag F1, que pode rebaixar isto a aviso.
5. **Unicidade (projeto, nível, ano)** — garantida pela `UniqueConstraint`, e
   validada também no `clean()` para virar 400 com `code` estável
   (`duplicate_board`) em vez de `IntegrityError` → 500. É o padrão que
   `AcademicTerm.clean()` já usa neste repositório.

---

## 6. API

`backend/apps/academic/router.py` e `schemas.py`. Padrão obrigatório de toda
rota: `require_perm` na primeira linha, `current_program` logo depois, chamada ao
model, schema de saída explícito, `audit.record()` dentro do mesmo
`transaction.atomic()`.

| Método | Rota | Permissão | Auditoria |
|---|---|---|---|
| GET | `/api/v1/academic/boards/` | `academic.view_board` | — |
| GET | `/api/v1/academic/boards/{id}/` | `academic.view_board` | — |
| POST | `/api/v1/academic/boards/` | `academic.add_board` | `academic.board.create` |
| PATCH | `/api/v1/academic/boards/{id}/` | `academic.change_board` | `academic.board.update` |
| DELETE | `/api/v1/academic/boards/{id}/` | `academic.delete_board` | `academic.board.delete` |

- Listagem escopa por `current_program(request)` e aceita filtros
  `?selection_year=`, `?level=`, `?project=`, `?teacher=` (este último usa
  `with_teacher`).
- `BoardOut` traz os quatro membros **expandidos** (id + nome da pessoa) e o
  projeto expandido (id, nome e a linha de pesquisa) — a tela precisa reproduzir
  a tabela publicada, e sem expansão seriam 5 requisições por linha.
- Permissões nativas do Django (`add_board` etc. saem do model). Grupo que as
  recebe: **Secretaria** e **Coordenação**, por data migration — ver flag F4.
- **DELETE**: ver flag F2 (apagar de verdade × desativar).

---

## 7. Tela

Rota SvelteKit: `frontend/src/routes/(app)/bancas/+page.svelte`, no padrão de
`professores` e `disciplinas`. Svelte 5 com runas; toda chamada por
`lib/api/client.ts`; `npm run gen:api` depois do backend de pé.

- **Listagem** agrupada exatamente como o PDF publicado: linha de pesquisa →
  projeto coletivo → presidente / titular 1 / titular 2 / suplente. Filtro por
  ano do processo seletivo e por nível no topo, com o ano corrente pré-selecionado.
- **Cadastro/edição** numa linha só: projeto, nível, ano e quatro `<select>` de
  docente. Com ~72 bancas por processo seletivo, um wizard de vários passos
  inviabiliza a operação — a secretaria preenche isso num dia.
- Os `<select>` de docente listam **docentes credenciados do programa**, ordenados
  por nome (`Teacher.objects.for_program(...)`), e a validação de UX barra membro
  repetido antes de mandar. A validação que vale continua sendo a do backend.
- Rótulo do campo de ano: **"ano do processo seletivo"** (mitigação da Q3).

---

## 8. Fatia vertical — arquivos tocados

1. `backend/apps/academic/models.py` — `Board` + `BoardQuerySet`.
2. `backend/apps/academic/migrations/` — **human gate** (CLAUDE.md).
3. `backend/apps/academic/schemas.py` — `BoardIn`, `BoardOut`, `BoardPatch`.
4. `backend/apps/academic/router.py` — as 5 rotas.
5. `backend/apps/academic/admin.py` — leitura/correção quebra-vidro.
6. `backend/apps/academic/tests/test_boards.py` — invariantes no model (sem
   banco) + fluxo pela API.
7. Data migration de permissões nos grupos Secretaria/Coordenação — **human
   gate** (§Human gates, item 4).
8. `frontend/src/lib/api/schema.d.ts` + `openapi.json` — **gerados**, via
   `make gen-api`. Nunca editar à mão.
9. `frontend/src/routes/(app)/bancas/+page.svelte`.
10. Item de menu no layout do app.

`make ready` verde é pré-condição do commit.

---

## 9. Pontos em aberto

O grill foi encerrado pelo usuário na Q5. Estes ficaram sem decisão explícita;
cada um tem um default recomendado, seguro o bastante para implementar, e
**nenhum deles bloqueia o início do trabalho**.

| # | Questão | Default recomendado | Quem decide |
|---|---|---|---|
| **F1** | Membro precisa estar **credenciado**? E se for descredenciado depois de já compor uma banca? | Exigir credenciamento **na criação**; não revalidar depois — banca de 2026 com docente descredenciado em 2027 continua válida, é história. | Usuário / secretaria |
| **F2** | DELETE apaga mesmo ou desativa? | O projeto tem o hábito de nunca apagar (`Teacher.deaccredit`, `Discipline.is_active`). Mas banca cadastrada errada antes da divulgação é lixo, não história. **Default: DELETE real enquanto não divulgada; depois, só edição auditada.** Depende de F3. | Usuário |
| **F3** | Existe estado **"divulgada"**? O edital tem data de divulgação (13/08) e exige declaração de impedimento no mesmo prazo. | Fora desta fatia — cadastro é cadastro. Mas se a secretaria quiser travar edição pós-divulgação, isso é um campo `published_on` e uma transição, e muda F2. | Usuário |
| **F4** | Quais grupos recebem as permissões? | Secretaria e Coordenação. Precisa confirmar se docente pode *ver* as bancas. | Coordenação |
| **F5** | `CollectiveProject` **não tem campo de código** (`1-B`, `4-F`), mas o edital e a secretaria falam por código. | Adicionar `code` a `CollectiveProject` é fatia própria e mexe em model já em uso. Nesta tela, exibir só o nome. | Usuário |
| **F6** | Exportar a relação nominal (o PDF que hoje é feito à mão)? | Fora do escopo. É o próximo passo óbvio depois do cadastro, e vale como história separada. | Usuário |
| **F7** | Declaração de impedimento/suspeição dos examinadores (itens 5.2 / 4.2) | Fora do escopo. Envolve upload de documento e vínculo com candidato inscrito — nada disso existe no sistema. | Usuário |
| **F8** | Banca do **edital suplementar** (por linha de pesquisa) | Fatia futura. A modelagem já foi discutida: duas FKs nuláveis + `CheckConstraint` amarrada ao tipo de edital, ou model separado. | Usuário |

---

## 10. Q&A log da sessão

### Q1 — banca de seleção x banca de defesa
- Asked: a banca julga candidatos de processo seletivo, ou é banca de
  qualificação/dissertação/tese de aluno matriculado?
- **Captured: BANCA DE SELEÇÃO** ("banca de seleção, sim").
- Recomendação minha: seleção. Confirmada.

### Achado de código (fato levantado, não perguntado)
- O único "edital" modelado hoje é `IsolatedEnrollmentCycle` = edital de
  **disciplina isolada**. As rotas `/editais` e `/classificacao` do front são de
  isolada.
- **Não existe** model de processo seletivo de mestrado/doutorado, nem
  `Candidate`, nem inscrição de candidato regular. A banca não tem processo
  seletivo para pendurar; pendura no projeto coletivo + ano.
- `AcademicTerm` existe, é institucional (sem FK `program`, ADR-007 dec. 4),
  `ano + semestre`, rótulo canônico `"2026/1"`.

### Q2 — perene x por certame
- Asked: o projeto tem "sua" banca (editar substitui), ou cada certame tem a sua,
  com histórico?
- **Captured: POR CERTAME.**

### Q3 — granularidade do certame
- Asked: FK `AcademicTerm` de ingresso (a); inteiro "ano do certame" (b);
  semestre em que a banca trabalha (c)?
- **Captured: (b), ano inteiro.** Recomendei (a); usuário escolheu (b).
- Preço aceito: duas noções de tempo no sistema, sem amarra.
- Validação posterior pela fonte: o PS2027 é publicado em 2026 — o rótulo do
  campo precisa dizer "ano do processo seletivo".

### Q4 — alvo duplo (projeto coletivo x linha de pesquisa)
- Contexto: descoberto nos editais que regular pendura em projeto coletivo e
  suplementar em linha de pesquisa.
- Asked: um model com duas FKs nuláveis + `CheckConstraint` (a); dois models (b);
  só o regular nesta fatia (c)?
- **Captured: (c), só o regular.** Recomendei (a); usuário escolheu (c).
- Consequência: `Board.project` é FK obrigatória e única; não existe campo
  `kind` regular/suplementar no model.

### Q5 — composição
- Asked: through-model `BoardMember` com `role` (a), ou quatro FKs diretas (b)?
- **Captured: (b), quatro FKs.** `president`, `member_1`, `member_2`, `alternate`.
  **Não haverá `BoardMember`.**
- Preço aceito: consulta por professor vira `Q()` de quatro ramos; substituição de
  membro sobrescreve, e o rastro fica no `AuditLog`.

### Encerramento
Sessão encerrada pelo usuário após a Q5 ("vamos encerrar o grill e escreve as
specs na pasta"). As questões que ficariam nas rodadas seguintes estão em §9 com
default recomendado.
