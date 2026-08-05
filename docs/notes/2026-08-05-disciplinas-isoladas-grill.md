# Disciplinas Isoladas e Eletivas — Grill / Discovery Notes
Date: 2026-08-05 · Goal: entender o que são matrícula em disciplina isolada
e eletiva no PPGD, e decidir onde essas pessoas moram no modelo de dados —
insumo para o ADR-007.

## Contexto já estabelecido (não perguntar de novo)
- Já existem ADR-001 a ADR-006 em `docs/adr/`. Este será o **ADR-007**.
- Dois PRDs já escritos e commitados: `tasks/prd-cadastros-basicos.md` e
  `tasks/prd-matricula.md`. **Nada implementado ainda** — corrigir o
  desenho agora é de graça.
- `Student.status` foi definido pelo usuário como: REGULAR, TRANCADO,
  ISOLADA, ELETIVA, EXCLUÍDO. Ou seja, no modelo mental do usuário
  isolada/eletiva aparecem como **status de aluno**, na mesma lista.
- Detalhe do grill anterior: "matrícula" em disciplinas é feita e mantida
  no sistema da UFMG; o PPGD Manager só trata o *acerto* (ajuste)
  pós-matrícula.

## Conflito estrutural identificado (a razão de existir este ADR)
O `Student` especificado em `tasks/prd-cadastros-basicos.md` tem três
campos que **não fazem sentido** para aluno de isolada/eletiva:
- `project` — FK **obrigatória** para projeto coletivo
- `level` — mestrado ou doutorado, obrigatório
- `admission_date` + `deadline` — prazo regimental de 24/48 meses
Também não se aplicam: `advisor`, `defense_date`.
Ou seja: ~6 dos 9 campos de `Student` não valem para essa população. Isso
é o sinal clássico de que talvez não seja a mesma entidade — mas o usuário
os chama de "aluno" e os colocou como status de `Student`. É essa tensão
que o ADR-007 tem que resolver.

## Summary / key decisions
- **Disciplina eletiva**: cursada por **aluno da UFMG de outro curso ou
  programa**. Logo, essa pessoa **tem** número de registro (o do curso
  dela, gerado pela UFMG).
- **Disciplina isolada**: cursada por **"um aluno sem número de
  registro"** (palavras do usuário). É o traço distintivo entre as duas.

## Q&A log

### Q1 — definições de eletiva vs isolada (confirmação)
- Asked: "isolada" é pessoa de fora do programa/universidade cursando
  disciplina avulsa da pós, e "eletiva" é aluno regular de outro programa
  da UFMG cursando disciplina daqui?
- Captured: CONFIRMADO pelo usuário, com a distinção precisa nas palavras
  dele: *"disciplina eletiva é de alunos da UFMG de outros cursos ou
  programa. A isolada é um aluno sem número de registro."*
  Consequência: o número de registro é o discriminador entre os dois
  casos — eletiva tem, isolada não tem.
- Flags: nenhum.

### Q2 — a pessoa de isolada existe no sistema da UFMG?
- Asked: como isolada não tem número de registro, a UFMG não tem onde
  guardar essa pessoa, e o PPGD Manager seria o único registro dela?
- Captured: **ERRADO — corrigido pelo usuário.** O ciclo real é:
  1. A secretaria **envia para a UFMG** os alunos de isolada.
  2. A UFMG **gera um número de matrícula** para eles. (Ou seja: eles
     TÊM número de matrícula — o que não têm é número *antes* de a
     secretaria enviar. A frase "aluno sem número de registro" da Q1 se
     refere ao estado de entrada, não ao estado final.)
  3. O aluno pode cursar **até duas disciplinas isoladas por semestre**.
  4. **Ao final do semestre ele é excluído.**
  5. Se cursar nova isolada em **outro semestre**, ele **ganha outro
     número de matrícula** (novo, diferente do anterior).
- Consequências estruturais (importantes):
  - **`Student.person` NÃO pode ser `OneToOneField`.** O PRD
    `tasks/prd-cadastros-basicos.md` (US-004) especifica OneToOne — está
    ERRADO. A mesma pessoa que faz isolada em dois semestres diferentes
    gera **dois registros de aluno**, cada um com seu próprio número de
    matrícula. Tem que ser `ForeignKey`. (O projeto já tem esse mesmo
    instinto documentado em `Person.user`, que é FK e não OneToOne
    justamente para permitir 1 conta ↔ N pessoas.)
  - `registration_number` com `unique=True` continua correto (cada número
    é único), mas deixa de ser identificador estável da *pessoa* — é
    identificador do *episódio* de vínculo.
  - **Aparece uma entidade de semestre/período que não existe em nenhum
    PRD ainda.** "duas por semestre", "excluído ao final do semestre" e
    "nova isolada em outro semestre" todos dependem de o sistema saber o
    que é um semestre.
  - **`EXCLUÍDO` não é só desistência.** Para isolada é o **estado final
    normal e esperado**, ao fim de cada semestre. Isso reenquadra a lista
    de status capturada no grill anterior.
  - O pipeline "secretaria envia pra UFMG → UFMG gera número → secretaria
    preenche" é **o mesmo** já descrito para aluno regular vindo do
    processo seletivo (grill anterior, Q14). É um padrão recorrente, não
    um caso especial.
  - Regra de negócio concreta e testável: **máximo 2 disciplinas isoladas
    por semestre** por aluno.
