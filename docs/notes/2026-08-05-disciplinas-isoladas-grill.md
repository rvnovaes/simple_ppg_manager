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
*TL;DR consolidado ao fim da sessão. Escopo validado: **apenas ISOLADA**.
A modalidade ELETIVA foi adiada explicitamente pelo usuário (Q10).*

**As duas modalidades**
- **Isolada**: pessoa **sem vínculo com a UFMG**. O protocolo oficial
  exige *não ser aluno de Graduação nem de Pós-graduação da UFMG*. Chega
  sem número de registro; a UFMG gera um **a cada semestre** que ela
  cursa.
- **Eletiva**: aluno da UFMG **de outro curso ou programa** — já tem
  número de registro. Populações mutuamente exclusivas. **Fluxo não
  levantado.**

**Decisões de modelagem**
1. **`Student.person` é `ForeignKey`, não `OneToOneField`** (Q3). A mesma
   pessoa que faz isolada em dois semestres gera **dois vínculos**, cada
   um com seu próprio `registration_number`. ⚠️ Corrige erro em
   `tasks/prd-cadastros-basicos.md` (US-004).
2. **Dois campos, não um** (Q5): `modality` (Regular / Isolada / Eletiva —
   não muda) e `status` (Ativo / Trancado / Excluído — muda). Um campo só
   apagaria a informação de que alguém era de isolada assim que virasse
   Excluído. ⚠️ Substitui a lista única do grill anterior.
3. **`project`, `level`, `deadline`, `advisor`, `defense_date` só são
   exigidos quando `modality=Regular`** — regra explícita e checável
   (candidata a `CheckConstraint` condicional), não "às vezes
   obrigatório". `TRANCADO` idem: só para Regular.
4. **Período letivo é entidade** (Q4), **global da instituição, sem FK de
   programa** — exceção consciente ao padrão multi-tenant, a declarar no
   ADR.
5. **Oferta de disciplina no período** (Q13, Q25): disciplina × período ×
   **nº de vagas** × **docente responsável**.
6. **Uma inscrição por pessoa por período, com 1 ou 2 disciplinas**
   (Q17). Documentação anexada uma vez, **uma GRU** para as duas (Q18).

**O fluxo (todo dentro do sistema)**
Candidato se auto-registra e se inscreve (janela de **um único dia**) →
anexa documentação → **docente responsável classifica os candidatos da sua
disciplina em ordem de prioridade** → secretaria defere/indefere dentro do
limite de vagas → publica lista → **recurso** (secretaria julga, aceita
documento faltante, **não** derruba a classificação docente, **não**
dispensa a GRU) → deferido paga GRU pelo link da UFMG e **envia o
comprovante pelo próprio login** → secretaria lança a matrícula na UFMG e
preenche o número → fim do semestre, **secretaria encerra o período** e os
vínculos viram Excluídos.

**Regras duras**
- **Sem classificação do docente, ninguém é matriculado** naquela
  disciplina. Portão absoluto, sem caminho alternativo (Q27).
- Deferimento é **por classificação docente**, não por ordem de chegada.
  Documentação incompleta desclassifica e **a vaga passa ao próximo da
  lista**.
- **Servidor da UFMG é isento** da GRU mediante **contracheque +
  autorização da chefia**.
- Taxa **nunca** é devolvida.

**Cortes deliberados**
- **Sem SMTP / sem notificação por e-mail** (Q9) — a pessoa descobre o
  resultado voltando ao sistema. É isso que torna a conta própria (Q8)
  estrutural, e não conveniência.
- **Sem agendador de tarefas** (Q15, Q23) — nada expira sozinho; a
  secretaria cancela inscrição e encerra período manualmente.
- **Sem nota, frequência ou aprovação** (Q16) — desempenho é da UFMG.
- **Sem geração de GRU nem conciliação financeira** (Q12) — o sistema
  guarda o link, o estado (pendente/pago/isento) e o comprovante.
- **Documentos guardados indefinidamente** (Q27), visíveis **só pela
  Secretaria**. Decisão explícita do usuário; declarar no ADR.

