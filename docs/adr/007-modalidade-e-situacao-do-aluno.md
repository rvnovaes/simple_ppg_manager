# ADR-007: Modalidade do vínculo separada da situação do aluno

- **Data**: 2026-08-05
- **Status**: aceito
- **Origem**: `docs/notes/2026-08-05-disciplinas-isoladas-grill.md`
- **Substitui**: a lista única de situação do aluno capturada em
  `docs/notes/2026-08-05-cadastros-professores-alunos-grill.md` (Q8) e
  especificada na primeira versão de `tasks/prd-cadastros-basicos.md`

## Contexto

O primeiro levantamento capturou a situação do aluno como uma lista só:
`REGULAR`, `TRANCADO`, `ISOLADA`, `ELETIVA`, `EXCLUÍDO`. É como a
secretaria fala, então foi assim que entrou no PRD.

Ao detalhar o que são disciplinas isoladas e eletivas, apareceu que essa
lista mistura **duas dimensões diferentes**:

- **Modalidade do vínculo** — regular (de grau), isolada, eletiva. Não
  muda enquanto o vínculo existe.
- **Situação atual** — ativo, trancado, excluído. Muda com o tempo.

Com campo único, o aluno de isolada sai de `ISOLADA` e vira `EXCLUÍDO` ao
fim do semestre, e **nesse instante o sistema esquece que ele era de
isolada**. Um mestrando que abandonou e um aluno de isolada que terminou
normalmente ficam idênticos no banco. A pergunta "quantos alunos de
isolada tivemos em 2026/1?" — que a CAPES pede — deixa de ter resposta.

Dois fatos adicionais do mesmo levantamento reforçam o problema:

1. **O aluno de isolada é excluído ao fim de cada semestre e recebe um
   novo número de matrícula se voltar em outro semestre.** A mesma pessoa
   gera vários registros de aluno ao longo do tempo — o usuário confirmou
   textualmente "mesma pessoa, dois registros de aluno".
2. **A maior parte dos campos de `Student` não se aplica a isolada e
   eletiva.** `level`, `project`, `advisor`, `admission_date`, `deadline`
   e `defense_date` são todos de aluno de grau. Sobravam três de nove.

## Decisão

**1. Dois campos, não um.**

- `modality` — `REGULAR` / `ISOLATED` / `ELECTIVE`
  ("Regular" / "Isolada" / "Eletiva"). Imutável na prática: mudar de
  modalidade é outro vínculo, ou seja, outro registro.
- `status` — `ACTIVE` / `LEAVE` / `EXCLUDED`
  ("Ativo" / "Trancado" / "Excluído"). Muda livremente, sem validação de
  transição (decisão mantida do levantamento anterior); toda troca gera
  `AuditLog`. Única restrição: **`LEAVE` só é válido em
  `modality=REGULAR`** — trancar não se aplica a isolada nem eletiva, que
  duram um semestre e terminam em `EXCLUDED`. Garantido por
  `CheckConstraint`.

`EXCLUDED` deixa de significar só desistência: para isolada é o estado
final normal e esperado ao fim do semestre.

**2. `Student.person` é `ForeignKey`, não `OneToOneField`.**

Uma `Person` tem N registros de aluno ao longo do tempo, cada um com seu
próprio `registration_number`. É o mesmo instinto já registrado em
`Person.user` (`apps/people/models.py`), que é FK justamente para
permitir uma conta ligada a várias pessoas.

`registration_number` continua `unique=True`, mas passa a identificar o
**episódio de vínculo**, não a pessoa.

`Teacher.person` **continua `OneToOneField`** — nada no levantamento
sugere que uma pessoa tenha dois vínculos docentes simultâneos.

**3. Campos de grau passam a ser exigidos por modalidade, no banco.**

`level`, `project`, `admission_date` e `deadline` viram `null=True` no
banco e obrigatórios via `CheckConstraint` condicional quando
`modality=REGULAR`. `advisor` e `defense_date` continuam opcionais, mas
só fazem sentido em `REGULAR`.

Isso troca "às vezes obrigatório, depende de quem preenche" por uma regra
explícita que o banco garante — não só o formulário.

**4. Período letivo vira entidade (`AcademicTerm`).**

