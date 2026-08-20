# Processo Seletivo — Grill / Discovery Notes
Date: 2026-08-20 · Goal: extrair a spec completa do módulo de processo
seletivo do PPGD, insumo para `plans/processo-seletivo.md` (sessão nova
em plan mode). O grill extrai; não redige o plano.

## Glossário
- **KPG** = apelido deste próprio sistema (PPGD Manager).
- **DRCA** = Departamento de Registro e Controle Acadêmico da UFMG; emite o
  número de matrícula, recebe a documentação do aprovado em ofícios de 5 nomes.
- **Comissão do processo seletivo** = ator distinto da banca; julga recurso de
  inscrição e decide redistribuição de vagas.
- **Banca** = examinadores de um (edital × nível × projeto coletivo); lançam
  nota, assinam as atas, julgam recurso de etapa.

## Contexto já estabelecido (lido do repositório — NÃO perguntar de novo)

- **Stack e arquitetura**: `CLAUDE.md`. Django 5 LTS + Ninja + Postgres,
  SvelteKit `adapter-static`, origem única no Nginx. Model = entidade,
  regra de negócio em método de model, `services.py` só quando a
  operação cruza vários models. Admin só para sysadmin — toda tela de
  usuário de negócio é Svelte.
- **Multi-tenant por `Program`**: todo model de negócio carrega FK
  `program` direta (ADR-007). Exceção única: `AcademicTerm` (período
  letivo é institucional, da UFMG inteira).
- **Já implementado** em `backend/apps/`: `people` (`Person`),
  `programs` (`Program`, `ResearchLine`, `CollectiveProject`,
  `Discipline`, `AcademicTerm`), `academic` (`Teacher`, `Student`,
  acerto de matrícula, e o ciclo completo de **disciplinas isoladas**:
  `IsolatedEnrollmentCycle`, `DisciplineOffering`,
  `IsolatedEnrollmentRequest`, `IsolatedEnrollmentItem`,
  `RequestDocument`), `accounts`, `audit`, `core`.
- **Módulos anteriores levantados**: cadastros básicos
  (`tasks/prd-cadastros-basicos.md`), acerto de matrícula
  (`tasks/prd-matricula.md`), isoladas (`tasks/prd-isoladas.md` +
  `docs/notes/2026-08-05-disciplinas-isoladas-grill.md`).
- **Padrão herdado de isoladas** (candidato pode reaproveitar): auto-registro
  do candidato, janela de inscrição, anexo de documento (`RequestDocument`,
  `FileField` em `backend/media/`), decisão da secretaria, recurso,
  comprovante de GRU enviado pelo próprio candidato, e a regra de que o
  sistema **não** manda e-mail e **não** tem agendador (nada expira sozinho).
- **Human gates** que este módulo vai tocar (`CLAUDE.md`): decisão sobre a
  vida acadêmica de alguém, regra de classificação e contagem de vaga,
  migrations, contrato de API publicado.
- **Erro de schema conhecido e já corrigido no código**: `Student.person`
  é FK (não OneToOne) — a mesma pessoa gera vários vínculos ao longo do
  tempo.
- **Processo seletivo NÃO existe no código.** Nenhum model, rota ou PRD.
  Partimos do zero.

## Summary / key decisions

TL;DR autossuficiente — a sessão de plano lê **isto**, não a conversa.

### O objeto
- **Dois editais por safra**, publicados em **junho**: **Regular** (mestrado +
  doutorado) e **Suplementar** (mestrado + doutorado). São editais distintos,
  não um com anexo, e **estanques entre si**: nada transborda de um para o outro.
- **Vaga = (edital × nível × projeto coletivo × categoria).** O **projeto
  coletivo** é a unidade de vaga; ele pertence a uma linha de pesquisa. Ambos já
  existem no código (`apps/programs`), e **não devem ser recriados**.
- **Cotas**: Regular → **raciais**, ao lado da ampla concorrência. Suplementar →
  **só cota** (PCD, quilombola, trans/travesti, indígena), **cada categoria com
  contagem separada**.
- **Aritmética da vaga** ⚠️ *human gate*: no Regular o cotista **disputa a ampla
  primeiro** e só consome reserva se não classificar; **reserva ociosa reverte
  para a ampla do mesmo edital**. No Suplementar **não há ampla**, e vaga não
  preenchida **fica vazia** — não volta para o Regular.
- **Redistribuição de vagas** ⚠️ *human gate*: existe, **só dentro do mesmo
  projeto coletivo, entre níveis, nos dois sentidos**, por **decisão da comissão
  do processo seletivo registrada no sistema** — nunca automática. **A vaga muda
  de nível; o candidato não.** Por isso **não há lista de espera**.

### O funil
- **Etapas sucessivas e eliminatórias, corte fixo em 70** por etapa. A lista de
  etapas é **dado por edital**, não código:
  - **Regular**: resumo expandido → prova oral (ponto sorteado entre 10, com a
    respectiva bibliografia) → entrevista sobre o projeto.
  - **Suplementar**: memorial → prova oral → análise do projeto e do memorial.
- **A nota final é a nota da ÚLTIMA etapa.** Não há média, soma nem peso. As
  notas anteriores são guardadas mesmo assim — o **desempate** as usa.
- **Desempate (Regular)**: nota do resumo expandido → nota da prova oral →
  **mais velho ganha**.