**Papéis**
Candidato (auto-registro, papel novo) · **Docente** (classifica) ·
**Secretaria** (defere, julga recurso, lança matrícula, encerra período) ·
**Coordenação** (só leitura, sem papel ativo neste módulo).

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

### Q12 — a GRU entra no sistema, e em que momento?
- Asked: pagamento antes ou depois do deferimento? A secretaria precisa
  acompanhar quem pagou dentro do nosso sistema?
- Captured: o pagamento vem **depois**. Sequência nas palavras do usuário:
  *"depois que a secretaria valida a documentação e a quantidade de vagas
  disponíveis para a disciplina. A UFMG gera um link específico para
  pagamento de GRU em disciplina isolada. Uma vez pago, o comprovante
  deverá ser enviado pelo login do aluno."*
- Fatos novos:
  - **VAGAS**: a secretaria valida "a quantidade de vagas disponíveis
    **para a disciplina**". Existe capacidade por disciplina — peça nova,
    não prevista em nenhum PRD. -> Q13.
  - **A GRU é gerada pela UFMG**, não pelo nosso sistema — é um **link
    específico** para pagamento de GRU em disciplina isolada. Confirma a
    recomendação de o sistema não gerar nem conciliar pagamento.
  - **O comprovante é enviado pelo próprio aluno, pelo login dele.** Isso
    torna a decisão da Q8 (conta própria) **estrutural, não conveniência**:
    sem conta, não há como a pessoa enviar o comprovante depois. Registrar
    isso no ADR como a justificativa mais forte da Q8.
- **Máquina de estados da inscrição em isolada** (derivada, confirmar na
  Q14):
  1. pessoa se inscreve e anexa documentação
  2. secretaria valida documentação **e vagas** → defere ou indefere
  3. (se não isento) UFMG gera link de GRU → pessoa paga
  4. pessoa envia o comprovante **pelo login dela**
  5. secretaria envia pra UFMG → UFMG gera número de matrícula
  6. secretaria preenche o número → vínculo de aluno criado
  7. fim do semestre → excluído
  Ramo de isenção: servidor da UFMG (contracheque anexado) pula os passos
  3 e 4.
- Flags: onde fica o link da GRU? (a secretaria cola no sistema para a
  pessoa ver ao logar?) -> a confirmar.

### Q13 — o sistema guarda quantas vagas cada disciplina tem?
- Asked: as vagas moram no nosso sistema (por disciplina e por período) ou
  a secretaria consulta fora?
- Captured: **"guardar as vagas no sistema"** — confirmado.
- Consequência: **entra a entidade "oferta de disciplina no período"**
  (`DisciplineOffering` ou similar): disciplina × período letivo × número
  de vagas. É a mesma entidade que eu tinha conseguido evitar na Q7 —
  agora ela entra por outro caminho, e com justificativa própria.
  Não implica (ainda) em ter professor responsável pela oferta: isso
  continua fora, porque ninguém aprova por disciplina (Q7).
- Regra de negócio que o sistema passa a poder checar sozinho: **não
  deferir inscrição além do número de vagas da oferta**. Candidata a
  invariante em método do model (padrão ADR-002), não só aviso de tela.
- Justificativa registrada: a secretaria já vai estar dentro do sistema
  deferindo uma a uma; se o número de vagas estivesse numa planilha à
  parte, ela conferiria manualmente a cada deferimento — e é aí que se
  defere a mais. Com o número aqui, a tela mostra "3 de 5 vagas ocupadas"
  no momento da decisão.
- Flags: contagem de vaga ocupada — conta a partir do **deferimento** ou
  só quando a matrícula se completa (número da UFMG preenchido)? Importa
  porque entre um e outro a pessoa pode não pagar a GRU e a vaga ficaria
  presa. -> a confirmar.

### Q14 — quando a vaga conta como ocupada, e o que a libera?
- Asked: vaga ocupada a partir do deferimento ou da matrícula concluída?
  Existe prazo formal de pagamento que o sistema deva fazer valer?