- Flags: nenhum.

### Q3 — a pessoa é reconhecida quando volta em outro semestre?
- Asked: mesma pessoa com dois registros de aluno (um por semestre), ou
  cadastro do zero a cada semestre sem ligação com o anterior?
- Captured: **"mesma pessoa, dois registros de aluno"** — confirmado.
  Sela a decisão: `Student.person` é `ForeignKey`, não `OneToOneField`.
  Uma `Person` tem N registros de aluno ao longo do tempo; cada registro
  carrega seu próprio `registration_number`.
- Consequência: dá de graça a resposta para "quem já cursou isolada aqui
  antes?", que interessa quando essa pessoa depois presta o processo
  seletivo (módulo futuro).
- Flags: a `UniqueConstraint` em `(program, primary_email)` de `Person`
  (já existente no código, `apps/people/models.py`) continua sendo o que
  evita pessoa duplicada — a secretaria precisa **encontrar** a pessoa
  existente ao recadastrar, senão vai bater na constraint e não vai saber
  o que fazer. Isso é requisito de TELA (busca por e-mail antes de criar),
  não de model.

### Q4 — semestre como entidade ou como texto?
- Asked: criar entidade de período letivo (2026/1, com início e fim), ou
  guardar o semestre como texto no registro do aluno?
- Captured: **"mais uma entidade é melhor"** — confirmado. Criar entidade
  de **período letivo** (`AcademicTerm` ou similar), com data de início e
  fim, escolhida de lista. Aceito o custo da tela a mais para a secretaria
  manter o período a cada semestre.
- Justificativa registrada: semestre como texto seria digitado em três
  lugares diferentes (limite de isoladas, exclusão ao fim do semestre,
  acerto de matrícula) e divergiria ("2026/1" vs "2026-1" vs "1/2026"),
  fazendo a contagem de "quantas isoladas neste semestre" errar em
  silêncio.
- Flags: definir em que app o período letivo mora (provavelmente
  `programs`, junto de Program/ResearchLine/Discipline — é estrutura, não
  pessoa) e se é global ou por programa.

### Q5 — "isolada" é situação ou modalidade? (o coração do ADR-007)
- Asked: a lista REGULAR/TRANCADO/ISOLADA/ELETIVA/EXCLUÍDO mistura duas
  dimensões (modalidade do vínculo × situação atual) — separar em dois
  campos?
- Captured: **"separa em dois campos"** — confirmado. Decisão:
  - **`modality`** (modalidade do vínculo, não muda enquanto o vínculo
    existe): Regular (de grau) / Isolada / Eletiva.
  - **`status`** (situação atual, muda com o tempo): Ativo / Trancado /
    Excluído.
- Argumento que fechou a decisão (registrar no ADR): com campo único, o
  aluno de isolada sai de `ISOLADA` e vira `EXCLUÍDO` ao fim do semestre —
  e nesse instante **o sistema esquece que ele era de isolada**. Um
  mestrando que abandonou e um aluno de isolada que terminou normalmente
  ficariam idênticos no banco (ambos `EXCLUÍDO`), e a pergunta "quantos
  alunos de isolada tivemos em 2026/1?" deixaria de ter resposta — número
  que a CAPES pede.
- Consequência que resolve o conflito estrutural desta sessão: `project`,
  `level`, `admission_date`/`deadline` (e `advisor`, `defense_date`)
  passam a ser exigidos **só quando `modality=Regular`**. Deixa de ser
  "às vezes obrigatório" e vira regra explícita e checável — candidata a
  `CheckConstraint` condicional no banco, não só validação de formulário.
- Substitui: a lista de status única capturada no grill anterior
  (`docs/notes/2026-08-05-cadastros-professores-alunos-grill.md`, Q8).
  Aquela entrada está **superada** por esta.
- Flags: mapear TRANCADO — faz sentido para modalidade Isolada/Eletiva, ou
  só para Regular? (provavelmente só Regular)