- **Nota fracionária, sem arredondamento** → `DecimalField` (nº de casas em
  aberto). `FloatField` é proibido pelo `CLAUDE.md`.

### A inversão de fluxo — a razão de existir do módulo
- **Hoje**: a banca produz um PDF assinado por etapa e a **secretaria transcreve
  as notas à mão**.
- **O que se quer**: *"inverter o fluxo — as bancas lançam as notas por etapa e
  o sistema gera a ata"*, com assinatura digital no próprio sistema.
- **A ata é chaveada por (edital × nível × projeto coletivo × etapa)** e é
  entidade de primeira classe.
- **A ata assinada é o que FECHA a etapa** e promove quem passou. Nota lançada é
  rascunho até lá.
- **Banca = 3 membros**, a mesma nas três etapas, **podendo incluir externo**.
  **Os três assinam** — assinatura pendente trava o funil.
- **Assinatura eletrônica simples** (login + registro de quem/quando + hash),
  **sem ICP-Brasil/GOV.BR**. O **externo assina por link com token enviado por
  e-mail**, sem login, e tem cadastro no sistema para participar do projeto
  coletivo.
- **A ata em PDF é o ÚNICO documento que o sistema gera.** Dependência de PDF
  aprovada pelo usuário → **ADR**.

### O candidato — sem login
- **Não há área do candidato.** Um **formulário público** recebe dados e
  documentos e devolve um **protocolo**. Difere de isoladas, onde o candidato
  autentica.
- **Uma inscrição = um nível + um projeto coletivo.** Sem 1ª e 2ª opção. **A
  mesma pessoa pode se inscrever nos dois editais** ao mesmo tempo — o unique
  constraint é por edital, nunca por pessoa/safra.
- **Há taxa de inscrição (GRU)**: o comprovante é anexado e **conferido à mão**;
  o sistema **não gera GRU nem faz conciliação financeira** (igual isoladas).
- **Documentos**: diploma/certificado · identidade · Lattes · **resumo
  expandido** (Regular) ou **memorial** (Suplementar) · comprovante de GRU ·
  autodeclaração/laudo quando cotista. **Sem histórico escolar.**
- **A secretaria homologa**, por conferência documental.

### Divulgação e comunicação
- **Publicação é manual, no WordPress do PPGD.** O sistema **não** monta
  documento de divulgação e **não** tem página pública de resultado.
  Homologação, resultado de etapa e resultado final saem por lá — e o
  **resultado publicado mostra a nota**.
- **O sistema envia UM tipo de e-mail: a convocação para cada etapa.** Decisão
  explícita do usuário, contra a recomendação de manter o corte de SMTP das
  isoladas. **A secretaria clica**, o envio é **em lote**, com **modelo
  cadastrado**, e o horário é **da sessão — único para todos** (não há agenda
  por candidato). Sem fila e sem agendador.

### O edital no sistema
- **A secretaria cria o edital**: vagas por nível/projeto coletivo/cota, **janela
  de inscrição**, **datas das três etapas** (conhecidas desde a publicação) e o
  **PDF do edital anexado**.

### A saída
- **A secretaria converte o aprovado em `Student` dentro do sistema** ⚠️ *human
  gate*. O **orientador é escolhido depois**, fora deste módulo.
- Fora do sistema: documentação vai ao **DRCA** em **ofício com 5 nomes**, em
  pacotes; o **número de matrícula é emitido pelo DRCA e digitado de volta** no
  sistema pela secretaria — mesmo padrão das isoladas.

### Precedência
Onde este arquivo divergir de `specs/bancas-projeto-coletivo.md`, **vence o que
estiver fundamentado no edital** — aquela spec cita os editais do PS2027
verbatim. Ver a seção "Interseção", logo abaixo.

### Escopo cortado nesta rodada
- **Recursos inteiros → fase 2** (decisão do usuário). Mas a ata precisa nascer
  **versionável** agora, senão a fase 2 custa migration destrutiva.

## Interseção com `specs/bancas-projeto-coletivo.md` (12/08/2026)

⚠️ **Ler antes de planejar.** Existe uma spec anterior, fechada, sobre o
**cadastro da banca examinadora**, fundamentada nos **editais reais do PS2027**
(SEI 5294767 / Edital 1539 regular; SEI 5294775 / Edital 1540 suplementar) e nas
relações nominais publicadas. Ela **já modelou** o `Board` (4 FKs diretas:
presidente, titular 1, titular 2, suplente; sem through-model; chave temporal =
**ano do processo seletivo como inteiro**, ex. `2027`). Este módulo **pendura
nela** — não recria composição de banca.

### O que ela resolve de flag meu
- **Existe PRESIDENTE**, papel nomeado, coluna do documento oficial. (Meu flag 5.)
- **Banca é por (projeto coletivo × nível)** — provado por evidência: no projeto
  "Direito Administrativo…", presidente do mestrado ≠ presidente do doutorado.
  Confirma que a **ata por nível** que capturei está certa.
- **Volume**: 6 linhas de pesquisa, **~36 projetos coletivos**, até **~72 bancas**
  por processo seletivo, ~288 vínculos de docente. (Meu flag 9, parcialmente.)

### Conflitos reais a resolver com o usuário