- Captured: o usuário **reafirmou a sequência** em vez de responder o caso
  de borda, e a sequência confirma o que já estava registrado:
  *"o aluno pede a isolada e envia os documentos. a secretaria verifica a
  documentação e as vagas e defere se estiver ok. Depois o aluno paga a
  GRU"*.
  Ou seja: a **checagem de vagas é pré-condição do deferimento** — a
  secretaria confere vagas *antes* de deferir. Isso sustenta contar a vaga
  como ocupada **no deferimento** (senão a conferência que ela faz não
  significaria nada para o próximo deferimento).
- Flags: continua **em aberto** o caso de borda — o que acontece com a
  vaga se a pessoa é deferida e nunca paga a GRU. -> Q15.

### Q15 — deferida mas nunca paga: o que libera a vaga?
- Asked: a secretaria cancela manualmente (devolvendo a vaga), ou existe
  prazo formal que o sistema deva aplicar sozinho?
- Captured: **"basta isso, sem prazo automático"** — confirmado. A
  secretaria tem uma ação de **cancelar a inscrição**, que devolve a vaga.
  **Nenhuma expiração automática**, nenhum prazo de pagamento aplicado
  pelo sistema.
- Consequência: **não entra agendador de tarefas** (Celery/cron/qdispatch)
  no projeto por causa disso. Mantém a stack como está — decisão alinhada
  com a Seção 2 do CLAUDE.md (menos peças móveis). Registrar no ADR
  explicitamente, porque "expira sozinho depois de X dias" é exatamente o
  tipo de requisito que reaparece depois e arrasta infraestrutura nova.
- Estado novo na máquina: **CANCELADA** (pela secretaria), distinta de
  INDEFERIDA (recusada na análise da documentação/vagas).

### Q16 — o sistema registra o resultado da disciplina?
- Asked: nota/frequência/aprovação da isolada ficam no nosso sistema ou só
  na UFMG?
- Captured: **"fica só na UFMG"** — confirmado. O PPGD Manager **não**
  registra nota, frequência nem aprovação.
- Consequência: o vínculo de isolada no nosso sistema é um registro de
  **inscrição e matrícula**, não de **desempenho**. Mantém a regra que já
  vale para o aluno regular: desempenho acadêmico é da UFMG, fonte única.
- Contrapartida aceita conscientemente: quando essa pessoa depois prestar
  o processo seletivo, o sistema saberá **que** ela cursou isolada e
  **quais** disciplinas pediu, mas não se foi aprovada — a secretaria
  consulta a UFMG se precisar.

### Q17 — uma inscrição com duas disciplinas, ou duas inscrições?
- Asked: uma inscrição carregando até 2 disciplinas, ou uma inscrição por
  disciplina? E a GRU é uma por inscrição ou uma por disciplina?
- Captured: **"uma inscrição com duas disciplinas"** — confirmado.
  Uma inscrição por pessoa por período, carregando 1 ou 2 disciplinas,
  com a documentação anexada **uma vez**, deferida de uma vez.
  Mesmo desenho do acerto de matrícula: um pedido com N itens.
- Justificativa registrada: a documentação é **da pessoa**, não da
  disciplina — pedir os mesmos quatro documentos duas vezes seria
  retrabalho para ela e para a secretaria conferir. A checagem de vagas
  continua funcionando porque é por disciplina: uma inscrição com duas
  disciplinas consome uma vaga em **cada** oferta.
- Regra derivada: **limite de 2 itens por inscrição**, e uma inscrição
  ativa por pessoa por período. Invariante candidato a método do model.
- Flags: **a pergunta sobre a GRU (uma por inscrição ou uma por
  disciplina) NÃO foi respondida** -> Q18.

### Q18 — a GRU é uma por inscrição ou uma por disciplina?
- Asked: pessoa com duas isoladas paga uma guia ou duas?
- Captured: **"a gru é uma por inscrição que dá direito de fazer duas
  disciplinas"** — confirmado. **Uma GRU por inscrição**, cobrindo até as
  duas disciplinas.