### Q6 — como a pessoa de isolada chega até a secretaria?
- Asked: (1) ela mesma se inscreve no nosso sistema, escolhe até duas
  disciplinas e alguém aprova antes de a secretaria enviar pra UFMG; ou
  (2) a secretaria digita direto o que chegou por e-mail/presencialmente?
- Captured: **opção 1** — confirmado. Existe **fluxo de inscrição** no
  nosso sistema: a própria pessoa se inscreve, informa seus dados, escolhe
  as disciplinas, e há uma etapa de **aprovação** antes de a secretaria
  enviar pra UFMG.
- Consequência: "matrícula em isoladas" **não é um cadastro, é um
  workflow** — mesmo desenho do acerto de matrícula (pedido → aprovação →
  ação da secretaria). Precisa de tela pública ou semipública (a pessoa
  ainda não é aluna e provavelmente não tem conta no sistema quando se
  inscreve — ver flag abaixo).
- Consequência de dados: o sistema **passa a registrar quais disciplinas**
  a pessoa de isolada cursa (Student × Discipline × Período). Isso é
  assimétrico em relação ao aluno regular, cujas disciplinas ficam só na
  UFMG — e a assimetria se justifica porque aqui o pedido nasce no nosso
  sistema, antes de a UFMG saber que essa pessoa existe.
- Flags: **quem aprova a inscrição de isolada?** (coordenação? professor
  da disciplina? secretaria?) -> Q7. **Como a pessoa acessa a tela sem ter
  conta?** -> a definir (inscrição pública sem login vs criar conta).

### Q7 — quem aprova a inscrição em isolada?
- Asked: coordenação (simples, sem dado novo) ou professor da disciplina
  (exige saber quem ministra cada disciplina em cada semestre)?
- Captured: **"a secretaria que defere"** — nem coordenação nem professor.
  A própria **secretaria defere** a inscrição.
- Consequência: o fluxo é mais curto do que o acerto de matrícula — tem
  **dois atores, não três**: pessoa se inscreve → secretaria defere (ou
  indefere) → secretaria envia pra UFMG e preenche o número de matrícula.
  Não há etapa de aprovação por docente ou coordenação.
- Consequência boa: **não precisa** da entidade "oferta de disciplina por
  semestre com professor responsável". Fica fora do escopo, como eu tinha
  recomendado, mas por um motivo ainda mais forte.
- Nota de vocabulário do usuário: ele usa **"deferir"/"indeferir"**, não
  "aprovar/recusar". Usar esse vocabulário nas telas e nos nomes dos
  estados — é o termo que a secretaria reconhece.
- Flags: nenhum.

### Q8 — como a pessoa acessa se ainda não é aluna nem tem conta?
- Asked: formulário público sem login, ou a pessoa cria conta e se
  inscreve logada?
- Captured: **"conta própria"** — confirmado. A pessoa **cria uma conta**
  (auto-registro) e se inscreve autenticada.
- Argumento que fechou (registrar no ADR): decorre da Q3. Se ela volta em
  outro semestre, ou se depois presta o processo seletivo e vira aluna
  regular, a conta já existe e o histórico se liga naturalmente, em vez de
  virar três cadastros soltos com o mesmo e-mail.
- Consequência arquitetural relevante para o ADR: isto cria a **primeira
  funcionalidade do sistema acessível a alguém que não é usuário interno**.
  Até aqui todo endpoint pressupõe sessão de usuário do programa
  (Seção 5 do CLAUDE.md). Precisa de:
  - endpoint de **auto-registro** (público, sem sessão) — o único endpoint
    público de escrita do projeto; exige justificativa explícita e
    proteção contra abuso (rate limit / anti-robô).
  - um **papel novo** para essa pessoa (ex.: "Candidato" ou "Externo"),
    com permissão apenas de criar/ver a própria inscrição — nunca
    `is_staff`, nunca papel de negócio interno.
  - o vínculo `Person.user` (FK já existente) é o que liga a conta à
    pessoa quando a secretaria defere.
- Flags: confirmação de e-mail -> Q9.
- Verificado no código (não perguntar): `backend/config/settings/base.py`
  **não tem nenhuma configuração de e-mail** (sem `EMAIL_BACKEND`, sem
  SMTP) e **nenhum throttling/rate limit**. `MEDIA_ROOT`/`MEDIA_URL`
  existem, então upload de arquivo é possível se a inscrição precisar de
  documento.

### Q9 — auto-registro exige confirmação de e-mail?
- Asked: exigir confirmação (e portanto adicionar SMTP, dependência de
  infra nova) ou não?