**C1 — Membro externo.** Hoje (Q15/Q16) o usuário disse: *"a banca tem 3 membros
**e pode ter externo**"*, e que o externo ganha cadastro e **assina por link com
token**. A spec de 12/08 registra, a partir dos PDFs oficiais: *"**sem coluna de
instituição — todos os membros são docentes do programa**"*. As duas podem ser
verdade (permitido no regulamento, não usado no PS2027), mas **a diferença é
cara**: se não há externo, cai a assinatura por token — que é a **segunda
superfície não autenticada** do módulo, com todo o desenho de token de uso único.
→ **Decidir antes de planejar a assinatura.**

**C2 — Composição: 3 ou 4.** Hoje: *"3 membros, os três assinam"*. Edital,
verbatim: *"3 (três) membros titulares e 1 (um) membro suplente"*, e *"o suplente
somente participará em caso de impedimento de um dos membros titulares"*.
Reconciliação provável (a confirmar): **assinam os 3 titulares**; havendo
impedimento, o suplente assina **no lugar** do titular. A ata precisa registrar
**quem de fato assinou**, não a composição nominal.

**C3 — O alvo da banca DIFERE por edital.** Item 5.1 do Regular: banca *"para
cada **projeto coletivo**"*. Item 4.1 do Suplementar: banca *"para cada **linha
de pesquisa**"*. Hoje capturei a ata como (edital × nível × **projeto coletivo** ×
etapa) — mas o exemplo que o usuário deu era do **Regular**. Para o Suplementar,
a ata provavelmente é por **linha de pesquisa**. E, por tabela: **as vagas do
Suplementar são por projeto coletivo ou por linha?** Hoje o usuário respondeu
"por nível e projeto coletivo" **sem distinguir edital**. → **Flag alto: muda a
chave de duas entidades centrais.**

**C4 — Retificação de edital move vaga entre projetos coletivos.** A spec de
12/08 registra caso real do PS2027: o projeto *"4E – Justiça: teoria e
realidade"* foi **excluído por retificação**, com **realocação de vagas** para
*"4F – Macrofilosofia do Estado de Direito"*. Hoje o usuário disse que
redistribuição de vaga é *"apenas dentro do mesmo projeto coletivo, entre
níveis"*. São coisas diferentes — retificação de edital não é redistribuição de
vaga —, mas **o efeito no dado é o mesmo**, e o desenho precisa comportar as
duas. A banca de um projeto extinto **precisa sobreviver como histórico**.

### Dependência de escopo
A spec de bancas deixou **fora** a banca do Suplementar (flag F8 dela) e a
**declaração de impedimento/suspeição** (F7), que os editais exigem divulgar
junto com as bancas. Como aqui a ata do Suplementar é necessária, **este módulo
não fecha sem a fatia F8**.

---

## Q&A log

### Q1 — Quantos processos seletivos existem e o que cada um seleciona
- **Asked**: é um edital por ano ou por nível? Quantas entradas? Vagas por quê
  (nível / linha / orientador)? Existe modalidade paralela que muda a contagem?
- **Captured**:
  - "**um edital que se desdobra em dois**": (a) edital **Regular**, englobando
    mestrado e doutorado; (b) edital **Suplementar**, também englobando
    mestrado e doutorado. São dois editais, não um com anexo.
  - **Os editais saem em junho.**
  - **Vagas são por nível e por projeto coletivo.** Uma linha de pesquisa tem
    vários projetos; o projeto é a unidade de vaga. (Bate com o model
    `CollectiveProject` já existente em `apps/programs/models.py`, que é a
    unidade que professores e alunos citam no vínculo.)
  - **Vagas de cotistas são separadas** das demais — não é ordenação dentro da
    mesma lista, é reserva com contagem própria.
  - **As cotas diferem por edital**:
    - **Regular** → cotas **raciais**.
    - **Suplementar** → cotas para **pessoa com deficiência, quilombola,
      trans e travesti, indígena**.
- **Decisões que isso já fixa**:
  - `SelectionProcess` (edital) precisa de um campo de tipo: REGULAR |
    SUPLEMENTAR — e o tipo governa quais categorias de cota são válidas.
  - A vaga não é atributo do edital: é uma linha própria, chaveada por
    (edital × nível × projeto coletivo × categoria de cota/ampla concorrência).
  - `CollectiveProject` e `ResearchLine` são reaproveitados, não recriados.
- **Flags**: periodicidade exata (1×/ano? ingresso em qual semestre?) e se os
  dois editais correm no mesmo calendário — a confirmar na Q2.


### Q2 — Os dois editais são a mesma máquina com cotas diferentes, ou processos distintos?
- **Asked**: Suplementar tem ampla concorrência ou é só cota? Mesmo calendário e
  mesmas etapas? Dá para se inscrever nos dois? Cotista do Regular concorre
  também à ampla?
- **Captured**:
  - **As etapas de avaliação DIFEREM entre os editais**: "o processo seletivo
    previsto no suplementar **não tem apresentação de resumo expandido, mas de
    memorial**". Ou seja, Regular → **resumo expandido**; Suplementar →
    **memorial**.
  - **"É permitido que uma pessoa se inscreva nos dois ao mesmo tempo."** As
    duas inscrições são independentes e coexistem na mesma safra.
- **Decisões que isso já fixa**:
  - A lista de etapas **não pode ser hardcoded** no model: é dado, configurado
    por edital. Dois editais da mesma safra têm conjuntos de etapas diferentes.
  - A inscrição é chaveada por (edital × candidato), e a mesma `Person` pode
    ter duas inscrições vivas simultâneas na mesma safra — o unique constraint
    é por edital, nunca por safra/pessoa.