- Consequência de modelagem: o estado de pagamento (**pendente / pago /
  isento**) e o **comprovante** são atributos da **inscrição**, não do
  item de disciplina. O item de disciplina carrega só qual disciplina e a
  vaga que ele consome. Não existe o caso "paga numa disciplina e
  pendente na outra".
- Reforça a decisão da Q17: a inscrição é a unidade de tudo — uma
  documentação, um deferimento, uma GRU, um comprovante.

### Q19–Q22 — quatro pontos menores (perguntados em bloco)
- **Link da GRU**: fica **registrado no sistema**. Ao deferir, a secretaria
  cola o link gerado pela UFMG; a pessoa loga, vê "deferida" e o link para
  pagar. É o que fecha o ciclo sem e-mail, já que SMTP ficou fora (Q9).
  → campo de URL na inscrição, preenchido no deferimento.
- **Acesso aos documentos**: **só a Secretaria** pode visualizar/baixar os
  arquivos anexados. A Coordenação vê a inscrição e seu status, mas **não
  abre os arquivos** — menor exposição de dado sensível (LGPD).
  → permissão separada para download de documento, não basta `view` da
  inscrição.
- **TRANCADO**: **não se aplica** a isolada, só a aluno **Regular**.
  Isolada dura um semestre e termina em Excluído. → as situações válidas
  são restritas por modalidade; candidato à mesma `CheckConstraint`
  condicional da Q5.
- **Período letivo**: **global da instituição, sem FK de programa** — o
  calendário 2026/1 é o mesmo da UFMG inteira. Evita "PPGD 2026/1" e
  "PPGA 2026/1" duplicados. **Exceção consciente ao padrão multi-tenant**
  do resto do sistema (todo dado de negócio carrega FK de programa,
  Seção 1 do CLAUDE.md) — registrar essa exceção explicitamente no ADR,
  com este motivo, senão parece descuido em revisão futura.

### Q23 — quem marca o aluno de isolada como excluído no fim do semestre?
- Asked: derivar do fim do período letivo (calculado), ou a secretaria
  encerra explicitamente?
- Captured: **"secretaria encerra o semestre"** — confirmado. Existe uma
  ação explícita de **encerrar o período letivo**, que marca como
  Excluídos todos os vínculos de isolada daquele período de uma vez.
- Consequência: `situação` continua sendo **dado digitado, não calculado**
  — coerente com o resto do sistema e mais óbvio para quem for mexer no
  código depois. O preço aceito é que, se a secretaria esquecer de
  encerrar, o sistema mostra como ativo quem já terminou.
- É uma operação **multi-model / em lote** (encerra o período e atualiza N
  vínculos) → é caso legítimo de `services.py` com `transaction.atomic()`,
  pelo critério da Seção 3 do CLAUDE.md, e precisa de `AuditLog` próprio
  (um evento de encerramento, não N eventos soltos).

### Q24 — janela de inscrição + PROTOCOLO OFICIAL fornecido pelo usuário
- Asked: existe janela de inscrição? algo que não tocamos?
- Captured: o usuário colou o **protocolo oficial de requerimento de
  isoladas do PPGD** (edital vigente, datas de agosto/2026). Este é o
  documento de referência da sessão — **vale mais que minhas inferências
  anteriores**. Conteúdo integral extraído abaixo.

#### Exigências (critérios de elegibilidade)
1. **Existência de vaga** (há lista publicada de disciplinas com nº de vagas).
2. **NÃO ser aluno de curso de Graduação ou de Pós-graduação da UFMG.**
   → regra de elegibilidade dura, repetida em destaque no protocolo:
   *"Alunos com vínculo em cursos (Graduação e Pós-graduação) da UFMG não
   poderão solicitar matrícula em disciplina isolada."* Confirma que
   ISOLADA e ELETIVA são populações **mutuamente exclusivas**.
3. **Autorização do professor responsável pela disciplina**, ou
   recomendação do orientador, no caso de pós-graduando de programa
   *stricto sensu* **externo à UFMG**.