"Até duas isoladas por semestre", "excluído ao fim do semestre" e "nova
isolada em outro semestre" só existem se o sistema souber o que é um
semestre. Como texto, o semestre seria digitado em três lugares e
divergiria ("2026/1" vs "2026-1" vs "1/2026"), fazendo a contagem errar
em silêncio.

`AcademicTerm` mora em `apps/programs` e é **institucional — sem FK
`program`**. O calendário 2026/1 é o mesmo da UFMG inteira; mantê-lo por
programa produziria "PPGD 2026/1" e "PPGA 2026/1" divergentes, e a
contagem de "quantas isoladas neste semestre" erraria em silêncio.

Esta é a **única exceção** à decisão 5 abaixo, e é deliberada. A
consequência — `AuditLog` com `program=None` nas escritas de
`AcademicTerm` — é aqui a resposta **correta**, não uma perda: a entidade
não pertence a programa nenhum.

`Student.term` é obrigatório quando `modality` é `ISOLATED` ou
`ELECTIVE`, e nulo em `REGULAR` (aluno de grau atravessa vários
semestres; o recorte dele é `admission_date`/`deadline`).

**5. Todo model de negócio novo carrega a FK `program` diretamente.**

Vale para `CollectiveProject`, `Teacher`, `Student` e para os models do
acerto de matrícula, mesmo quando o programa poderia ser alcançado por
navegação (`person.program`, `research_line.program`). **`AcademicTerm`
é a exceção**, pelo motivo dado na decisão 4. São dois motivos:

- É a regra da Seção 1 do CLAUDE.md, já registrada no docstring de
  `apps/programs/models.py`: adicionar a chave depois, com dados em
  produção, é caro; agora é de graça.
- `apps.core.audit.record()` infere o programa com
  `getattr(target, "program", None)`. Sem a FK direta, **todo `AuditLog`
  desses models gravaria `program=None`** e a trilha de auditoria perderia
  a chave de tenant justamente nos dados de negócio.

A coerência com o pai (`student.program == student.person.program`,
`project.program == project.research_line.program`) é garantida em
`clean()`.

**Atenção de implementação**: o Django **não** chama `clean()` em
`.save()`/`.create()` — só em formulários. O service que cria o registro
precisa chamar `full_clean()` explicitamente, senão o invariante existe
no código e nunca roda no caminho real.

## Consequências

- **A pergunta da CAPES fica respondível.** "Quantos alunos de isolada em
  2026/1" é `Student.objects.filter(modality=ISOLATED, term=...)`, e
  continua respondível depois que todos foram excluídos.
- **A secretaria ganha uma tela nova para manter** — o período letivo, uma
  vez por semestre. Custo aceito explicitamente.
- **Recadastrar quem volta exige buscar a `Person` antes de criar.** A
  `UniqueConstraint (program, primary_email)` de `Person` continua sendo
  o que evita pessoa duplicada; se a tela não oferecer busca por e-mail,
  a secretaria bate na constraint sem entender o que fazer. Vira
  requisito de tela, não de model.
- **`Student` fica com mais campos nulos.** É o preço de uma entidade que
  cobre três modalidades. A alternativa — entidades separadas para
  isolada/eletiva — foi descartada porque o usuário chama todos de
  "aluno", todos consomem número de matrícula da UFMG pelo mesmo caminho,
  e a duplicação de `person`/`registration_number`/`status` apareceria
  em cada uma.
- **A modalidade `ELECTIVE` nasce sem fluxo.** O levantamento da eletiva
  foi adiado explicitamente pelo usuário. O valor existe no enum e as
  regras condicionais valem, mas nenhuma tela ou workflow de eletiva é
  especificado até que essa sessão aconteça.
- **O fluxo de inscrição em isolada não entra aqui.** Auto-registro
  público, upload de documentos (identidade, CPF, diploma, currículo,
  comprovante de endereço, contracheque) e a dimensão de pagamento (GRU,
  com isenção para servidor da UFMG) são um módulo próprio, que precisa
  de PRD e provavelmente de ADR próprio — o auto-registro seria o
  primeiro endpoint público de escrita do projeto e tensiona a Seção 5 do
  CLAUDE.md. Este ADR só prepara o modelo de dados para recebê-lo.
- **Nada disso custa migração de dados**, porque nada foi implementado
  ainda. Descoberto depois do primeiro `migrate` em produção, seria a
  troca de um `OneToOneField` por `ForeignKey` e a quebra de um campo em
  dois, com dados dentro.