- **Flags** (não respondidos na Q2, reperguntados na Q3):
  - Suplementar tem vaga de ampla concorrência ou é 100% cota?
  - Cotista do Regular concorre também à ampla concorrência?
  - Os dois editais correm no mesmo calendário?


### Q3 — Aritmética da vaga de cota  ⚠️ human gate (contagem de vaga)
- **Asked**: Suplementar tem ampla? Cotista do Regular disputa a ampla primeiro?
  Vaga de cota vaga sobra para quem? Cotas do Suplementar contam por categoria?
- **Captured** (as quatro confirmadas como propostas):
  1. **Suplementar: "só cota"** — não existe ampla concorrência nesse edital.
     "Suplementar" = vaga adicional às do Regular.
  2. **Regular: "cotista disputa a ampla primeiro"** — só consome vaga
     reservada quem não classificou na ampla (padrão Lei 12.711 / PN MEC).
  3. **"Vaga não preenchida de cota volta para a ampla."** — ⚠️ **reconciliado
     na Q4**: isso vale **dentro do edital Regular**. Vaga não preenchida do
     **Suplementar NÃO volta** para bolo nenhum do Regular (nem ampla, nem cota
     racial): fica sem preencher.
  4. **"São vagas separadas"** — cada categoria do Suplementar (PCD,
     quilombola, trans/travesti, indígena) tem **contagem própria**; não é um
     bolo único disputado entre categorias.
- **Decisões que isso já fixa**:
  - A linha de vaga é (edital × nível × projeto coletivo × **categoria**), com
    categoria ∈ {ampla, racial, PCD, quilombola, trans/travesti, indígena} e o
    conjunto válido governado pelo tipo do edital.
  - A classificação do Regular tem **duas passadas**: ampla primeiro (todos os
    inscritos, cotistas incluídos), reserva depois só com os cotistas que
    sobraram. Isso é regra de negócio de verdade — vai para método de model /
    service, com teste, e é human gate.
- **Flag aberto**: no **Suplementar não há ampla**; então vaga de categoria não
  preenchida lá **vai para onde**? (outra categoria? fica vazia?) → Q4.


### Q4 — Quem calcula, e como as etapas encadeiam
- **Asked**: sistema calcula a classificação ou a banca entrega lista pronta?
  Pesos configuráveis? Etapa eliminatória? Sobra de vaga no Suplementar?
- **Captured**:
  - **"As etapas são sucessivas."** Não são avaliações paralelas somadas no
    fim: é funil, uma depois da outra.
  - **Etapas do edital REGULAR**, nesta ordem:
    1. **resumo expandido**
    2. **prova oral**, "na qual é sorteado um ponto de 10 com a respectiva
       bibliografia"
    3. **entrevista sobre o projeto**
  - **Etapas do edital SUPLEMENTAR**, nesta ordem:
    1. **memorial**
    2. **prova oral**
    3. **análise do projeto e do memorial**
  - **"Cada etapa elimina com nota < 70."** Corte fixo em 70, etapa a etapa —
    eliminatória, não classificatória-e-somada.
  - **"Vaga não preenchida do suplementar não volta para o bolo da ampla (nem
    da cota racial), ou seja não volta no regular."** Fica sem preencher.
- **Decisões que isso já fixa**:
  - `SelectionStage` é entidade por edital, com **ordem** e conjunto próprio de
    etapas. Regular e Suplementar têm três etapas cada, com nomes diferentes.
  - **Eliminação é por etapa**: candidato com nota < 70 numa etapa não avança —
    e portanto **não tem nota** nas etapas seguintes. O model precisa
    distinguir "não avaliado porque foi eliminado antes" de "faltou".
  - Os dois editais são **estanques na contagem de vaga**: nada transborda de um
    para o outro. A reversão de vaga ociosa da Q3 é intra-edital.
- **Flags** (não respondidos, vão para a Q5): quem **lança** a nota; se o
  sistema **calcula** a classificação ou só registra a lista da banca; e como
  sai a **nota final** que ordena os aprovados (soma? média? peso por etapa?
  só a última etapa?).


### Q5 — Nota final, quem lança, e a ata  ⚠️ human gate (classificação)
- **Asked**: média ou última etapa? pesos? quem lança? desempate? arredondamento?
- **Captured**:
  - **"A nota final é a nota da última etapa."** Não é média, não é soma
    ponderada. "Os candidatos vão sendo eliminados a cada etapa. **É um funil.**"
  - **A ata é a unidade de trabalho da banca**: "a banca faz **uma ata para cada
    etapa e cada nível**". Exemplo dado pelo usuário, literal: *"mestrado do
    projeto coletivo x: ata para resumo expandido, para prova oral e para
    entrevista"* → a ata é chaveada por (edital × **nível** × **projeto
    coletivo** × **etapa**).
  - **Estado atual (o que se faz hoje, fora do sistema)**: "a secretaria recebe
    um **pdf assinado** e **lança manualmente**".
  - **O que se quer (a razão de existir do módulo)**: *"o ideal seria **inverter
    o fluxo**: as bancas lançam as notas por etapa e **o sistema gera a ata**.
    A assinatura poderá ser **digital pelo próprio sistema**."*
  - **"Existe nota fracionária. Não há arredondamento."** → `DecimalField` com
    casas suficientes para guardar o que a banca digitou, sem arredondar
    (`CLAUDE.md` proíbe `FloatField`). Nº de casas decimais: a definir.