#### Documentos (lista oficial — corrige e refina a Q11)
1. cópia simples de documento de identificação **e CPF** (passaporte com
   visto válido, **se estrangeiro**);
2. cópia de **diploma de graduação OU certidão de conclusão**;
3. **currículo Lattes em PDF** (não "currículo" genérico);
4. comprovante de endereço;
5. no caso de servidor da UFMG: cópia de contracheque **E AUTORIZAÇÃO DA
   CHEFIA** ← a Q11 tinha capturado só o contracheque. São **dois**
   documentos.

#### Recomendação docente — CORRIGE A Q7
O protocolo diz: *"para aprovação da matrícula é necessária a recomendação
do professor responsável pela disciplina (esta recomendação será feita em
formulário próprio, enviado pelo respectivo professor ou professora à
Secretaria do PPGD, com indicação de **ordem decrescente de prioridade** a
ser considerada dentro do limite de vagas disponíveis. Cabe à **pessoa
interessada entrar em contato com o docente** solicitando sua inclusão
nesse formulário)."*
- O docente **participa**, ao contrário do que a Q7 concluiu. A Q7 não
  está errada no essencial — **quem defere é a secretaria** —, mas a
  recomendação docente é **insumo obrigatório** da decisão.
- **Existe "professor responsável pela disciplina"** — a entidade que eu
  tinha declarado desnecessária na Q7 e que já havia voltado pela Q13
  (oferta com vagas). Agora está confirmada por duas vias.
- **O deferimento NÃO é por ordem de chegada**: é por **ordem de
  prioridade definida pelo professor**, dentro do limite de vagas. Isso
  invalida a lógica simples de "vaga ocupada no deferimento" da Q14 —
  existe uma **classificação**.
- O formulário do docente hoje é **externo ao sistema** (o professor envia
  à Secretaria). O contato do docente está na seção Docentes do site, e é
  **a pessoa candidata** que corre atrás do docente.

#### Lista de espera / desclassificação
*"O candidato que não apresentar a documentação completa será
desclassificado, sendo a **vaga transferida para o próximo da lista**."*
→ Existe **lista classificada com repasse de vaga**. Não capturado antes.

#### RECURSO — etapa inteira não capturada
Existe **interposição de recurso**, com link próprio, e uma **lista de
deferidos após recurso**. Nenhuma pergunta desta sessão tocou nisso.

#### Agenda oficial (2026/2 — datas reais)
| Etapa | Data |
|---|---|
| Protocolo / envio de documentos | **10/08/2026, exclusivamente neste dia, até 23:59** |
| Análise dos documentos pelo PPGD | 10 a 11/08/2026 |
| Listagem de requerimentos DEFERIDOS | 11/08/2026 |
| Interposição de recurso | 12/08/2026 (link próprio) |
| Listagem de DEFERIDOS APÓS RECURSO / resultado final | 13/08/2026 |
| Envio do comprovante da GRU | 13/08 até 23:59 de 16/08/2026 |

→ A janela de inscrição é de **UM ÚNICO DIA**. Confirma a Q24: janela
existe, é rígida e curta, e o sistema tem que fazê-la valer.
→ **Inconsistência no próprio protocolo**: o texto corrido diz *"Até o dia
12 de agosto será divulgada a lista dos aprovados que poderão pagar a
GRU"*, mas a agenda diz deferidos em 11/08 e resultado final em 13/08.
Não é erro meu de leitura — é divergência do documento. -> confirmar com
a secretaria qual data vale.

#### Acesso por PROTOCOLO — CONFLITA COM A Q8
*"deverá enviar no sistema de inscrições (**com acesso pelo protocolo
recebido no ato da inscrição**) o comprovante de pagamento"*.
→ Hoje o acesso de retorno é por **número de protocolo**, não por conta
com login. A Q8 decidiu "conta própria". Não é necessariamente
contradição — pode ser mudança deliberada de processo —, mas **precisa
ser decisão consciente**, não descuido. -> Q25.