- Captured: **"sem smtp por agora"** — confirmado. Nenhum envio de e-mail
  nesta versão; sem confirmação de e-mail no auto-registro.
- Argumento registrado: quem faz o papel de porteiro é a **secretaria**,
  que defere/indefere olhando os dados. Conta com e-mail falso é
  simplesmente indeferida — a confirmação de e-mail resolveria um problema
  que o deferimento manual já resolve, ao custo de uma dependência nova.
- Consequência: a pessoa **descobre o resultado voltando ao sistema** (é a
  decisão da Q8, de ter conta, que sustenta este corte). Não há
  notificação ativa de deferimento/indeferimento.
- Flags: se algum dia entrar notificação por e-mail, é ADR próprio +
  alinhamento com infra (relay, variável de ambiente, quem opera).

### Q10 — a eletiva segue o mesmo fluxo da isolada?
- Asked: eletiva segue o mesmo fluxo, mas sem a etapa de pedir número à
  UFMG (já tem o do curso dela), também excluída ao fim do semestre e
  também com limite de disciplinas?
- Captured: **NÃO RESPONDIDO — "vamos falar das eletivas depois".** O
  usuário adiou deliberadamente. Toda a modelagem desta sessão está
  validada **apenas para ISOLADA**.
- Flags: a modalidade ELETIVA fica com o desenho em aberto. O campo
  `modality` já prevê o valor (decisão da Q5, que é válida), mas o *fluxo*
  da eletiva não foi levantado. Não implementar eletiva no primeiro corte
  além do valor do enum.

### Q11 — o que a inscrição precisa conter para a secretaria deferir?
- Asked: conteúdo mínimo do formulário; precisa de upload de documento?
- Captured: **precisa anexar documentação.** Lista exata do usuário:
  1. **identidade e CPF**
  2. **cópia do diploma de graduação**
  3. **currículo**
  4. **comprovante de endereço**
  5. **se for servidor da UFMG: cópia do contracheque**, "pq fica isento
     da GRU"
- **DIMENSÃO NOVA — pagamento (GRU).** Existe uma **GRU** (Guia de
  Recolhimento da União) associada à inscrição em isolada: é uma taxa.
  **Servidor da UFMG é isento**, e comprova essa condição anexando o
  contracheque. Nenhum módulo anterior tocou em pagamento — isso é
  território novo no sistema e precisa entrar no ADR. -> Q12.
- Consequências de modelagem:
  - Precisa de **upload de arquivo** (4 ou 5 documentos por inscrição).
    `MEDIA_ROOT`/`MEDIA_URL` já existem em `base.py`, mas backup e
    retenção de arquivo passam a ser assunto com a infra.
  - Provavelmente um model de **documento da inscrição** (tipo + arquivo),
    em vez de N `FileField` fixos — porque a lista de tipos muda (o
    contracheque é condicional) e vai crescer com o processo seletivo, que
    também pede documentos (grill anterior, Q14).
  - **Tensão com decisão anterior sobre LGPD**: no grill anterior (Q11) o
    CPF foi deliberadamente deixado **fora** de escopo para evitar dado
    sensível sem uso. Agora a inscrição em isolada exige anexar identidade
    e CPF — o que é *mais* sensível que um campo de CPF, porque é imagem de
    documento. Não é contradição (documento anexado ≠ campo indexado), mas
    o ADR precisa dizer explicitamente quem pode ver esses arquivos e por
    quanto tempo eles ficam guardados.
- Flags: retenção/descarte dos documentos após o semestre (LGPD) -> a
  definir. Quem pode baixar o documento (só secretaria?) -> a definir.

## Open flags (pending input)
- Retenção e descarte dos documentos anexados após o fim do semestre
  (LGPD) -> a definir com o time; não é decisão técnica isolada.
- Quem pode visualizar/baixar os documentos anexados (só Secretaria?
  Coordenação também?) -> a confirmar.
- **ELETIVA: fluxo inteiro em aberto** (usuário adiou explicitamente na
  Q10). Sabe-se só que é aluno da UFMG de outro curso/programa e que
  portanto já tem número de matrícula. Perguntas não feitas: passa pela
  secretaria? limite de disciplinas? excluída ao fim do semestre?
  -> próxima sessão de grill.
- `TRANCADO` se aplica a Isolada/Eletiva ou só a Regular? -> a confirmar.
- App e escopo do período letivo (global da instituição ou por programa?)
  -> a decidir; recomendação a fazer.
- Tela de cadastro de aluno precisa buscar `Person` existente por e-mail
  antes de criar uma nova, senão a secretaria bate na UniqueConstraint de
  `(program, primary_email)` ao recadastrar quem volta -> requisito de UX
  a incluir no PRD revisado.