- **Decisões que isso já fixa**:
  - Não existe cálculo de média a implementar. A classificação ordena pela nota
    da **última etapa**; as etapas anteriores só decidem quem chegou lá.
  - `ExaminationRecord` (ata) é entidade de primeira classe, não um relatório:
    tem identidade, conteúdo gerado, e estado de assinatura.
  - O lançamento de nota é **da banca**, no sistema — inversão explícita do
    fluxo atual em que a secretaria transcreve PDF.
- **Flags**: **critério de desempate** (não respondido → Q7); nº de casas
  decimais da nota; escopo e natureza da **assinatura digital** (→ Q6).


### Q6 — Ata gerada, assinatura digital e desempate  ⚠️ human gate (classificação)
- **Asked**: assinatura simples basta? composição da banca? a ata fecha a etapa?
  PDF de verdade?
- **Captured**:
  - **"Assinatura eletrônica simples resolve"** — não é preciso ICP-Brasil,
    GOV.BR nem certificado A1/A3. Login + registro de quem/quando + hash do
    conteúdo, estampado no documento.
  - **"Banca é a mesma nas três etapas."** A composição não muda por etapa —
    a banca é do (edital × nível × projeto coletivo), e assina as três atas.
  - **"Gerar o pdf com as assinaturas"** — saída é **PDF mesmo**, não tela
    imprimível. ⚠️ Isso é **biblioteca nova em Python** (weasyprint/reportlab):
    `CLAUDE.md` §2 exige discutir antes; provável **ADR**.
  - **Critérios de desempate, nesta ordem** (literal):
    1. **nota da análise do resumo expandido**
    2. **nota da prova oral**
    3. **idade — o mais velho ganha**
  - **"A ata que fecha a etapa."** O avanço no funil não acontece no lançamento
    da nota: acontece quando a ata da etapa está assinada. A ata é o evento de
    transição de estado, não um registro posterior.
  - **"Os aprovados para a seguinte são convocados por e-mail."**
- **Decisões que isso já fixa**:
  - A nota lançada é **rascunho** até a ata fechar; a ata assinada é o commit.
    Isso define o ciclo de vida: lançar → conferir → assinar → fechar etapa.
  - O desempate usa notas de **etapas anteriores** — então as notas intermediárias
    precisam ser guardadas mesmo não valendo para a classificação (a final é só
    a da última etapa).
- **Flags**:
  - **Desempate do Suplementar**: os critérios citados são do **Regular**
    (resumo expandido). O Suplementar tem memorial no lugar — qual é a ordem lá?
  - **Quantos membros** tem a banca e se **todos** precisam assinar (ou só o
    presidente) para a ata fechar.
  - **PDF**: escolher biblioteca → ADR.
  - **E-mail de convocação**: o sistema envia? (isoladas cortou SMTP de
    propósito) → Q7.


### Q7 — E-mail de convocação  ⚠️ decisão que reverte um corte anterior
- **Asked**: manter o corte de SMTP (como nas isoladas), meio-termo (texto
  pronto para colar), ou enviar de verdade?
- **Recomendação dada**: manter o corte — SMTP em produção é fila, retry,
  bounce, SPF/DKIM e uma forma nova de falhar em silêncio, e o candidato já vê
  o status no próprio login.
- **Decisão do usuário**: **"enviar de verdade."** Opção 3. O usuário foi
  informado do custo e reafirmou. **O sistema envia e-mail.**
- **Consequências assumidas** (a tratar no plano):
  - Contraria o corte das isoladas ("sem SMTP/notificação") → o corte vale para
    isoladas, **não** para processo seletivo. Vale registrar em ADR e alinhar
    com a infra (SPF/DKIM/relay do domínio da UFMG).
  - Sem agendador e sem fila (o projeto não tem Celery e não vai ter por causa
    disto): o envio acontece **na ação**, e a falha precisa ser **visível e
    reenviável** — não pode ser exceção engolida.
  - Configuração de SMTP é `.env` + `settings` → **human gate** (infra e
    segredos).
- **Flag**: o candidato tem login desde a inscrição (auto-registro, como nas
  isoladas)? Não respondido → Q9.


### Q8 — Eventos de e-mail e superfície do candidato  ← CORRIGIU premissa minha
- **Asked**: seis eventos de e-mail? tratamento de falha? lote ou individual?
  agenda da prova oral?
- **Captured** (a lista proposta foi cortada quase toda):
  - **"A inscrição não dispara e-mail."**
  - **"O candidato entra no sistema e faz seu cadastro e gera um protocolo."**
  - **"NÃO HÁ UMA ÁREA DO CANDIDATO. É um formulário que recebe os dados e
    documentos."** → ⚠️ **Difere de isoladas**, onde o candidato tem login,
    acompanha o status e envia o comprovante de GRU pelo próprio acesso. Aqui
    o candidato **não autentica**: preenche um formulário público, anexa
    documentos e recebe um **protocolo**.
  - **Inscrição homologada / indeferida** → **publicada no site**.
  - **Convocação para cada etapa** → **por e-mail**. (É o **único** e-mail do
    fluxo.)
  - **Resultado de cada etapa** → **no site**.
  - **Resultado final** → **no site**.