#### Outros pontos do protocolo
- **Uma taxa para até duas disciplinas** — confirma exatamente a Q17/Q18.
- **GRU só deve ser paga após a publicação do deferimento**; o protocolo
  alerta em destaque para conferir antes de pagar.
- **Taxa nunca é devolvida**, em nenhuma hipótese.
- *"a matrícula será lançada pela própria Secretaria, com base nas
  informações contidas nos documentos apresentados"* — confirma a Q12.
- **Servidor da UFMG é isento** mediante cópia do **último** contracheque.
- Sem comprovante de pagamento, **a secretaria não efetiva a matrícula**.

### Q25 — o formulário de recomendação do professor entra no sistema?
- Asked: o docente ordena a prioridade dentro do sistema, ou continua em
  formulário externo com a secretaria digitando a classificação?
- Captured: **"dentro do sistema"** — confirmado. O professor responsável
  pela disciplina passa a **ver os requerimentos da disciplina dele e
  ordenar a prioridade na tela**.
- Consequências (grandes, registrar no ADR):
  - **Entra a relação "professor responsável pela oferta"** —
    definitivamente. A oferta de disciplina no período (Q13) precisa saber
    **quem é o docente responsável**, senão não há como mostrar a ele os
    requerimentos que lhe cabem.
  - **Entra um terceiro papel ativo no fluxo**: candidato → **docente
    (classifica)** → secretaria (defere). O fluxo deixa de ter dois atores
    (Q7) e passa a ter três.
  - Precisa de um modelo de **classificação/prioridade** por oferta: a
    ordem que o docente define entre os candidatos daquela disciplina.
  - Risco operacional aceito conscientemente: a janela é de **um dia**
    (protocolo) e a análise ocorre em 24–48h — depende de os docentes
    entrarem no sistema nesse prazo. Se não entrarem, a secretaria precisa
    de um caminho alternativo. -> flag.
  - **A pessoa candidata continua tendo que procurar o docente por fora**
    (o protocolo diz que cabe a ela solicitar sua inclusão) — o sistema
    não substitui esse contato, só o registro da classificação.

### Q26 — como funciona o recurso?
- Asked: quem julga? o que pode ser contestado? pode juntar documento novo?
- Captured (palavras do usuário): *"a secretaria analisa os motivos do
  aluno, aprecia documentos faltantes mas o que importa é a recomendação
  do professor. Não pode abrir mão do pagamento da GRU e envio"*.
- Decompondo:
  1. **Quem julga: a SECRETARIA** — não a coordenação. Minha recomendação
     de escalar para a coordenação estava errada; a coordenação **continua
     sem papel ativo** em todo este módulo (só leitura).
  2. **Pode juntar documento novo**: sim — a secretaria "aprecia
     documentos faltantes". O recurso é, na prática, a **segunda chance de
     completar a documentação**.
  3. **A recomendação do professor é DECISIVA e não é recorrível.**
     *"o que importa é a recomendação do professor"* — o recurso conserta
     documentação, **não** derruba a classificação docente. Quem ficou
     fora por ordem de prioridade não entra por recurso.
  4. **O recurso não dispensa a GRU**: mesmo deferido em recurso, a pessoa
     **paga e envia o comprovante** dentro do prazo, como todo mundo.
- Consequência de modelagem: o recurso é uma **reabertura da mesma
  inscrição** para anexar documento e argumentar, e não um objeto novo com
  vida própria — o resultado dele é apenas mudar o estado da inscrição de
  Indeferida para Deferida (ou manter). O estado final continua sendo o da
  inscrição.
- Reforça a Q25: se a recomendação docente é o que decide e não é
  recorrível, ela **tem** que estar no sistema e ser auditável — é o ponto
  de maior consequência de todo o fluxo.

### Q27 — recurso no sistema, retenção de documentos, docente ausente
- Asked: (1) o recurso é feito no sistema? (2) por quanto tempo os
  documentos ficam guardados? (3) o que acontece se o docente não
  classificar no prazo?