- **Decisões que isso já fixa**:
  - O SMTP da Q7 serve a **um** caso de uso: convocação de etapa. Escopo bem
    menor do que a lista de seis que propus.
  - O **protocolo** é o identificador que o candidato carrega — é o que
    substitui o login. Precisa ser único, legível e provavelmente não
    sequencial-adivinhável.
  - Existe uma superfície **pública e sem autenticação**: o formulário de
    inscrição com upload de documentos. Isso tem implicação de segurança
    (upload anônimo, rate limit, tamanho/tipo de arquivo) que o fluxo das
    isoladas não tinha.
  - "Publicado no site" precisa de definição: site externo do PPGD ou página
    pública deste sistema? → Q9.
- **Flags**: tratamento de falha de envio (não respondido); lote vs individual
  na convocação; agenda/horário da prova oral; **como o candidato interpõe
  recurso sem área logada**.


### Q9 — Publicação no site, e o fluxo de recurso
- **Asked**: qual site? sistema gera ou hospeda? resultado mostra nota? como se
  interpõe recurso sem área logada?
- **Captured**:
  - **"Sistema não gera documento nenhum. A secretaria que faz manualmente e a
    secretaria sobe manualmente no WP."** → publicação é **WordPress**, fora
    deste sistema, e o documento de divulgação é **feito à mão** pela
    secretaria. Este sistema **não** tem página pública de resultado e **não**
    monta a lista de divulgação.
  - **"Resultado publicado mostra a nota."** Nota é dado público na divulgação.
  - **"O recurso é enviado por formulário."** Coerente com a ausência de área
    do candidato: formulário público, sem login.
  - **"Há recurso de cada etapa."** Não é recurso só da inscrição — cada uma das
    três etapas admite recurso.
  - **Quem julga**:
    - recurso da **inscrição** → **comissão do processo seletivo**;
    - recurso **de cada etapa** → **a própria banca**.
  - → Entra um ator novo, distinto da banca: a **comissão do processo
    seletivo**. Composição e escopo a levantar.
- ⚠️ **CONTRADIÇÃO A RECONCILIAR (→ Q10)**: a Q6 diz *"gerar o pdf com as
  assinaturas"* (a ata) e a Q9 diz *"sistema não gera documento nenhum"*.
  Leitura provável: a **ata** é gerada pelo sistema; os **documentos de
  divulgação** (homologação, resultado de etapa, resultado final) não são.
- **Flags**: composição da comissão; prazo e efeito do recurso; tratamento de
  falha de envio de e-mail; lote vs individual na convocação; agenda da prova
  oral.


### Q10 — Reconciliação do PDF
- **Asked**: o sistema gera a ata em PDF, ou não gera documento nenhum?
- **Captured**: **"Ata sim, divulgação não. Topo o pdf."**
  - O sistema gera **um único tipo de documento**: a **ata assinada**, em PDF.
  - Homologação, resultado de etapa e resultado final continuam **manuais**,
    montados pela secretaria e publicados no WordPress.
  - **Dependência nova de PDF aprovada pelo usuário** (weasyprint ou reportlab),
    ciente de que exige discussão/ADR pelo `CLAUDE.md` §2.
- **Contradição da Q9 resolvida.**


### Q11 — A saída do funil: o aprovado vira aluno  ⚠️ human gate (vida acadêmica)
- **Asked**: conversão candidato→aluno acontece no sistema? projeto coletivo
  define orientador? há lista de espera? aprovado nos dois editais?
- **Captured**:
  - **"No sistema a secretaria converte o candidato em aluno."** A conversão é
    uma operação deste sistema — não é recadastro à mão.
  - **Depois**, fora do sistema: "envia a documentação para o **DRCA**. Faz
    **ofício com cinco nomes** e envia a documentação respectiva **em pacotes**."
    → o encaminhamento ao DRCA é manual, em lotes de 5.
  - **"O candidato ocupa a vaga do projeto coletivo. O orientador é escolhido
    depois."** → a vaga não carrega orientador; `Student.advisor` é preenchido
    num momento posterior, fora deste módulo.
  - **REDISTRIBUIÇÃO DE VAGAS**: "pode haver redistribuição de vagas: **apenas
    dentro do mesmo projeto coletivo, entre níveis**." → vaga de mestrado pode
    virar de doutorado (e vice-versa) **no mesmo projeto coletivo**; nunca entre
    projetos coletivos.
  - **"Não existe lista de espera"**, porque "a redistribuição de vagas acaba
    permitindo a entrada de quase todo mundo".
  - **Número de matrícula**: "é como na isolada, ou seja, **o DRCA emite e a
    secretaria copia de volta** para o kpg". → campo preenchido pela secretaria
    depois, com dado vindo de fora.
- **Decisões que isso já fixa**:
  - Existe um serviço de conversão candidato→`Student` (multi-model: `Person` +
    `Student` + `AuditLog`) → `services.py` com `transaction.atomic`.
  - A redistribuição entre níveis é regra de vaga de verdade, e **human gate**.
  - Sem lista de espera = sem convocação automática de suplente. Simplifica.
- **Flags**: "**kpg**" — confirmar o que é (apelido do sistema?); quem decide e
  como se registra a **redistribuição**; **aprovado nos dois editais** (não
  respondido); o **ofício para o DRCA** é gerado pelo sistema ou manual (a Q10
  diz que só a ata é gerada — presumir manual).


### Q12 — Redistribuição de vagas: quem decide  ⚠️ human gate (contagem de vaga)
- **Asked**: quem decide? nos dois sentidos? candidato "desce de nível"?
  aprovado nos dois editais? o que é kpg?
- **Captured**:
  - **"A comissão decide"** — a redistribuição é ato deliberado da **comissão do
    processo seletivo**, registrado no sistema; **não** é cálculo automático.
  - **"Nos dois sentidos"** — mestrado→doutorado e doutorado→mestrado, sempre
    dentro do mesmo projeto coletivo.
  - **"kpg é o sistema"** → **KPG é o apelido deste sistema (PPGD Manager)**.
    Quando o usuário diz "copia de volta para o kpg", quer dizer "para cá".
- **Flags remanescentes (reperguntados na Q13)**: candidato não aprovado em
  doutorado pode ocupar vaga de mestrado redistribuída? candidato aprovado nos
  **dois editais**?


### Q13 — Redistribuição: quem muda de nível
- **Captured**: **"A vaga muda de nível."** O **candidato não desce de nível** —
  quem ocupa a vaga redistribuída é quem já concorria ao nível de destino.
- **Flag persistente (3ª tentativa sem resposta)**: candidato **aprovado nos
  dois editais** — escolhe um? a vaga liberada vai para quem? → owner: usuário /
  secretaria / comissão. **Reperguntar no fechamento.**

### Q14 — A inscrição: formulário público, documentos e homologação
- **Asked**: há taxa/GRU? lista de documentos? um ou vários projetos coletivos?
  quem homologa?
- **Captured**:
  1. **Há taxa de inscrição (GRU). "A secretaria confere os comprovantes."** →
     mesmo padrão das isoladas: o sistema **recebe o comprovante como anexo** e
     **não gera GRU nem faz conciliação financeira**; a conferência é humana.
  2. **"Não é necessário histórico"** — histórico escolar sai da lista.
  3. **"O candidato só pode se inscrever em um projeto coletivo."** Não há 1ª e
     2ª opção. → constraint: uma inscrição = um (nível × projeto coletivo).
  4. **A secretaria homologa** (não a comissão). Conferência documental; o
     mérito é da banca, nas etapas.
- **Lista de documentos resultante** (a validar no edital real):
  diploma/certificado de conclusão · documento de identidade · currículo Lattes ·
  **resumo expandido** (Regular) ou **memorial** (Suplementar) · comprovante de
  pagamento da GRU · autodeclaração/laudo, quando cotista.
- **Decisões que isso já fixa**:
  - A superfície pública sem login recebe **upload de arquivo de anônimo** →
    exige limite de tamanho/tipo e proteção contra abuso; classe de risco que
    isoladas não tinha (lá o candidato estava logado).
  - Reaproveitar `RequestDocument` (já existe em `apps/academic`) como modelo de
    anexo, se o vínculo genérico permitir.


### Q15 — Atores: banca e comissão  ⚠️ human gate (permissões)
- **Asked**: lista de papéis? quantos membros na banca e quem assina? membro
  externo? quem cria o edital?
- **Captured**:
  - **"A banca tem 3 membros e pode ter externo."**
  - → **Membro externo não é `Teacher` do programa e não tem usuário do
    sistema.** Como a ata é assinada eletronicamente pelos membros, isso abre
    um problema concreto: o externo precisa de **algum caminho de assinatura**
    (link com token? cadastro mínimo? assina só o presidente?).
- **Flags (não respondidos)**: lista fechada de papéis/Groups; **todos os 3
  assinam** ou só o presidente; existe presidente com poder distinto; **quem
  cria o edital** no sistema.


### Q16 — Assinatura do membro externo, e quem cria o edital
- **Captured**:
  - **Opção 2: link com token por e-mail.** Cada membro abre a ata pelo link,
    confere e clica "assinar" — sem senha, sem sessão; **o token é a
    credencial**. (Segunda superfície não autenticada do módulo, depois do
    formulário de inscrição.)
  - **"Os três assinam."** A ata só fecha com as **três** assinaturas — e é a
    ata que fecha a etapa (Q6). Logo: **uma assinatura pendente trava o funil**.
  - **"Secretaria cria o edital"** (vagas por nível/projeto coletivo/cota).
  - **"O externo ganhará um cadastro no sistema para participar do projeto
    coletivo."** → o externo **existe como registro** (docente externo ligado ao
    projeto coletivo), mas **assina pelo token**, não por login.
- **Decisões que isso já fixa**:
  - Token de assinatura: uso único por (membro × ata), com validade, e o ato
    registra quem/quando/hash — auditado como qualquer escrita.
  - `Teacher` (ou equivalente) precisa admitir **docente externo** ao programa.
    Conferir se o model atual já comporta isso.


### Q17 — Recurso  → **ADIADO PELO USUÁRIO**
- **Asked**: prazo, identificação do candidato, retificação da ata assinada,
  como a resposta chega.
- **Decisão**: **"vamos fazer a parte de recursos depois."**
- **Status**: branch inteira **fora do escopo desta rodada**. O que já se sabe e
  fica registrado para a fase 2 (da Q9):
  - o recurso é enviado **por formulário** (público, sem login);
  - **há recurso de cada etapa**, além do da inscrição;
  - julga: **comissão** (inscrição) e **a própria banca** (etapa).
  - Pergunta em aberto e não trivial: recurso deferido **depois da ata
    assinada** exige ata de retificação — a ata original não pode ser editada.
- **Consequência para o plano desta rodada**: o desenho de `ata` precisa nascer
  **versionável** (retificação como registro novo), mesmo sem implementar
  recurso agora — senão a fase 2 exige migration destrutiva.