- Captured:
  1. **"o recurso é no sistema"** — confirmado. O recurso é feito dentro
     do PPGD Manager, não por link externo separado. Consolida: inscrição,
     classificação docente, deferimento, recurso, comprovante de GRU —
     tudo no mesmo sistema.
  2. **"os documentos ficam para sempre no sistema"** — decisão explícita
     do usuário, tomada **depois** de eu levantar a implicação de LGPD.
     Não é omissão nem default: é escolha. **Retenção indefinida** de
     identidade, CPF, diploma, comprovante de endereço e contracheque,
     inclusive de quem nunca virou aluno. → O ADR deve **declarar isso por
     escrito**, junto com a restrição de acesso já decidida (só
     Secretaria abre os arquivos), para que a política seja explícita e
     defensável, e não implícita.
  3. **"se o professor não enviar a lista ninguém será matriculado"** —
     regra dura e sem exceção. A recomendação docente é um **portão
     absoluto**: sem ela, **nenhum** requerimento daquela disciplina é
     deferido. Não existe caminho alternativo, não existe a secretaria
     classificar no lugar do docente, não existe deferir sem
     classificação.
     → Consequência de produto: o sistema deve **avisar com destaque** a
     secretaria sobre ofertas sem classificação enquanto a janela está
     aberta, porque o custo do silêncio é a disciplina inteira ficar sem
     ninguém matriculado. É a informação mais crítica da tela dela.
     → Fecha a flag "e se o docente não classificar" — a resposta é que o
     processo simplesmente não anda, por desenho.

## Open flags (pending input)
*Revisado ao fim da sessão — só o que continua realmente em aberto.*

1. **Conta própria × número de protocolo** — a Q8 decidiu auto-registro
   com conta, mas o protocolo oficial descreve o processo atual como
   acesso *"pelo protocolo recebido no ato da inscrição"*. Levantei o
   conflito, mas a pergunta acabou não sendo respondida (a resposta
   seguinte tratou do formulário docente). **Precisa de decisão
   consciente**: manter a conta (e mudar o processo) ou reproduzir o
   protocolo. -> usuário.
2. **ELETIVA: fluxo inteiro em aberto** — adiado explicitamente na Q10.
   Sabe-se só que é aluno da UFMG de outro curso/programa, que já tem
   número de registro, e que é população mutuamente exclusiva da isolada.
   Não levantado: passa pela secretaria? tem limite? paga GRU? é excluída
   ao fim do semestre? precisa de recomendação docente?
   -> próxima sessão de grill.
3. **Divergência de datas dentro do próprio protocolo** — o texto corrido
   diz que a lista de aprovados sai até 12/08; a agenda diz deferidos em
   11/08 e resultado final em 13/08. -> confirmar com a secretaria qual
   vale.
4. **Em qual app mora o período letivo** — decidido que é global (sem FK
   de programa), mas não em que app. Recomendação a fazer: `programs`,
   junto de Program/ResearchLine/Discipline. -> baixa relevância, decidir
   ao escrever o ADR.
5. **Como a pessoa candidata encontra o docente** — o protocolo diz que
   cabe a ela procurá-lo, e o contato está na seção Docentes do site. Se
   a classificação passa a ser no sistema (Q25), esse contato prévio
   continua por fora? Vale checar se o fluxo novo não deixa a pessoa sem
   saber que precisa falar com o professor. -> usuário.

## Ações decorrentes (fora desta sessão)
- ⚠️ **Corrigir `tasks/prd-cadastros-basicos.md`** (já commitado, não
  implementado): `Student.person` deve ser `ForeignKey`, não
  `OneToOneField` (Q3); separar `modality` de `status` (Q5); tornar
  `project`/`level`/`deadline`/`advisor` condicionais à modalidade
  Regular. Enquanto não corrigir, `ralph/prd.json` está com o desenho
  errado.
- **Escrever o ADR-007** com as decisões desta sessão.
- **Requisito de UX para o PRD revisado**: a tela de cadastro de aluno
  precisa **buscar `Person` existente por e-mail** antes de criar uma
  nova, senão a secretaria bate na `UniqueConstraint (program,
  primary_email)` ao recadastrar quem volta em outro semestre (Q3).