### Q18 — Calendário do edital
- **Captured**:
  - **"A secretaria cadastra a janela de inscrição."** → abertura e encerramento
    são dado do edital; o formulário público valida a data no envio (comparação
    na requisição, não agendador).
  - **"As datas são conhecidas desde o edital."** → as datas das três etapas são
    **cadastráveis no edital**, não descobertas ao longo do processo. Logo a
    convocação por e-mail pode montar data/hora a partir do cadastro.
  - **"Guardar o edital no sistema"** → o **PDF do edital publicado** fica
    anexado ao registro (`FileField`, como `RequestDocument`).
- **Decisão que isso fixa**: `SelectionProcess` carrega janela de inscrição +
  datas das etapas + o arquivo do edital.


### Q19 — Mecânica da convocação por e-mail
- **Captured** (as quatro):
  1. **"A secretaria clica"** — o envio **não** é automático ao fechar a ata.
     Ato humano explícito, sempre.
  2. **"Em lote"** — todos os aprovados da etapa de uma vez, um e-mail por
     candidato.
  3. **"Modelo cadastrado"** — o corpo é template guardado (provavelmente no
     edital), preenchido pelo sistema; a secretaria não redige a cada vez.
  4. "Horário individual" — ⚠️ **CORRIGIDO NA Q20**: ver abaixo. Vale o da Q20.


### Q20 — Agenda da etapa presencial  ← CORRIGE a Q19
- **Captured**: **"Os candidatos são convocados para a sessão. Um horário único
  para todos os candidatos."**
- **Efeito**: **não existe agenda por candidato.** Cai o subsistema de slots que
  a leitura anterior ("horário individual") tinha criado. A convocação em lote
  manda **o mesmo horário e local** para todos os aprovados da etapa — e esses
  dados já estão no cadastro do edital (Q18).
- **Não respondidos** (a etapa foi encerrada aqui): ordem de chamada dos
  candidatos na sessão; se o **sorteio do ponto entre 10** da prova oral é feito
  no sistema ou presencialmente com a banca transcrevendo.

---

## Encerramento

O usuário encerrou a sessão na Q20: *"vamos fechar o processo por agora"*.
O que está abaixo é o estado final desta rodada.

## Open flags (pending input)

Nada aqui bloqueia a **sessão de plano**; tudo aqui bloqueia a **implementação**
da fatia correspondente.

### Domínio — precisam do usuário / da secretaria / do edital real
0. **Os quatro conflitos C1–C4** com `specs/bancas-projeto-coletivo.md` (ver
   seção "Interseção"). **C1** (existe membro externo?) e **C3** (banca e vaga do
   Suplementar são por linha de pesquisa, não por projeto coletivo?) são os que
   mudam chave de entidade — resolver **antes** do plan mode.
1. **Candidato aprovado nos DOIS editais** (perguntado 3×, sem resposta):
   escolhe um? a vaga liberada vai para quem, se não há lista de espera?
   → owner: usuário / comissão do processo seletivo.
2. **Critério de desempate do SUPLEMENTAR**: os três critérios conhecidos são do
   Regular (resumo expandido → prova oral → mais velho). O Suplementar tem
   memorial no lugar do resumo expandido. → owner: edital do Suplementar.
3. **Casas decimais da nota** (há nota fracionária e não há arredondamento —
   falta o `decimal_places` do `DecimalField`). → owner: edital / secretaria.
4. **Formato do protocolo** de inscrição: sequencial? por edital? não
   adivinhável? É a única identificação do candidato sem login.
5. **Lista fechada de papéis/Groups** do Django. Conhecidos: Secretaria,
   Comissão do processo seletivo, Banca. Falta confirmar Coordenação e quem
   designa banca/comissão.
6. **Sorteio do ponto (1 entre 10) da prova oral**: feito no sistema e
   registrado na ata, ou presencial com a banca transcrevendo?
7. **Ordem de chamada** dos candidatos dentro da sessão.
8. **Ofício de 5 nomes para o DRCA**: gerado pelo sistema ou manual? (A Q10 diz
   que só a ata é gerada — presumir **manual** até desmentido.)
9. **Volume**: quantos candidatos por edital? Muda decisão de listagem,
   paginação e limite de upload.

### Técnicos — decisão de projeto, não do usuário
10. **Falha no envio de e-mail**: proposta não confirmada — enviar após o
    commit, registrar status por destinatário, tela de reenvio, e **nunca**
    deixar o SMTP travar a etapa.
11. **`Teacher` não comporta "externo"** hoje: tem `category` CAPES
    (permanente/colaborador/visitante), `program` obrigatório e `person`
    OneToOne. Membro externo de banca precisa de desenho — categoria nova,
    flag, ou entidade própria. → decidir no plan mode.
12. **Biblioteca de PDF** (weasyprint × reportlab) → ADR, aprovado pelo usuário.
13. **SMTP** → ADR + configuração `.env`/`settings` (human gate: infra e
    segredos); alinhar relay/SPF/DKIM com a infra.
14. **Upload anônimo** no formulário público: limite de tamanho, tipos aceitos,
    proteção contra abuso. Classe de risco que isoladas não tinha.

### Escopo adiado pelo usuário
15. **Recursos inteiros** → fase 2 (Q17). Mas a **ata precisa nascer
    versionável** nesta rodada, senão a fase 2 custa migration destrutiva.
